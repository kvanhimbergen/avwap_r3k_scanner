from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analytics.regime_e1_schemas import (
    RECORD_TYPE_SIGNAL,
    RECORD_TYPE_SKIPPED,
    SCHEMA_VERSION,
    build_regime_id,
    stable_json_dumps,
)


@dataclass(frozen=True)
class RegimeWriteResult:
    ledger_path: str
    records_written: int
    skipped: int
    regime_id: str


def ledger_path(repo_root: Path, ny_date: str) -> Path:
    return repo_root / "ledger" / "REGIME_E1" / f"{ny_date}.jsonl"


def _load_existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    existing: set[str] = set()
    with path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            record_type = data.get("record_type")
            if record_type not in {RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED}:
                continue
            regime_id = data.get("regime_id")
            if regime_id:
                existing.add(str(regime_id))
    return existing


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(stable_json_dumps(record) + "\n")


def build_record(*, record_type: str, ny_date: str, as_of_utc: str, payload: dict[str, Any]) -> dict[str, Any]:
    if record_type not in {RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED}:
        raise ValueError("unsupported record_type")
    base_payload = {
        "record_type": record_type,
        "schema_version": SCHEMA_VERSION,
        "ny_date": ny_date,
        "as_of_utc": as_of_utc,
        **payload,
    }
    regime_id = build_regime_id(base_payload)
    return {
        **base_payload,
        "regime_id": regime_id,
    }


def write_record(*, repo_root: Path, ny_date: str, record: dict[str, Any]) -> RegimeWriteResult:
    path = ledger_path(repo_root, ny_date)
    existing = _load_existing_ids(path)
    regime_id = str(record.get("regime_id"))
    if regime_id in existing:
        return RegimeWriteResult(
            ledger_path=str(path),
            records_written=0,
            skipped=1,
            regime_id=regime_id,
        )
    _append_record(path, record)
    return RegimeWriteResult(
        ledger_path=str(path),
        records_written=1,
        skipped=0,
        regime_id=regime_id,
    )
