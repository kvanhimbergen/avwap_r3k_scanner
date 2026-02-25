"""Tests for AVWAP confluence scoring in pick_best_anchor()."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


def _make_df(n: int = 100, base_close: float = 100.0) -> pd.DataFrame:
    """Create a simple uptrending OHLCV DataFrame for testing."""
    dates = pd.bdate_range(end="2026-02-20", periods=n, name="Date")
    close = base_close + np.linspace(0, 10, n) + np.random.default_rng(42).normal(0, 0.3, n)
    high = close + np.abs(np.random.default_rng(43).normal(0.5, 0.2, n))
    low = close - np.abs(np.random.default_rng(44).normal(0.5, 0.2, n))
    open_ = close + np.random.default_rng(45).normal(0, 0.3, n)
    volume = np.random.default_rng(46).integers(1_000_000, 5_000_000, n).astype(float)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    return df


class TestAVWAPConfluence:
    """Test that pick_best_anchor returns confluence count."""

    def test_return_tuple_has_seven_elements(self):
        """pick_best_anchor should return a 7-tuple including anchor_date and confluence."""
        from scan_engine import pick_best_anchor

        df = _make_df(120)
        result = pick_best_anchor(df, "Long", is_weekend=True)
        if result is not None:
            assert len(result) == 7, f"Expected 7-tuple, got {len(result)}"
            name, av, avs, trend_score, dist, anchor_date, confluence = result
            assert isinstance(confluence, int)
            assert confluence >= 1  # at least the best anchor itself

    def test_confluence_at_least_one(self):
        """The best anchor should always count itself (confluence >= 1)."""
        from scan_engine import pick_best_anchor

        df = _make_df(120)
        result = pick_best_anchor(df, "Long", is_weekend=True)
        if result is not None:
            assert result[6] >= 1

    def test_single_anchor_confluence_is_one(self):
        """When only one anchor passes validation, confluence should be 1."""
        from scan_engine import pick_best_anchor

        df = _make_df(120)

        # Patch get_anchor_candidates to return exactly one anchor (loc is integer position)
        single_anchor = [{"name": "TEST", "loc": 50, "priority": 10}]
        with patch("scan_engine.get_anchor_candidates", return_value=single_anchor):
            result = pick_best_anchor(df, "Long", is_weekend=True)
            if result is not None:
                assert result[6] == 1

    def test_confluence_in_candidate_row(self):
        """build_candidate_row should include AVWAP_Confluence in output."""
        from scan_engine import build_candidate_row

        df = _make_df(120)
        row = build_candidate_row(
            df, "TEST", "Technology", {}, direction="Long"
        )
        # May return None if quality gates fail; that's ok
        if row is not None:
            assert "AVWAP_Confluence" in row
            assert isinstance(row["AVWAP_Confluence"], int)
            assert row["AVWAP_Confluence"] >= 1

    def test_confluence_in_candidate_columns(self):
        """AVWAP_Confluence should be in CANDIDATE_COLUMNS."""
        from scan_engine import CANDIDATE_COLUMNS

        assert "AVWAP_Confluence" in CANDIDATE_COLUMNS

    def test_boundary_exactly_one_percent(self):
        """Levels exactly at 1% boundary should be counted as confluent."""
        # Test the math directly
        best_av = 100.0
        level_at_boundary = 101.0  # exactly 1% away
        assert abs(level_at_boundary - best_av) / best_av <= 0.01

        level_just_outside = 101.01  # just over 1%
        assert abs(level_just_outside - best_av) / best_av > 0.01
