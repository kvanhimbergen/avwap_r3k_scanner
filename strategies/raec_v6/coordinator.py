"""RAEC v6 coordinator — daily dry-run orchestrator.

Runs once per trading day in the post-scan pipeline. Pure dry-run during
Phase E parallel period; live cutover happens in Phase F via a separate
adapter. The architecture:

    1. Load persistent state (shadow book + allocator history + breakers)
    2. Build SignalState for asof_date from price provider + regime + VIX
    3. Call all 7 strategies (pure functions); collect outputs
    4. Allocator → conviction-weighted risk-parity book targets
    5. Overlay → vol-scale + DD/shock breakers
    6. Compute intents (delta from shadow positions to target × equity)
    7. Step shadow book at today's closes (advances equity curve)
    8. Persist updated state
    9. Write ledger record to ledger/RAEC_V6/<date>.jsonl
    10. Post `[V6 DRY]` advisory via DryRunAdapter

The coordinator NEVER touches the real Schwab book. The shadow book lives
entirely in state/strategies/RAEC_V6_DRY_RUN/coordinator.json.

CLI:
    venv/bin/python -m strategies.raec_v6.coordinator \\
        --asof-date 2026-06-09 [--repo-root /path/to/repo]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from data.prices import PriceProvider, get_default_price_provider
from strategies.raec_v6 import asset_classes as ac
from strategies.raec_v6.allocator import AllocatorResult, allocate
from strategies.raec_v6.dry_run_adapter import (
    DRY_RUN_BOOK_ID,
    DryRunAdapter,
    V6DryRunSafetyError,
    V6Intent,
)
from strategies.raec_v6.overlay import OverlayResult, apply_overlay
from strategies.raec_v6.shadow_book import ShadowBook
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.signals.credit_spread import compute_credit_spread_signal
from strategies.raec_v6.signals.cross_asset_trend import (
    REPRESENTATIVES,
    compute_cross_asset_trend,
)
from strategies.raec_v6.signals.regime_label import classify_from_spy_closes
from strategies.raec_v6.signals.vix_implied import compute_vix_implied
from strategies.raec_v6.signals.vol_percentile import compute_vol_percentile
from strategies.raec_v6.signals.yield_curve import compute_yield_curve_signal
from strategies.raec_v6.strategies.bond_carry import BondCarry
from strategies.raec_v6.strategies.crisis_alpha import CrisisAlpha
from strategies.raec_v6.strategies.cross_asset_trend import CrossAssetTrend
from strategies.raec_v6.strategies.crypto_trend import CryptoTrend
from strategies.raec_v6.strategies.equity_leveraged_momentum import (
    EquityLeveragedMomentum,
    _RISK_UNIVERSE as EQUITY_LEV_UNIVERSE,
)
from strategies.raec_v6.strategies.sector_relative_strength import SectorRelativeStrength
from strategies.raec_v6.strategies.thematic_conviction import ThematicConviction
from strategies.raec_v6.strategy_output import StrategyOutput


STRATEGY_ID = "RAEC_V6"
BOOK_ID = DRY_RUN_BOOK_ID
STATE_SCHEMA_VERSION = 1
DEFAULT_STARTING_CASH = 230_000.0
LEDGER_RECORD_TYPE = "RAEC_V6_RUN"

# Rebalance triggers (mirror the backtest harness).
REBALANCE_DRIFT_THRESHOLD_PCT = 5.0  # L1 drift above this → rebalance


@dataclass(frozen=True)
class CoordinatorResult:
    asof_date: date
    rebalanced: bool
    notice: str | None
    intent_count: int
    posted: bool
    failed_strategies: tuple[str, ...]


# ── State file I/O ────────────────────────────────────────────────────────


def _state_dir(repo_root: Path) -> Path:
    return repo_root / "state" / "strategies" / BOOK_ID


def _state_path(repo_root: Path) -> Path:
    return _state_dir(repo_root) / "coordinator.json"


def _empty_state() -> dict:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "started_at": None,
        "last_eval_date": None,
        "prior_strategy_shares": {},
        "strategy_returns": {},
        "dd_breaker_currently_active": False,
        "freeze_days_remaining": 0,
        "shadow_book": None,  # filled on first run
    }


def _load_state(path: Path) -> dict:
    if not path.exists():
        return _empty_state()
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(
            f"v6 coordinator state schema version "
            f"{payload.get('schema_version')} != {STATE_SCHEMA_VERSION}; "
            f"manual migration required"
        )
    return payload


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(path)


# ── Ledger I/O ────────────────────────────────────────────────────────────


def _ledger_path(repo_root: Path, asof_date: date) -> Path:
    return repo_root / "ledger" / "RAEC_V6" / f"{asof_date.isoformat()}.jsonl"


def _append_ledger(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ── Price universe ────────────────────────────────────────────────────────


def _universe_symbols() -> tuple[str, ...]:
    """Every symbol the v6 strategies (collectively) might touch + signal
    inputs + benchmark."""
    return tuple(sorted(
        set(REPRESENTATIVES.values())
        | set(EQUITY_LEV_UNIVERSE)
        | set(ac.get_symbols_in_class("sector"))
        | set(ac.get_symbols_in_class("theme"))
        | set(ac.get_symbols_in_class("bond_short"))
        | set(ac.get_symbols_in_class("bond_mid"))
        | set(ac.get_symbols_in_class("bond_long"))
        | set(ac.get_symbols_in_class("bond_inverse"))
        | set(ac.get_symbols_in_class("credit"))
        | set(ac.get_symbols_in_class("crypto"))
        | set(ac.get_symbols_in_class("crypto_inverse"))
        | set(ac.get_symbols_in_class("inverse_equity"))
        | set(ac.get_symbols_in_class("metal"))
        | {"SPY", "BIL", "^VIX"}
    ))


# ── Pure helpers ──────────────────────────────────────────────────────────


def _strategies() -> list:
    return [
        CrossAssetTrend(top_k=4),
        EquityLeveragedMomentum(top_k=5),
        SectorRelativeStrength(top_k=4),
        ThematicConviction(top_k=3),
        BondCarry(),
        CryptoTrend(),
        CrisisAlpha(),
    ]


def _close_at_or_before(provider: PriceProvider, sym: str, asof: date) -> float | None:
    series = provider.get_daily_close_series(sym)
    for d, c in reversed(series):
        if d <= asof:
            return c
    return None


def _daily_returns_window(
    provider: PriceProvider, sym: str, asof: date, n: int
) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    if len(closes) < 2:
        return []
    closes = closes[-(n + 1):]
    rs: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rs.append(closes[i] / closes[i - 1] - 1.0)
    return rs


def _spy_realized_vol_60d(provider: PriceProvider, asof: date) -> float:
    rs = _daily_returns_window(provider, "SPY", asof, 60)
    if len(rs) < 20:
        return 0.0
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


def _build_signal_state(provider: PriceProvider, asof: date) -> SignalState:
    trend = compute_cross_asset_trend(provider, asof)
    spy_vol = _spy_realized_vol_60d(provider, asof)
    vol_pct = compute_vol_percentile(provider, ["SPY"], asof)
    yc = compute_yield_curve_signal(provider, asof)
    cs = compute_credit_spread_signal(provider, asof)
    vix = compute_vix_implied(provider, asof) or 0.0
    spy_series = provider.get_daily_close_series("SPY")
    spy_closes = [c for d, c in spy_series if d <= asof]
    regime_label, regime_conf = classify_from_spy_closes(spy_closes)
    return SignalState(
        asof_date=asof,
        regime_label=regime_label,
        regime_confidence=regime_conf,
        cross_asset_trend=trend,
        vol_percentile_252d=vol_pct,
        spy_realized_vol_60d=spy_vol,
        vix_implied=vix,
        yield_curve_signal=yc,
        credit_spread_signal=cs,
    )


def _l1_drift_pct(current: Mapping[str, float], target: Mapping[str, float]) -> float:
    """Sum of |target - current| across all symbols, in pct units (×100)."""
    syms = set(current) | set(target)
    return sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in syms) * 100.0


def _generate_intents(
    *,
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    equity: float,
    close_prices: Mapping[str, float],
    min_trade_pct: float = 0.5,
) -> list[V6Intent]:
    intents: list[V6Intent] = []
    syms = set(current_weights) | set(target_weights)
    for sym in sorted(syms):
        cur = current_weights.get(sym, 0.0)
        tgt = target_weights.get(sym, 0.0)
        delta = tgt - cur
        if abs(delta) * 100 < min_trade_pct:
            continue
        side = "BUY" if delta > 0 else "SELL"
        dollar = delta * equity
        intents.append(V6Intent(
            symbol=sym,
            side=side,
            delta_pct=delta,
            target_pct=tgt,
            current_pct=cur,
            dollar_delta=dollar,
        ))
    return intents


# ── Main orchestrator ─────────────────────────────────────────────────────


def run_coordinator(
    *,
    asof_date: date,
    repo_root: Path,
    price_provider: PriceProvider | None = None,
    adapter: DryRunAdapter | None = None,
    post_enabled: bool = True,
) -> CoordinatorResult:
    """Run one daily cycle of the v6 dry-run coordinator.

    Returns a CoordinatorResult. Persistent side effects:
    - Updates state/strategies/RAEC_V6_DRY_RUN/coordinator.json
    - Appends to ledger/RAEC_V6/<date>.jsonl
    - Posts to Slack via DryRunAdapter (if post_enabled)
    """
    if price_provider is None:
        price_provider = get_default_price_provider(str(repo_root), period="5y")
    if adapter is None:
        adapter = DryRunAdapter()
    if adapter.book_id != DRY_RUN_BOOK_ID:
        raise V6DryRunSafetyError(
            f"v6 coordinator must be paired with DryRunAdapter on "
            f"{DRY_RUN_BOOK_ID}; got {adapter.book_id}"
        )

    # 1. Load state.
    state_path = _state_path(repo_root)
    state = _load_state(state_path)
    if state["shadow_book"] is None:
        book = ShadowBook(starting_cash=DEFAULT_STARTING_CASH)
        state["started_at"] = asof_date.isoformat()
    else:
        book = ShadowBook.from_dict(state["shadow_book"])

    # 2. Build SignalState.
    signal_state = _build_signal_state(price_provider, asof_date)

    # 3. Call strategies.
    strategies = _strategies()
    strategy_ids = [s.manifest.strategy_id for s in strategies]
    outputs: dict[str, StrategyOutput | None] = {}
    for strat in strategies:
        try:
            outputs[strat.manifest.strategy_id] = strat.compute(
                signal_state=signal_state,
                price_provider=price_provider,
                asof_date=asof_date,
            )
        except Exception:
            outputs[strat.manifest.strategy_id] = None

    # 4. Allocator.
    prior_shares = state.get("prior_strategy_shares") or {sid: 0.0 for sid in strategy_ids}
    strategy_returns = {
        sid: list(state.get("strategy_returns", {}).get(sid, []))
        for sid in strategy_ids
    }
    has_history = {sid: len(strategy_returns[sid]) >= 20 for sid in strategy_ids}
    recent_sharpes: dict[str, float] = {}
    for sid in strategy_ids:
        rets = strategy_returns[sid][-60:]
        if len(rets) >= 20:
            m = sum(rets) / len(rets)
            v = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
            sd = math.sqrt(v) if v > 0 else 0.0
            if sd > 0:
                recent_sharpes[sid] = m / sd * math.sqrt(252)

    alloc = allocate(
        outputs=outputs,
        recent_sharpes=recent_sharpes,
        has_live_history=has_history,
        prior_shares=prior_shares,
        strategy_returns=strategy_returns,
    )

    # 5. Overlay.
    per_symbol_returns: dict[str, list[float]] = {}
    for sym in alloc.book_targets:
        per_symbol_returns[sym] = _daily_returns_window(price_provider, sym, asof_date, 60)
    overlay = apply_overlay(
        book_targets=alloc.book_targets,
        spy_realized_vol_60d=signal_state.spy_realized_vol_60d,
        vix_implied=signal_state.vix_implied,
        portfolio_daily_returns=book.daily_returns[-60:],
        per_symbol_daily_returns=per_symbol_returns,
        equity_curve=book.equity_curve,
        dd_breaker_currently_active=state["dd_breaker_currently_active"],
    )

    # 6. Determine rebalance trigger.
    current_weights = (
        {s: v / book.equity for s, v in book.positions.items()}
        if book.equity > 0
        else {}
    )
    freeze_remaining = state.get("freeze_days_remaining", 0)
    drift = _l1_drift_pct(current_weights, overlay.final_weights)

    notice: str | None = None
    if freeze_remaining > 0:
        target_weights = current_weights
        rebalance = False
        notice = f"REBALANCING FROZEN ({freeze_remaining} days remaining from shock)"
        freeze_remaining = max(0, freeze_remaining - 1)
    elif drift < REBALANCE_DRIFT_THRESHOLD_PCT:
        target_weights = current_weights
        rebalance = False
        notice = f"within tolerance (L1 drift {drift:.1f}% < {REBALANCE_DRIFT_THRESHOLD_PCT:.1f}%)"
    else:
        target_weights = dict(overlay.final_weights)
        rebalance = True

    # 7. Close prices (need for shadow book step + intent dollars).
    close_prices: dict[str, float] = {}
    for sym in set(target_weights) | set(book.positions):
        px = _close_at_or_before(price_provider, sym, asof_date)
        if px is not None:
            close_prices[sym] = px

    # 8. Compute intents from current → target.
    intents = _generate_intents(
        current_weights=current_weights,
        target_weights=target_weights,
        equity=book.equity if book.equity > 0 else book.starting_cash,
        close_prices=close_prices,
    )

    # 9. Step the shadow book (advances equity even on no-rebalance days
    # because MTM still happens at the new close).
    step_result = book.step(
        asof=asof_date,
        target_weights=target_weights,
        close_prices=close_prices,
    )

    # 10. Update strategy_returns from prior_contributions × today's per-symbol
    # returns. (Today's return for strategy s ≈ Σ_sym yesterday_contrib[s][sym]
    # × today's symbol return.)
    today_per_symbol_return: dict[str, float] = {}
    for sym in close_prices:
        last_two = _daily_returns_window(price_provider, sym, asof_date, 1)
        if last_two:
            today_per_symbol_return[sym] = last_two[-1]
    # Get the prior contributions saved in state (or {} if first run).
    prior_contribs: dict[str, dict[str, float]] = state.get("prior_contributions", {})
    for sid in strategy_ids:
        r = 0.0
        for sym, w in prior_contribs.get(sid, {}).items():
            r += w * today_per_symbol_return.get(sym, 0.0)
        strategy_returns[sid].append(r)
        # Trim history to ~252 days (don't grow unboundedly).
        if len(strategy_returns[sid]) > 252:
            strategy_returns[sid] = strategy_returns[sid][-252:]

    if overlay.shock_day_detected:
        freeze_remaining = overlay.freeze_rebalancing_until_idx

    # 11. Persist state.
    state["last_eval_date"] = asof_date.isoformat()
    state["prior_strategy_shares"] = dict(alloc.strategy_shares)
    state["strategy_returns"] = strategy_returns
    state["dd_breaker_currently_active"] = overlay.dd_breaker_active
    state["freeze_days_remaining"] = freeze_remaining
    state["prior_contributions"] = {
        sid: dict(alloc.contributions.get(sid, {})) for sid in strategy_ids
    }
    state["shadow_book"] = book.to_dict()
    _save_state(state_path, state)

    # 12. Build ledger record.
    record = {
        "record_type": LEDGER_RECORD_TYPE,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ny_date": asof_date.isoformat(),
        "strategy_id": STRATEGY_ID,
        "book_id": BOOK_ID,
        "shadow_book": {
            "equity": step_result.equity,
            "cash": step_result.cash,
            "positions": dict(step_result.positions),
        },
        "signal_state": {
            "regime_label": signal_state.regime_label,
            "regime_confidence": signal_state.regime_confidence,
            "spy_realized_vol_60d": signal_state.spy_realized_vol_60d,
            "vix_implied": signal_state.vix_implied,
            "yield_curve_signal": signal_state.yield_curve_signal,
            "credit_spread_signal": signal_state.credit_spread_signal,
        },
        "strategy_outputs": {
            sid: ({
                "weights": dict(out.weights),
                "conviction": out.conviction,
                "regime_gate": out.regime_gate,
                "realized_vol_60d": out.realized_vol_60d,
                "diagnostics": dict(out.diagnostics),
            } if out else None)
            for sid, out in outputs.items()
        },
        "allocator": {
            "strategy_shares": dict(alloc.strategy_shares),
            "failed_strategies": list(alloc.failed_strategies),
        },
        "overlay": {
            "exposure_scale": overlay.exposure_scale,
            "target_vol": overlay.target_vol,
            "forecast_vol": overlay.forecast_vol,
            "dd_breaker_active": overlay.dd_breaker_active,
            "shock_day_detected": overlay.shock_day_detected,
            "freeze_rebalancing_until_idx": overlay.freeze_rebalancing_until_idx,
        },
        "book_targets_pre_overlay": dict(alloc.book_targets),
        "final_weights": dict(overlay.final_weights),
        "rebalance": rebalance,
        "notice": notice,
        "drift_l1_pct": drift,
        "intents": [asdict(i) for i in intents],
    }
    _append_ledger(_ledger_path(repo_root, asof_date), record)

    # 13. Post Slack.
    posted = False
    if post_enabled:
        try:
            adapter.post_advisory(
                asof=asof_date,
                equity=step_result.equity,
                cash=step_result.cash,
                rebalance=rebalance,
                intents=intents,
                regime_label=signal_state.regime_label,
                target_vol=overlay.target_vol,
                forecast_vol=overlay.forecast_vol,
                exposure_scale=overlay.exposure_scale,
                strategy_shares=alloc.strategy_shares,
                notice=notice,
            )
            posted = True
        except Exception:
            posted = False

    return CoordinatorResult(
        asof_date=asof_date,
        rebalanced=rebalance,
        notice=notice,
        intent_count=len(intents),
        posted=posted,
        failed_strategies=alloc.failed_strategies,
    )


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAEC v6 dry-run coordinator (one day)."
    )
    parser.add_argument("--asof-date", required=True, type=date.fromisoformat,
                        help="NY date to evaluate, e.g. 2026-06-09")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2],
                        help="Repo root (defaults to current repo)")
    parser.add_argument("--no-post", action="store_true",
                        help="Skip the Slack post (useful for backfilling state)")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        result = run_coordinator(
            asof_date=args.asof_date,
            repo_root=args.repo_root,
            post_enabled=not args.no_post,
        )
        print(json.dumps({
            "asof_date": result.asof_date.isoformat(),
            "rebalanced": result.rebalanced,
            "intent_count": result.intent_count,
            "posted": result.posted,
            "failed_strategies": list(result.failed_strategies),
            "notice": result.notice,
        }, indent=2))
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
