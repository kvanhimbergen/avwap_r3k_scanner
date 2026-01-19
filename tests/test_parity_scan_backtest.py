from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import backtest_engine
import scan_engine
from config import cfg
from parity import (
    PARITY_DIFF_PATH,
    PARITY_REPORT_PATH,
    ParityMismatchError,
    compare_scan_backtest,
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


def _write_history(tmp_path: Path) -> Path:
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    dates = pd.date_range("2024-01-02", periods=120, freq="B")
    history = _make_history_frame(symbols, dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)
    return history_path


def test_parity_scan_backtest_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    history_path = _write_history(tmp_path)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))

    history = backtest_engine.load_ohlcv_history(Path(cfg.BACKTEST_OHLCV_PATH))
    symbols = ["AAA", "BBB", "CCC"]
    sector_map = {symbol: "Unknown" for symbol in symbols}

    as_of_dates = pd.date_range("2024-06-03", periods=3, freq="B")
    for as_of_dt in as_of_dates:
        result = compare_scan_backtest(
            history,
            symbols,
            sector_map,
            as_of_dt,
            cfg,
            history_path=history_path,
        )
        assert result.is_equal

    assert not PARITY_REPORT_PATH.exists()
    assert not PARITY_DIFF_PATH.exists()


def test_parity_scan_backtest_mismatch_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    history_path = _write_history(tmp_path)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))

    history = backtest_engine.load_ohlcv_history(Path(cfg.BACKTEST_OHLCV_PATH))
    symbols = ["AAA", "BBB", "CCC"]
    sector_map = {symbol: "Unknown" for symbol in symbols}

    as_of_dt = pd.Timestamp("2024-06-03")

    original_scan = backtest_engine._scan_as_of

    def _scan_with_mismatch(*args, **kwargs):
        df = original_scan(*args, **kwargs)
        if df.empty:
            fake_row = {
                "SchemaVersion": 1,
                "ScanDate": as_of_dt.date().isoformat(),
                "Symbol": symbols[0],
                "Direction": "Long",
                "TrendTier": "A",
                "Price": 100.0,
                "Entry_Level": 100.0,
                "Entry_DistPct": 0.0,
                "Stop_Loss": 95.0,
                "Target_R1": 105.0,
                "Target_R2": 110.0,
                "TrendScore": 1.0,
                "Sector": "Unknown",
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
            return scan_engine._build_candidates_dataframe([fake_row])
        df = df.copy()
        df.loc[df.index[0], "Target_R1"] = float(df.loc[df.index[0], "Target_R1"]) + 1.0
        return df

    monkeypatch.setattr(backtest_engine, "_scan_as_of", _scan_with_mismatch)

    with pytest.raises(ParityMismatchError):
        compare_scan_backtest(
            history,
            symbols,
            sector_map,
            as_of_dt,
            cfg,
            history_path=history_path,
        )

    assert PARITY_REPORT_PATH.exists()
    assert PARITY_DIFF_PATH.exists()
