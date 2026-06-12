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
from strategies.raec_v6.live_trade_adapter import (
    LIVE_BOOK_ID,
    LiveIntent,
    LiveTradeAdapter,
    make_intent_id,
)
from strategies.raec_v6.overlay import OverlayResult, apply_overlay
from strategies.raec_v6.schwab_positions import (
    LiveBookSnapshot,
    SchwabPositionsStaleError,
    read_latest_snapshot,
)
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
STATE_SCHEMA_VERSION = 1
DEFAULT_STARTING_CASH = 230_000.0
LEDGER_RECORD_TYPE_DRY = "RAEC_V6_RUN"
LEDGER_RECORD_TYPE_LIVE = "RAEC_V6_LIVE_RUN"

# Rebalance triggers (mirror the backtest harness).
REBALANCE_DRIFT_THRESHOLD_PCT = 5.0  # L1 drift above this → rebalance
# Minimum per-symbol intent size as % of book. Intents smaller than this
# are filtered as noise — avoids many small trim trades each day. Raised
# from 0.5% → 1.5% on 2026-06-12 after the user flagged whipsaw (ARKG
# bought day 2, sold day 3) eating real bid-ask cost without alpha.
# On a ~$250K book, 1.5% ≈ $3.7K minimum per intent.
MIN_TRADE_PCT = 1.5

# Modes
MODE_DRY_RUN = "dry-run"
MODE_LIVE = "live"

# In dry-run mode, the v6 coordinator's "book" is a synthetic shadow book.
# In live mode, current positions come from Schwab readonly snapshots and
# the shadow book is only used for equity-curve continuity (DD breaker).
BOOK_ID_DRY_RUN = DRY_RUN_BOOK_ID  # "RAEC_V6_DRY_RUN"
BOOK_ID_LIVE = LIVE_BOOK_ID  # "SCHWAB_401K_MANUAL"

# Backwards-compat alias (the dry-run-only code path still imports this).
BOOK_ID = BOOK_ID_DRY_RUN


@dataclass(frozen=True)
class CoordinatorResult:
    asof_date: date
    rebalanced: bool
    notice: str | None
    intent_count: int
    posted: bool
    failed_strategies: tuple[str, ...]


# ── State file I/O ────────────────────────────────────────────────────────


def _state_dir(repo_root: Path, book_id: str = BOOK_ID_DRY_RUN) -> Path:
    return repo_root / "state" / "strategies" / book_id


def _state_path(repo_root: Path, book_id: str = BOOK_ID_DRY_RUN) -> Path:
    return _state_dir(repo_root, book_id) / "coordinator.json"


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


def _ledger_path(repo_root: Path, asof_date: date, mode: str = MODE_DRY_RUN) -> Path:
    subdir = "RAEC_V6" if mode == MODE_DRY_RUN else "RAEC_V6_LIVE"
    return repo_root / "ledger" / subdir / f"{asof_date.isoformat()}.jsonl"


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
    min_trade_pct: float = MIN_TRADE_PCT,
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


def _convert_to_live_intents(
    *,
    asof: date,
    v6_intents: list[V6Intent],
    close_prices: Mapping[str, float],
) -> list[LiveIntent]:
    """Convert dry-run V6Intent into LiveIntent (adds intent_id + shares)."""
    out: list[LiveIntent] = []
    for ix in v6_intents:
        px = close_prices.get(ix.symbol)
        shares = int(round(ix.dollar_delta / px)) if px and px > 0 else None
        out.append(LiveIntent(
            intent_id=make_intent_id(
                asof=asof,
                symbol=ix.symbol,
                side=ix.side,
                target_pct=ix.target_pct,
                current_pct=ix.current_pct,
            ),
            symbol=ix.symbol,
            side=ix.side,
            delta_pct=ix.delta_pct,
            target_pct=ix.target_pct,
            current_pct=ix.current_pct,
            dollar_delta=ix.dollar_delta,
            shares_delta=shares,
        ))
    return out


# ── Main orchestrator ─────────────────────────────────────────────────────


