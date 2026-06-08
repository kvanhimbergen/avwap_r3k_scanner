"""Tests for CrisisAlpha strategy: regime + vol-pct double-gate."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.crisis_alpha import CrisisAlpha


def _provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    n = 80
    return FixturePriceProvider({
        "PSQ": linear_series(start=start, base=10, slope=0.02, wiggle=0.10, n=n),
        "SDS": linear_series(start=start, base=20, slope=0.05, wiggle=0.20, n=n),
        "SH": linear_series(start=start, base=12, slope=0.01, wiggle=0.05, n=n),
        "GLD": linear_series(start=start, base=180, slope=0.05, wiggle=0.10, n=n),
    })


def _state(label: str, vol_pct: float) -> SignalState:
    return SignalState(
        asof_date=date(2024, 4, 1),
        regime_label=label,
        regime_confidence=0.9,
        vol_percentile_252d={"SPY": vol_pct},
    )


def test_risk_on_gate_off() -> None:
    out = CrisisAlpha().compute(
        signal_state=_state("RISK_ON", 0.95),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 0.0
    assert out.weights == {}


def test_stressed_moderate_vol_half_gate() -> None:
    out = CrisisAlpha().compute(
        signal_state=_state("STRESSED", 0.70),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 0.5
    assert out.weights  # holdings deployed


def test_stressed_extreme_vol_full_gate() -> None:
    out = CrisisAlpha().compute(
        signal_state=_state("STRESSED", 0.95),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 1.0
    assert set(out.weights) == {"PSQ", "SDS", "SH", "GLD"}


def test_neutral_high_vol_gate_off() -> None:
    """Regime must be STRESSED for the gate to fire — high vol alone isn't enough."""
    out = CrisisAlpha().compute(
        signal_state=_state("NEUTRAL", 0.95),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 0.0


def test_stressed_low_vol_pct_gate_off() -> None:
    """STRESSED label without high vol → still off (double-gate)."""
    out = CrisisAlpha().compute(
        signal_state=_state("STRESSED", 0.40),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 0.0


def test_manifest_caps() -> None:
    m = CrisisAlpha().manifest
    assert m.max_share_cap <= 0.10 + 1e-9
    assert m.history_quality == "thin"


def test_weights_inverse_vol_normalized() -> None:
    out = CrisisAlpha().compute(
        signal_state=_state("STRESSED", 0.95),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert abs(sum(out.weights.values()) - 1.0) < 0.05
