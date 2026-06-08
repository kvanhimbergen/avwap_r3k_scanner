"""Tests for BondCarry strategy."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.bond_carry import BondCarry


def _provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    n = 100
    return FixturePriceProvider({
        "SHY": linear_series(start=start, base=82, slope=0.005, wiggle=0.01, n=n),
        "IEF": linear_series(start=start, base=95, slope=0.0, wiggle=0.05, n=n),
        "TLT": linear_series(start=start, base=95, slope=0.05, wiggle=0.10, n=n),
        "EDV": linear_series(start=start, base=80, slope=0.10, wiggle=0.20, n=n),
        "TBT": linear_series(start=start, base=30, slope=-0.05, wiggle=0.10, n=n),
        "HYG": linear_series(start=start, base=78, slope=0.03, wiggle=0.05, n=n),
        "JNK": linear_series(start=start, base=92, slope=0.02, wiggle=0.04, n=n),
        "LQD": linear_series(start=start, base=110, slope=0.01, wiggle=0.05, n=n),
    })


def _state(*, yc: float | None = 0.0, cs: float | None = 0.0) -> SignalState:
    return SignalState(
        asof_date=date(2024, 4, 1),
        regime_label="NEUTRAL",
        regime_confidence=0.5,
        yield_curve_signal=yc,
        credit_spread_signal=cs,
    )


def test_weak_signals_default_to_short_end() -> None:
    """Both signals near 0 → default to SHY/IEF base carry."""
    out = BondCarry().compute(
        signal_state=_state(yc=0.5, cs=0.5),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert set(out.weights).issubset({"SHY", "IEF"})


def test_strong_yc_picks_tlt() -> None:
    """yield_curve > +1 → tilt long-duration (TLT)."""
    out = BondCarry().compute(
        signal_state=_state(yc=1.5, cs=0.0),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert "TLT" in out.weights


def test_very_strong_yc_adds_edv() -> None:
    """yield_curve > +2 → add EDV (extra long duration)."""
    out = BondCarry().compute(
        signal_state=_state(yc=2.5, cs=0.0),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert "EDV" in out.weights


def test_negative_yc_picks_tbt() -> None:
    """yield_curve < -1 → inverse treasuries."""
    out = BondCarry().compute(
        signal_state=_state(yc=-1.5, cs=0.0),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert "TBT" in out.weights


def test_positive_credit_picks_hyg() -> None:
    """credit_spread > +1 → HYG."""
    out = BondCarry().compute(
        signal_state=_state(yc=0.0, cs=1.5),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert "HYG" in out.weights


def test_regime_gate_always_one() -> None:
    out = BondCarry().compute(
        signal_state=_state(yc=0.0, cs=0.0),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert out.regime_gate == 1.0


def test_none_signals_default_to_short_end() -> None:
    """Both signals None → default to SHY/IEF base carry."""
    out = BondCarry().compute(
        signal_state=_state(yc=None, cs=None),
        price_provider=_provider(),
        asof_date=date(2024, 4, 1),
    )
    assert set(out.weights).issubset({"SHY", "IEF"})
