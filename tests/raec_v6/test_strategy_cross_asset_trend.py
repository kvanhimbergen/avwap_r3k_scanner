"""Tests for the CrossAssetTrend strategy."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.cross_asset_trend import CrossAssetTrend


def _provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    return FixturePriceProvider({
        "SPY": linear_series(start=start, base=400, slope=0.5, wiggle=0.2, n=320),
        "EEM": linear_series(start=start, base=40, slope=0.02, wiggle=0.03, n=320),
        "XLK": linear_series(start=start, base=150, slope=0.20, wiggle=0.10, n=320),
        "GLD": linear_series(start=start, base=180, slope=0.05, wiggle=0.04, n=320),
        "USO": linear_series(start=start, base=70, slope=0.08, wiggle=0.06, n=320),
        "IBIT": linear_series(start=start, base=45, slope=0.15, wiggle=0.10, n=320),
        "TLT": linear_series(start=start, base=95, slope=-0.05, wiggle=0.10, n=320),
    })


def _state_with_trend(scores: dict[str, float]) -> SignalState:
    return SignalState(
        asof_date=date(2024, 11, 15),
        regime_label="RISK_ON",
        regime_confidence=0.8,
        cross_asset_trend=scores,
    )


def test_picks_top_k_positive_trend_classes() -> None:
    strat = CrossAssetTrend(top_k=3)
    state = _state_with_trend({
        "equity_us_broad": 5.0,  # SPY trends up most
        "metal": 3.0,
        "crypto": 2.0,
        "bond_long": -2.0,       # excluded (negative)
        "energy": 1.0,
    })
    out = strat.compute(signal_state=state, price_provider=_provider(), asof_date=date(2024, 11, 15))
    # Top 3 positive: equity_us_broad (SPY), metal (GLD), crypto (IBIT)
    held = set(out.weights.keys())
    assert held == {"SPY", "GLD", "IBIT"}
    assert out.regime_gate == 1.0


def test_no_positive_classes_zero_conviction() -> None:
    strat = CrossAssetTrend(top_k=3)
    state = _state_with_trend({"equity_us_broad": -1.0, "metal": -2.0})
    out = strat.compute(signal_state=state, price_provider=_provider(), asof_date=date(2024, 11, 15))
    assert out.conviction == 0.0
    assert out.weights == {}


def test_weights_sum_le_one_and_capped_at_max_single() -> None:
    strat = CrossAssetTrend(top_k=4, max_single_weight=0.30)
    state = _state_with_trend({
        "equity_us_broad": 5.0, "metal": 5.0, "crypto": 5.0, "energy": 5.0
    })
    out = strat.compute(signal_state=state, price_provider=_provider(), asof_date=date(2024, 11, 15))
    assert sum(out.weights.values()) <= 1.0
    for w in out.weights.values():
        assert w <= 0.30 + 1e-9


def test_higher_dispersion_higher_conviction() -> None:
    strat = CrossAssetTrend(top_k=3)
    # Wide dispersion: one dominant class.
    state_wide = _state_with_trend({"equity_us_broad": 10.0, "metal": 1.0, "crypto": 0.5})
    out_wide = strat.compute(signal_state=state_wide, price_provider=_provider(), asof_date=date(2024, 11, 15))
    # Narrow dispersion: all classes look similar.
    state_narrow = _state_with_trend({"equity_us_broad": 1.0, "metal": 0.9, "crypto": 0.85})
    out_narrow = strat.compute(signal_state=state_narrow, price_provider=_provider(), asof_date=date(2024, 11, 15))
    assert out_wide.conviction > out_narrow.conviction


def test_manifest_exposes_caps_and_classes() -> None:
    strat = CrossAssetTrend()
    m = strat.manifest
    assert m.strategy_id == "V6_CROSS_ASSET_TREND"
    assert 0.0 < m.max_share_cap <= 1.0
    assert "equity_us_broad" in m.asset_classes
    assert "crypto" in m.asset_classes
