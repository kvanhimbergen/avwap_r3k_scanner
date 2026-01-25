from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

import scan_engine


def _make_history(tickers: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    frames = []
    for idx, ticker in enumerate(tickers):
        close = np.linspace(100.0 + idx, 110.0 + idx, len(dates))
        frame = pd.DataFrame(
            {
                "Date": dates,
                "Ticker": ticker,
                "Open": close - 0.5,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": np.full(len(dates), 1_000_000.0),
            }
        )
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


class _FakeAlpacaClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], object]] = []

    def get_stock_bars(self, req) -> SimpleNamespace:
        symbols = list(req.symbol_or_symbols)
        self.calls.append((symbols, req.start))
        now = pd.Timestamp("2024-04-01")
        rows = [
            {
                "symbol": symbol,
                "timestamp": now,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1_000_000,
            }
            for symbol in symbols
        ]
        return SimpleNamespace(df=pd.DataFrame(rows))


def test_run_scan_refreshes_benchmarks_without_scanning(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark_set = {"SPY", "IWM", "IWV", "QQQ"}
    filtered = ["AAA"]
    all_symbols = filtered + sorted(benchmark_set)
    dates = pd.date_range("2024-01-02", periods=90, freq="B")

    history = _make_history(all_symbols, dates)
    fake_client = _FakeAlpacaClient()
    scanned: list[str] = []

    def _fake_build_candidate_row(df, ticker, sector, setup_rules, *, as_of_dt=None, direction="Long"):
        scanned.append(ticker)
        return {"Symbol": ticker}

    monkeypatch.setattr(scan_engine, "StockHistoricalDataClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(scan_engine, "get_market_regime", lambda *_: True)
    monkeypatch.setattr(scan_engine, "load_setup_rules", lambda: {})
    monkeypatch.setattr(
        scan_engine,
        "build_liquidity_snapshot",
        lambda universe, client: pd.DataFrame([{"Ticker": "AAA", "Sector": "Tech"}]),
    )
    monkeypatch.setattr(scan_engine, "load_universe", lambda: ["AAA"])
    monkeypatch.setattr(scan_engine, "is_near_earnings_cached", lambda *_: False)
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_build_candidate_row)
    monkeypatch.setattr(scan_engine.cs, "read_parquet", lambda *_: history.copy())
    monkeypatch.setattr(scan_engine.cs, "write_parquet", lambda *_: None)

    result = scan_engine.run_scan(scan_engine.default_cfg, as_of_dt=dates[-1])

    assert set(result["Symbol"]) == {"AAA"}
    assert scanned == ["AAA"]
    assert any(benchmark_set.issubset(set(call[0])) for call in fake_client.calls)


def test_run_scan_backfills_missing_benchmark_history(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark_set = {"SPY", "IWM", "IWV", "QQQ"}
    filtered = ["AAA"]
    dates = pd.date_range("2024-01-02", periods=90, freq="B")
    history = _make_history(filtered, dates)

    fixed_now = pd.Timestamp("2024-04-01")

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    fake_client = _FakeAlpacaClient()
    scanned: list[str] = []

    def _fake_build_candidate_row(df, ticker, sector, setup_rules, *, as_of_dt=None, direction="Long"):
        scanned.append(ticker)
        return {"Symbol": ticker}

    monkeypatch.setattr(scan_engine, "datetime", _FixedDatetime)
    monkeypatch.setattr(scan_engine, "StockHistoricalDataClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(scan_engine, "get_market_regime", lambda *_: True)
    monkeypatch.setattr(scan_engine, "load_setup_rules", lambda: {})
    monkeypatch.setattr(
        scan_engine,
        "build_liquidity_snapshot",
        lambda universe, client: pd.DataFrame([{"Ticker": "AAA", "Sector": "Tech"}]),
    )
    monkeypatch.setattr(scan_engine, "load_universe", lambda: ["AAA"])
    monkeypatch.setattr(scan_engine, "is_near_earnings_cached", lambda *_: False)
    monkeypatch.setattr(scan_engine, "build_candidate_row", _fake_build_candidate_row)
    monkeypatch.setattr(scan_engine.cs, "read_parquet", lambda *_: history.copy())
    monkeypatch.setattr(scan_engine.cs, "write_parquet", lambda *_: None)

    scan_engine.run_scan(scan_engine.default_cfg, as_of_dt=dates[-1])

    expected_start = fixed_now - scan_engine.timedelta(days=scan_engine.BENCHMARK_BACKFILL_DAYS)
    assert any(benchmark_set.issubset(set(call[0])) and call[1] == expected_start for call in fake_client.calls)


def test_run_scan_skips_sufficient_benchmark_history(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark_set = {"SPY", "IWM", "IWV", "QQQ"}
    filtered = ["AAA"]
    dates = pd.date_range("2023-01-02", periods=scan_engine.BENCHMARK_MIN_BARS + 5, freq="B")
    history = _make_history(filtered + sorted(benchmark_set), dates)

    fake_client = _FakeAlpacaClient()

    monkeypatch.setattr(scan_engine, "StockHistoricalDataClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(scan_engine, "get_market_regime", lambda *_: True)
    monkeypatch.setattr(scan_engine, "load_setup_rules", lambda: {})
    monkeypatch.setattr(
        scan_engine,
        "build_liquidity_snapshot",
        lambda universe, client: pd.DataFrame([{"Ticker": "AAA", "Sector": "Tech"}]),
    )
    monkeypatch.setattr(scan_engine, "load_universe", lambda: ["AAA"])
    monkeypatch.setattr(scan_engine, "is_near_earnings_cached", lambda *_: False)
    monkeypatch.setattr(scan_engine, "build_candidate_row", lambda *_args, **_kwargs: {"Symbol": "AAA"})
    monkeypatch.setattr(scan_engine.cs, "read_parquet", lambda *_: history.copy())
    monkeypatch.setattr(scan_engine.cs, "write_parquet", lambda *_: None)

    scan_engine.run_scan(scan_engine.default_cfg, as_of_dt=dates[-1])

    assert not any(benchmark_set.issubset(set(call[0])) for call in fake_client.calls)
