"""Tests for SectorRelativeStrength."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.sector_relative_strength import (
    SectorRelativeStrength,
    _SECTORS,
)


def _provider() -> FixturePriceProvider:
    """SPY trends moderately; some sectors crush SPY, others lag."""
    start = date(2024, 1, 1)
    n = 200
    data: dict[str, list[tuple[date, float]]] = {
        "SPY": linear_series(start=start, base=400, slope=0.30, wiggle=0.10, n=n),
        # Sectors that outperform SPY
        "XLK": linear_series(start=start, base=180, slope=0.80, wiggle=0.20, n=n),
        "SMH": linear_series(start=start, base=200, slope=0.90, wiggle=0.30, n=n),
        "XLC": linear_series(start=start, base=85, slope=0.50, wiggle=0.15, n=n),
        # Sector that ties with SPY
        "XLY": linear_series(start=start, base=170, slope=0.30, wiggle=0.10, n=n),
        # Sectors that underperform
        "XLE": linear_series(start=start, base=80, slope=0.05, wiggle=0.20, n=n),
        "XLF": linear_series(start=start, base=40, slope=0.05, wiggle=0.05, n=n),
        "XLV": linear_series(start=start, base=130, slope=0.05, wiggle=0.08, n=n),
        "XLI": linear_series(start=start, base=110, slope=0.10, wiggle=0.10, n=n),
        "XLP": linear_series(start=start, base=72, slope=0.02, wiggle=0.04, n=n),
        "XLU": linear_series(start=start, base=68, slope=0.04, wiggle=0.05, n=n),
        "XLB": linear_series(start=start, base=85, slope=0.05, wiggle=0.08, n=n),
        "XLRE": linear_series(start=start, base=40, slope=0.02, wiggle=0.04, n=n),
        "XBI": linear_series(start=start, base=85, slope=0.10, wiggle=0.15, n=n),
        "XME": linear_series(start=start, base=60, slope=0.05, wiggle=0.10, n=n),
    }
    return FixturePriceProvider(data)


def test_picks_top_k_by_rs_vs_spy() -> None:
    out = SectorRelativeStrength(top_k=3).compute(
        signal_state=SignalState(
            asof_date=date(2024, 9, 15),
            regime_label="RISK_ON",
            regime_confidence=0.8,
            cross_asset_trend={"equity_us_broad": 2.0},
        ),
        price_provider=_provider(),
        asof_date=date(2024, 9, 15),
    )
    held = set(out.weights)
    # The 3 fastest-rising sectors should be picked: XLK, SMH, XLC.
    assert held == {"XLK", "SMH", "XLC"}


def test_falling_market_zeros_regime_gate() -> None:
    out = SectorRelativeStrength(top_k=3).compute(
        signal_state=SignalState(
            asof_date=date(2024, 9, 15),
            regime_label="RISK_OFF",
            regime_confidence=0.8,
            cross_asset_trend={"equity_us_broad": -2.0},
        ),
        price_provider=_provider(),
        asof_date=date(2024, 9, 15),
    )
    assert out.regime_gate == 0.0


def test_no_positive_rs_returns_zero_conviction() -> None:
    """When every sector trails SPY, strategy stands down."""
    start = date(2024, 1, 1)
    n = 200
    data: dict[str, list[tuple[date, float]]] = {
        "SPY": linear_series(start=start, base=400, slope=1.0, wiggle=0.10, n=n),
    }
    for sym in _SECTORS:
        data[sym] = linear_series(start=start, base=100, slope=0.05, wiggle=0.05, n=n)
    out = SectorRelativeStrength(top_k=3).compute(
        signal_state=SignalState(
            asof_date=date(2024, 9, 15),
            regime_label="RISK_ON",
            regime_confidence=0.8,
            cross_asset_trend={"equity_us_broad": 2.0},
        ),
        price_provider=FixturePriceProvider(data),
        asof_date=date(2024, 9, 15),
    )
    assert out.weights == {}
    assert out.conviction == 0.0


def test_weights_capped() -> None:
    out = SectorRelativeStrength(top_k=4, max_single_weight=0.20).compute(
        signal_state=SignalState(
            asof_date=date(2024, 9, 15),
            regime_label="RISK_ON",
            regime_confidence=0.8,
            cross_asset_trend={"equity_us_broad": 2.0},
        ),
        price_provider=_provider(),
        asof_date=date(2024, 9, 15),
    )
    for w in out.weights.values():
        assert w <= 0.20 + 1e-9
