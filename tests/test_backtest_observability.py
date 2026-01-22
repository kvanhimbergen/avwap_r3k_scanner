from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

import backtest_engine
from config import cfg
import scan_engine


def _make_sparse_history(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for idx, dt in enumerate(dates):
        rows.append(
            {
                "Date": dt,
                "Ticker": "BBB",
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Volume": 1_000_000.0,
            }
        )
        if idx != 1:
            rows.append(
                {
                    "Date": dt,
                    "Ticker": "AAA",
                    "Open": 50.0,
                    "High": 51.0,
                    "Low": 49.0,
                    "Close": 50.0,
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
        if as_of_dt is None or pd.Timestamp(as_of_dt).normalize() != signal_date.normalize():
            return None
        if ticker != "AAA":
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
            "Stop_Loss": 45.0,
            "Target_R1": 55.0,
            "Target_R2": 60.0,
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
                    "High": 101.0,
                    "Low": 99.0,
                    "Close": 100.0,
                    "Volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _setup_offline_scan(monkeypatch: pytest.MonkeyPatch, history: pd.DataFrame) -> None:
    class _DummyBars:
        def __init__(self) -> None:
            self.df = pd.DataFrame()

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_stock_bars(self, *args, **kwargs) -> _DummyBars:
            return _DummyBars()

    universe = pd.DataFrame(
        [
            {"Ticker": "AAA", "Sector": "Tech"},
            {"Ticker": "BBB", "Sector": "Finance"},
        ]
    )

    monkeypatch.setattr(scan_engine, "StockHistoricalDataClient", _DummyClient)
    monkeypatch.setattr(scan_engine, "load_universe", lambda allow_network=True: universe)
    monkeypatch.setattr(scan_engine, "build_liquidity_snapshot", lambda *args, **kwargs: universe)
    monkeypatch.setattr(scan_engine, "get_market_regime", lambda *args, **kwargs: True)
    monkeypatch.setattr(scan_engine, "is_near_earnings_cached", lambda *args, **kwargs: False)
    monkeypatch.setattr(scan_engine, "load_bad_tickers", lambda: [])
    monkeypatch.setattr(scan_engine.cs, "read_parquet", lambda *args, **kwargs: history.copy())
    monkeypatch.setattr(scan_engine.cs, "upsert_history", lambda current, new: current)
    monkeypatch.setattr(scan_engine.cs, "write_parquet", lambda *args, **kwargs: None)


def test_backtest_scan_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    history = _make_sparse_history(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(dates[0]))
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_MODEL", "next_open")
    monkeypatch.setattr(cfg, "BACKTEST_MAX_HOLD_DAYS", 2)
    monkeypatch.setattr(cfg, "BACKTEST_INITIAL_CASH", 100_000.0)
    monkeypatch.setattr(cfg, "BACKTEST_SLIPPAGE_BPS", 5.0)
    monkeypatch.setattr(cfg, "BACKTEST_ENTRY_LIMIT_BPS", 1.0)

    backtest_engine.run_backtest(
        cfg, dates[0].date(), dates[-1].date(), universe_symbols=["AAA", "BBB"]
    )

    diagnostics_path = tmp_path / "out" / "scan_diagnostics.csv"
    assert diagnostics_path.exists()

    diagnostics = pd.read_csv(diagnostics_path)
    for col in [
        "entries_skipped_max_positions",
        "entries_skipped_cash",
        "entries_skipped_gross_exposure",
        "entries_skipped_size_zero",
        "entries_missed_limit",
        "invalidations_today",
        "stops_today",
        "targets_r1_today",
        "targets_r2_today",
    ]:
        assert col in diagnostics.columns
    first_day = diagnostics[diagnostics["date"] == dates[0].date().isoformat()].iloc[0]
    second_day = diagnostics[diagnostics["date"] == dates[1].date().isoformat()].iloc[0]

    assert first_day["universe_symbols"] == 2
    assert first_day["symbols_with_ohlcv_today"] == 2
    assert first_day["symbols_scanned"] == 2
    assert first_day["candidates_total"] == 1
    assert first_day["candidates_with_required_fields"] == 1
    assert first_day["entries_placed"] == 1
    assert first_day["entries_filled"] == 0

    assert second_day["candidates_skipped_missing_next_open_bar"] == 1
    assert second_day["entries_filled"] == 0


def test_backtest_scan_parity_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-02", periods=90, freq="B")
    history = _make_history_frame(dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_candidate_row_factory(dates[-1]))
    _setup_offline_scan(monkeypatch, history)

    history_indexed = backtest_engine.load_ohlcv_history(history_path)
    sector_map = {"AAA": "Tech", "BBB": "Finance"}
    backtest_candidates = backtest_engine._scan_as_of(
        history_indexed, ["AAA", "BBB"], sector_map, dates[-1], cfg
    )
    scan_candidates = scan_engine.run_scan(cfg, as_of_dt=dates[-1])

    backtest_candidates = backtest_candidates.sort_values(["Symbol"]).reset_index(drop=True)
    scan_candidates = scan_candidates.sort_values(["Symbol"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(backtest_candidates, scan_candidates)
