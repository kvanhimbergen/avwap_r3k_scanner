import hashlib
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from config import cfg
import backtest_engine
import scan_engine


def _make_history_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    symbols = ["AAA", "BBB", "CCC"]
    rows = []
    for symbol in symbols:
        for idx, dt in enumerate(dates):
            open_px = 100.0
            high_px = 101.0
            low_px = 99.0
            close_px = 100.0
            if symbol == "AAA" and idx == 2:
                high_px = 106.0
                close_px = 104.0
            if symbol == "AAA" and idx == 3:
                high_px = 111.0
                low_px = 103.0
                close_px = 110.0
            if symbol == "BBB" and idx == 2:
                high_px = 106.0
                low_px = 94.0
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


def _fake_candidate_row_factory(signal_date: pd.Timestamp):
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
        if pd.Timestamp(as_of_dt).normalize() != signal_date.normalize():
            return None
        stops = {"AAA": 95.0, "BBB": 95.0, "CCC": 90.0}
        r1s = {"AAA": 105.0, "BBB": 105.0, "CCC": 120.0}
        r2s = {"AAA": 110.0, "BBB": 110.0, "CCC": 130.0}
        if ticker not in stops:
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
            "Stop_Loss": stops[ticker],
            "Target_R1": r1s[ticker],
            "Target_R2": r2s[ticker],
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


@pytest.mark.parametrize(
    ("entry_model", "expected_entry_idx"),
    [("next_open", 1), ("same_close", 0)],
)
def test_entry_model_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_model: str, expected_entry_idx: int
) -> None:
    dates = pd.date_range("2024-01-02", periods=8, freq="B")
    history = _make_history_frame(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(dates[0]))
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", entry_model)
    monkeypatch.setattr(cfg, "BACKTEST_MAX_HOLD_DAYS", 3)
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)

    result = backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA"]
    )
    entry_row = result.trades[result.trades["fill_type"] == "entry"].iloc[0]
    assert entry_row["date"] == dates[expected_entry_idx].date().isoformat()


def test_backtest_exit_priority_and_determinism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=8, freq="B")
    history = _make_history_frame(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(dates[0]))
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "next_open")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_HOLD_DAYS", 3)
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)

    out_dir_1 = tmp_path / "run1"
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(out_dir_1))
    result_1 = backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA", "BBB", "CCC"]
    )

    trades = result_1.trades
    aaa_trades = trades[trades["symbol"] == "AAA"]
    bbb_trades = trades[trades["symbol"] == "BBB"]
    ccc_trades = trades[trades["symbol"] == "CCC"]

    assert "target_r2" in aaa_trades["reason"].tolist()
    assert "stop" in bbb_trades["reason"].tolist()
    assert "target_r1" not in bbb_trades["reason"].tolist()

    time_stop_row = ccc_trades[ccc_trades["reason"] == "time_stop"].iloc[0]
    assert time_stop_row["date"] == dates[3].date().isoformat()

    out_dir_2 = tmp_path / "run2"
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(out_dir_2))
    result_2 = backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA", "BBB", "CCC"]
    )

    trades_bytes_1 = (result_1.trades_path).read_bytes()
    trades_bytes_2 = (result_2.trades_path).read_bytes()
    assert hashlib.sha256(trades_bytes_1).hexdigest() == hashlib.sha256(trades_bytes_2).hexdigest()
