"""
Execution V2 – Strategy Registry

Phase S0 structure per docs/ROADMAP.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class StrategyID(str, Enum):
    S1_AVWAP_CORE = "S1_AVWAP_CORE"


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: StrategyID
    asset_universe: str
    holding_horizon: str
    execution_style: str
    risk_profile: str


_STRATEGY_REGISTRY: dict[StrategyID, StrategyMetadata] = {
    StrategyID.S1_AVWAP_CORE: StrategyMetadata(
        strategy_id=StrategyID.S1_AVWAP_CORE,
        asset_universe="US equities (AVWAP universe)",
        holding_horizon="swing",
        execution_style="systematic",
        risk_profile="directional",
    )
}

STRATEGY_REGISTRY: Mapping[StrategyID, StrategyMetadata] = MappingProxyType(_STRATEGY_REGISTRY)
DEFAULT_STRATEGY_ID = StrategyID.S1_AVWAP_CORE.value


def resolve_strategy_metadata(strategy_id: str) -> StrategyMetadata:
    return STRATEGY_REGISTRY[StrategyID(strategy_id)]


def list_strategy_ids() -> list[str]:
    return [strategy_id.value for strategy_id in StrategyID]
