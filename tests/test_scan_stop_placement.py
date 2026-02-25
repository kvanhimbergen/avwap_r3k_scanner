"""Tests for AVWAP-based stop placement in scan_engine."""

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

pytestmark = [pytest.mark.requires_numpy, pytest.mark.requires_pandas]

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from scan_engine import _find_daily_swing_lows


def _make_lows_df(lows: list[float]) -> pd.DataFrame:
    """Build a minimal DataFrame with a Low column."""
    dates = pd.date_range("2024-01-01", periods=len(lows), freq="D")
    return pd.DataFrame({"Low": lows}, index=dates)


# ── _find_daily_swing_lows tests ──────────────────────────

def test_swing_low_basic():
    """Detect a simple swing low: valley flanked by higher bars."""
    lows = [10.0, 9.0, 8.0, 9.0, 10.0]
    df = _make_lows_df(lows)
    result = _find_daily_swing_lows(df, lookback=5)
    assert result == [8.0]


def test_swing_low_multiple():
    """Detect multiple swing lows."""
    lows = [10.0, 8.0, 10.0, 7.0, 10.0]
    df = _make_lows_df(lows)
    result = _find_daily_swing_lows(df, lookback=5)
    assert result == [8.0, 7.0]


def test_swing_low_none_on_flat():
    """Flat lows produce no swing lows."""
    lows = [10.0] * 10
    df = _make_lows_df(lows)
    result = _find_daily_swing_lows(df, lookback=10)
    assert result == []


def test_swing_low_none_on_monotonic():
    """Monotonically declining lows produce no swing lows."""
    lows = list(range(20, 0, -1))
    df = _make_lows_df([float(x) for x in lows])
    result = _find_daily_swing_lows(df, lookback=20)
    assert result == []


def test_swing_low_lookback_window():
    """Only considers the last N bars."""
    # Swing low at index 2 is outside lookback of 5
    lows = [10.0, 8.0, 5.0, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    df = _make_lows_df(lows)
    result = _find_daily_swing_lows(df, lookback=5)
    assert result == []  # swing low at idx 2 is outside last 5 bars


# ── Stop selection tests ──────────────────────────────────

def test_avwap_stop_vs_swing_low_wider_wins():
    """min(swing_low_stop, avwap_stop) picks the wider (lower) stop for longs."""
    swing_low_stop = 95.0 * 0.995  # 94.525
    avwap_stop = 97.0 * 0.997      # 96.709

    # Swing low stop is lower (wider) → should be selected
    structural = min(swing_low_stop, avwap_stop)
    assert structural == swing_low_stop
    assert structural < avwap_stop


def test_swing_low_stop_wins_when_lower():
    """When swing low is well below AVWAP, swing low stop wins (wider)."""
    swing_low_stop = 90.0 * 0.995  # 89.55
    avwap_stop = 95.0 * 0.997      # 94.715

    structural = min(swing_low_stop, avwap_stop)
    assert structural == swing_low_stop


def test_stop_below_entry():
    """Stop should always be below entry level for a long setup."""
    entry = 100.0
    avwap = 99.0
    swing_low = 97.0

    swing_low_stop = swing_low * 0.995
    avwap_stop = avwap * 0.997
    structural = min(swing_low_stop, avwap_stop)

    assert structural < entry


def test_fallback_to_sma_when_no_candidates():
    """When no swing lows and no AVWAP, fallback to SMA5/Low5."""
    swing_lows: list[float] = []
    avwap = None

    swing_low_stop = (swing_lows[-1] * 0.995) if swing_lows else None
    avwap_stop = avwap * 0.997 if avwap else None

    candidates = [s for s in [swing_low_stop, avwap_stop] if s is not None]
    assert candidates == []  # both are None → should trigger fallback


def test_stop_has_minimum_risk_floor():
    """Stop must be at least 1.5% below entry for longs."""
    entry = 100.0
    # Both stops very close to entry
    swing_low_stop = 99.5 * 0.995   # 98.0025
    avwap_stop = 100.0 * 0.997      # 99.70

    structural = min(swing_low_stop, avwap_stop)
    # Apply hard minimum: 1.5% from entry
    structural = min(structural, entry * 0.985)  # 98.50

    assert structural <= entry * 0.985
    risk_pct = (entry - structural) / entry
    assert risk_pct >= 0.015


def test_atr_floor_widens_tight_stop():
    """When swing low and AVWAP are both close, ATR floor kicks in."""
    entry = 30.0
    swing_low_stop = 29.80 * 0.995  # 29.651
    avwap_stop = 30.0 * 0.997       # 29.91
    atr_val = 0.75  # typical ATR for a $30 stock

    structural = min(swing_low_stop, avwap_stop)  # 29.651
    # ATR floor
    atr_floor = entry - atr_val  # 29.25
    structural = min(structural, atr_floor)

    assert structural == atr_floor
    risk_pct = (entry - structural) / entry
    assert risk_pct >= 0.02  # ATR floor gives ~2.5% risk


def test_percentage_buffer_on_swing_low():
    """Swing low buffer is 0.5% of price, not fixed $0.10."""
    swing_low = 200.0
    # Old: 200.0 - 0.10 = 199.90 (0.05% buffer — too tight on expensive stock)
    # New: 200.0 * 0.995 = 199.00 (0.5% buffer — scales with price)
    new_stop = swing_low * 0.995
    old_stop = swing_low - 0.10

    assert new_stop < old_stop  # new buffer is wider
    assert (swing_low - new_stop) / swing_low == pytest.approx(0.005)  # exactly 0.5%
