"""Tests for v6 signals."""

from __future__ import annotations

from datetime import date

import pytest

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signals.cross_asset_trend import compute_cross_asset_trend
from strategies.raec_v6.signals.vol_percentile import compute_vol_percentile


def _trend_up_provider() -> FixturePriceProvider:
    """Build prices where SPY is trending up, TLT trending down — clear regime."""
    start = date(2024, 1, 1)
    return FixturePriceProvider({
        "SPY": linear_series(start=start, base=400, slope=0.5, wiggle=0.2, n=320),
        "EEM": linear_series(start=start, base=40, slope=0.04, wiggle=0.02, n=320),
        "XLK": linear_series(start=start, base=150, slope=0.20, wiggle=0.10, n=320),
        "SHY": linear_series(start=start, base=82, slope=0.001, wiggle=0.005, n=320),
        "IEF": linear_series(start=start, base=95, slope=0.0, wiggle=0.05, n=320),
        "TLT": linear_series(start=start, base=95, slope=-0.05, wiggle=0.10, n=320),
        "HYG": linear_series(start=start, base=78, slope=0.02, wiggle=0.05, n=320),
        "PDBC": linear_series(start=start, base=14, slope=0.005, wiggle=0.01, n=320),
        "GLD": linear_series(start=start, base=180, slope=0.05, wiggle=0.04, n=320),
        "USO": linear_series(start=start, base=70, slope=0.08, wiggle=0.06, n=320),
        "IBIT": linear_series(start=start, base=45, slope=0.15, wiggle=0.10, n=320),
        "VIXY": linear_series(start=start, base=20, slope=-0.02, wiggle=0.05, n=320),
        "UUP": linear_series(start=start, base=28, slope=0.001, wiggle=0.01, n=320),
    })


def test_cross_asset_trend_returns_scores_for_classes_with_data() -> None:
    provider = _trend_up_provider()
    asof = date(2024, 1, 1) + (date(2024, 11, 15) - date(2024, 1, 1))  # ~10 months in
    scores = compute_cross_asset_trend(provider, asof)
    # Should produce scores for asset classes whose representative ETFs we provided.
    expected = {"equity_us_broad", "equity_intl", "sector", "bond_short", "bond_mid",
                "bond_long", "credit", "commodity_broad", "metal",
                "crypto", "vol_long", "currency_dollar"}
    assert set(scores.keys()) == expected


def test_cross_asset_trend_uptrend_positive_downtrend_negative() -> None:
    provider = _trend_up_provider()
    asof = date(2024, 11, 15)
    scores = compute_cross_asset_trend(provider, asof)
    assert scores["equity_us_broad"] > 0  # SPY up
    assert scores["bond_long"] < 0         # TLT down
    assert scores["crypto"] > 0            # IBIT up
    assert scores["vol_long"] < 0          # VIXY down


def test_cross_asset_trend_returns_empty_with_too_little_history() -> None:
    # All series too short → no scores possible.
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "SPY": linear_series(start=start, base=400, slope=0.5, n=100),  # need 210
    })
    scores = compute_cross_asset_trend(provider, date(2024, 4, 10))
    assert scores == {}


def test_vol_percentile_requires_long_history() -> None:
    # n=320 is needed (need 252 rolling vols + 20-day window).
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "SPY": linear_series(start=start, base=400, slope=0.5, wiggle=0.2, n=320),
    })
    out = compute_vol_percentile(provider, ["SPY"], date(2024, 11, 15))
    assert "SPY" in out
    assert 0.0 <= out["SPY"] <= 1.0


def test_vol_percentile_omits_symbols_with_short_history() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "SPY": linear_series(start=start, base=400, slope=0.5, n=320),
        "SHORTHIST": linear_series(start=start, base=10, slope=0.01, n=150),
    })
    out = compute_vol_percentile(provider, ["SPY", "SHORTHIST"], date(2024, 11, 15))
    assert "SPY" in out
    assert "SHORTHIST" not in out
