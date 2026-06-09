"""Earnings-proximity gate for the SingleNameMomentum strategy.

Two backends:
- LIVE: reads cache/earnings_cache.json populated by the daily scanner's
  is_near_earnings_cached(). Boolean per symbol — True if earnings are
  within ~2 trading days. The cache is refreshed daily with 1-day TTL.
- BACKTEST: reads universe/earnings_calendar.parquet via
  universe.point_in_time_earnings.is_near_earnings_pit() if the file
  exists. If it doesn't (current state — the parquet is empty), the
  gate returns False uniformly. Acknowledged limitation: backtest
  results will overstate slightly because we don't model earnings-day
  drawdowns. Fix is to backfill the calendar (TODO).
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterable


@lru_cache(maxsize=1)
def _load_live_cache(cache_path: str) -> dict:
    p = Path(cache_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def names_near_earnings_live(
    candidates: Iterable[str],
    *,
    cache_path: str | Path = "cache/earnings_cache.json",
) -> set[str]:
    """Return subset of `candidates` flagged as having earnings imminent.

    Reads the existing scanner-populated cache (boolean per symbol). A
    None/missing entry is treated as "no earnings near" (safe default).
    """
    cache = _load_live_cache(str(cache_path))
    flagged: set[str] = set()
    for sym in candidates:
        rec = cache.get(sym.upper())
        if isinstance(rec, dict) and rec.get("value") is True:
            flagged.add(sym.upper())
    return flagged


def names_near_earnings_backtest(
    candidates: Iterable[str],
    *,
    asof: date,
    earnings_calendar_path: str | Path | None = None,
) -> set[str]:
    """Same shape as the live version, but uses the PIT earnings calendar.

    If the calendar parquet is missing or empty (current default state),
    returns an empty set — the gate is effectively disabled in backtest
    mode. Documented limitation in the strategy's docstring.
    """
    try:
        from universe.point_in_time_earnings import (
            is_near_earnings_pit,
            load_earnings_calendar,
        )
    except Exception:
        return set()

    cal = load_earnings_calendar(earnings_calendar_path)
    if cal.empty:
        return set()
    return {
        sym.upper()
        for sym in candidates
        if is_near_earnings_pit(sym.upper(), asof.isoformat(), cal, window_days=3)
    }
