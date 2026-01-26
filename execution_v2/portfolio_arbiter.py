"""
Execution V2 – Portfolio Arbitration Layer (Phase S1).

Referenced in docs/ROADMAP.md (Phase S1: Trade Intent Contract & Control-Plane Arbitration).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import hashlib

from execution_v2.orders import OrderSpec
from execution_v2.portfolio_decision import PortfolioDecision, build_decision_hash
from execution_v2.portfolio_intents import RejectedIntent, TradeIntent
from execution_v2.shadow_strategies import parse_shadow_strategy_ids_from_env


@dataclass(frozen=True)
class PortfolioConstraints:
    max_positions: int | None = None
    max_positions_per_strategy: int | None = None
    max_symbol_concentration: int | None = 1
    open_positions_count: int | None = 0
    open_positions_by_strategy: dict[str, int] | None = None
    existing_symbols: list[str] | None = None

    def to_snapshot(self) -> dict[str, object]:
        return {
            "max_positions": self.max_positions,
            "max_positions_per_strategy": self.max_positions_per_strategy,
            "max_symbol_concentration": self.max_symbol_concentration,
            "open_positions_count": self.open_positions_count,
            "open_positions_by_strategy": self.open_positions_by_strategy or {},
            "existing_symbols": sorted(self.existing_symbols or []),
        }


def arbitrate_intents(
    intents: Iterable[TradeIntent],
    *,
    now_ts_utc: float,
    constraints: PortfolioConstraints,
    run_id: str,
    date_ny: str,
) -> PortfolioDecision:
    """
    Deterministically arbitrate portfolio trade intents per Phase S1 (docs/ROADMAP.md).
    """
    if not run_id:
        raise ValueError("run_id is required")
    if not date_ny:
        raise ValueError("date_ny is required")

    validated: list[TradeIntent] = []
    rejected: list[RejectedIntent] = []
    shadow_strategy_ids = parse_shadow_strategy_ids_from_env()

    for intent in intents:
        schema_errors = _validate_intent(intent)
        if schema_errors:
            rejected.append(
                RejectedIntent(
                    intent=intent,
                    rejection_reason="invalid_intent",
                    reason_codes=schema_errors,
                )
            )
            continue
        if intent.strategy_id in shadow_strategy_ids:
            rejected.append(
                RejectedIntent(
                    intent=intent,
                    rejection_reason="shadow_strategy",
                    reason_codes=["shadow_strategy"],
                )
            )
            continue
        if intent.valid_until_ts_utc < now_ts_utc:
            rejected.append(
                RejectedIntent(
                    intent=intent,
                    rejection_reason="stale_intent",
                    reason_codes=["stale_intent"],
                )
            )
            continue
        validated.append(intent)

    sorted_intents = sorted(validated, key=_intent_sort_key)
    winners: list[TradeIntent] = []
    seen_symbols: set[str] = set()
    for intent in sorted_intents:
        if intent.symbol in seen_symbols:
            rejected.append(
                RejectedIntent(
                    intent=intent,
                    rejection_reason="symbol_conflict",
                    reason_codes=["symbol_conflict"],
                )
            )
            continue
        seen_symbols.add(intent.symbol)
        winners.append(intent)

    filtered: list[TradeIntent] = []
    existing_symbols = set(constraints.existing_symbols or [])
    for intent in winners:
        if constraints.max_symbol_concentration is not None:
            if constraints.max_symbol_concentration <= 1 and intent.symbol in existing_symbols:
                rejected.append(
                    RejectedIntent(
                        intent=intent,
                        rejection_reason="symbol_concentration",
                        reason_codes=["symbol_concentration"],
                    )
                )
                continue
        filtered.append(intent)

    approved: list[TradeIntent] = []
    approved_by_strategy: dict[str, int] = {}
    open_positions = constraints.open_positions_count or 0
    open_by_strategy = dict(constraints.open_positions_by_strategy or {})

    for intent in filtered:
        if constraints.max_positions is not None:
            if open_positions + len(approved) >= constraints.max_positions:
                rejected.append(
                    RejectedIntent(
                        intent=intent,
                        rejection_reason="max_positions",
                        reason_codes=["max_positions"],
                    )
                )
                continue
        if constraints.max_positions_per_strategy is not None:
            base_count = open_by_strategy.get(intent.strategy_id, 0)
            next_count = base_count + approved_by_strategy.get(intent.strategy_id, 0)
            if next_count >= constraints.max_positions_per_strategy:
                rejected.append(
                    RejectedIntent(
                        intent=intent,
                        rejection_reason="max_positions_per_strategy",
                        reason_codes=["max_positions_per_strategy"],
                    )
                )
                continue
        approved.append(intent)
        approved_by_strategy[intent.strategy_id] = approved_by_strategy.get(intent.strategy_id, 0) + 1

    approved_orders = [
        _order_from_intent(intent, run_id=run_id)
        for intent in approved
    ]

    provisional = PortfolioDecision(
        run_id=run_id,
        date_ny=date_ny,
        approved_orders=approved_orders,
        rejected_intents=rejected,
        constraints_snapshot=constraints.to_snapshot(),
        decision_hash="",
    )
    decision_hash = build_decision_hash(provisional.to_payload())

    return PortfolioDecision(
        run_id=run_id,
        date_ny=date_ny,
        approved_orders=approved_orders,
        rejected_intents=rejected,
        constraints_snapshot=constraints.to_snapshot(),
        decision_hash=decision_hash,
    )


def _validate_intent(intent: TradeIntent) -> list[str]:
    errors: list[str] = []
    if not intent.strategy_id:
        errors.append("missing_strategy_id")
    if not intent.symbol:
        errors.append("missing_symbol")
    if intent.side not in ("buy", "sell"):
        errors.append("invalid_side")
    if int(intent.qty) <= 0:
        errors.append("invalid_qty")
    if intent.intent_ts_utc <= 0:
        errors.append("invalid_intent_ts")
    if intent.valid_until_ts_utc <= 0:
        errors.append("invalid_valid_until")
    if intent.valid_until_ts_utc < intent.intent_ts_utc:
        errors.append("valid_until_before_intent_ts")
    if not isinstance(intent.reason_codes, list):
        errors.append("invalid_reason_codes")
    return errors


def _intent_sort_key(intent: TradeIntent) -> tuple:
    side_priority = 0 if intent.side == "buy" else 1
    return (intent.symbol, side_priority, -int(intent.qty), intent.strategy_id)


def _order_from_intent(intent: TradeIntent, *, run_id: str) -> OrderSpec:
    key_payload = f"{run_id}|{intent.strategy_id}|{intent.symbol}|{intent.side}|{intent.qty}"
    idempotency_key = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()
    return OrderSpec(
        strategy_id=intent.strategy_id,
        symbol=intent.symbol,
        side=intent.side,
        qty=int(intent.qty),
        limit_price=0.0,
        tif="day",
        idempotency_key=idempotency_key,
    )
