"""
Shadow strategy helpers (Phase 2A: Shadow Decisions).
"""

from __future__ import annotations

import os
from typing import Iterable

from execution_v2.portfolio_intents import TradeIntent


DEFAULT_SHADOW_PREFIX = "shadow_"


def parse_shadow_strategy_ids_from_env() -> set[str]:
    raw = os.getenv("SHADOW_STRATEGY_IDS", "")
    if not raw:
        return set()
    return {item for item in (part.strip() for part in raw.split(",")) if item}


def shadow_strategy_prefix_from_env() -> str:
    value = os.getenv("SHADOW_STRATEGY_PREFIX", DEFAULT_SHADOW_PREFIX)
    prefix = value.strip()
    return prefix if prefix else DEFAULT_SHADOW_PREFIX


def clone_trade_intents_as_shadow(intents: Iterable[TradeIntent]) -> list[TradeIntent]:
    prefix = shadow_strategy_prefix_from_env()
    clones: list[TradeIntent] = []
    for intent in intents:
        risk_tags = list(intent.risk_tags)
        if "shadow" not in risk_tags:
            risk_tags.append("shadow")
        clones.append(
            TradeIntent(
                strategy_id=f"{prefix}{intent.strategy_id}",
                symbol=intent.symbol,
                side=intent.side,
                qty=intent.qty,
                intent_ts_utc=intent.intent_ts_utc,
                valid_until_ts_utc=intent.valid_until_ts_utc,
                reason_codes=list(intent.reason_codes) + ["shadow_clone"],
                risk_tags=risk_tags,
                sleeve_id=intent.sleeve_id,
            )
        )
    return clones
