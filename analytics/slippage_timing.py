from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 30
_MARKET_CLOSE_HOUR = 16
_MARKET_CLOSE_MINUTE = 0

_BUCKETS = [
    ("09:30-10:00", 9, 30, 10, 0),
    ("10:00-10:30", 10, 0, 10, 30),
    ("10:30-11:00", 10, 30, 11, 0),
    ("11:00-11:30", 11, 0, 11, 30),
    ("11:30-12:00", 11, 30, 12, 0),
    ("12:00-12:30", 12, 0, 12, 30),
    ("12:30-13:00", 12, 30, 13, 0),
    ("13:00-13:30", 13, 0, 13, 30),
    ("13:30-14:00", 13, 30, 14, 0),
    ("14:00-14:30", 14, 0, 14, 30),
    ("14:30-15:00", 14, 30, 15, 0),
    ("15:00-15:30", 15, 0, 15, 30),
    ("15:30-16:00", 15, 30, 16, 0),
]


def classify_time_bucket(fill_ts_utc: str) -> str:
    dt_utc = datetime.fromisoformat(fill_ts_utc)
    dt_et = dt_utc.astimezone(_ET)

    hour, minute = dt_et.hour, dt_et.minute
    total_minutes = hour * 60 + minute

    market_open = _MARKET_OPEN_HOUR * 60 + _MARKET_OPEN_MINUTE
    market_close = _MARKET_CLOSE_HOUR * 60 + _MARKET_CLOSE_MINUTE

    if total_minutes < market_open:
        return "pre-market"
    if total_minutes >= market_close:
        return "after-hours"

    for label, sh, sm, eh, em in _BUCKETS:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start <= total_minutes < end:
            return label

    return "after-hours"
