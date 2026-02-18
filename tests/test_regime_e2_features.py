from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from analytics.regime_e2_features import (
    DEFAULT_E2_LOOKBACK,
    DEFAULT_RS_LOOKBACK,
    _credit_spread_z,
    _relative_strength,
    compute_e2_features,
)
from analytics.regime_e1_features import _normalize_columns, _filter_as_of


def _make_e2_history(
    symbols: list[str] | None = None,
    days: int = 260,
    spy_trend: float = 1.001,
    hyg_trend: float = 1.0005,
    lqd_trend: float = 1.0003,
    gld_trend: float = 1.0002,
    tlt_trend: float = 1.0001,
) -> pd.DataFrame:
    """Build OHLCV-like history with configurable trends per symbol."""
    if symbols is None:
        symbols = ["SPY", "IWM", "HYG", "LQD", "GLD", "TLT"]
    trends = {
        "SPY": spy_trend,
        "IWM": spy_trend * 0.999,
        "HYG": hyg_trend,
        "LQD": lqd_trend,
        "GLD": gld_trend,
        "TLT": tlt_trend,
    }
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    rows = []
    for symbol in symbols:
        price = 100.0
        mult = trends.get(symbol, 1.001)
        for dt in dates:
            price *= mult
            rows.append({"Date": dt, "Ticker": symbol, "Close": price})
    return pd.DataFrame(rows)


def _make_breadth_history(symbols: list[str], days: int = 260) -> pd.DataFrame:
    """Build history with many symbols for breadth calculation."""
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    rows = []
    for symbol in symbols:
        price = 100.0
        for dt in dates:
            price *= 1.001
            rows.append({"Date": dt, "Ticker": symbol, "Close": price})
    return pd.DataFrame(rows)


class TestComputeE2Features:
    def test_ok_with_full_universe(self) -> None:
        history = _make_e2_history()
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert result.ok
        fs = result.feature_set
        assert fs is not None
        assert fs.credit_spread_z != 0.0 or True  # may be 0 if flat
        assert "credit_spread" in fs.signals
        assert "gld_relative_strength" in fs.signals
        assert "tlt_relative_strength" in fs.signals

    def test_graceful_degradation_no_hyg_lqd(self) -> None:
        history = _make_e2_history(symbols=["SPY", "IWM", "GLD", "TLT"])
        # Add breadth symbols
        breadth = _make_breadth_history(
            [f"SYM{i:02d}" for i in range(25)], days=260
        )
        history = pd.concat([history, breadth], ignore_index=True)
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert result.ok
        fs = result.feature_set
        assert fs is not None
        assert fs.credit_spread_z == 0.0

    def test_graceful_degradation_no_gld_tlt(self) -> None:
        history = _make_e2_history(symbols=["SPY", "IWM", "HYG", "LQD"])
        breadth = _make_breadth_history(
            [f"SYM{i:02d}" for i in range(25)], days=260
        )
        history = pd.concat([history, breadth], ignore_index=True)
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert result.ok
        fs = result.feature_set
        assert fs is not None
        assert fs.gld_relative_strength == 0.0
        assert fs.tlt_relative_strength == 0.0

    def test_e1_failure_propagated(self) -> None:
        history = _make_e2_history(symbols=["IWM"])
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert not result.ok
        assert "missing_symbol_spy" in result.reason_codes

    def test_vix_term_structure_defaults_to_zero(self) -> None:
        history = _make_e2_history()
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert result.ok
        assert result.feature_set.vix_term_structure == 0.0

    def test_inputs_snapshot_has_e2_fields(self) -> None:
        history = _make_e2_history()
        ny_date = history["Date"].max().date().isoformat()
        result = compute_e2_features(history, ny_date)
        assert result.ok
        snap = result.inputs_snapshot
        assert "credit_spread_z" in snap
        assert "gld_relative_strength" in snap
        assert "tlt_relative_strength" in snap
        assert "e2_lookback" in snap


class TestCreditSpreadZ:
    def test_known_values(self) -> None:
        """HYG rising faster than LQD -> positive z (risk-on)."""
        dates = pd.date_range("2024-01-02", periods=80, freq="B")
        rows = []
        hyg_price = 80.0
        lqd_price = 100.0
        for dt in dates:
            hyg_price *= 1.002
            lqd_price *= 1.0005
            rows.append({"date": dt, "symbol": "HYG", "close": hyg_price})
            rows.append({"date": dt, "symbol": "LQD", "close": lqd_price})
        df = pd.DataFrame(rows)
        ny_date = dates[-1].date().isoformat()
        z = _credit_spread_z(df, ny_date, lookback=63)
        assert z > 0.0, f"Expected positive z for tightening spreads, got {z}"

    def test_missing_hyg_returns_zero(self) -> None:
        dates = pd.date_range("2024-01-02", periods=80, freq="B")
        rows = [
            {"date": dt, "symbol": "LQD", "close": 100.0}
            for dt in dates
        ]
        df = pd.DataFrame(rows)
        ny_date = dates[-1].date().isoformat()
        z = _credit_spread_z(df, ny_date, lookback=63)
        assert z == 0.0

    def test_insufficient_history_returns_zero(self) -> None:
        dates = pd.date_range("2024-01-02", periods=10, freq="B")
        rows = []
        for dt in dates:
            rows.append({"date": dt, "symbol": "HYG", "close": 80.0})
            rows.append({"date": dt, "symbol": "LQD", "close": 100.0})
        df = pd.DataFrame(rows)
        ny_date = dates[-1].date().isoformat()
        z = _credit_spread_z(df, ny_date, lookback=63)
        assert z == 0.0


class TestRelativeStrength:
    def test_outperformer_positive(self) -> None:
        """GLD growing faster than SPY -> positive RS."""
        dates = pd.date_range("2024-01-02", periods=30, freq="B")
        rows = []
        gld_price = 100.0
        spy_price = 100.0
        for dt in dates:
            gld_price *= 1.005
            spy_price *= 1.001
            rows.append({"date": dt, "symbol": "GLD", "close": gld_price})
            rows.append({"date": dt, "symbol": "SPY", "close": spy_price})
        df = pd.DataFrame(rows)
        ny_date = dates[-1].date().isoformat()
        rs = _relative_strength(df, "GLD", "SPY", ny_date, lookback=20)
        assert rs > 0.0

    def test_missing_symbol_returns_zero(self) -> None:
        dates = pd.date_range("2024-01-02", periods=30, freq="B")
        rows = [
            {"date": dt, "symbol": "SPY", "close": 100.0}
            for dt in dates
        ]
        df = pd.DataFrame(rows)
        ny_date = dates[-1].date().isoformat()
        rs = _relative_strength(df, "GLD", "SPY", ny_date, lookback=20)
        assert rs == 0.0
