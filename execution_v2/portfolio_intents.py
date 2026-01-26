"""
Execution V2 – Portfolio Trade Intent Contracts (Phase S1).

Referenced in docs/ROADMAP.md (Phase S1: Trade Intent Contract & Control-Plane Arbitration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from execution_v2.config_types import EntryIntent
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


Side = Literal["buy", "sell"]

DEFAULT_INTENT_TTL_SEC = 6 * 60 * 60


@dataclass(frozen=True)
class TradeIntent:
    strategy_id: str
    symbol: str
    side: Side
    qty: int
    intent_ts_utc: float
    valid_until_ts_utc: float
    reason_codes: list[str]
    risk_tags: list[str] = field(default_factory=list)
    sleeve_id: str = "default"

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": int(self.qty),
            "intent_ts_utc": float(self.intent_ts_utc),
            "valid_until_ts_utc": float(self.valid_until_ts_utc),
            "reason_codes": list(self.reason_codes),
            "risk_tags": list(self.risk_tags),
            "sleeve_id": self.sleeve_id,
        }


@dataclass(frozen=True)
class RejectedIntent:
    intent: TradeIntent
    rejection_reason: str
    reason_codes: list[str]

    def to_dict(self) -> dict[str, object]:
        payload = self.intent.to_dict()
        payload["rejection_reason"] = self.rejection_reason
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def trade_intent_from_entry_intent(intent: EntryIntent) -> TradeIntent:
    """
    Translate an EntryIntent into a portfolio-facing TradeIntent (Phase S1, docs/ROADMAP.md).
    """
    strategy_id = intent.strategy_id or DEFAULT_STRATEGY_ID
    return TradeIntent(
        strategy_id=strategy_id,
        symbol=intent.symbol,
        side="buy",
        qty=int(intent.size_shares),
        intent_ts_utc=float(intent.boh_confirmed_at),
        valid_until_ts_utc=float(intent.scheduled_entry_at) + DEFAULT_INTENT_TTL_SEC,
        reason_codes=["entry_intent"],
        risk_tags=[],
        sleeve_id="default",
    )
