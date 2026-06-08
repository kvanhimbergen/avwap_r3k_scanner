"""Allocator — conviction-weighted risk parity with caps and net-out.

Given a list of strategy outputs, decide each strategy's share of the
book, then combine into a single book-level target weight dict with
per-symbol caps applied.

Math (per plan §architecture):

    base_share[s]      = (1 / strategy_s.realized_vol_60d) / Σ        # risk parity
    gated_share[s]     = base_share[s] · regime_gate[s]
    conviction_tilt[s] = 0.5 + 0.5 · conviction[s]                    # [0.5, 1.0]
    skill_tilt[s]      = sigmoid(clipped_sharpe[s] / 2)               # ~[0.1, 0.9]
    raw_share[s]       = gated_share[s] · conviction_tilt[s] · skill_tilt[s]
    capped_share[s]    = min(raw_share[s] / Σ, manifest.max_share_cap)
    final_share[s]     = renormalize(capped_share)
    Δshare ≤ 5% per day per strategy                                  # turnover damper

Then book_targets = Σ final_share[s] · strategy_s.weights, with a
post-aggregation per-symbol cap of 25%.

Failed strategies (`StrategyOutput is None`) get their share routed to
cash and produce a `failed` entry the coordinator can surface via Slack.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from strategies.raec_v6.strategy_output import StrategyOutput


@dataclass(frozen=True)
class AllocatorResult:
    """Output of the allocator for one as-of date."""

    # Final book-level target weights (sums to <= 1.0; residual = cash).
    book_targets: dict[str, float]
    # Per-strategy share of the book AFTER caps + renormalization.
    strategy_shares: dict[str, float]
    # Strategies that returned None or raised — share routed to cash.
    failed_strategies: tuple[str, ...] = ()
    # Per-symbol contribution from each strategy (for diagnostics).
    contributions: dict[str, dict[str, float]] = field(default_factory=dict)


def _sigmoid(x: float) -> float:
    if x > 50:
        return 1.0
    if x < -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _pairwise_correlation(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation; None if either series has 0 variance or <5 points."""
    n = min(len(a), len(b))
    if n < 5:
        return None
    aa, bb = a[-n:], b[-n:]
    ma = sum(aa) / n
    mb = sum(bb) / n
    da = [x - ma for x in aa]
    db = [x - mb for x in bb]
    cov = sum(x * y for x, y in zip(da, db))
    va = sum(x * x for x in da)
    vb = sum(x * x for x in db)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def _correlation_derate(
    raw_inv: Mapping[str, float],
    strategy_returns: Mapping[str, list[float]] | None,
    *,
    lookback: int = 60,
    threshold: float = 0.7,
    floor: float = 0.5,
) -> dict[str, float]:
    """Down-scale highly-correlated strategies' risk-parity base share.

    For each strategy, compute its average pairwise correlation with the
    others (over the most recent `lookback` days). If avg corr > threshold,
    scale raw_inv[s] by `max(floor, 1 - (avg_corr - threshold))`.

    Strategies with <30 days of history don't participate (they neither
    derate nor get derated by others — too noisy to estimate correlation).
    """
    out = dict(raw_inv)
    if not strategy_returns or len(strategy_returns) < 2:
        return out
    eligible = {
        sid: rets[-lookback:]
        for sid, rets in strategy_returns.items()
        if sid in raw_inv and len(rets) >= 30
    }
    if len(eligible) < 2:
        return out

    # Compute pairwise correlation matrix.
    corr: dict[str, dict[str, float]] = {sid: {} for sid in eligible}
    sids = list(eligible)
    for i, a_sid in enumerate(sids):
        for b_sid in sids[i + 1 :]:
            c = _pairwise_correlation(eligible[a_sid], eligible[b_sid])
            if c is None:
                continue
            corr[a_sid][b_sid] = c
            corr[b_sid][a_sid] = c

    # Per-strategy: avg correlation with eligible others; haircut if > threshold.
    for sid in eligible:
        peers = [c for c in corr[sid].values()]
        if not peers:
            continue
        avg = sum(peers) / len(peers)
        if avg > threshold:
            haircut = max(floor, 1.0 - (avg - threshold))
            out[sid] = out[sid] * haircut
    return out


