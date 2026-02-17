from __future__ import annotations

import pytest

from analytics.slippage_timing import classify_time_bucket


# --- 30-minute bucket boundaries ---


def test_bucket_0930_exactly() -> None:
    # 09:30 ET = 13:30 UTC (during EDT, UTC-4)
    assert classify_time_bucket("2024-06-03T13:30:00+00:00") == "09:30-10:00"


def test_bucket_0959() -> None:
    # 09:59 ET = 13:59 UTC
    assert classify_time_bucket("2024-06-03T13:59:00+00:00") == "09:30-10:00"


def test_bucket_1000_exactly() -> None:
    # 10:00 ET = 14:00 UTC
    assert classify_time_bucket("2024-06-03T14:00:00+00:00") == "10:00-10:30"


def test_bucket_1030_exactly() -> None:
    # 10:30 ET = 14:30 UTC
    assert classify_time_bucket("2024-06-03T14:30:00+00:00") == "10:30-11:00"


def test_bucket_1100_exactly() -> None:
    assert classify_time_bucket("2024-06-03T15:00:00+00:00") == "11:00-11:30"


def test_bucket_1200_exactly() -> None:
    assert classify_time_bucket("2024-06-03T16:00:00+00:00") == "12:00-12:30"


def test_bucket_1300_exactly() -> None:
    assert classify_time_bucket("2024-06-03T17:00:00+00:00") == "13:00-13:30"


def test_bucket_1400_exactly() -> None:
    assert classify_time_bucket("2024-06-03T18:00:00+00:00") == "14:00-14:30"


def test_bucket_1500_exactly() -> None:
    assert classify_time_bucket("2024-06-03T19:00:00+00:00") == "15:00-15:30"


def test_bucket_1530_exactly() -> None:
    # 15:30 ET = 19:30 UTC
    assert classify_time_bucket("2024-06-03T19:30:00+00:00") == "15:30-16:00"


def test_bucket_1559() -> None:
    # 15:59 ET = 19:59 UTC — last minute of trading
    assert classify_time_bucket("2024-06-03T19:59:00+00:00") == "15:30-16:00"


# --- pre-market and after-hours ---


def test_pre_market_early_morning() -> None:
    # 07:00 ET = 11:00 UTC
    assert classify_time_bucket("2024-06-03T11:00:00+00:00") == "pre-market"


def test_pre_market_just_before_open() -> None:
    # 09:29 ET = 13:29 UTC
    assert classify_time_bucket("2024-06-03T13:29:00+00:00") == "pre-market"


def test_after_hours_at_close() -> None:
    # 16:00 ET = 20:00 UTC — market close is after-hours
    assert classify_time_bucket("2024-06-03T20:00:00+00:00") == "after-hours"


def test_after_hours_evening() -> None:
    # 18:00 ET = 22:00 UTC
    assert classify_time_bucket("2024-06-03T22:00:00+00:00") == "after-hours"


# --- timezone handling (EST vs EDT) ---


def test_winter_time_est() -> None:
    # Jan 15 2024: EST (UTC-5). 09:30 ET = 14:30 UTC
    assert classify_time_bucket("2024-01-15T14:30:00+00:00") == "09:30-10:00"


def test_winter_time_est_pre_market() -> None:
    # 09:29 EST = 14:29 UTC
    assert classify_time_bucket("2024-01-15T14:29:00+00:00") == "pre-market"


def test_winter_time_est_after_hours() -> None:
    # 16:00 EST = 21:00 UTC
    assert classify_time_bucket("2024-01-15T21:00:00+00:00") == "after-hours"


def test_summer_time_edt() -> None:
    # Jun 3 2024: EDT (UTC-4). 09:30 ET = 13:30 UTC
    assert classify_time_bucket("2024-06-03T13:30:00+00:00") == "09:30-10:00"


def test_input_with_offset() -> None:
    # Provide UTC as explicit offset — 10:30 ET on Jun 3 EDT
    assert classify_time_bucket("2024-06-03T10:30:00-04:00") == "10:30-11:00"


def test_input_with_z_suffix() -> None:
    # 14:00Z = 10:00 ET during EDT
    assert classify_time_bucket("2024-06-03T14:00:00Z") == "10:00-10:30"
