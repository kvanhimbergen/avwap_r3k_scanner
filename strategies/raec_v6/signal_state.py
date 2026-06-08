"""SignalState — snapshot of all market signals strategies read at compute time."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class SignalState:
    """Immutable snapshot of market state for a given as-of date.

    Strategies read this to make decisions; they never compute these
    themselves (so a strategy can be tested with a fixture state without
    needing live regime data).

    Built by strategies.raec_v6.build_signal_state.build(asof, prices).
    """

    asof_date: date

    # Regime label from analytics/regime_e1_runner.py. One of:
    # RISK_ON / NEUTRAL / RISK_OFF / STRESSED / "" (unavailable).
    # The string is preserved as-is; strategies map it to their own gate.
    regime_label: str
    regime_confidence: float  # [0, 1]

    # Cross-asset trend votes — one signed score per asset class.
    # Positive = trending up, negative = trending down. Scale roughly [-3, +3].
    # Used by CrossAssetTrend and by the allocator's regime alignment check.
    cross_asset_trend: Mapping[str, float] = field(default_factory=dict)

    # Vol-percentile per symbol over trailing 252 trading days. [0, 1].
    # 0.0 = at min, 1.0 = at max. Used by EquityLeveragedMomentum's
    # leverage cap and by the vol overlay.
    vol_percentile_252d: Mapping[str, float] = field(default_factory=dict)

    # SPY realized vol (annualized, decimal e.g. 0.16 = 16%) over trailing 60d.
    # Used by the overlay to compute the 1.5x target.
    spy_realized_vol_60d: float = 0.0

    # VIX-implied vol (decimal, e.g. 0.20 = VIX of 20).
    # Used by the overlay as the leading-indicator component of the vol forecast.
    vix_implied: float = 0.0

    # Yield-curve / duration signal. Positive = duration favorable
    # (TLT/EDV); negative = inverse-treasury (TBT) or short-end (SHY).
    # Scale roughly [-3, +3]. None if no data.
    yield_curve_signal: float | None = None

    # Credit-spread direction. Positive = HYG outperforming IEF =
    # spreads tightening / credit favorable. Negative = spreads widening
    # / credit stress. Scale roughly [-3, +3]. None if no data.
    credit_spread_signal: float | None = None
