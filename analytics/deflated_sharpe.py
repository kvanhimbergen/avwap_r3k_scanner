"""Deflated Sharpe Ratio (DSR).

Implements Bailey & Lopez de Prado (2014) correction for multiple testing
of trading strategies. Returns a p-value indicating the probability that
the observed Sharpe ratio exceeds the expected maximum under the null
hypothesis of zero true Sharpe.
"""

from __future__ import annotations

import math

from scipy.stats import norm


# Euler-Mascheroni constant
EULER_GAMMA = 0.5772156649015329


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    variance_sharpe: float,
    T: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Compute the Deflated Sharpe Ratio p-value.

    Parameters
    ----------
    observed_sharpe : float
        The Sharpe ratio of the selected strategy.
    n_trials : int
        Number of strategy/parameter combinations tested.
    variance_sharpe : float
        Variance of Sharpe ratios across all trials.
    T : int
        Number of return observations used to compute the Sharpe ratio.
    skew : float
        Skewness of the strategy returns (default 0.0 = normal).
    kurtosis : float
        Kurtosis of the strategy returns (default 3.0 = normal).

    Returns
    -------
    float
        p-value: probability that observed Sharpe exceeds expected max under null.
        Low values (< 0.05) suggest the Sharpe is statistically significant
        even after correcting for multiple testing.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if T < 1:
        raise ValueError(f"T must be >= 1, got {T}")
    if variance_sharpe < 0:
        raise ValueError(f"variance_sharpe must be >= 0, got {variance_sharpe}")

    # Expected maximum Sharpe under the null (Bailey & Lopez de Prado)
    std_sharpe = math.sqrt(variance_sharpe) if variance_sharpe > 0 else 0.0

    if n_trials == 1:
        expected_max_sharpe = 0.0
    else:
        expected_max_sharpe = std_sharpe * (
            (1 - EULER_GAMMA) * norm.ppf(1 - 1 / n_trials)
            + EULER_GAMMA * norm.ppf(1 - 1 / (n_trials * math.e))
        )

    # Adjust observed Sharpe for non-normality
    sr = observed_sharpe
    sr_adjusted = sr * math.sqrt(
        1 + (skew / 6) * sr - ((kurtosis - 3) / 24) * sr**2
    )

    # Standard error of the Sharpe ratio estimate
    if T <= 1:
        # With only 1 observation, SE is undefined; return 1.0 (not significant)
        return 1.0

    se_sharpe = math.sqrt(
        (1 - skew * sr_adjusted + ((kurtosis - 1) / 4) * sr_adjusted**2) / (T - 1)
    )

    if se_sharpe <= 0:
        return 0.0 if sr_adjusted > expected_max_sharpe else 1.0

    # Test statistic: how many SEs is the adjusted Sharpe above the expected max?
    test_stat = (sr_adjusted - expected_max_sharpe) / se_sharpe

    # p-value: probability of observing this or higher under the null
    # We want P(SR > E[max]) so p = 1 - CDF(test_stat)
    p_value = 1.0 - norm.cdf(test_stat)

    return p_value
