from __future__ import annotations

import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

import backtest_engine
import scan_engine
from config import cfg
from parity import PARITY_REPORT_PATH, compare_scan_backtest
from provenance import (
    REQUIRED_PROVENANCE_FIELDS,
    compute_config_hash,
    compute_run_id,
)


def _make_history_frame(symbols: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for sym_idx, symbol in enumerate(symbols):
        base = 50.0 + sym_idx * 10.0
        for idx, dt in enumerate(dates):
            close_px = base + idx * 0.5
            open_px = close_px - 0.2
            high_px = close_px + 0.6
            low_px = close_px - 0.6
            rows.append(
                {
                    "Date": dt,
                    "Ticker": symbol,
                    "Open": open_px,
                    "High": high_px,
                    "Low": low_px,
                    "Close": close_px,
                    "Volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _assert_required_provenance(payload: dict) -> None:
    for key in REQUIRED_PROVENANCE_FIELDS:
        assert key in payload
        assert payload[key] not in (None, "")


def test_backtest_provenance_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    history = _make_history_frame(["AAA", "BBB"], dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))

    backtest_engine.run_backtest(
        cfg,
        dates[0].date(),
        dates[-1].date(),
        universe_symbols=["AAA", "BBB"],
    )

    summary_path = tmp_path / "out" / "summary.json"
    meta_path = tmp_path / "out" / "run_meta.json"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    _assert_required_provenance(summary)
    _assert_required_provenance(meta)
    assert summary["run_id"] == meta["run_id"]


def test_run_id_stability_and_drift() -> None:
    params = {"start_date": "2024-01-01", "end_date": "2024-02-01"}
    base_id = compute_run_id("abc123", "cfg456", "data789", "single", params)
    repeat_id = compute_run_id("abc123", "cfg456", "data789", "single", params)
    assert base_id == repeat_id

    assert base_id != compute_run_id("def456", "cfg456", "data789", "single", params)
    assert base_id != compute_run_id("abc123", "cfg999", "data789", "single", params)
    assert base_id != compute_run_id("abc123", "cfg456", "data999", "single", params)
    assert base_id != compute_run_id("abc123", "cfg456", "data789", "sweep", params)
    assert base_id != compute_run_id(
        "abc123", "cfg456", "data789", "single", {**params, "slippage_bps": 1.0}
    )


def test_run_id_changes_with_config_hash() -> None:
    class _DummyCfg:
        BACKTEST_ENTRY_MODEL = "next_open"
        BACKTEST_MAX_HOLD_DAYS = 5
        BACKTEST_INITIAL_CASH = 100_000.0
        BACKTEST_INITIAL_EQUITY = 100_000.0
        BACKTEST_MIN_DOLLAR_POSITION = 0.0
        BACKTEST_STRICT_SCHEMA = True
        BACKTEST_DEBUG_SAVE_CANDIDATES = False
        BACKTEST_VERBOSE = False
        BACKTEST_DYNAMIC_SCAN = True
        BACKTEST_STATIC_UNIVERSE = False
        BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS = False

    cfg_a = _DummyCfg()
    cfg_b = _DummyCfg()
    cfg_b.BACKTEST_MAX_HOLD_DAYS = 10

    params = {"start_date": "2024-01-01", "end_date": "2024-02-01"}
    run_id_a = compute_run_id(
        "abc123",
        compute_config_hash(cfg_a),
        "data789",
        "single",
        params,
    )
    run_id_b = compute_run_id(
        "abc123",
        compute_config_hash(cfg_b),
        "data789",
        "single",
        params,
    )
    assert run_id_a != run_id_b


def test_parity_report_includes_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    history = _make_history_frame(["AAA", "BBB", "CCC"], pd.date_range("2024-01-02", periods=60, freq="B"))
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    history_indexed = backtest_engine.load_ohlcv_history(history_path)
    symbols = ["AAA", "BBB"]
    sector_map = {symbol: "Unknown" for symbol in symbols}

    compare_scan_backtest(
        history_indexed,
        symbols,
        sector_map,
        pd.Timestamp("2024-06-03"),
        cfg,
        history_path=history_path,
    )

    report = json.loads(PARITY_REPORT_PATH.read_text(encoding="utf-8"))
    _assert_required_provenance(report)
