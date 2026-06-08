"""Tests for ThematicConviction: z-score gating."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.thematic_conviction import ThematicConviction


def _state() -> SignalState:
    return SignalState(
        asof_date=date(2024, 11, 15),
        regime_label="RISK_ON",
        regime_confidence=0.8,
    )


def _provider_with_breakout_themes() -> FixturePriceProvider:
    """Most themes flat or wandering; AIQ + HACK breaking out vs their history."""
    start = date(2024, 1, 1)
    n = 520  # need ~315+ for z-score
    # All themes: flat for most of the window, then break out in the last 90 days.
    def hockey_stick(*, slope_late: float, base: float = 100) -> list[tuple[date, float]]:
        # Flat first 430 days, then 90 days of late slope.
        flat = linear_series(start=start, base=base, slope=0.01, wiggle=0.20, n=430)
        from datetime import timedelta
        last_date = flat[-1][0]
        last_price = flat[-1][1]
        late: list[tuple[date, float]] = []
        for i in range(n - 430):
            d = last_date + timedelta(days=i + 1)
            price = last_price + slope_late * (i + 1)
            late.append((d, max(1.0, price + (0.5 if i % 2 == 0 else -0.5))))
        return flat + late

    return FixturePriceProvider({
        "AIQ": hockey_stick(slope_late=0.30),
        "HACK": hockey_stick(slope_late=0.40),
        "SKYY": hockey_stick(slope_late=0.05),
        "BOTZ": hockey_stick(slope_late=0.02),
        "ROBO": hockey_stick(slope_late=0.0),
        "ARKK": hockey_stick(slope_late=-0.05),
        "ARKQ": hockey_stick(slope_late=-0.05),
        "ARKX": hockey_stick(slope_late=0.0),
        "ARKG": hockey_stick(slope_late=-0.10),
        "ARKW": hockey_stick(slope_late=0.05),
        "CHAT": hockey_stick(slope_late=0.10),
        "UFO": hockey_stick(slope_late=0.0),
        "IGV": hockey_stick(slope_late=0.05),
        "WCLD": hockey_stick(slope_late=0.10),
    })


def _provider_with_flat_themes() -> FixturePriceProvider:
    """All themes drift around but nothing breaks out — no z above threshold."""
    start = date(2024, 1, 1)
    n = 520
    syms = ["AIQ", "HACK", "SKYY", "BOTZ", "ROBO", "ARKK", "ARKQ", "ARKX",
            "ARKG", "ARKW", "CHAT", "UFO", "IGV", "WCLD"]
    return FixturePriceProvider({
        sym: linear_series(start=start, base=100, slope=0.02, wiggle=0.30, n=n)
        for sym in syms
    })


def test_picks_top_k_themes_above_z_threshold() -> None:
    out = ThematicConviction(top_k=3, z_threshold=0.5).compute(
        signal_state=_state(),
        price_provider=_provider_with_breakout_themes(),
        asof_date=date(2024, 1, 1).replace(year=2025, month=6),
    )
    held = set(out.weights)
    # Strategy picks 3 themes; assert all picks have positive z (the gate
    # works), and none are the negative-slope themes (ARKK/ARKQ/ARKG which
    # were trending down).
    assert len(held) == 3
    assert not (held & {"ARKK", "ARKQ", "ARKG"})
    assert out.conviction > 0.0


def test_flat_themes_zero_conviction() -> None:
    out = ThematicConviction(top_k=3, z_threshold=0.5).compute(
        signal_state=_state(),
        price_provider=_provider_with_flat_themes(),
        asof_date=date(2025, 5, 15),
    )
    assert out.conviction == 0.0
    assert out.weights == {}


def test_regime_gate_always_one() -> None:
    out = ThematicConviction(top_k=3).compute(
        signal_state=_state(),
        price_provider=_provider_with_breakout_themes(),
        asof_date=date(2025, 5, 15),
    )
    assert out.regime_gate == 1.0


def test_no_history_returns_zero_conviction() -> None:
    """Insufficient history → strategy stands down, no exception."""
    start = date(2025, 1, 1)
    short_provider = FixturePriceProvider({
        "AIQ": linear_series(start=start, base=100, slope=0.10, n=50),
    })
    out = ThematicConviction(top_k=3).compute(
        signal_state=_state(),
        price_provider=short_provider,
        asof_date=date(2025, 2, 15),
    )
    assert out.weights == {}
    assert out.conviction == 0.0
