from datetime import datetime, timedelta, timezone

from execution_v2.exits import compute_stop_price, entry_day_from_ts
from execution_v2.pivots import DailyBar


def _make_bar(day_offset: int, low: float) -> DailyBar:
    base = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ts = (base + timedelta(days=day_offset)).timestamp()
    return DailyBar(ts=ts, open=low + 1, high=low + 2, low=low, close=low + 1.5)


def test_compute_stop_price_uses_prior_pivot_low() -> None:
    lows = [15, 14, 13, 12, 11, 10, 12, 13, 14, 15, 16, 17]
    bars = [_make_bar(i, low) for i, low in enumerate(lows)]
    entry_day = entry_day_from_ts(bars[-1].ts) + timedelta(days=1)

    stop_price = compute_stop_price(bars, entry_day=entry_day, buffer_dollars=0.1)

    assert stop_price == 9.9


def test_compute_stop_price_returns_none_without_pivot() -> None:
    lows = [10, 11, 12, 13, 14, 15, 16]
    bars = [_make_bar(i, low) for i, low in enumerate(lows)]
    entry_day = entry_day_from_ts(bars[-1].ts) + timedelta(days=1)

    stop_price = compute_stop_price(bars, entry_day=entry_day, buffer_dollars=0.1)

    assert stop_price is None
