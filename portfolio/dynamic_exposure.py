"""Dynamic gross exposure targeting.

Scales portfolio gross exposure inversely with realized portfolio volatility.
Low vol + RISK_ON regime = higher exposure; vol spike + regime deterioration = lower.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DynamicExposureResult:
    target_exposure: float
    realized_vol: float
    regime_multiplier: float
    raw_target: float
    clamped: bool


def compute_realized_portfolio_vol(
    daily_pnl_series: Sequence[float],
    lookback_days: int = 20,
) -> float:
    """Compute annualized volatility from daily P&L returns.

    Returns 0.0 when fewer than 5 data points or all zeros.
    """
    if lookback_days < 1:
        return 0.0

    values = list(daily_pnl_series)[-lookback_days:]

    if len(values) < 5:
        return 0.0

    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)

    if variance <= 0.0:
        return 0.0

    daily_std = math.sqrt(variance)
    return daily_std * math.sqrt(252)


def compute_target_exposure(
    realized_portfolio_vol: float,
    target_vol: float,
    regime_multiplier: float,
    floor: float = 0.2,
    ceiling: float = 1.0,
) -> DynamicExposureResult:
    """Vol-targeting formula for dynamic gross exposure.

    If realized_vol <= 0: return ceiling * regime_multiplier (capped).
    Otherwise: raw_target = target_vol / realized_vol, then regime-adjusted.
    Result is clamped between floor and ceiling.
    """
    if realized_portfolio_vol <= 0:
        raw_target = ceiling
        regime_adjusted = ceiling * regime_multiplier
    else:
        raw_target = target_vol / realized_portfolio_vol
        regime_adjusted = raw_target * regime_multiplier

    clamped_value = max(floor, min(ceiling, regime_adjusted))
    was_clamped = regime_adjusted < floor or regime_adjusted > ceiling

    return DynamicExposureResult(
        target_exposure=clamped_value,
        realized_vol=realized_portfolio_vol,
        regime_multiplier=regime_multiplier,
        raw_target=raw_target,
        clamped=was_clamped,
    )
