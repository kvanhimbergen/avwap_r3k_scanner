"""Tests for EquityLeveragedMomentum: vol-percentile leverage gating."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.equity_leveraged_momentum import (
    EquityLeveragedMomentum,
    _LEVERAGED_SYMBOLS,
)


def _provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    n = 400  # need >=260 for momentum + 252 for z-score history
    return FixturePriceProvider({
        # Broad equity (non-leveraged) — uptrend
        "SPY": linear_series(start=start, base=400, slope=0.5, wiggle=0.2, n=n),
        "QQQ": linear_series(start=start, base=400, slope=0.55, wiggle=0.2, n=n),
        "IWM": linear_series(start=start, base=200, slope=0.20, wiggle=0.15, n=n),
        "VTI": linear_series(start=start, base=250, slope=0.30, wiggle=0.15, n=n),
        "MDY": linear_series(start=start, base=500, slope=0.30, wiggle=0.20, n=n),
        "VOO": linear_series(start=start, base=410, slope=0.50, wiggle=0.20, n=n),
        # Leveraged equity — extreme uptrend
        "TQQQ": linear_series(start=start, base=50, slope=0.90, wiggle=1.20, n=n),
        "UPRO": linear_series(start=start, base=60, slope=0.70, wiggle=0.90, n=n),
        "SSO": linear_series(start=start, base=70, slope=0.50, wiggle=0.50, n=n),
        # Sectors
        "XLE": linear_series(start=start, base=80, slope=0.10, wiggle=0.10, n=n),
        "XLK": linear_series(start=start, base=180, slope=0.40, wiggle=0.15, n=n),
        "XLF": linear_series(start=start, base=40, slope=0.05, wiggle=0.05, n=n),
        "XLV": linear_series(start=start, base=130, slope=0.10, wiggle=0.10, n=n),
        "XLI": linear_series(start=start, base=110, slope=0.15, wiggle=0.10, n=n),
        "XLY": linear_series(start=start, base=170, slope=0.20, wiggle=0.15, n=n),
        "XLP": linear_series(start=start, base=72, slope=0.02, wiggle=0.04, n=n),
        "XLU": linear_series(start=start, base=68, slope=0.04, wiggle=0.05, n=n),
        "XLB": linear_series(start=start, base=85, slope=0.10, wiggle=0.08, n=n),
        "XLRE": linear_series(start=start, base=40, slope=0.04, wiggle=0.04, n=n),
        "XLC": linear_series(start=start, base=85, slope=0.30, wiggle=0.15, n=n),
        "SMH": linear_series(start=start, base=180, slope=0.50, wiggle=0.20, n=n),
        "XBI": linear_series(start=start, base=85, slope=0.05, wiggle=0.10, n=n),
        "XME": linear_series(start=start, base=60, slope=0.10, wiggle=0.15, n=n),
        # Leveraged sectors
        "SOXL": linear_series(start=start, base=30, slope=0.85, wiggle=1.50, n=n),
        "TECL": linear_series(start=start, base=40, slope=0.80, wiggle=1.10, n=n),
        "FNGU": linear_series(start=start, base=25, slope=0.95, wiggle=1.80, n=n),
        "ERX": linear_series(start=start, base=50, slope=0.20, wiggle=0.50, n=n),
        "NVDL": linear_series(start=start, base=40, slope=0.80, wiggle=1.20, n=n),
        "FAS": linear_series(start=start, base=80, slope=0.30, wiggle=0.60, n=n),
        "LABU": linear_series(start=start, base=30, slope=0.20, wiggle=0.50, n=n),
    })


def _state(spy_vol_pct: float, eq_trend: float = 3.0) -> SignalState:
    return SignalState(
        asof_date=date(2024, 11, 15),
        regime_label="RISK_ON",
        regime_confidence=0.8,
        cross_asset_trend={"equity_us_broad": eq_trend},
        vol_percentile_252d={"SPY": spy_vol_pct},
    )


def test_low_vol_allows_leveraged() -> None:
    """SPY vol pct < 0.30 → leveraged ETFs allowed in top-K."""
    out = EquityLeveragedMomentum(top_k=5).compute(
        signal_state=_state(spy_vol_pct=0.15),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    held = set(out.weights)
    # In low-vol regime with strong fixture trends, leveraged symbols win.
    assert held & _LEVERAGED_SYMBOLS, f"Expected ≥1 leveraged in picks, got {held}"


def test_high_vol_excludes_leveraged() -> None:
    """SPY vol pct >= 0.70 → leveraged ETFs filtered out."""
    out = EquityLeveragedMomentum(top_k=5).compute(
        signal_state=_state(spy_vol_pct=0.85),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    held = set(out.weights)
    assert not (held & _LEVERAGED_SYMBOLS), f"Expected no leveraged in picks, got {held}"


def test_negative_equity_trend_zeros_regime_gate() -> None:
    """Cross-asset equity trend < 0 → regime_gate = 0.0."""
    out = EquityLeveragedMomentum(top_k=5).compute(
        signal_state=_state(spy_vol_pct=0.5, eq_trend=-1.0),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert out.regime_gate == 0.0


def test_strong_equity_trend_full_regime_gate() -> None:
    out = EquityLeveragedMomentum(top_k=5).compute(
        signal_state=_state(spy_vol_pct=0.5, eq_trend=2.5),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert out.regime_gate == 1.0


def test_weights_capped_per_symbol() -> None:
    out = EquityLeveragedMomentum(top_k=5, max_single_weight=0.25).compute(
        signal_state=_state(spy_vol_pct=0.5),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    for w in out.weights.values():
        assert w <= 0.25 + 1e-9


def test_weights_sum_under_one_when_capped() -> None:
    out = EquityLeveragedMomentum(top_k=5).compute(
        signal_state=_state(spy_vol_pct=0.5),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert sum(out.weights.values()) <= 1.0
