from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import backtest_engine
from config import cfg
import scan_engine


def _make_history_frame(dates: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        for dt in dates:
            rows.append(
                {
                    "Date": dt,
                    "Ticker": symbol,
                    "Open": 100.0,
                    "High": 105.0,
                    "Low": 95.0,
                    "Close": 100.0,
                    "Volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _fake_candidate_row_factory(signal_map: dict[pd.Timestamp, set[str]]):
    def _fake_candidate_row(
        df: pd.DataFrame,
        ticker: str,
        sector: str,
        setup_rules: dict,
        *,
        as_of_dt=None,
        direction: str = "Long",
    ) -> dict | None:
        if as_of_dt is None:
            return None
        signal_date = pd.Timestamp(as_of_dt).normalize()
        if signal_date not in signal_map or ticker not in signal_map[signal_date]:
            return None
        price = float(df.loc[pd.Timestamp(as_of_dt), "Close"])
        return {
            "SchemaVersion": 1,
            "ScanDate": pd.Timestamp(as_of_dt).date().isoformat(),
            "Symbol": ticker,
            "Direction": direction,
            "TrendTier": "A",
            "Price": round(price, 2),
            "Entry_Level": round(price, 2),
            "Entry_DistPct": 0.0,
            "Stop_Loss": 90.0,
            "Target_R1": 110.0,
            "Target_R2": 120.0,
            "TrendScore": 1.0,
            "Sector": sector,
            "Anchor": "Test",
            "AVWAP_Slope": 0.0,
            "Setup_VWAP_Control": "inside",
            "Setup_VWAP_Reclaim": "none",
            "Setup_VWAP_Acceptance": "accepted",
            "Setup_VWAP_DistPct": 0.0,
            "Setup_AVWAP_Control": "inside",
            "Setup_AVWAP_Reclaim": "none",
            "Setup_AVWAP_Acceptance": "accepted",
            "Setup_AVWAP_DistPct": 0.0,
            "Setup_Extension_State": "neutral",
            "Setup_Gap_Reset": "none",
            "Setup_Structure_State": "neutral",
        }

    return _fake_candidate_row


def _configure_backtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history: pd.DataFrame
) -> None:
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_RISK_PER_TRADE_PCT", 0.01)
    monkeypatch.setattr(cfg, "BACKTEST_MIN_DOLLAR_POSITION", 0.0)
    monkeypatch.setattr(cfg, "BACKTEST_SLIPPAGE_BPS", 0.0)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", 10.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_NEW_ENTRIES_PER_DAY", 10_000)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_UNIQUE_SYMBOLS_PER_DAY", 10_000)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", 1.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS", 1_000_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_RISK_PER_TRADE_DOLLARS", 1_000_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_KILL_SWITCH", False)
    monkeypatch.setattr(cfg, "BACKTEST_KILL_SWITCH_START_DATE", None)


def _assert_no_backtest_artifacts(output_dir: Path) -> None:
    assert not (output_dir / "trades.csv").exists()
    assert not (output_dir / "positions.csv").exists()
    assert not (output_dir / "equity_curve.csv").exists()
    assert not (output_dir / "summary.json").exists()


def test_guardrail_max_risk_per_trade_abs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_RISK_PER_TRADE_DOLLARS", 50.0)

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "max_risk_per_trade_abs" in str(excinfo.value)
    assert "current=" in str(excinfo.value)
    assert "limit=" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_max_gross_exposure_pct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", 0.05)

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "max_gross_exposure_pct" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_max_gross_exposure_abs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS", 5_000.0)

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "max_gross_exposure_abs" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_max_concurrent_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA", "BBB"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "next_open")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_POSITIONS", 1)

    signal_map = {dates[0].normalize(): {"AAA", "BBB"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA", "BBB"]
        )

    assert "max_concurrent_positions" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_max_new_entries_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_NEW_ENTRIES_PER_DAY", 0)

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "max_new_entries_per_day" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_max_unique_symbols_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_UNIQUE_SYMBOLS_PER_DAY", 0)

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "max_unique_symbols_per_day" in str(excinfo.value)
    _assert_no_backtest_artifacts(Path(cfg.BACKTEST_OUTPUT_DIR))


def test_guardrail_kill_switch_blocks_entries_but_allows_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    history = _make_history_frame(dates, ["AAA"])
    _configure_backtest(tmp_path, monkeypatch, history)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "same_close")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_HOLD_DAYS", 1)
    monkeypatch.setattr(cfg, "BACKTEST_KILL_SWITCH_START_DATE", dates[1].date().isoformat())

    signal_map = {dates[0].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    result = backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
    )
    exits = result.trades[result.trades["fill_type"] == "exit"]
    assert exits.iloc[0]["date"] == dates[1].date().isoformat()

    output_dir = tmp_path / "out_fail"
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(output_dir))
    signal_map = {dates[0].normalize(): {"AAA"}, dates[1].normalize(): {"AAA"}}
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(signal_map))

    with pytest.raises(RuntimeError) as excinfo:
        backtest_engine.run_backtest(
            cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
        )

    assert "kill_switch" in str(excinfo.value)
    _assert_no_backtest_artifacts(output_dir)
