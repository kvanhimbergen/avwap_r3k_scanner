"""
Execution V2 – 10-minute Breakout-and-Hold (BOH) Detection

Implements PRD Option 2 (Confirmed):
- Break: first 10m CLOSE above the pivot level
- Hold: the NEXT 10m bar must NOT close back below the pivot level
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Bar10m:
    ts: float   # epoch seconds at bar close
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class BOHResult:
    confirmed: bool
    break_bar_ts: Optional[float] = None
    confirm_bar_ts: Optional[float] = None


def boh_confirmed_option2(
    last_two_closed: list[Bar10m],
    pivot_level: float,
    avg_volume: float = 0.0,
    min_rvol: float = 0.8,
) -> BOHResult:
    """
    Evaluate BOH Option 2 (Confirmed) using exactly two most recent CLOSED 10m bars.

    Inputs:
      - last_two_closed: [bar_prev, bar_last] where both are CLOSED bars, ordered oldest->newest
      - pivot_level: prior daily swing high level
      - avg_volume: average 10m bar volume (0 = skip volume check, fail-open)
      - min_rvol: minimum relative volume ratio for breakout bar (default 0.8)

    Logic:
      - bar_prev.close > pivot_level  => break condition met
      - bar_last.close >= pivot_level => hold condition met (must NOT close back below)
      - bar_prev.volume >= avg_volume * min_rvol => volume validates the breakout

    Returns:
      BOHResult(confirmed=True, break_bar_ts=..., confirm_bar_ts=...) when confirmed,
      else confirmed=False.
    """
    if len(last_two_closed) != 2:
        raise ValueError("last_two_closed must contain exactly 2 closed 10m bars")

    bar_prev, bar_last = last_two_closed

    broke = bar_prev.close > pivot_level
    held = bar_last.close >= pivot_level

    if broke and held:
        # Volume validation: breakout bar must have sufficient volume
        if avg_volume > 0 and bar_prev.volume < avg_volume * min_rvol:
            return BOHResult(False)
        return BOHResult(True, break_bar_ts=bar_prev.ts, confirm_bar_ts=bar_last.ts)

    return BOHResult(False)
