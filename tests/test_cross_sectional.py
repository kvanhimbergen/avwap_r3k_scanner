"""Tests for analytics.cross_sectional — Phase 3 cross-sectional scoring."""

import math

import numpy as np
import pandas as pd
import pytest

from analytics.cross_sectional import (
    apply_cross_sectional_scoring,
    composite_rank,
    compute_percentile_ranks,
    compute_z_scores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidates(n: int, *, trend_scores=None, dist_pcts=None, slopes=None) -> pd.DataFrame:
    """Build a synthetic candidates DataFrame with *n* rows."""
    rng = np.random.default_rng(42)
    if trend_scores is None:
        trend_scores = rng.uniform(3.0, 20.0, size=n)
    if dist_pcts is None:
        dist_pcts = rng.uniform(0.1, 5.0, size=n)
    if slopes is None:
        slopes = rng.uniform(-0.02, 0.10, size=n)

    return pd.DataFrame({
        "Symbol": [f"SYM{i:03d}" for i in range(n)],
        "TrendScore": trend_scores,
        "Entry_DistPct": dist_pcts,
        "AVWAP_Slope": slopes,
        "SchemaVersion": 1,
        "ScanDate": "2026-01-15",
        "Direction": "Long",
        "Price": 100.0,
        "Entry_Level": 99.0,
        "Stop_Loss": 95.0,
        "Target_R1": 105.0,
        "Target_R2": 110.0,
        "Sector": "Tech",
        "Anchor": "earnings_gap",
        "TrendTier": "A",
    })


# ---------------------------------------------------------------------------
# compute_z_scores
# ---------------------------------------------------------------------------

class TestComputeZScores:
    def test_known_values(self):
        df = pd.DataFrame({"A": [10.0, 20.0, 30.0]})
        zs = compute_z_scores(df, ["A"])
        assert "A_Zscore" in zs.columns
        # mean=20, std=10 → z-scores = [-1, 0, 1]
        np.testing.assert_allclose(zs["A_Zscore"].values, [-1.0, 0.0, 1.0], atol=1e-9)

    def test_single_row_returns_zero(self):
        df = pd.DataFrame({"A": [42.0]})
        zs = compute_z_scores(df, ["A"])
        assert zs["A_Zscore"].iloc[0] == 0.0

    def test_empty_dataframe(self):
        df = pd.DataFrame({"A": pd.Series(dtype="float64")})
        zs = compute_z_scores(df, ["A"])
        assert len(zs) == 0

    def test_all_identical_values_std_zero(self):
        df = pd.DataFrame({"A": [5.0, 5.0, 5.0, 5.0]})
        zs = compute_z_scores(df, ["A"])
        assert (zs["A_Zscore"] == 0.0).all()

    def test_nan_handling(self):
        df = pd.DataFrame({"A": [10.0, np.nan, 30.0, 20.0]})
        zs = compute_z_scores(df, ["A"])
        # NaN row should get z-score = 0.0
        assert zs["A_Zscore"].iloc[1] == 0.0
        # Others should be valid z-scores (not NaN)
        assert not np.isnan(zs["A_Zscore"].iloc[0])
        assert not np.isnan(zs["A_Zscore"].iloc[2])

    def test_missing_column_returns_zeros(self):
        df = pd.DataFrame({"A": [1.0, 2.0, 3.0]})
        zs = compute_z_scores(df, ["NonExistent"])
        assert "NonExistent_Zscore" in zs.columns
        assert (zs["NonExistent_Zscore"] == 0.0).all()

    def test_multiple_columns(self):
        df = pd.DataFrame({"A": [10.0, 20.0, 30.0], "B": [1.0, 2.0, 3.0]})
        zs = compute_z_scores(df, ["A", "B"])
        assert "A_Zscore" in zs.columns
        assert "B_Zscore" in zs.columns
        # Both should have same z-scores since the ratios are identical
        np.testing.assert_allclose(zs["A_Zscore"].values, zs["B_Zscore"].values, atol=1e-9)


# ---------------------------------------------------------------------------
# compute_percentile_ranks
# ---------------------------------------------------------------------------

class TestComputePercentileRanks:
    def test_basic_ranking(self):
        df = pd.DataFrame({"A": [10.0, 20.0, 30.0, 40.0]})
        pr = compute_percentile_ranks(df, ["A"])
        assert "A_Pctile" in pr.columns
        assert pr["A_Pctile"].iloc[0] == 0.25
        assert pr["A_Pctile"].iloc[-1] == 1.0

    def test_nan_values_get_nan_rank(self):
        df = pd.DataFrame({"A": [10.0, np.nan, 30.0]})
        pr = compute_percentile_ranks(df, ["A"])
        assert np.isnan(pr["A_Pctile"].iloc[1])

    def test_missing_column(self):
        df = pd.DataFrame({"A": [1.0, 2.0]})
        pr = compute_percentile_ranks(df, ["NonExistent"])
        assert "NonExistent_Pctile" in pr.columns


# ---------------------------------------------------------------------------
# composite_rank
# ---------------------------------------------------------------------------

class TestCompositeRank:
    def test_default_weights(self):
        result = composite_rank(1.0, 1.0, 1.0)
        # 0.4*1 - 0.3*1 + 0.3*1 = 0.4
        assert abs(result - 0.4) < 1e-9

    def test_dist_inversion(self):
        # Higher dist_z should LOWER the composite rank
        high_dist = composite_rank(1.0, 2.0, 1.0)
        low_dist = composite_rank(1.0, 0.0, 1.0)
        assert low_dist > high_dist

    def test_custom_weights(self):
        result = composite_rank(
            1.0, 1.0, 1.0, weights={"trend": 0.5, "dist": 0.25, "slope": 0.25}
        )
        # 0.5*1 - 0.25*1 + 0.25*1 = 0.5
        assert abs(result - 0.5) < 1e-9

    def test_all_zeros(self):
        assert composite_rank(0.0, 0.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# apply_cross_sectional_scoring
# ---------------------------------------------------------------------------

class TestApplyCrossSectionalScoring:
    def test_top_decile_filtering(self):
        """50 candidates → ~5 selected (top 10%)."""
        df = _make_candidates(50)
        result = apply_cross_sectional_scoring(df, top_decile=0.1, hard_floor_trend=0.0)
        assert len(result) <= math.ceil(50 * 0.1) + 1  # quantile can include ties
        assert len(result) >= 1
        assert "Composite_Rank" in result.columns
        assert "TrendScore_Zscore" in result.columns
        assert "TrendScore_Pctile" in result.columns
        assert "DistPct_Zscore" in result.columns

    def test_hard_floor_enforcement(self):
        """Candidate with high rank but low trend_score is excluded."""
        # Create a candidate with extremely good dist/slope but trend_score=3.0
        df = _make_candidates(20, trend_scores=[3.0] + [15.0] * 19)
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=5.0)
        assert "SYM000" not in result["Symbol"].values

    def test_single_candidate_no_filtering(self):
        """Single candidate: z-scores are 0, no decile filtering applied."""
        df = _make_candidates(1, trend_scores=[10.0])
        result = apply_cross_sectional_scoring(df, hard_floor_trend=5.0)
        assert len(result) == 1
        assert result["TrendScore_Zscore"].iloc[0] == 0.0
        assert result["Composite_Rank"].iloc[0] == 0.0

    def test_all_identical_values(self):
        """All identical values → std=0, all z-scores=0."""
        df = _make_candidates(
            10,
            trend_scores=[10.0] * 10,
            dist_pcts=[2.0] * 10,
            slopes=[0.05] * 10,
        )
        result = apply_cross_sectional_scoring(df, top_decile=0.1, hard_floor_trend=5.0)
        assert (result["TrendScore_Zscore"] == 0.0).all()
        assert (result["DistPct_Zscore"] == 0.0).all()
        assert (result["Composite_Rank"] == 0.0).all()

    def test_nan_handling(self):
        """NaN in feature columns should not crash; z-score defaults to 0.0."""
        df = _make_candidates(5)
        df.loc[2, "TrendScore"] = np.nan
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=0.0)
        assert not result["TrendScore_Zscore"].isna().any()

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["Symbol", "TrendScore", "Entry_DistPct", "AVWAP_Slope"])
        result = apply_cross_sectional_scoring(df)
        assert result.empty
        assert "Composite_Rank" in result.columns

    def test_enriched_columns_present(self):
        df = _make_candidates(10)
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=0.0)
        for col in ("TrendScore_Zscore", "TrendScore_Pctile", "DistPct_Zscore", "Composite_Rank"):
            assert col in result.columns

    def test_hard_floor_below_all_removes_none(self):
        """If hard floor is below all trend scores, nobody is removed by floor."""
        df = _make_candidates(10, trend_scores=np.linspace(6.0, 20.0, 10))
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=5.0)
        assert len(result) == 10

    def test_top_decile_one_keeps_all_above_floor(self):
        """top_decile=1.0 keeps everyone that passes the floor."""
        df = _make_candidates(20, trend_scores=np.linspace(6.0, 20.0, 20))
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=5.0)
        assert len(result) == 20

    def test_composite_rank_ordered(self):
        """Higher TrendScore → higher Composite_Rank (all else equal)."""
        df = _make_candidates(
            5,
            trend_scores=[5.0, 10.0, 15.0, 20.0, 25.0],
            dist_pcts=[2.0] * 5,
            slopes=[0.05] * 5,
        )
        result = apply_cross_sectional_scoring(df, top_decile=1.0, hard_floor_trend=0.0)
        ranks = result.sort_values("TrendScore")["Composite_Rank"].values
        # Composite rank should increase with TrendScore
        assert all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))


