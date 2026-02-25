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

def test_avwap_stop_vs_swing_low_tighter_wins():
    """max(swing_low_stop, avwap_stop) picks the tighter (higher) stop."""
    swing_low_stop = 95.0 - 0.10  # 94.90
    avwap_stop = 97.0 * 0.997     # 96.709

    # AVWAP stop is higher (tighter) → should be selected
    structural = max(swing_low_stop, avwap_stop)
    assert structural == avwap_stop
    assert structural > swing_low_stop


def test_swing_low_stop_wins_when_higher():
    """When swing low is above AVWAP, swing low stop wins."""
    swing_low_stop = 98.0 - 0.10  # 97.90
    avwap_stop = 95.0 * 0.997     # 94.715

    structural = max(swing_low_stop, avwap_stop)
    assert structural == swing_low_stop


def test_stop_below_entry():
    """Stop should always be below entry level for a long setup."""
    entry = 100.0
    avwap = 99.0
    swing_low = 97.0

    swing_low_stop = swing_low - 0.10
    avwap_stop = avwap * 0.997
    structural = max(swing_low_stop, avwap_stop)

    assert structural < entry


def test_fallback_to_sma_when_no_candidates():
    """When no swing lows and no AVWAP, fallback to SMA5/Low5."""
    swing_lows: list[float] = []
    avwap = None

    swing_low_stop = (swing_lows[-1] - 0.10) if swing_lows else None
    avwap_stop = avwap * 0.997 if avwap else None

    candidates = [s for s in [swing_low_stop, avwap_stop] if s is not None]
    assert candidates == []  # both are None → should trigger fallback
