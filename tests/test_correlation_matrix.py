"""Tests for analytics.correlation_matrix (Phase 5)."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from analytics.correlation_matrix import compute_rolling_correlation, get_sector_exposure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(symbol_returns: dict[str, list[float]], base_price: float = 100.0) -> pd.DataFrame:
    """Build a flat OHLCV DataFrame from per-symbol daily return lists.

    All symbols share the same date index starting from 2024-01-02.
    """
    rows = []
    for symbol, returns in symbol_returns.items():
        price = base_price
        date = pd.Timestamp("2024-01-02")
        for ret in returns:
            price *= 1.0 + ret
            rows.append({"Date": date, "Symbol": symbol, "Close": price})
            date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# compute_rolling_correlation
# ---------------------------------------------------------------------------

class TestComputeRollingCorrelation:
    def test_perfectly_correlated(self):
        """Two symbols with identical returns should have correlation ~1.0."""
        returns = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01, 0.02, -0.015, 0.01, 0.005] * 5
        df = _make_ohlcv({"A": returns, "B": returns})
        corr = compute_rolling_correlation(df, ["A", "B"], lookback_days=100)
        assert not corr.empty
        assert corr.loc["A", "B"] == pytest.approx(1.0, abs=1e-6)
        assert corr.loc["B", "A"] == pytest.approx(1.0, abs=1e-6)

    def test_anti_correlated(self):
        """Two symbols with opposite returns should have correlation ~-1.0."""
        returns_a = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01, 0.02, -0.015, 0.01, 0.005] * 5
        returns_b = [-r for r in returns_a]
        df = _make_ohlcv({"A": returns_a, "B": returns_b})
        corr = compute_rolling_correlation(df, ["A", "B"], lookback_days=100)
        assert not corr.empty
        assert corr.loc["A", "B"] == pytest.approx(-1.0, abs=1e-6)

    def test_uncorrelated(self):
        """Random uncorrelated returns should have near-zero correlation."""
        rng = np.random.default_rng(42)
        n = 200
        returns_a = list(rng.normal(0, 0.02, n))
        returns_b = list(rng.normal(0, 0.02, n))
        df = _make_ohlcv({"A": returns_a, "B": returns_b})
        corr = compute_rolling_correlation(df, ["A", "B"], lookback_days=250)
        assert not corr.empty
        assert abs(corr.loc["A", "B"]) < 0.3  # should be close to 0

    def test_empty_symbols_list(self):
        """Empty symbols list returns empty DataFrame."""
        df = _make_ohlcv({"A": [0.01] * 10})
        corr = compute_rolling_correlation(df, [], lookback_days=60)
        assert corr.empty

    def test_missing_data_exclusion(self):
        """Symbol with too few data points is excluded from the matrix."""
        returns_a = [0.01, -0.02, 0.015, -0.005, 0.03] * 10  # 50 points
        returns_b = [0.01, -0.01, 0.02]  # only 3 points
        df = _make_ohlcv({"A": returns_a, "B": returns_b})
        corr = compute_rolling_correlation(df, ["A", "B"], lookback_days=60)
        # B should be excluded (3 < 60//2 = 30)
        assert "B" not in corr.columns
        assert "A" in corr.columns

    def test_single_symbol(self):
        """Single symbol returns a 1x1 matrix with self-correlation 1.0."""
        returns = [0.01, -0.02, 0.015, -0.005, 0.03] * 10
        df = _make_ohlcv({"A": returns})
        corr = compute_rolling_correlation(df, ["A"], lookback_days=60)
        assert not corr.empty
        assert corr.loc["A", "A"] == pytest.approx(1.0, abs=1e-6)

    def test_multiindex_input(self):
        """Handles MultiIndex (Date, Symbol) format."""
        returns_a = [0.01, -0.02, 0.015, -0.005, 0.03] * 10
        returns_b = [0.01, -0.02, 0.015, -0.005, 0.03] * 10
        df = _make_ohlcv({"A": returns_a, "B": returns_b})
        df = df.set_index(["Date", "Symbol"])
        corr = compute_rolling_correlation(df, ["A", "B"], lookback_days=100)
        assert not corr.empty
        assert corr.loc["A", "B"] == pytest.approx(1.0, abs=1e-6)

    def test_case_insensitive_symbols(self):
        """Symbols are normalised to uppercase."""
        returns = [0.01, -0.02, 0.015, -0.005, 0.03] * 10
        df = _make_ohlcv({"aapl": returns})
        corr = compute_rolling_correlation(df, ["AAPL"], lookback_days=60)
        assert "AAPL" in corr.columns

    def test_symmetric_matrix(self):
        """Correlation matrix should be symmetric."""
        rng = np.random.default_rng(99)
        n = 60
        df = _make_ohlcv({
            "A": list(rng.normal(0, 0.02, n)),
            "B": list(rng.normal(0, 0.02, n)),
            "C": list(rng.normal(0, 0.02, n)),
        })
        corr = compute_rolling_correlation(df, ["A", "B", "C"], lookback_days=100)
        pd.testing.assert_frame_equal(corr, corr.T)

    def test_three_symbols_mixed(self):
        """Three symbols: A~B correlated, C independent."""
        rng = np.random.default_rng(7)
        n = 100
        base = list(rng.normal(0, 0.02, n))
        noise = list(rng.normal(0, 0.002, n))
        returns_a = base
        returns_b = [b + n_ for b, n_ in zip(base, noise)]  # nearly identical to A
        returns_c = list(rng.normal(0, 0.02, n))  # independent

        df = _make_ohlcv({"A": returns_a, "B": returns_b, "C": returns_c})
        corr = compute_rolling_correlation(df, ["A", "B", "C"], lookback_days=150)
        assert corr.loc["A", "B"] > 0.9  # highly correlated
        assert abs(corr.loc["A", "C"]) < 0.5  # not highly correlated


# ---------------------------------------------------------------------------
# get_sector_exposure
# ---------------------------------------------------------------------------

class TestGetSectorExposure:
    def test_no_positions(self):
        result = get_sector_exposure([], "Technology", {"AAPL": "Technology"})
        assert result["sector"] == "Technology"
        assert result["current_exposure_pct"] == 0.0

    def test_single_sector(self):
        positions = [
            {"symbol": "AAPL", "notional": 10_000},
            {"symbol": "MSFT", "notional": 10_000},
        ]
        sector_map = {"AAPL": "Technology", "MSFT": "Technology"}
        result = get_sector_exposure(positions, "Technology", sector_map)
        assert result["sector"] == "Technology"
        assert result["current_exposure_pct"] == pytest.approx(1.0)

    def test_mixed_sectors(self):
        positions = [
            {"symbol": "AAPL", "notional": 10_000},
            {"symbol": "XOM", "notional": 10_000},
        ]
        sector_map = {"AAPL": "Technology", "XOM": "Energy"}
        result = get_sector_exposure(positions, "Technology", sector_map)
        assert result["sector"] == "Technology"
        assert result["current_exposure_pct"] == pytest.approx(0.5)

    def test_no_candidate_sector(self):
        result = get_sector_exposure(
            [{"symbol": "AAPL", "notional": 10_000}],
            None,
            {"AAPL": "Technology"},
        )
        assert result["sector"] == ""
        assert result["current_exposure_pct"] == 0.0
