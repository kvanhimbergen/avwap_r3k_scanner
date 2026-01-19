from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import backtest_engine
from config import cfg
import scan_engine


def _make_history_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    symbols = ["AAA", "BBB"]
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


def test_backtest_sizing_and_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "next_open")
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_RISK_PER_TRADE_PCT", 0.01)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_POSITIONS", 2)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_PCT", 1.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS", 1_000_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_RISK_PER_TRADE_DOLLARS", 1_000_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_NEW_ENTRIES_PER_DAY", 10)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_UNIQUE_SYMBOLS_PER_DAY", 10)
    monkeypatch.setattr(cfg, "BACKTEST_MIN_DOLLAR_POSITION", 0.0)
    monkeypatch.setattr(cfg, "BACKTEST_SLIPPAGE_BPS", 0.0)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", 10.0)

    result = backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA", "BBB"]
    )

    entry_trades = result.trades[result.trades["fill_type"] == "entry"]
    assert entry_trades.shape[0] == 2
    assert entry_trades.iloc[0]["qty"] == 100
    assert entry_trades.iloc[1]["qty"] == 100


def test_backtest_missed_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    history = _make_history_frame(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "next_open")
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_SLIPPAGE_BPS", 5.0)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", 1.0)

    backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
    )

    diagnostics = pd.read_csv(Path(cfg.BACKTEST_OUTPUT_DIR) / "scan_diagnostics.csv")
    fill_day = diagnostics[diagnostics["date"] == dates[1].date().isoformat()].iloc[0]
    assert fill_day["entries_missed_limit"] == 1
