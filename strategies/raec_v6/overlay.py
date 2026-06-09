"""Vol-target overlay and drawdown circuit breaker.

Given book_targets (from the allocator) + market state, scale total
exposure so the portfolio's expected vol ≈ target_vol = 1.5 × SPY 60d
realized vol.

Forecast vol uses max(realized_20d, ewma_10d, vix/16) — the max is
intentional: any of three signals saying "vol is high" wins, so the
overlay reacts to leading indicators rather than only trailing P&L.

Drawdown breaker: when rolling DD < -15%, exposure × 0.5. Re-arms when
DD heals to -7%.

Shock-day breaker (separate state machine, returned in the result):
when 1-day book return < -3.5σ of trailing 60d, suggest freezing
rebalancing for 2 days and posting a manual-ack alert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


# Defaults; coordinator can override
DEFAULT_VOL_TARGET_MULTIPLIER = 1.5
DEFAULT_DD_BREAKER_THRESHOLD = 0.15  # 15% peak-to-trough
DEFAULT_DD_BREAKER_REARM = 0.07
DEFAULT_DD_BREAKER_SCALE = 0.50  # cut exposure to half when tripped
DEFAULT_SHOCK_SIGMA = 3.5
DEFAULT_SHOCK_FREEZE_DAYS = 2
DEFAULT_FLOOR_EXPOSURE = 0.10  # never go fully to cash on vol overlay alone
DEFAULT_CEILING_EXPOSURE = 2.0  # allow overlay to scale book targets UP when
# forecast vol is well below target. This does NOT imply margin: the final
# weights are still capped to sum ≤ 1.0 by `_cap_to_full_deployment`. The
# scale-up matters because the allocator's risk-parity base often under-deploys
# (low-vol strategies like BondCarry get a big share but generate low return).
# Raising the ceiling lets the overlay fully deploy the book via the leveraged
# ETFs already inside the strategies' universes when conditions warrant it.


@dataclass(frozen=True)
class OverlayResult:
    """Output of the overlay for one as-of date."""

    final_weights: dict[str, float]
    exposure_scale: float
    target_vol: float
    forecast_vol: float
    dd_breaker_active: bool
    shock_day_detected: bool
    freeze_rebalancing_until_idx: int  # number of days from now to freeze; 0 = no freeze
    diagnostics: dict[str, object]


def _portfolio_realized_vol(
    weights: Mapping[str, float],
    daily_returns_per_symbol: Mapping[str, Sequence[float]],
    window: int = 20,
) -> float:
    """Approximate portfolio vol from per-symbol daily returns × weights.

    Uses sum-of-weighted-variances + light correlation (full covariance
    requires the matrix; for the overlay's purposes, a weighted sum of
    individual vols with a 0.7 correlation assumption is conservative
    enough to size exposure honestly).

    Returns 0.0 if no data.
    """
    if not weights:
        return 0.0
    annualizer = math.sqrt(252)
    # Per-symbol annualized vol from the last `window` returns.
    vols: dict[str, float] = {}
    for sym, rets in daily_returns_per_symbol.items():
        if sym not in weights:
            continue
        rs = list(rets)[-window:]
        if len(rs) < 5:
            continue
        mean = sum(rs) / len(rs)
        var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
        if var > 0:
            vols[sym] = math.sqrt(var) * annualizer
    if not vols:
        return 0.0
    # Conservative portfolio vol: weighted vols with 0.7 average correlation
    # (over-states vol vs true correlation matrix, which is fine — we'd rather
    # de-risk slightly too much than too little under uncertainty).
    weighted = sum(weights.get(s, 0.0) * v for s, v in vols.items())
    return weighted * 0.85  # tighter than 1.0 (perfectly correlated) but not naive sum


def _ewma_vol(returns: Sequence[float], halflife: int = 10) -> float:
    if len(returns) < 5:
        return 0.0
    decay = math.log(2) / halflife
    weights = [math.exp(-decay * (len(returns) - 1 - i)) for i in range(len(returns))]
    total_w = sum(weights)
    if total_w <= 0:
        return 0.0
    mean = sum(w * r for w, r in zip(weights, returns)) / total_w
    var = sum(w * (r - mean) ** 2 for w, r in zip(weights, returns)) / total_w
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


def _max_drawdown(
    equity_curve: Sequence[float], rolling_window: int = 252
) -> tuple[float, float]:
    """Return (current_dd, max_dd) using a ROLLING peak over the trailing
    `rolling_window` observations.

    Using all-time peak makes the DD breaker effectively one-way: once an
    old peak is far above the de-leveraged system's reach, the breaker
    never re-arms even after the original shock has long passed. A rolling
    window (default ~1 year) lets the system re-arm once the bad period
    rolls out of the window.

    dd values are negative (e.g. -0.12 = 12% off rolling peak).
    """
    if not equity_curve:
        return 0.0, 0.0
    window_curve = list(equity_curve[-rolling_window:])
    peak = window_curve[0]
    max_dd = 0.0
    for v in window_curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (v / peak) - 1.0
            max_dd = min(max_dd, dd)
    current_dd = (window_curve[-1] / peak) - 1.0 if peak > 0 else 0.0
    return current_dd, max_dd


def apply_overlay(
    *,
    book_targets: Mapping[str, float],
    spy_realized_vol_60d: float,
    vix_implied: float,
    portfolio_daily_returns: Sequence[float],
    per_symbol_daily_returns: Mapping[str, Sequence[float]],
    equity_curve: Sequence[float],
    dd_breaker_currently_active: bool = False,
    target_vol_multiplier: float = DEFAULT_VOL_TARGET_MULTIPLIER,
    floor_exposure: float = DEFAULT_FLOOR_EXPOSURE,
    ceiling_exposure: float = DEFAULT_CEILING_EXPOSURE,
) -> OverlayResult:
    """Scale book_targets by exposure_scale; return weights + diagnostics.

    Args:
        book_targets: from allocator.
        spy_realized_vol_60d: SPY's own 60d annualized vol (from SignalState).
        vix_implied: VIX (annualized vol), e.g. 0.18.
        portfolio_daily_returns: trailing daily total-book P&L returns
                                 (for ewma vol). 0 length OK on day 1.
        per_symbol_daily_returns: per-symbol returns; used to estimate
                                  portfolio vol from current book composition
                                  even on day 1 (before P&L history exists).
        equity_curve: rolling equity values; used for DD breaker.
        dd_breaker_currently_active: passed in by coordinator; the breaker
                                     stays armed until DD heals to rearm threshold.

    Returns OverlayResult with final_weights (scaled) and breaker flags.
    """
    # Target.
    target_vol = (target_vol_multiplier * spy_realized_vol_60d) if spy_realized_vol_60d > 0 else 0.24

    # Forecast components.
    composition_vol = _portfolio_realized_vol(book_targets, per_symbol_daily_returns)
    ewma = _ewma_vol(list(portfolio_daily_returns))
    # VIX is annualized implied vol; historically it overshoots realized
    # by ~20-30% (vol risk premium). Discount to make it a fair forecast
    # of REALIZED rather than implied. Without this discount the overlay
    # over-de-leverages whenever VIX > 20 even when the book itself is
    # diversified and running at much lower realized vol.
    vix_discounted = vix_implied * 0.7

    if len(portfolio_daily_returns) >= 60:
        # We have a real portfolio return history — trust it. The leading
        # indicator (VIX, discounted) acts as a floor so regime shifts
        # still register before realized vol catches up.
        forecast_vol = max(ewma, vix_discounted)
    else:
        # Cold-start: no real history yet. Fall back to composition vol
        # (which over-estimates for diversified books — but during the
        # first 60 days we'd rather under-deploy than over-deploy).
        forecast_vol = max(composition_vol, ewma, vix_discounted)
    if forecast_vol <= 0:
        forecast_vol = target_vol  # fallback: no info → assume on target

    raw_scale = target_vol / forecast_vol
    exposure_scale = max(floor_exposure, min(ceiling_exposure, raw_scale))

    # Cap-to-full-deployment safety: even with ceiling > 1.0, the final book
    # weights must sum to ≤ 1.0 (we have no margin — leverage comes only via
    # the leveraged ETFs already inside the book). If the requested scale-up
    # would push allocated weight above 1.0, reduce the scale just enough to
    # land at 1.0.
    raw_total = sum(book_targets.values())
    if raw_total > 0 and exposure_scale * raw_total > 1.0:
        exposure_scale = 1.0 / raw_total

    # DD breaker.
    current_dd, max_dd = _max_drawdown(equity_curve)
    dd_breaker_active = dd_breaker_currently_active
    if not dd_breaker_active:
        if current_dd <= -DEFAULT_DD_BREAKER_THRESHOLD:
            dd_breaker_active = True
    else:
        # Re-arm only when DD heals above rearm threshold.
        if current_dd >= -DEFAULT_DD_BREAKER_REARM:
            dd_breaker_active = False

    if dd_breaker_active:
        exposure_scale *= DEFAULT_DD_BREAKER_SCALE

    # Shock-day detection: today's return < -k σ of trailing 60.
    shock = False
    freeze_days = 0
    if len(portfolio_daily_returns) >= 60:
        body = list(portfolio_daily_returns[-60:-1])  # exclude today
        today = portfolio_daily_returns[-1]
        if body:
            mean_body = sum(body) / len(body)
            var_body = sum((r - mean_body) ** 2 for r in body) / (len(body) - 1)
            if var_body > 0:
                sd = math.sqrt(var_body)
                if today < mean_body - DEFAULT_SHOCK_SIGMA * sd:
                    shock = True
                    freeze_days = DEFAULT_SHOCK_FREEZE_DAYS

    final = {sym: w * exposure_scale for sym, w in book_targets.items()}

    return OverlayResult(
        final_weights=final,
        exposure_scale=exposure_scale,
        target_vol=target_vol,
        forecast_vol=forecast_vol,
        dd_breaker_active=dd_breaker_active,
        shock_day_detected=shock,
        freeze_rebalancing_until_idx=freeze_days,
        diagnostics={
            "composition_vol": composition_vol,
            "ewma_vol": ewma,
            "vix_implied": vix_implied,
            "vix_discounted": vix_discounted,
            "current_dd": current_dd,
            "max_dd": max_dd,
            "raw_scale": raw_scale,
        },
    )
