"""Tests for portfolio.dynamic_exposure — Phase 6: Dynamic Gross Exposure."""

from __future__ import annotations

import math

import pytest

from portfolio.dynamic_exposure import (
    DynamicExposureResult,
    compute_realized_portfolio_vol,
    compute_target_exposure,
)


# ---------------------------------------------------------------------------
# compute_realized_portfolio_vol
# ---------------------------------------------------------------------------


class TestComputeRealizedPortfolioVol:
    def test_known_daily_std(self):
        """daily std = 0.01 -> annualized ~15.87%"""
        # 100 data points with exactly 0.01 std is hard to construct,
        # but we can verify the math: std * sqrt(252)
        daily_std = 0.01
        expected_annualized = daily_std * math.sqrt(252)

        # Create a series whose sample std ≈ 0.01
        # Use alternating +/- values around 0 so mean ≈ 0
        n = 100
        series = [0.01 if i % 2 == 0 else -0.01 for i in range(n)]
        vol = compute_realized_portfolio_vol(series, lookback_days=n)

        # The sample std of [0.01, -0.01, ...] is exactly 0.01 (for large n)
        assert abs(vol - expected_annualized) < 0.01

    def test_fewer_than_5_points_returns_zero(self):
        assert compute_realized_portfolio_vol([0.01, 0.02, 0.03, -0.01]) == 0.0

    def test_exactly_5_points(self):
        series = [0.01, -0.01, 0.02, -0.02, 0.01]
        vol = compute_realized_portfolio_vol(series, lookback_days=5)
        assert vol > 0.0

    def test_all_zeros_returns_zero(self):
        assert compute_realized_portfolio_vol([0.0] * 20) == 0.0

    def test_lookback_truncation(self):
        # 30 values but lookback=10 — only last 10 used
        long_series = [0.0] * 20 + [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
        vol_full = compute_realized_portfolio_vol(long_series, lookback_days=30)
        vol_last10 = compute_realized_portfolio_vol(long_series, lookback_days=10)
        # Last 10 have non-zero variance; full 30 includes 20 zeros so vol should differ
        assert vol_last10 > vol_full

    def test_empty_series(self):
        assert compute_realized_portfolio_vol([]) == 0.0

    def test_single_value(self):
        assert compute_realized_portfolio_vol([0.05]) == 0.0

    def test_lookback_zero(self):
        assert compute_realized_portfolio_vol([0.01, 0.02, 0.03, 0.04, 0.05], lookback_days=0) == 0.0


# ---------------------------------------------------------------------------
# compute_target_exposure
# ---------------------------------------------------------------------------


class TestComputeTargetExposure:
    def test_basic_target(self):
        """realized_vol=0.20, target=0.15 -> raw_target=0.75"""
        result = compute_target_exposure(0.20, 0.15, regime_multiplier=1.0)
        assert isinstance(result, DynamicExposureResult)
        assert abs(result.raw_target - 0.75) < 1e-9
        assert abs(result.target_exposure - 0.75) < 1e-9
        assert result.regime_multiplier == 1.0
        assert result.realized_vol == 0.20
        assert result.clamped is False

    def test_floor_clamping(self):
        """Extremely high vol -> target hits floor"""
        result = compute_target_exposure(1.0, 0.15, regime_multiplier=1.0, floor=0.2)
        # raw_target = 0.15 / 1.0 = 0.15, regime_adjusted = 0.15
        # 0.15 < 0.2 floor -> clamped to 0.2
        assert abs(result.target_exposure - 0.2) < 1e-9
        assert result.clamped is True

    def test_ceiling_clamping(self):
        """Extremely low vol -> target hits ceiling"""
        result = compute_target_exposure(0.05, 0.15, regime_multiplier=1.0, ceiling=1.0)
        # raw_target = 0.15 / 0.05 = 3.0, regime_adjusted = 3.0
        # 3.0 > 1.0 ceiling -> clamped to 1.0
        assert abs(result.target_exposure - 1.0) < 1e-9
        assert result.clamped is True

    def test_regime_multiplier_halves(self):
        """regime_multiplier=0.5 halves the target"""
        result = compute_target_exposure(0.15, 0.15, regime_multiplier=0.5)
        # raw_target = 1.0, regime_adjusted = 0.5
        assert abs(result.raw_target - 1.0) < 1e-9
        assert abs(result.target_exposure - 0.5) < 1e-9
        assert result.clamped is False

    def test_regime_multiplier_zero(self):
        """regime_multiplier=0 -> regime_adjusted=0 -> clamped to floor"""
        result = compute_target_exposure(0.15, 0.15, regime_multiplier=0.0, floor=0.2)
        assert abs(result.target_exposure - 0.2) < 1e-9
        assert result.clamped is True

    def test_zero_vol_returns_ceiling_times_regime(self):
        result = compute_target_exposure(0.0, 0.15, regime_multiplier=0.8, ceiling=1.0)
        # When vol <= 0: raw_target = ceiling, regime_adjusted = ceiling * regime
        assert abs(result.target_exposure - 0.8) < 1e-9
        assert result.clamped is False

    def test_negative_vol_returns_ceiling_times_regime(self):
        result = compute_target_exposure(-0.1, 0.15, regime_multiplier=1.0, ceiling=1.0)
        assert abs(result.target_exposure - 1.0) < 1e-9

    def test_custom_floor_ceiling(self):
        result = compute_target_exposure(0.30, 0.15, regime_multiplier=1.0, floor=0.3, ceiling=0.9)
        # raw_target = 0.5, within bounds
        assert abs(result.target_exposure - 0.5) < 1e-9
        assert result.clamped is False

    def test_result_dataclass_fields(self):
        result = compute_target_exposure(0.20, 0.15, regime_multiplier=0.9)
        assert hasattr(result, "target_exposure")
        assert hasattr(result, "realized_vol")
        assert hasattr(result, "regime_multiplier")
        assert hasattr(result, "raw_target")
        assert hasattr(result, "clamped")


# ---------------------------------------------------------------------------
# Integration: vol computation -> target exposure
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_vol_to_target_pipeline(self):
        """End-to-end: daily returns -> vol -> target exposure."""
        # Generate daily returns with known properties
        daily_returns = [0.01, -0.01] * 15  # 30 days of alternating returns
        vol = compute_realized_portfolio_vol(daily_returns, lookback_days=20)
        assert vol > 0.0

        result = compute_target_exposure(vol, 0.15, regime_multiplier=1.0)
        assert 0.2 <= result.target_exposure <= 1.0

    def test_stable_market_high_exposure(self):
        """Low vol market should produce high exposure target."""
        # Very small daily moves
        daily_returns = [0.001, -0.001] * 15
        vol = compute_realized_portfolio_vol(daily_returns, lookback_days=20)
        result = compute_target_exposure(vol, 0.15, regime_multiplier=1.0)
        # Low vol -> high raw target -> likely ceiling
        assert result.target_exposure >= 0.8

    def test_volatile_market_low_exposure(self):
        """High vol market should produce low exposure target."""
        # Large daily moves
        daily_returns = [0.05, -0.05] * 15
        vol = compute_realized_portfolio_vol(daily_returns, lookback_days=20)
        result = compute_target_exposure(vol, 0.15, regime_multiplier=1.0)
        # High vol -> low raw target -> likely floor
        assert result.target_exposure <= 0.3
