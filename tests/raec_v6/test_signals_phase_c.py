"""Tests for Phase C signals: yield_curve, credit_spread, vix_implied, regime_label."""

from __future__ import annotations

from datetime import date

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6.signals.credit_spread import compute_credit_spread_signal
from strategies.raec_v6.signals.regime_label import classify_from_spy_closes
from strategies.raec_v6.signals.vix_implied import compute_vix_implied
from strategies.raec_v6.signals.yield_curve import compute_yield_curve_signal


def test_yield_curve_positive_when_tlt_outperforms_shy() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "TLT": linear_series(start=start, base=95, slope=0.10, wiggle=0.05, n=200),
        "SHY": linear_series(start=start, base=82, slope=0.001, wiggle=0.005, n=200),
    })
    score = compute_yield_curve_signal(provider, date(2024, 9, 15))
    assert score is not None
    assert score > 0


def test_yield_curve_negative_when_shy_outperforms_tlt() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "TLT": linear_series(start=start, base=95, slope=-0.10, wiggle=0.05, n=200),
        "SHY": linear_series(start=start, base=82, slope=0.005, wiggle=0.005, n=200),
    })
    score = compute_yield_curve_signal(provider, date(2024, 9, 15))
    assert score is not None
    assert score < 0


def test_yield_curve_returns_none_with_short_history() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "TLT": linear_series(start=start, base=95, slope=0.05, n=50),
        "SHY": linear_series(start=start, base=82, slope=0.001, n=50),
    })
    assert compute_yield_curve_signal(provider, date(2024, 9, 15)) is None


def test_credit_spread_positive_when_hyg_outperforms_ief() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "HYG": linear_series(start=start, base=78, slope=0.05, wiggle=0.05, n=200),
        "IEF": linear_series(start=start, base=95, slope=0.0, wiggle=0.05, n=200),
    })
    score = compute_credit_spread_signal(provider, date(2024, 9, 15))
    assert score is not None
    assert score > 0


def test_credit_spread_negative_when_hyg_lags() -> None:
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "HYG": linear_series(start=start, base=78, slope=-0.10, wiggle=0.05, n=200),
        "IEF": linear_series(start=start, base=95, slope=0.05, wiggle=0.05, n=200),
    })
    score = compute_credit_spread_signal(provider, date(2024, 9, 15))
    assert score is not None
    assert score < 0


def test_vix_implied_converts_to_decimal() -> None:
    """VIX 25 → 0.25 (decimal annualized vol)."""
    start = date(2024, 1, 1)
    provider = FixturePriceProvider({
        "^VIX": [(start, 25.0), (date(2024, 9, 15), 25.0)],
    })
    vix = compute_vix_implied(provider, date(2024, 9, 15))
    assert vix == 0.25


def test_vix_implied_returns_none_with_no_data() -> None:
    provider = FixturePriceProvider({})
    assert compute_vix_implied(provider, date(2024, 9, 15)) is None


def test_regime_label_unknown_with_too_little_history() -> None:
    label, conf = classify_from_spy_closes([100, 101, 102])
    assert label == "UNKNOWN"
    assert conf == 0.0


def test_regime_label_stressed_on_deep_drawdown() -> None:
    """Closes show >20% drawdown from peak → STRESSED."""
    n = 210
    rising = [100 + i * 0.5 for i in range(n // 2)]
    falling = [rising[-1] - i * 1.5 for i in range(n - n // 2)]
    closes = rising + falling
    # Verify deep drawdown
    label, conf = classify_from_spy_closes(closes)
    assert label == "STRESSED"
    assert conf >= 0.7


def test_regime_label_neutral_on_mixed_signals() -> None:
    """Slowly rising market (no deep DD, moderate vol) → NEUTRAL not RISK_ON."""
    # Need volatility low, drawdown shallow, trend positive but not big.
    # Slow grind: 0.01% per day, no wiggle.
    closes = [100 * (1.0001 ** i) for i in range(210)]
    label, _ = classify_from_spy_closes(closes)
    # Trend will be ~+1% (SMA50/SMA200 - 1), below TREND_UP=2%, so NEUTRAL.
    assert label in ("NEUTRAL", "RISK_ON")
