"""
Execution V2 – Time / Market Hours Helpers

Defines:
- NYSE regular session open/close (09:30–16:00 ET, weekdays)
- Entry window for PRD: 09:45–15:30 ET, weekdays

Notes:
- We do not attempt to model exchange holidays here. The existing system already
  treats "market OPEN/CLOSED" operationally; this helper is used for entry gating.
- Uses America/New_York timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")

REG_OPEN = time(9, 30)
REG_CLOSE = time(16, 0)

ENTRY_START = time(9, 45)
ENTRY_END = time(15, 30)


@dataclass(frozen=True)
class ClockSnapshot:
    now_ts: float
    now_et: datetime
    weekday: int
    market_open: bool
    entry_window_open: bool


def now_snapshot() -> ClockSnapshot:
    """
    Returns a timezone-aware snapshot in ET plus gating booleans.
    """
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    return snapshot_at(now_et)


def snapshot_at(dt_et: datetime) -> ClockSnapshot:
    """
    dt_et must be timezone-aware and in ET.
    """
    if dt_et.tzinfo is None:
        raise ValueError("dt_et must be timezone-aware")
    dt_et = dt_et.astimezone(ET)

    wd = dt_et.weekday()  # 0=Mon ... 6=Sun
    is_weekday = wd <= 4
    t = dt_et.time()

    market_open = bool(is_weekday and (REG_OPEN <= t < REG_CLOSE))
    entry_window_open = bool(is_weekday and (ENTRY_START <= t <= ENTRY_END) and market_open)

    return ClockSnapshot(
        now_ts=dt_et.timestamp(),
        now_et=dt_et,
        weekday=wd,
        market_open=market_open,
        entry_window_open=entry_window_open,
    )
# Execution V2 placeholder: clocks.py
