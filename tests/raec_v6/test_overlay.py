"""Tests for the overlay: vol forecast, exposure scale, DD breaker, shock detection."""

from __future__ import annotations

import random

import pytest

from strategies.raec_v6.overlay import (
    DEFAULT_DD_BREAKER_REARM,
    DEFAULT_DD_BREAKER_SCALE,
    DEFAULT_DD_BREAKER_THRESHOLD,
    apply_overlay,
)


def test_empty_history_scales_up_when_forecast_under_target() -> None:
    r = apply_overlay(
        book_targets={"SPY": 0.5},
        spy_realized_vol_60d=0.16,
        vix_implied=0.18,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=[],
    )
    # No data → forecast uses VIX discounted ×0.7 = 0.126; target = 1.5*0.16 = 0.24
    # raw_scale = 0.24 / 0.126 ≈ 1.90. SPY at 0.5 × 1.90 = 0.95 < 1.0,
    # so cap-to-full-deployment doesn't bite.
    assert pytest.approx(r.target_vol) == 0.24
    assert pytest.approx(r.forecast_vol, abs=1e-3) == 0.126
    assert pytest.approx(r.exposure_scale, abs=0.01) == 0.24 / 0.126
    assert pytest.approx(r.final_weights["SPY"], abs=0.01) == 0.5 * (0.24 / 0.126)


def test_cap_to_full_deployment_prevents_over_100_percent_book() -> None:
    """If scaling would push Σ weights > 1, cap scale so Σ = 1 exactly."""
    r = apply_overlay(
        book_targets={"SPY": 0.7, "QQQ": 0.2},  # already 0.9 of book
        spy_realized_vol_60d=0.16,
        vix_implied=0.10,  # forecast low → wants to lever up to 2.4×
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=[],
    )
    total = sum(r.final_weights.values())
    assert total <= 1.0 + 1e-6
    # And should be exactly at the deployment cap, not less.
    assert total > 0.95


def test_high_forecast_vol_scales_down() -> None:
    # VIX = 40 (vol spike), target = 1.5 * 16% = 24%
    # Forecast = max(...) ≥ 0.40, so scale = 0.24/0.40 = 0.6
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.40,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=[],
    )
    assert r.exposure_scale < 1.0
    # Scaled SPY weight = 1.0 * scale
    assert r.final_weights["SPY"] == r.exposure_scale


def test_dd_breaker_fires_at_threshold() -> None:
    """Equity peaks at 100, then drops to below 85 → DD < -15%, breaker fires."""
    curve = [100, 95, 90, 85, 82]
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=[-0.01] * 5,
        per_symbol_daily_returns={"SPY": [-0.01] * 5},
        equity_curve=curve,
    )
    assert r.dd_breaker_active is True


def test_dd_breaker_does_not_fire_above_threshold() -> None:
    """DD only -10% does NOT trip the 15% breaker."""
    curve = [100, 95, 92, 90]
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=curve,
    )
    assert r.dd_breaker_active is False


def test_dd_breaker_persists_until_rearm() -> None:
    """Breaker stays armed at DD=-12% (between threshold and rearm)."""
    curve = [100, 95, 90, 88]  # current DD -12% (between -15 trigger and -7 rearm)
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=curve,
        dd_breaker_currently_active=True,
    )
    assert r.dd_breaker_active is True


def test_dd_breaker_disarms_when_dd_heals() -> None:
    """Breaker re-arms when current DD heals to within -7% of peak."""
    curve = [100, 90, 95, 96]  # current DD = -4% (above -7% rearm)
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=curve,
        dd_breaker_currently_active=True,
    )
    assert r.dd_breaker_active is False


def test_dd_breaker_halves_exposure_when_active() -> None:
    """When DD breaker active, exposure scale cut by DEFAULT_DD_BREAKER_SCALE."""
    # Setup: vol low so raw scale = 1.0, then breaker should halve.
    r_off = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.10,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=[100, 95, 92, 90],
    )
    r_on = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.10,
        portfolio_daily_returns=[],
        per_symbol_daily_returns={},
        equity_curve=[100, 80, 78, 75],  # < -20% DD; triggers
    )
    assert r_off.dd_breaker_active is False
    assert r_on.dd_breaker_active is True
    assert r_on.exposure_scale < r_off.exposure_scale * 0.55  # roughly halved


def test_shock_day_detected_on_outlier_loss() -> None:
    """A -6% day vs trailing 60d of ~50bp stdev should trigger shock detection."""
    random.seed(0)
    body = [random.gauss(0.0005, 0.005) for _ in range(60)]
    returns = body + [-0.06]
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=returns,
        per_symbol_daily_returns={"SPY": returns},
        equity_curve=[100] * 60 + [94],
    )
    assert r.shock_day_detected is True
    assert r.freeze_rebalancing_until_idx == 2


def test_normal_day_not_shock() -> None:
    random.seed(0)
    body = [random.gauss(0.0005, 0.01) for _ in range(60)]
    returns = body + [-0.005]
    r = apply_overlay(
        book_targets={"SPY": 1.0},
        spy_realized_vol_60d=0.16,
        vix_implied=0.20,
        portfolio_daily_returns=returns,
        per_symbol_daily_returns={"SPY": returns},
        equity_curve=[100] * 61,
    )
    assert r.shock_day_detected is False
