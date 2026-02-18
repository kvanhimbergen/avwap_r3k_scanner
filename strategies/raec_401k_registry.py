"""Auto-discovery registry for RAEC 401(k) strategy instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategies.raec_401k_base import BaseRAECStrategy

_REGISTRY: dict[str, BaseRAECStrategy] = {}


def register(strategy: BaseRAECStrategy) -> BaseRAECStrategy:
    _REGISTRY[strategy.STRATEGY_ID] = strategy
    return strategy


def get(strategy_id: str) -> BaseRAECStrategy:
    return _REGISTRY[strategy_id]


def all_strategies() -> dict[str, BaseRAECStrategy]:
    return dict(_REGISTRY)


def registered_ids() -> list[str]:
    return sorted(_REGISTRY)
