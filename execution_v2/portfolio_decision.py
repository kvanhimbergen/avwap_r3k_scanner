"""
Execution V2 – Portfolio Decision Contracts (Phase S1).

Referenced in docs/ROADMAP.md (Phase S1: Trade Intent Contract & Control-Plane Arbitration).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from execution_v2.orders import OrderSpec
from execution_v2.portfolio_intents import RejectedIntent
from utils.atomic_write import atomic_write_text


@dataclass(frozen=True)
class PortfolioDecision:
    run_id: str
    date_ny: str
    approved_orders: list[OrderSpec]
    rejected_intents: list[RejectedIntent]
    constraints_snapshot: dict[str, Any]
    decision_hash: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "date_ny": self.date_ny,
            "approved_orders": _sort_orders(self.approved_orders),
            "rejected_intents": _sort_rejections(self.rejected_intents),
            "constraints_snapshot": _normalize_constraints(self.constraints_snapshot),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload["decision_hash"] = self.decision_hash
        return payload


def build_decision_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dumps_portfolio_decision(decision: PortfolioDecision) -> str:
    payload = decision.to_dict()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def write_portfolio_decision(decision: PortfolioDecision, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps_portfolio_decision(decision)
    atomic_write_text(path, payload)


def _sort_orders(orders: list[OrderSpec]) -> list[dict[str, Any]]:
    def _key(order: OrderSpec) -> tuple:
        return (
            order.symbol,
            order.strategy_id,
            order.side,
            int(order.qty),
            order.idempotency_key,
        )

    return [
        {
            "strategy_id": order.strategy_id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": int(order.qty),
            "limit_price": float(order.limit_price),
            "tif": order.tif,
            "idempotency_key": order.idempotency_key,
        }
        for order in sorted(orders, key=_key)
    ]


def _sort_rejections(rejections: list[RejectedIntent]) -> list[dict[str, Any]]:
    def _key(rejected: RejectedIntent) -> tuple:
        intent = rejected.intent
        return (
            intent.symbol,
            intent.strategy_id,
            intent.side,
            int(intent.qty),
            rejected.rejection_reason,
        )

    return [rejection.to_dict() for rejection in sorted(rejections, key=_key)]


def _normalize_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in constraints.items():
        if isinstance(value, list):
            normalized[key] = sorted(value)
        elif isinstance(value, dict):
            normalized[key] = dict(sorted(value.items()))
        else:
            normalized[key] = value
    return dict(sorted(normalized.items()))