def run_coordinator(
    *,
    asof_date: date,
    repo_root: Path,
    mode: str = MODE_DRY_RUN,
    price_provider: PriceProvider | None = None,
    adapter: DryRunAdapter | LiveTradeAdapter | None = None,
    post_enabled: bool = True,
    live_snapshot: LiveBookSnapshot | None = None,
) -> CoordinatorResult:
    """Run one daily cycle of the v6 coordinator.

    Args:
        mode: "dry-run" (default) or "live".
        live_snapshot: optional pre-loaded Schwab snapshot for live mode.
                      If None and mode=live, reads from ledger automatically.

    Persistent side effects (dry-run mode):
    - Updates state/strategies/RAEC_V6_DRY_RUN/coordinator.json
    - Appends to ledger/RAEC_V6/<date>.jsonl
    - Posts [V6 DRY] advisory via DryRunAdapter

    Persistent side effects (live mode):
    - Reads positions from latest Schwab readonly snapshot
    - Updates state/strategies/SCHWAB_401K_MANUAL/v6_coordinator.json
      (separate from the legacy V3-V5 state files at the same book ID)
    - Appends to ledger/RAEC_V6_LIVE/<date>.jsonl
    - Posts executable ticket via LiveTradeAdapter
    """
    if mode not in (MODE_DRY_RUN, MODE_LIVE):
        raise ValueError(f"mode must be {MODE_DRY_RUN!r} or {MODE_LIVE!r}, got {mode!r}")

    if price_provider is None:
        price_provider = get_default_price_provider(str(repo_root), period="5y")

    # Adapter selection + safety check per mode.
    if mode == MODE_DRY_RUN:
        if adapter is None:
            adapter = DryRunAdapter()
        if not isinstance(adapter, DryRunAdapter):
            raise V6DryRunSafetyError(
                f"dry-run mode requires DryRunAdapter; got {type(adapter).__name__}"
            )
        if adapter.book_id != DRY_RUN_BOOK_ID:
            raise V6DryRunSafetyError(
                f"v6 coordinator must be paired with DryRunAdapter on "
                f"{DRY_RUN_BOOK_ID}; got {adapter.book_id}"
            )
        book_id = BOOK_ID_DRY_RUN
    else:
        if adapter is None:
            adapter = LiveTradeAdapter()
        if not isinstance(adapter, LiveTradeAdapter):
            raise V6DryRunSafetyError(
                f"live mode requires LiveTradeAdapter; got {type(adapter).__name__}"
            )
        if adapter.book_id != LIVE_BOOK_ID:
            raise V6DryRunSafetyError(
                f"live mode adapter must operate on {LIVE_BOOK_ID}; got {adapter.book_id}"
            )
        book_id = BOOK_ID_LIVE
        # In live mode, fetch the Schwab snapshot if not pre-provided.
        if live_snapshot is None:
            live_snapshot = read_latest_snapshot(repo_root=repo_root, asof=asof_date)

    # 1. Load state. In live mode we keep state under a v6-suffixed file
    # so V3-V5's state at the same book_id is untouched.
    if mode == MODE_DRY_RUN:
        state_path = _state_path(repo_root, BOOK_ID_DRY_RUN)
    else:
        state_path = _state_dir(repo_root, BOOK_ID_LIVE) / "v6_coordinator.json"
    state = _load_state(state_path)
    if state["shadow_book"] is None:
        # In live mode the shadow book equity = cash + sum(positions). Set
        # starting_cash = the Schwab cash component ONLY; positions get
        # seeded separately below (step 9). If we seeded starting_cash to
        # total_equity here AND positions, the book would double-count
        # on the first step (real cash + positions = total + positions =
        # 2× real equity).
        starting = live_snapshot.cash if mode == MODE_LIVE else DEFAULT_STARTING_CASH
        book = ShadowBook(starting_cash=starting)
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
    # In live mode, "current_weights" comes from real Schwab positions, not
    # the shadow book. This ensures intents reflect what the user actually
    # holds. The shadow book equity is still maintained for DD breaker /
    # equity-curve continuity but isn't the source of truth for trade diff.
    if mode == MODE_LIVE:
        equity_for_intent = live_snapshot.total_equity
        current_weights: dict[str, float] = dict(live_snapshot.positions_pct)
    else:
        equity_for_intent = book.equity if book.equity > 0 else book.starting_cash
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
        equity=equity_for_intent,
        close_prices=close_prices,
    )

    # 9. Step the shadow book.
    # In LIVE mode, the shadow book is a tracker — Schwab is the source
    # of truth. Reset BOTH cash and positions from the live snapshot
    # before stepping. Resetting positions alone (the old behavior) left
    # stale cash from yesterday's shadow accounting, so shadow equity
    # diverged from real equity over time, falsely tripping the DD
    # breaker.
    if mode == MODE_LIVE:
        book.positions = dict(live_snapshot.positions_dollars)
        # Sync cash to the live snapshot. Overwrite the last cash_curve
        # entry if present; otherwise set starting_cash so book.cash
        # returns the synced value.
        if book.cash_curve:
            book.cash_curve[-1] = live_snapshot.cash
        else:
            book.starting_cash = live_snapshot.cash
        # Seed _last_close so the step's MTM math doesn't double-mark
        # (today's close == today's close → no change).
        if not hasattr(book, "_last_close"):
            book._last_close = {}
        for sym, px in close_prices.items():
            book._last_close[sym] = px
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
        "record_type": LEDGER_RECORD_TYPE_LIVE if mode == MODE_LIVE else LEDGER_RECORD_TYPE_DRY,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ny_date": asof_date.isoformat(),
        "mode": mode,
        "strategy_id": STRATEGY_ID,
        "book_id": book_id,
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
    _append_ledger(_ledger_path(repo_root, asof_date, mode=mode), record)

    # 13. Post Slack.
    posted = False
    if post_enabled:
        try:
            if mode == MODE_LIVE:
                live_intents = _convert_to_live_intents(
                    asof=asof_date,
                    v6_intents=intents,
                    close_prices=close_prices,
                )
                # Augment ledger with the intent_ids for traceability.
                record["live_intents"] = [
                    {
                        "intent_id": li.intent_id,
                        "symbol": li.symbol,
                        "side": li.side,
                        "shares_delta": li.shares_delta,
                    }
                    for li in live_intents
                ]
                # Re-write the ledger line with the augmentation (last line).
                _append_ledger(_ledger_path(repo_root, asof_date, mode=mode),
                               {"record_type": "RAEC_V6_LIVE_INTENT_IDS",
                                "ny_date": asof_date.isoformat(),
                                "intent_ids": [li.intent_id for li in live_intents]})
                adapter.post_ticket(
                    asof=asof_date,
                    equity=live_snapshot.total_equity,
                    cash_pct=live_snapshot.cash_pct,
                    rebalance=rebalance,
                    regime_label=signal_state.regime_label,
                    target_vol=overlay.target_vol,
                    forecast_vol=overlay.forecast_vol,
                    exposure_scale=overlay.exposure_scale,
                    strategy_shares=alloc.strategy_shares,
                    intents=live_intents,
                    notice=notice,
                )
            else:
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
        description="RAEC v6 coordinator (one day). Default mode is dry-run."
    )
    parser.add_argument("--asof-date", required=True, type=date.fromisoformat,
                        help="NY date to evaluate, e.g. 2026-06-09")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2],
                        help="Repo root (defaults to current repo)")
    parser.add_argument("--mode", choices=[MODE_DRY_RUN, MODE_LIVE],
                        default=MODE_DRY_RUN,
                        help="dry-run (default) or live. Live reads real Schwab "
                             "positions and posts executable tickets.")
    parser.add_argument("--no-post", action="store_true",
                        help="Skip the Slack post (useful for backfilling state)")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        result = run_coordinator(
            asof_date=args.asof_date,
            repo_root=args.repo_root,
            mode=args.mode,
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
