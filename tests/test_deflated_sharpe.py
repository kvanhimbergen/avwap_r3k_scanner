"""Tests for analytics.deflated_sharpe — Deflated Sharpe Ratio."""

from __future__ import annotations

import pytest

from analytics.deflated_sharpe import deflated_sharpe_ratio


class TestSignificantSharpe:
    def test_high_sharpe_single_trial_is_significant(self):
        # Sharpe=2.0 with only 1 trial — no multiple testing penalty
        p = deflated_sharpe_ratio(
            observed_sharpe=2.0, n_trials=1, variance_sharpe=0.5, T=252
        )
        assert p < 0.05, f"Expected significant p-value, got {p}"

    def test_very_high_sharpe_many_trials_still_significant(self):
        p = deflated_sharpe_ratio(
            observed_sharpe=3.0, n_trials=100, variance_sharpe=0.5, T=500
        )
        assert p < 0.05, f"Expected significant p-value, got {p}"


class TestInsignificantSharpe:
    def test_low_sharpe_many_trials_not_significant(self):
        # Sharpe=0.5 with 100 trials — should fail multiple testing correction
        p = deflated_sharpe_ratio(
            observed_sharpe=0.5, n_trials=100, variance_sharpe=0.5, T=252
        )
        assert p > 0.05, f"Expected non-significant p-value, got {p}"

    def test_mediocre_sharpe_many_trials(self):
        p = deflated_sharpe_ratio(
            observed_sharpe=1.0, n_trials=200, variance_sharpe=1.0, T=252
        )
        assert p > 0.05, f"Expected non-significant p-value, got {p}"


class TestSkewKurtosis:
    def test_skew_changes_result(self):
        p_normal = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=0.0, kurtosis=3.0,
        )
        p_skewed = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=-1.0, kurtosis=3.0,
        )
        assert p_normal != p_skewed, "Skew should change the p-value"

    def test_kurtosis_changes_result(self):
        p_normal = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=0.0, kurtosis=3.0,
        )
        p_heavy_tail = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=0.0, kurtosis=5.0,
        )
        assert p_normal != p_heavy_tail, "Kurtosis should change the p-value"

    def test_negative_skew_increases_p_value(self):
        # Negative skew penalizes the Sharpe, making it harder to be significant
        p_normal = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=0.0, kurtosis=3.0,
        )
        p_neg_skew = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.5, T=252,
            skew=-2.0, kurtosis=3.0,
        )
        assert p_neg_skew > p_normal, "Negative skew should increase p-value"


class TestEdgeCases:
    def test_n_trials_1(self):
        # Single trial: no multiple testing correction, just standard test
        p = deflated_sharpe_ratio(
            observed_sharpe=1.0, n_trials=1, variance_sharpe=0.5, T=252
        )
        assert 0.0 <= p <= 1.0

    def test_T_1_returns_1(self):
        # T=1: SE undefined, should return 1.0 (not significant)
        p = deflated_sharpe_ratio(
            observed_sharpe=2.0, n_trials=1, variance_sharpe=0.5, T=1
        )
        assert p == 1.0

    def test_zero_variance(self):
        # All trials have same Sharpe, variance=0
        p = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=10, variance_sharpe=0.0, T=252
        )
        assert 0.0 <= p <= 1.0

    def test_zero_observed_sharpe(self):
        p = deflated_sharpe_ratio(
            observed_sharpe=0.0, n_trials=10, variance_sharpe=0.5, T=252
        )
        assert p > 0.5, "Zero Sharpe should be non-significant"

    def test_invalid_n_trials_raises(self):
        with pytest.raises(ValueError, match="n_trials must be >= 1"):
            deflated_sharpe_ratio(
                observed_sharpe=1.0, n_trials=0, variance_sharpe=0.5, T=252
            )

    def test_invalid_T_raises(self):
        with pytest.raises(ValueError, match="T must be >= 1"):
            deflated_sharpe_ratio(
                observed_sharpe=1.0, n_trials=1, variance_sharpe=0.5, T=0
            )

    def test_negative_variance_raises(self):
        with pytest.raises(ValueError, match="variance_sharpe must be >= 0"):
            deflated_sharpe_ratio(
                observed_sharpe=1.0, n_trials=1, variance_sharpe=-0.1, T=252
            )

    def test_p_value_bounded_0_1(self):
        for sharpe in [0.0, 0.5, 1.0, 2.0, 5.0]:
            for n in [1, 10, 100]:
                p = deflated_sharpe_ratio(
                    observed_sharpe=sharpe, n_trials=n, variance_sharpe=0.5, T=252
                )
                assert 0.0 <= p <= 1.0, f"p={p} out of bounds for SR={sharpe}, n={n}"


class TestMonotonicity:
    def test_more_trials_increases_p_value(self):
        p_few = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=5, variance_sharpe=0.5, T=252
        )
        p_many = deflated_sharpe_ratio(
            observed_sharpe=1.5, n_trials=100, variance_sharpe=0.5, T=252
        )
        assert p_many > p_few, "More trials should raise the bar (higher p-value)"

    def test_higher_sharpe_decreases_p_value(self):
        p_low = deflated_sharpe_ratio(
            observed_sharpe=0.5, n_trials=10, variance_sharpe=0.5, T=252
        )
        p_high = deflated_sharpe_ratio(
            observed_sharpe=2.5, n_trials=10, variance_sharpe=0.5, T=252
        )
        assert p_high < p_low, "Higher Sharpe should be more significant (lower p)"
