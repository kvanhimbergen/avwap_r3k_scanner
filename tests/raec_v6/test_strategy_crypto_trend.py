"""Tests for CryptoTrend strategy."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategies.crypto_trend import CryptoTrend


def _state() -> SignalState:
    return SignalState(
        asof_date=date(2025, 6, 15),
        regime_label="NEUTRAL",
        regime_confidence=0.5,
    )


def _uptrend_provider() -> FixturePriceProvider:
    start = date(2024, 6, 1)
    n = 220
    return FixturePriceProvider({
        "IBIT": linear_series(start=start, base=40, slope=0.30, wiggle=0.50, n=n),
        "ETHA": linear_series(start=start, base=20, slope=0.10, wiggle=0.30, n=n),
        "BITI": linear_series(start=start, base=10, slope=-0.05, wiggle=0.10, n=n),
    })


def _downtrend_provider() -> FixturePriceProvider:
    start = date(2024, 6, 1)
    n = 220
    return FixturePriceProvider({
        "IBIT": linear_series(start=start, base=70, slope=-0.20, wiggle=0.50, n=n),
        "ETHA": linear_series(start=start, base=30, slope=-0.08, wiggle=0.30, n=n),
        "BITI": linear_series(start=start, base=5, slope=0.05, wiggle=0.10, n=n),
    })


def _flat_provider() -> FixturePriceProvider:
    start = date(2024, 6, 1)
    n = 220
    return FixturePriceProvider({
        "IBIT": linear_series(start=start, base=50, slope=0.01, wiggle=0.20, n=n),
        "ETHA": linear_series(start=start, base=25, slope=0.01, wiggle=0.10, n=n),
        "BITI": linear_series(start=start, base=7, slope=0.01, wiggle=0.05, n=n),
    })


def test_short_history_returns_zero() -> None:
    """Thin-history defense: <210 closes → empty/zero."""
    start = date(2025, 4, 1)
    short = FixturePriceProvider({
        "IBIT": linear_series(start=start, base=40, slope=0.30, n=50),
        "ETHA": linear_series(start=start, base=20, slope=0.10, n=50),
    })
    out = CryptoTrend().compute(signal_state=_state(), price_provider=short, asof_date=date(2025, 6, 15))
    assert out.conviction == 0.0
    assert out.weights == {}


def test_uptrend_goes_long_ibit() -> None:
    out = CryptoTrend().compute(
        signal_state=_state(),
        price_provider=_uptrend_provider(),
        asof_date=date(2025, 1, 5),
    )
    assert "IBIT" in out.weights
    assert "BITI" not in out.weights


def test_strong_downtrend_flips_to_biti() -> None:
    out = CryptoTrend().compute(
        signal_state=_state(),
        price_provider=_downtrend_provider(),
        asof_date=date(2025, 1, 5),
    )
    assert "BITI" in out.weights
    assert "IBIT" not in out.weights


def test_flat_market_stands_down() -> None:
    out = CryptoTrend().compute(
        signal_state=_state(),
        price_provider=_flat_provider(),
        asof_date=date(2025, 1, 5),
    )
    assert out.conviction == 0.0


def test_manifest_caps() -> None:
    cf = CryptoTrend().manifest
    assert cf.history_quality == "thin"
    assert cf.max_share_cap <= 0.05 + 1e-9
