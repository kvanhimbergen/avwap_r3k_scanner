"""Centralized freshness contract for data sources.

The system has multiple silent-stale failure modes — price caches, ledger
files, state snapshots, scan outputs — where downstream code can't tell
fresh data from data that's been frozen by an upstream feed failure.

This module is the single helper every freshness check should go through
so the failure mode is uniform: compute the business-day gap between
``last`` and ``requested``, and either return it (caller decides) or
raise ``StaleDataError`` when it exceeds a caller-supplied threshold.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Union
from zoneinfo import ZoneInfo

import pandas as pd

_NY_TZ = ZoneInfo("America/New_York")

DateLike = Union[str, date, datetime, pd.Timestamp]


class StaleDataError(Exception):
    """Raised when a data source is older than the caller's tolerance.

    Attributes
    ----------
    label : str
        Human-readable identifier of the data source (e.g. "regime_e1.spy_history").
    last_ny_date : str
        The most recent NY trading date the data source covers.
    requested_ny_date : str
        The NY date the caller wanted data for.
    staleness_bdays : int
        Business-day gap between ``last`` and ``requested``.
    max_stale_bdays : int
        The tolerance that was exceeded.
    """

    def __init__(
        self,
        *,
        label: str,
        last_ny_date: str,
        requested_ny_date: str,
        staleness_bdays: int,
        max_stale_bdays: int,
    ) -> None:
        self.label = label
        self.last_ny_date = last_ny_date
        self.requested_ny_date = requested_ny_date
        self.staleness_bdays = staleness_bdays
        self.max_stale_bdays = max_stale_bdays
        super().__init__(
            f"{label}: data stale by {staleness_bdays} business days "
            f"(last={last_ny_date}, requested={requested_ny_date}, "
            f"max_allowed={max_stale_bdays})"
        )


def _to_iso_date(value: DateLike) -> str:
    if isinstance(value, str):
        # Trust caller; pd.Timestamp normalizes if it's a parseable form.
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported date type: {type(value).__name__}")


def staleness_bdays(last: DateLike, requested: DateLike) -> int:
    """Return the business-day gap between ``last`` and ``requested``.

    Returns 0 when ``last >= requested`` (data is at-or-ahead of the
    request). Weekends and US business holidays beyond the pandas default
    business-day calendar are not modeled — this is a coarse gap, not a
    market-calendar gap.
    """
    last_iso = _to_iso_date(last)
    requested_iso = _to_iso_date(requested)
    if last_iso >= requested_iso:
        return 0
    # pd.bdate_range is inclusive on both ends; subtract 1 to get the gap.
    return max(0, len(pd.bdate_range(last_iso, requested_iso)) - 1)


def assert_fresh(
    *,
    last: DateLike,
    requested: DateLike,
    max_stale_bdays: int,
    label: str,
) -> int:
    """Raise ``StaleDataError`` when staleness exceeds ``max_stale_bdays``.

    Returns the computed staleness in business days on success so the
    caller can log it without recomputing.
    """
    gap = staleness_bdays(last, requested)
    if gap > max_stale_bdays:
        raise StaleDataError(
            label=label,
            last_ny_date=_to_iso_date(last),
            requested_ny_date=_to_iso_date(requested),
            staleness_bdays=gap,
            max_stale_bdays=max_stale_bdays,
        )
    return gap


def file_mtime_ny_date(path: Path) -> str:
    """Return the NY date a file was last modified, as ISO ``YYYY-MM-DD``.

    Useful for freshness-checking caches, CSVs, or other artifacts whose
    contents don't carry an embedded date.
    """
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=_NY_TZ)
    return mtime.date().isoformat()
