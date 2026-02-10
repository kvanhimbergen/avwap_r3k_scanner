from __future__ import annotations

import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from strategies import s2_letf_orb_aggro


def _build_history(
    rows_per_symbol: int = 260,
    symbol_growth: list[tuple[str, float]] | None = None,
) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=rows_per_symbol, freq="B")
    rows: list[dict] = []
    symbols = symbol_growth or [("TQQQ", 1.004), ("SOXL", 1.003), ("LABU", 0.999)]
    for symbol, growth in symbols:
        close = 40.0
        for dt in dates:
            close *= growth
            rows.append(
                {
                    "Date": dt,
                    "Ticker": symbol,
                    "Open": close * 0.995,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": 4_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _base_candidate(symbol: str) -> dict[str, object]:
    return {
        "Symbol": symbol,
        "Direction": "Long",
        "Entry_Level": 100.0,
        "Stop_Loss": 95.0,
        "Target_R1": 105.0,
        "Target_R2": 110.0,
        "Entry_DistPct": 2.0,
        "Price": 100.0,
    }


def test_run_strategy_writes_candidates_and_signal_ledger(tmp_path: Path) -> None:
    history = _build_history()
    history_path = tmp_path / "ohlcv.parquet"
    history.to_parquet(history_path, index=False)

    base_csv = tmp_path / "base.csv"
    pd.DataFrame([_base_candidate("AAPL")]).to_csv(base_csv, index=False)
    output_csv = tmp_path / "layered.csv"

    cfg = s2_letf_orb_aggro.StrategyConfig(
        min_price=5.0,
        min_adv_usd=20_000_000.0,
        max_candidates=3,
        max_per_complex=2,
    )
    artifacts = s2_letf_orb_aggro.run_strategy(
        asof_date="2025-12-31",
        repo_root=tmp_path,
        history_path=history_path,
        base_candidates_csv=base_csv,
        output_csv=output_csv,
        merge_base_candidates=True,
        dry_run=False,
        config=cfg,
    )

    assert artifacts.selected_count >= 1
    assert output_csv.exists()
    layered = pd.read_csv(output_csv)
    assert "Strategy_ID" in layered.columns
    strategy_rows = layered[layered["Strategy_ID"] == s2_letf_orb_aggro.STRATEGY_ID]
    assert not strategy_rows.empty
    assert set(strategy_rows["Symbol"]).issubset(set(s2_letf_orb_aggro.DEFAULT_UNIVERSE))
    assert artifacts.signal_ledger.exists()
    lines = [line for line in artifacts.signal_ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    sample = json.loads(lines[0])
    assert sample["record_type"] == "STRATEGY_SIGNAL"
    assert sample["strategy_id"] == s2_letf_orb_aggro.STRATEGY_ID


def test_run_strategy_marks_symbol_conflict_with_base_candidates(tmp_path: Path) -> None:
    history = _build_history()
    history_path = tmp_path / "ohlcv.parquet"
    history.to_parquet(history_path, index=False)

    base_csv = tmp_path / "base.csv"
    pd.DataFrame([_base_candidate("TQQQ")]).to_csv(base_csv, index=False)
    output_csv = tmp_path / "layered.csv"

    cfg = s2_letf_orb_aggro.StrategyConfig(
        min_price=5.0,
        min_adv_usd=20_000_000.0,
        max_candidates=3,
        max_per_complex=2,
    )
    artifacts = s2_letf_orb_aggro.run_strategy(
        asof_date="2025-12-31",
        repo_root=tmp_path,
        history_path=history_path,
        base_candidates_csv=base_csv,
        output_csv=output_csv,
        merge_base_candidates=True,
        dry_run=False,
        config=cfg,
    )

    layered = pd.read_csv(output_csv)
    tqqq_rows = layered[layered["Symbol"] == "TQQQ"]
    assert len(tqqq_rows) == 1
    assert pd.isna(tqqq_rows.iloc[0].get("Strategy_ID"))

    records = [
        json.loads(line)
        for line in artifacts.signal_ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    conflict_records = [rec for rec in records if rec.get("symbol") == "TQQQ"]
    assert conflict_records
    assert any(
        "symbol_conflict_with_base_candidates" in rec.get("reason_codes", [])
        for rec in conflict_records
    )


def test_run_strategy_respects_universe_profile(tmp_path: Path) -> None:
    history = _build_history(symbol_growth=[("TQQQ", 1.004), ("NVDA", 1.004)])
    history_path = tmp_path / "ohlcv.parquet"
    history.to_parquet(history_path, index=False)

    output_csv = tmp_path / "layered.csv"
    cfg = s2_letf_orb_aggro.StrategyConfig(
        min_price=5.0,
        min_adv_usd=20_000_000.0,
        max_candidates=5,
        max_per_complex=3,
    )
    artifacts = s2_letf_orb_aggro.run_strategy(
        asof_date="2025-12-31",
        repo_root=tmp_path,
        history_path=history_path,
        base_candidates_csv=tmp_path / "base.csv",
        output_csv=output_csv,
        universe_profile="leveraged_only",
        merge_base_candidates=False,
        dry_run=False,
        config=cfg,
    )

    assert artifacts.evaluated_count == 1
    records = [
        json.loads(line)
        for line in artifacts.signal_ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {rec["symbol"] for rec in records} == {"TQQQ"}
