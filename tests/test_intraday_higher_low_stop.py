import pytest

from execution_v2.exits import compute_intraday_higher_low_stop


def _bars_from_lows(lows):
    return [{"low": low} for low in lows]


def test_intraday_higher_low_stop_none_when_no_swings():
    bars = _bars_from_lows([10, 11, 12, 13, 14, 15])
    assert compute_intraday_higher_low_stop(bars, stop_buffer_dollars=0.1) is None


def test_intraday_higher_low_stop_returns_latest_higher_low():
    bars = _bars_from_lows([10, 9, 11, 8, 10, 9, 11])
    stop = compute_intraday_higher_low_stop(bars, stop_buffer_dollars=0.25)
    assert stop == 8.75


def test_intraday_higher_low_stop_respects_min_bars():
    bars = _bars_from_lows([10, 9, 11, 8, 10])
    assert compute_intraday_higher_low_stop(bars, stop_buffer_dollars=0.1, min_bars=6) is None


def test_intraday_higher_low_stop_rounding_and_buffer():
    bars = _bars_from_lows([11, 10.5, 11.2, 10.1, 10.8, 10.4, 11.0])
    stop = compute_intraday_higher_low_stop(bars, stop_buffer_dollars=0.03)
    assert stop == 10.37
