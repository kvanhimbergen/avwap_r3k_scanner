"""Tests for BOH volume validation in boh_confirmed_option2."""

from execution_v2.boh import Bar10m, boh_confirmed_option2


def _bar(ts: float, close: float, volume: float = 1000.0) -> Bar10m:
    return Bar10m(ts=ts, open=close - 0.5, high=close + 0.5, low=close - 1.0, close=close, volume=volume)


def test_boh_rejects_zero_volume_breakout():
    """Breakout bar with zero volume when avg_volume is provided should reject."""
    bars = [_bar(1, 101.0, volume=0.0), _bar(2, 101.5, volume=500.0)]
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=1000.0)
    assert result.confirmed is False


def test_boh_rejects_low_volume_breakout():
    """Breakout bar below min_rvol threshold should reject."""
    bars = [_bar(1, 101.0, volume=700.0), _bar(2, 101.5, volume=1200.0)]
    # 700 < 1000 * 0.8 = 800 → reject
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=1000.0, min_rvol=0.8)
    assert result.confirmed is False


def test_boh_passes_with_sufficient_volume():
    """Breakout bar with volume >= avg * min_rvol should confirm."""
    bars = [_bar(1, 101.0, volume=900.0), _bar(2, 101.5, volume=1200.0)]
    # 900 >= 1000 * 0.8 = 800 → pass
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=1000.0, min_rvol=0.8)
    assert result.confirmed is True
    assert result.break_bar_ts == 1
    assert result.confirm_bar_ts == 2


def test_boh_skips_volume_check_when_avg_zero():
    """Fail-open: when avg_volume is 0, volume check is skipped (backward compat)."""
    bars = [_bar(1, 101.0, volume=0.0), _bar(2, 101.5, volume=0.0)]
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=0.0)
    assert result.confirmed is True


def test_boh_skips_volume_check_when_avg_not_provided():
    """Default avg_volume=0 means volume check is skipped."""
    bars = [_bar(1, 101.0, volume=0.0), _bar(2, 101.5, volume=0.0)]
    result = boh_confirmed_option2(bars, pivot_level=100.0)
    assert result.confirmed is True


def test_boh_volume_check_only_applies_to_breakout_bar():
    """Volume check is on bar_prev (breakout bar), not bar_last (confirmation bar)."""
    # bar_prev has high volume, bar_last has low volume — should still confirm
    bars = [_bar(1, 101.0, volume=2000.0), _bar(2, 101.5, volume=100.0)]
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=1000.0)
    assert result.confirmed is True


def test_boh_volume_exact_threshold():
    """Volume exactly at threshold (avg * min_rvol) should confirm."""
    bars = [_bar(1, 101.0, volume=800.0), _bar(2, 101.5, volume=500.0)]
    # 800 >= 1000 * 0.8 = 800 → pass (equal to threshold)
    result = boh_confirmed_option2(bars, pivot_level=100.0, avg_volume=1000.0, min_rvol=0.8)
    assert result.confirmed is True
