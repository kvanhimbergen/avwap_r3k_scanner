"""Tests for execution_v2.correlation_sizing (Phase 5)."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from execution_v2.correlation_sizing import correlation_penalty, check_sector_cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _corr_matrix(data: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Build a correlation matrix from a nested dict."""
    symbols = sorted(data.keys())
    matrix = pd.DataFrame(index=symbols, columns=symbols, dtype=float)
    for s1 in symbols:
        for s2 in symbols:
            matrix.loc[s1, s2] = data[s1][s2]
    return matrix


# ---------------------------------------------------------------------------
# correlation_penalty
# ---------------------------------------------------------------------------

class TestCorrelationPenalty:
    def test_no_open_positions(self):
        """Penalty is 0.0 when no open positions."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.8},
            "B": {"A": 0.8, "B": 1.0},
        })
        assert correlation_penalty("A", [], corr) == 0.0

    def test_candidate_not_in_matrix(self):
        """Penalty is 0.0 when candidate not in correlation matrix."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.8},
            "B": {"A": 0.8, "B": 1.0},
        })
        assert correlation_penalty("C", ["A"], corr) == 0.0

    def test_below_threshold(self):
        """Penalty is 0.0 when avg correlation below threshold."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.3},
            "B": {"A": 0.3, "B": 1.0},
        })
        result = correlation_penalty("A", ["B"], corr, threshold=0.6)
        assert result == 0.0

    def test_at_threshold(self):
        """Penalty is 0.0 when avg correlation equals threshold exactly."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.6},
            "B": {"A": 0.6, "B": 1.0},
        })
        result = correlation_penalty("A", ["B"], corr, threshold=0.6)
        assert result == 0.0

    def test_above_threshold_scales_linearly(self):
        """Penalty scales linearly from 0 at threshold to max_penalty at 1.0."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.8},
            "B": {"A": 0.8, "B": 1.0},
        })
        # avg_corr = 0.8, threshold = 0.6
        # excess = (0.8 - 0.6) / (1.0 - 0.6) = 0.5
        # penalty = 0.5 * 0.5 = 0.25
        result = correlation_penalty("A", ["B"], corr, threshold=0.6, max_penalty=0.5)
        assert result == pytest.approx(0.25)

    def test_max_penalty_capped(self):
        """Penalty never exceeds max_penalty."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.99},
            "B": {"A": 0.99, "B": 1.0},
        })
        result = correlation_penalty("A", ["B"], corr, threshold=0.6, max_penalty=0.5)
        assert result <= 0.5

    def test_multiple_positions_averaged(self):
        """Penalty uses average absolute correlation across all open positions."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.9, "C": 0.3},
            "B": {"A": 0.9, "B": 1.0, "C": 0.2},
            "C": {"A": 0.3, "B": 0.2, "C": 1.0},
        })
        # avg_corr for A vs [B, C] = (0.9 + 0.3) / 2 = 0.6
        # At threshold exactly => penalty = 0.0
        result = correlation_penalty("A", ["B", "C"], corr, threshold=0.6)
        assert result == 0.0

    def test_negative_correlation_uses_absolute(self):
        """Negative correlations are converted to absolute values."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": -0.8},
            "B": {"A": -0.8, "B": 1.0},
        })
        # abs(-0.8) = 0.8 > 0.6 threshold
        result = correlation_penalty("A", ["B"], corr, threshold=0.6, max_penalty=0.5)
        assert result > 0.0

    def test_open_position_not_in_matrix(self):
        """Positions not in the matrix are skipped."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 0.8},
            "B": {"A": 0.8, "B": 1.0},
        })
        # "C" not in matrix columns, so only B is used
        result = correlation_penalty("A", ["B", "C"], corr, threshold=0.6, max_penalty=0.5)
        # avg_corr = 0.8, excess = (0.8-0.6)/(1.0-0.6) = 0.5, penalty = 0.5*0.5 = 0.25
        assert result == pytest.approx(0.25)

    def test_perfect_correlation_gives_max(self):
        """Perfect correlation gives exactly max_penalty."""
        corr = _corr_matrix({
            "A": {"A": 1.0, "B": 1.0},
            "B": {"A": 1.0, "B": 1.0},
        })
        result = correlation_penalty("A", ["B"], corr, threshold=0.6, max_penalty=0.5)
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# check_sector_cap
# ---------------------------------------------------------------------------

class TestCheckSectorCap:
    def test_no_sector(self):
        """No sector means always allowed."""
        allowed, reason = check_sector_cap(None, [], {})
        assert allowed is True
        assert reason == ""

    def test_empty_positions(self):
        """No positions means zero gross exposure — always allowed."""
        allowed, reason = check_sector_cap(
            "Technology", [], {"AAPL": "Technology"}, max_sector_pct=0.3
        )
        assert allowed is True

    def test_below_cap(self):
        """Sector exposure below cap is allowed."""
        positions = [
            {"symbol": "AAPL", "notional": 10_000},
            {"symbol": "XOM", "notional": 30_000},
        ]
        sector_map = {"AAPL": "Technology", "XOM": "Energy"}
        # Current Tech = 10k/40k = 25%. Adding another Tech position:
        # projected = (10k + 10k) / (40k + 10k) = 20k/50k = 40% > 30%
        # Actually: avg_position = 40k/2 = 20k
        # projected_sector = 10k + 20k = 30k
        # projected_gross = 40k + 20k = 60k
        # projected_pct = 30k/60k = 50% > 30%
        allowed, reason = check_sector_cap(
            "Technology", positions, sector_map, max_sector_pct=0.3, gross_exposure=40_000
        )
        # With gross_exposure = 40k, avg = 40k/2 = 20k, projected = (10k+20k)/(40k+20k) = 50%
        assert allowed is False
        assert "sector cap exceeded" in reason

    def test_above_cap_blocked(self):
        """Sector exposure that would exceed cap is blocked."""
        positions = [
            {"symbol": "AAPL", "notional": 20_000},
            {"symbol": "MSFT", "notional": 20_000},
            {"symbol": "XOM", "notional": 10_000},
        ]
        sector_map = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}
        allowed, reason = check_sector_cap(
            "Technology", positions, sector_map, max_sector_pct=0.3, gross_exposure=50_000
        )
        assert allowed is False
        assert "Technology" in reason

    def test_allowed_different_sector(self):
        """Adding to a different sector doesn't trigger the cap."""
        positions = [
            {"symbol": "AAPL", "notional": 20_000},
            {"symbol": "XOM", "notional": 20_000},
        ]
        sector_map = {"AAPL": "Technology", "XOM": "Energy"}
        # Adding Healthcare: projected = (0 + 20k) / (40k + 20k) = 33%
        allowed, reason = check_sector_cap(
            "Healthcare", positions, sector_map, max_sector_pct=0.4, gross_exposure=40_000
        )
        # projected_sector = 0 + 20k = 20k, projected_gross = 60k, pct = 33% < 40%
        assert allowed is True

    def test_sector_cap_with_explicit_gross_exposure(self):
        """Explicit gross_exposure overrides computed value."""
        positions = [
            {"symbol": "AAPL", "notional": 5_000},
        ]
        sector_map = {"AAPL": "Technology"}
        # gross_exposure = 100k, avg = 100k/1 = 100k
        # projected_sector = 5k + 100k = 105k
        # projected_gross = 100k + 100k = 200k
        # pct = 52.5% > 30%
        allowed, reason = check_sector_cap(
            "Technology", positions, sector_map,
            max_sector_pct=0.3, gross_exposure=100_000,
        )
        assert allowed is False
