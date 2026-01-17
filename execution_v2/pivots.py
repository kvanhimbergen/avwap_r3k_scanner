"""
Execution V2 – Daily Pivot Levels

Responsibilities:
- Compute prior DAILY swing high (3-left / 3-right)
- Compute R1 / R2 levels from daily structure

This module must remain deterministic and side-effect free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class DailyBar:
    ts: float        # epoch seconds
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PivotLevels:
    swing_high: float
    r1: float
    r2: float


def prior_swing_high(bars: list[DailyBar]) -> Optional[float]:
    """
    Returns the most recent completed DAILY swing high using 3L/3R logic.

    bars must be ordered oldest -> newest and must NOT include the current day.
    """
    if len(bars) < 7:
        return None

    # We look at bars[-4] as the candidate (3 left, 3 right)
    for i in range(len(bars) - 4, 2, -1):
        h = bars[i].high
        left = bars[i-3:i]
        right = bars[i+1:i+4]

        if all(h > b.high for b in left) and all(h > b.high for b in right):
            return h

    return None


def compute_pivot_levels(
    swing_high: float,
    prior_day_high: float,
    prior_day_low: float,
) -> PivotLevels:
    """
    Compute R1 / R2 from the prior day's range.

    This is intentionally simple and stable:
    - R1 = swing_high + 0.5 * prior range
    - R2 = swing_high + 1.0 * prior range
    """
    day_range = prior_day_high - prior_day_low
    if day_range <= 0:
        raise ValueError("Invalid prior day range")

    r1 = swing_high + 0.5 * day_range
    r2 = swing_high + 1.0 * day_range

    return PivotLevels(
        swing_high=swing_high,
        r1=r1,
        r2=r2,
    )
# Execution V2 placeholder: pivots.py
