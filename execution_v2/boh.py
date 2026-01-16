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


@dataclass(frozen=True)
class BOHResult:
    confirmed: bool
    break_bar_ts: Optional[float] = None
    confirm_bar_ts: Optional[float] = None


def boh_confirmed_option2(last_two_closed: list[Bar10m], pivot_level: float) -> BOHResult:
    """
    Evaluate BOH Option 2 (Confirmed) using exactly two most recent CLOSED 10m bars.

    Inputs:
      - last_two_closed: [bar_prev, bar_last] where both are CLOSED bars, ordered oldest->newest
      - pivot_level: prior daily swing high level

    Logic:
      - bar_prev.close > pivot_level  => break condition met
      - bar_last.close >= pivot_level => hold condition met (must NOT close back below)

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
        return BOHResult(True, break_bar_ts=bar_prev.ts, confirm_bar_ts=bar_last.ts)

    return BOHResult(False)
# Execution V2 placeholder: boh.py
