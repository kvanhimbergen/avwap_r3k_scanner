from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


DEFAULT_RULES_PATH = Path("knowledge/rules/universe_rules.yaml")


@dataclass(frozen=True)
class UniverseRules:
    raw: Dict[str, Any]

    @property
    def liquidity(self) -> Dict[str, Any]:
        return (self.raw.get("universe") or {}).get("liquidity") or {}

    @property
    def structure(self) -> Dict[str, Any]:
        return (self.raw.get("universe") or {}).get("structure") or {}


def load_universe_rules(path: Optional[str] = None) -> UniverseRules:
    p = Path(path) if path else DEFAULT_RULES_PATH
    if not p.exists():
        # Fail-open: no rules file => no additional filtering.
        return UniverseRules(raw={})

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return UniverseRules(raw={})
    return UniverseRules(raw=data)
