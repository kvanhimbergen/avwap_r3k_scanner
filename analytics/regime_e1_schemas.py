from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

RECORD_TYPE_SIGNAL = "REGIME_E1_SIGNAL"
RECORD_TYPE_SKIPPED = "REGIME_E1_SKIPPED"

REGIME_LABELS = {"RISK_ON", "NEUTRAL", "RISK_OFF", "STRESSED"}


@dataclass(frozen=True)
class RegimeRecord:
    record_type: str
    schema_version: int
    ny_date: str
    as_of_utc: str
    regime_id: str
    payload: dict[str, Any]


def stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_regime_id(payload: dict[str, Any]) -> str:
    packed = stable_json_dumps(payload)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()