# ---------------------------------------------------------------------------
# Config integration smoke test
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def test_config_fields_exist(self):
        from config import CFG
        c = CFG()
        assert c.CROSS_SECTIONAL_ENABLED is False
        assert c.CROSS_SECTIONAL_TOP_DECILE == 0.1
        assert c.CROSS_SECTIONAL_FEATURES == ["TrendScore", "Entry_DistPct", "AVWAP_Slope"]
        assert c.CROSS_SECTIONAL_HARD_FLOOR_TREND_SCORE == 5.0


# ---------------------------------------------------------------------------
# Feature store writer smoke test
# ---------------------------------------------------------------------------

class TestWriteCrossSectionalDistributions:
    def test_writes_json(self, tmp_path):
        from feature_store.writers import write_cross_sectional_distributions
        df = _make_candidates(10)
        path = write_cross_sectional_distributions(
            base_dir=tmp_path,
            date_str="2026-01-15",
            candidates_df=df,
            features=["TrendScore", "Entry_DistPct", "AVWAP_Slope"],
        )
        assert path.exists()
        import json
        data = json.loads(path.read_text())
        assert "features" in data
        assert "TrendScore" in data["features"]
        stats = data["features"]["TrendScore"]
        assert "mean" in stats
        assert "std" in stats
        assert "p50" in stats
