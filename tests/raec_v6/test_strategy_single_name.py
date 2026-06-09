"""Tests for SingleNameMomentum strategy."""

from __future__ import annotations

from datetime import date

import pytest

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.single_name_universe import UNIVERSE
from strategies.raec_v6.strategies.single_name_momentum import (
    MODE_BACKTEST,
    SingleNameMomentum,
)


def _provider() -> FixturePriceProvider:
    """Build fixture with enough history for momentum + z-score on all
    universe names. Sloping different speeds so the strategy has to rank."""
    start = date(2024, 1, 1)
    n = 400
    series: dict[str, list[tuple[date, float]]] = {}
    # Add SPY (used by other signals indirectly even though this test
    # doesn't need it — keep the fixture self-contained).
    series["SPY"] = linear_series(start=start, base=400, slope=0.30, wiggle=0.10, n=n)
    # Universe names — give each a unique slope based on hash so we can
    # predict ordering. Mega-tech (NVDA/MSFT) get higher slopes.
    fast = {"NVDA", "META", "AAPL", "AMD"}
    slow = {"XOM", "CVX", "KO", "PG", "JNJ"}
    for sym in UNIVERSE:
        if sym in fast:
            series[sym] = linear_series(start=start, base=100, slope=0.40, wiggle=0.20, n=n)
        elif sym in slow:
            series[sym] = linear_series(start=start, base=100, slope=0.02, wiggle=0.05, n=n)
        else:
            series[sym] = linear_series(start=start, base=100, slope=0.20, wiggle=0.15, n=n)
    return FixturePriceProvider(series)


def _state(eq_trend: float = 2.0) -> SignalState:
    return SignalState(
        asof_date=date(2024, 11, 15),
        regime_label="RISK_ON",
        regime_confidence=0.8,
        cross_asset_trend={"equity_us_broad": eq_trend},
    )


def test_picks_top_k() -> None:
    out = SingleNameMomentum(top_k=5, mode=MODE_BACKTEST).compute(
        signal_state=_state(),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert len(out.weights) <= 5


def test_picks_include_fastest_movers_subject_to_sector_cap() -> None:
    out = SingleNameMomentum(top_k=5, mode=MODE_BACKTEST).compute(
        signal_state=_state(),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    held = set(out.weights)
    # At least one of the fast movers (NVDA/META/AAPL/AMD) should be in.
    assert held & {"NVDA", "META", "AAPL", "AMD"}


def test_sector_cap_caps_tech_at_3() -> None:
    """Even though 4 of the fastest movers are tech-adjacent (NVDA/META/
    AAPL/AMD), sector cap limits to ≤3 from any single sector. META and
    AAPL/GOOGL spread across Communication/Tech, so we expect ≤3 Tech."""
    out = SingleNameMomentum(top_k=5, mode=MODE_BACKTEST).compute(
        signal_state=_state(),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    from strategies.raec_v6.single_name_universe import SECTOR_MAP
    sector_counts: dict[str, int] = {}
    for sym in out.weights:
        sec = SECTOR_MAP[sym]
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    for sec, cnt in sector_counts.items():
        assert cnt <= 3, f"sector {sec} has {cnt} picks (cap 3)"


def test_negative_equity_trend_zeros_gate() -> None:
    out = SingleNameMomentum(top_k=5, mode=MODE_BACKTEST).compute(
        signal_state=_state(eq_trend=-1.0),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert out.regime_gate == 0.0


def test_strong_equity_trend_full_gate() -> None:
    out = SingleNameMomentum(top_k=5, mode=MODE_BACKTEST).compute(
        signal_state=_state(eq_trend=2.5),
        price_provider=_provider(),
        asof_date=date(2024, 11, 15),
    )
    assert out.regime_gate == 1.0


def test_manifest_caps() -> None:
    m = SingleNameMomentum().manifest
    assert m.max_share_cap <= 0.15 + 1e-9
    assert m.history_quality == "moderate"


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="mode must be"):
        SingleNameMomentum(mode="invalid")