def _skill_tilt(
    *,
    recent_sharpe: float | None,
    backtest_prior: float,
    has_live_history: bool,
) -> float:
    """Map recent skill -> [~0.1, ~0.9].

    - Without live history (first ~20 days), blend prior toward 0 (0.3 ×).
    - With live history, use clipped recent Sharpe.
    """
    if not has_live_history:
        effective = backtest_prior * 0.3
    else:
        if recent_sharpe is None:
            effective = backtest_prior * 0.3
        else:
            effective = max(-2.0, min(2.0, recent_sharpe))
    return _sigmoid(effective / 2.0)


def allocate(
    *,
    outputs: Mapping[str, StrategyOutput | None],
    recent_sharpes: Mapping[str, float] | None = None,
    has_live_history: Mapping[str, bool] | None = None,
    prior_shares: Mapping[str, float] | None = None,
    strategy_returns: Mapping[str, list[float]] | None = None,
    turnover_damper_per_day: float = 0.05,
    per_symbol_cap: float = 0.25,
    correlation_threshold: float = 0.7,
    correlation_lookback: int = 60,
) -> AllocatorResult:
    """Combine strategy outputs into a single book target.

    Args:
        outputs: {strategy_id: StrategyOutput or None}. None means the
                 strategy errored or chose not to participate — its share
                 routes to cash.
        recent_sharpes: {strategy_id: rolling Sharpe}. None entries fall
                        back to the manifest prior.
        has_live_history: {strategy_id: bool}. False means the strategy
                          hasn't accumulated enough live track record yet.
        prior_shares: {strategy_id: yesterday's share}. If provided, the
                      turnover damper limits |Δshare| ≤ turnover_damper_per_day.
        turnover_damper_per_day: max change in any strategy's share per day.
        per_symbol_cap: max fraction any single symbol can take of the book.
    """
    recent_sharpes = recent_sharpes or {}
    has_live_history = has_live_history or {}
    prior_shares = prior_shares or {}

    valid: dict[str, StrategyOutput] = {}
    failed: list[str] = []
    for sid, out in outputs.items():
        if out is None:
            failed.append(sid)
            continue
        valid[sid] = out

    if not valid:
        return AllocatorResult(
            book_targets={},
            strategy_shares={},
            failed_strategies=tuple(failed),
        )

    # Risk parity base: 1/vol normalized. Strategies with vol<=0 are treated
    # as 0-share (allocator can't size them; they go to cash residual).
    raw_inv_base: dict[str, float] = {}
    for sid, out in valid.items():
        if out.realized_vol_60d > 0:
            raw_inv_base[sid] = 1.0 / out.realized_vol_60d
        else:
            raw_inv_base[sid] = 0.0

    # Correlation derate: down-scale strategies that are highly correlated
    # with others over the trailing window. Two correlated strategies
    # double-count their exposure; the haircut prevents the allocator from
    # treating them as independent diversifiers. The derate is applied AFTER
    # the baseline is computed so that the total allocator commitment
    # genuinely shrinks (not just rebalances) when strategies are correlated.
    raw_inv = _correlation_derate(
        raw_inv_base,
        strategy_returns,
        lookback=correlation_lookback,
        threshold=correlation_threshold,
    )

    # Apply gate, conviction tilt, skill tilt.
    # We compute two parallel sums:
    #   - baseline_weighted uses raw_inv_base (no derate). Total of this is
    #     what the allocator WOULD have committed if strategies were
    #     uncorrelated.
    #   - weighted uses raw_inv (with derate). Total of this is what the
    #     allocator commits given observed correlations.
    # Normalizing by baseline_total (not by total_weighted) preserves the
    # derate: correlated strategies see their shares drop in absolute terms
    # and the difference flows to the cash residual.
    weighted: dict[str, float] = {}
    baseline_weighted: dict[str, float] = {}
    for sid, out in valid.items():
        if raw_inv[sid] <= 0:
            weighted[sid] = 0.0
            baseline_weighted[sid] = 0.0
            continue
        gate = out.regime_gate
        conv_tilt = 0.5 + 0.5 * out.conviction
        skill = _skill_tilt(
            recent_sharpe=recent_sharpes.get(sid),
            backtest_prior=out.manifest.backtest_oos_sharpe,
            has_live_history=has_live_history.get(sid, False),
        )
        weighted[sid] = raw_inv[sid] * gate * conv_tilt * skill
        baseline_weighted[sid] = raw_inv_base[sid] * gate * conv_tilt * skill

    baseline_total = sum(baseline_weighted.values())
    if baseline_total <= 0:
        # Every strategy is either off or zero-vol. Route everything to cash.
        return AllocatorResult(
            book_targets={},
            strategy_shares={sid: 0.0 for sid in valid},
            failed_strategies=tuple(failed),
        )

    # Pre-cap shares: normalize by baseline_total so the derate genuinely
    # reduces total commitment (the missing fraction goes to cash residual).
    pre_cap = {sid: w / baseline_total for sid, w in weighted.items()}

    # Apply per-strategy max_share_cap from manifest, then renormalize.
    # Strategies that get capped contribute their cap; un-capped strategies
    # absorb the freed share proportionally. Iterate to a fixed point so a
    # second strategy doesn't blow through its own cap after redistribution.
    capped = dict(pre_cap)
    for _ in range(8):  # ≤8 iterations; converges fast in practice
        overflow = 0.0
        uncapped_total = 0.0
        for sid, share in capped.items():
            cap = valid[sid].manifest.max_share_cap
            if share > cap:
                overflow += share - cap
                capped[sid] = cap
            elif share < cap:
                uncapped_total += share
        if overflow <= 1e-9 or uncapped_total <= 0:
            break
        # Redistribute overflow to uncapped strategies pro-rata.
        for sid, share in list(capped.items()):
            cap = valid[sid].manifest.max_share_cap
            if share < cap:
                capped[sid] = share + overflow * (share / uncapped_total)
    # After cap iterations, renormalize so capped shares sum to <= 1.
    cap_total = sum(capped.values())
    if cap_total > 0:
        # Don't force shares to sum to 1 — if all caps were hit (rare), the
        # residual goes to cash. So we normalize only if cap_total > 1.
        if cap_total > 1.0:
            capped = {sid: s / cap_total for sid, s in capped.items()}

    # Turnover damper: cap day-over-day change in each strategy's share.
    if prior_shares:
        damped: dict[str, float] = {}
        for sid, share in capped.items():
            prior = prior_shares.get(sid, share)
            delta = share - prior
            if abs(delta) > turnover_damper_per_day:
                delta = math.copysign(turnover_damper_per_day, delta)
            damped[sid] = max(0.0, prior + delta)
        capped = damped

    # Final renormalize-down if turnover damper let the sum exceed 1.
    final_total = sum(capped.values())
    if final_total > 1.0:
        capped = {sid: s / final_total for sid, s in capped.items()}

    final_shares = capped

    # Build book-level targets by summing share × strategy.weights.
    book: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {sid: {} for sid in valid}
    for sid, share in final_shares.items():
        if share <= 0:
            continue
        out = valid[sid]
        for sym, w in out.weights.items():
            sym_u = sym.upper()
            contrib = share * w
            book[sym_u] = book.get(sym_u, 0.0) + contrib
            contributions[sid][sym_u] = contrib

    # Per-symbol cap. Excess is dropped (goes to cash residual, NOT to other
    # symbols — would distort what each strategy declared it wanted).
    capped_book: dict[str, float] = {}
    for sym, w in book.items():
        capped_book[sym] = min(w, per_symbol_cap)

    return AllocatorResult(
        book_targets=capped_book,
        strategy_shares=final_shares,
        failed_strategies=tuple(failed),
        contributions=contributions,
    )
