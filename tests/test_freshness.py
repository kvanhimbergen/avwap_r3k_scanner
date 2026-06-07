from __future__ import annotations

import os
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from utils.freshness import (
    StaleDataError,
    assert_fresh,
    file_mtime_ny_date,
    staleness_bdays,
)


# ---------------------------------------------------------------------------
# staleness_bdays
# ---------------------------------------------------------------------------

def test_staleness_zero_when_last_equals_requested() -> None:
    assert staleness_bdays("2026-03-02", "2026-03-02") == 0


def test_staleness_zero_when_last_after_requested() -> None:
    # Backtests legitimately call with last data ahead of the requested date.
    assert staleness_bdays("2026-03-10", "2026-03-02") == 0


def test_staleness_weekend_gap_is_one_bday() -> None:
    # Friday last data, Saturday requested -> 1 bday gap (the Friday itself counts as
    # the only business day in bdate_range, so the gap is 0). The next request — Mon —
    # should also be just 1 bday between them.
    assert staleness_bdays("2026-03-06", "2026-03-07") == 0  # Sat over Fri
    assert staleness_bdays("2026-03-06", "2026-03-09") == 1  # Mon over Fri


def test_staleness_accepts_date_objects() -> None:
    assert staleness_bdays(date(2026, 3, 2), date(2026, 3, 4)) == 2


def test_staleness_accepts_datetime_objects() -> None:
    assert staleness_bdays(
        datetime(2026, 3, 2, 16, 0),
        datetime(2026, 3, 4, 16, 0),
    ) == 2


def test_staleness_full_week_gap() -> None:
    # Mon -> next Mon: 5 business days
    assert staleness_bdays("2026-03-02", "2026-03-09") == 5


def test_staleness_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        staleness_bdays(12345, "2026-03-02")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assert_fresh
# ---------------------------------------------------------------------------

def test_assert_fresh_returns_gap_when_within_threshold() -> None:
    gap = assert_fresh(
        last="2026-03-06",
        requested="2026-03-09",
        max_stale_bdays=5,
        label="test.source",
    )
    assert gap == 1


def test_assert_fresh_raises_when_over_threshold() -> None:
    with pytest.raises(StaleDataError) as excinfo:
        assert_fresh(
            last="2026-02-24",
            requested="2026-06-05",
            max_stale_bdays=5,
            label="regime_e1.spy_history",
        )
    err = excinfo.value
    assert err.label == "regime_e1.spy_history"
    assert err.last_ny_date == "2026-02-24"
    assert err.requested_ny_date == "2026-06-05"
    assert err.staleness_bdays > 5
    assert err.max_stale_bdays == 5
    # Message must include the label so log scrapers can identify the source.
    assert "regime_e1.spy_history" in str(err)


def test_assert_fresh_exact_threshold_does_not_raise() -> None:
    # 5 bday gap == max_stale_bdays should pass (strict greater-than gate).
    gap = assert_fresh(
        last="2026-03-02",
        requested="2026-03-09",
        max_stale_bdays=5,
        label="test.source",
    )
    assert gap == 5


# ---------------------------------------------------------------------------
# file_mtime_ny_date
# ---------------------------------------------------------------------------

def test_file_mtime_ny_date_reads_filesystem_mtime(tmp_path: Path) -> None:
    target = tmp_path / "thing.txt"
    target.write_text("x")
    # Stamp the file to noon NY on a specific date.
    # 2026-03-04 17:00 UTC == 2026-03-04 12:00 EST (EST is UTC-5 in March pre-DST;
    # use a post-DST date to dodge that detail).
    fixed_utc = datetime(2026, 6, 4, 16, 0, 0).timestamp()  # 2026-06-04 12:00 EDT
    os.utime(target, (fixed_utc, fixed_utc))
    assert file_mtime_ny_date(target) == "2026-06-04"
