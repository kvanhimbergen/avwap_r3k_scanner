#!/usr/bin/env python
"""
Repro: timezone boundary checks for market open/close in America/New_York.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from execution_v2 import clocks


def _show(label: str, dt: datetime) -> None:
    snap = clocks.snapshot_at(dt)
    print(
        label,
        "market_open=",
        snap.market_open,
        "entry_window_open=",
        snap.entry_window_open,
        "ts=",
        snap.now_et.isoformat(),
    )


def main() -> None:
    ny = ZoneInfo("America/New_York")
    _show("pre-open", datetime(2024, 6, 3, 9, 29, tzinfo=ny))
    _show("open", datetime(2024, 6, 3, 9, 30, tzinfo=ny))
    _show("close", datetime(2024, 6, 3, 16, 0, tzinfo=ny))
    _show("after-close", datetime(2024, 6, 3, 16, 1, tzinfo=ny))


if __name__ == "__main__":
    main()
