"""Tests for universe/point_in_time_earnings.py — point-in-time earnings calendar."""

import pandas as pd
import pytest

from universe.point_in_time_earnings import (
    is_near_earnings_pit,
    load_earnings_calendar,
)


def _make_calendar(rows: list[tuple[str, str, bool]]) -> pd.DataFrame:
    """Create an earnings calendar DataFrame from (symbol, date, is_before_market) tuples."""
    return pd.DataFrame(rows, columns=["symbol", "earnings_date", "is_before_market"])


class TestLoadEarningsCalendar:
    def test_missing_file_returns_empty(self, tmp_path):
        df = load_earnings_calendar(tmp_path / "nonexistent.parquet")
        assert df.empty
        assert list(df.columns) == ["symbol", "earnings_date", "is_before_market"]

    def test_loads_from_parquet(self, tmp_path):
        path = tmp_path / "cal.parquet"
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "earnings_date": ["2024-01-25", "2024-02-01"],
                "is_before_market": [True, False],
            }
        )
        df.to_parquet(path, index=False)
        result = load_earnings_calendar(path)
        assert len(result) == 2
        assert result.iloc[0]["symbol"] == "AAPL"

    def test_normalizes_symbols_to_uppercase(self, tmp_path):
        path = tmp_path / "cal.parquet"
        df = pd.DataFrame(
            {
                "symbol": ["aapl"],
                "earnings_date": ["2024-01-25"],
                "is_before_market": [True],
            }
        )
        df.to_parquet(path, index=False)
        result = load_earnings_calendar(path)
        assert result.iloc[0]["symbol"] == "AAPL"


class TestIsNearEarningsPit:
    def test_within_window_returns_true(self):
        """Earnings date within window_days of as_of_date -> True."""
        cal = _make_calendar([("AAPL", "2024-01-25", True)])
        # Normalize to Timestamp
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])
        assert is_near_earnings_pit("AAPL", "2024-01-24", cal, window_days=3) is True
        assert is_near_earnings_pit("AAPL", "2024-01-25", cal, window_days=3) is True
        assert is_near_earnings_pit("AAPL", "2024-01-26", cal, window_days=3) is True

    def test_outside_window_returns_false(self):
        """Earnings date outside window_days -> False."""
        cal = _make_calendar([("AAPL", "2024-01-25", True)])
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])
        assert is_near_earnings_pit("AAPL", "2024-01-15", cal, window_days=3) is False
        assert is_near_earnings_pit("AAPL", "2024-02-05", cal, window_days=3) is False

    def test_different_symbol_returns_false(self):
        """Calendar has AAPL but we query MSFT -> False."""
        cal = _make_calendar([("AAPL", "2024-01-25", True)])
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])
        assert is_near_earnings_pit("MSFT", "2024-01-25", cal) is False

    def test_empty_calendar_returns_false(self):
        """Empty calendar -> all symbols pass (fail-open)."""
        cal = pd.DataFrame(columns=["symbol", "earnings_date", "is_before_market"])
        assert is_near_earnings_pit("AAPL", "2024-01-25", cal) is False

    def test_point_in_time_constraint(self):
        """Earnings announced on 2024-03-20 for date 2024-03-25.

        When queried as-of 2024-03-19, the earnings on 2024-03-25
        ARE visible in the calendar (they're within the window of 3 days
        from 2024-03-22, but not from 2024-03-19).

        The key: as-of 2024-03-19 with window=3, the window is
        [2024-03-16, 2024-03-22]. Earnings on 2024-03-25 is outside.
        """
        cal = _make_calendar([("AAPL", "2024-03-25", True)])
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])

        # As of 2024-03-19 (window 3 days = [Mar 16, Mar 22]) -> earnings Mar 25 outside
        assert is_near_earnings_pit("AAPL", "2024-03-19", cal, window_days=3) is False

        # As of 2024-03-23 (window 3 days = [Mar 20, Mar 26]) -> earnings Mar 25 inside
        assert is_near_earnings_pit("AAPL", "2024-03-23", cal, window_days=3) is True

    def test_multiple_earnings_dates(self):
        """Multiple earnings dates for same symbol."""
        cal = _make_calendar([
            ("AAPL", "2024-01-25", True),
            ("AAPL", "2024-04-25", False),
            ("AAPL", "2024-07-25", True),
        ])
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])

        assert is_near_earnings_pit("AAPL", "2024-01-24", cal, window_days=3) is True
        assert is_near_earnings_pit("AAPL", "2024-03-01", cal, window_days=3) is False
        assert is_near_earnings_pit("AAPL", "2024-04-26", cal, window_days=3) is True

    def test_case_insensitive_symbol(self):
        """Symbol matching is case-insensitive."""
        cal = _make_calendar([("AAPL", "2024-01-25", True)])
        cal["earnings_date"] = pd.to_datetime(cal["earnings_date"])
        assert is_near_earnings_pit("aapl", "2024-01-25", cal) is True
        assert is_near_earnings_pit("Aapl", "2024-01-25", cal) is True
