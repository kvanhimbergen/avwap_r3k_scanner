from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from analytics.schwab_readonly_schemas import (
    SchwabBalanceSnapshot,
    SchwabOrdersSnapshot,
    SchwabPositionsSnapshot,
    build_snapshot_id,
    serialize_balance_snapshot,
    serialize_orders_snapshot,
    serialize_positions_snapshot,
    stable_json_dumps,
)

RECORD_TYPE_ACCOUNT = "SCHWAB_READONLY_ACCOUNT_SNAPSHOT"
RECORD_TYPE_POSITIONS = "SCHWAB_READONLY_POSITIONS_SNAPSHOT"
RECORD_TYPE_ORDERS = "SCHWAB_READONLY_ORDERS_SNAPSHOT"
RECORD_TYPE_RECONCILIATION = "SCHWAB_READONLY_RECONCILIATION"


@dataclass(frozen=True)
class SnapshotWriteResult:
    ledger_path: str
    records_written: int
    skipped: int


def _parse_as_of(as_of_utc: str) -> datetime:
    raw = as_of_utc.strip()
    if raw.endswith("Z"):
        raw = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError("as_of_utc missing timezone")
    return dt


def ny_date_from_as_of(as_of_utc: str) -> str:
    dt = _parse_as_of(as_of_utc)
    from analytics.util import date_ny

    return date_ny(dt)


def ledger_path(repo_root: Path, book_id: str, ny_date: str) -> Path:
    return repo_root / "ledger" / book_id / f"{ny_date}.jsonl"


def _load_existing_snapshot_ids(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    existing: set[tuple[str, str]] = set()
    with path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            record_type = data.get("record_type")
            snapshot_id = data.get("snapshot_id") or data.get("reconciliation_id")
            if record_type and snapshot_id:
                existing.add((str(record_type), str(snapshot_id)))
    return existing


def _append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(stable_json_dumps(record) + "\n")


def _build_snapshot_record(snapshot: dict, *, record_type: str, ny_date: str) -> dict:
    snapshot_id = build_snapshot_id(snapshot)
    return {
        "record_type": record_type,
        "snapshot_id": snapshot_id,
        "ny_date": ny_date,
        **snapshot,
        "provenance": {
            "module": "analytics.schwab_readonly_storage",
        },
    }


def write_snapshot_records(
    *,
    repo_root: Path,
    account_snapshot: SchwabBalanceSnapshot,
    positions_snapshot: SchwabPositionsSnapshot,
    orders_snapshot: SchwabOrdersSnapshot,
) -> SnapshotWriteResult:
    if account_snapshot.book_id != positions_snapshot.book_id or account_snapshot.book_id != orders_snapshot.book_id:
        raise ValueError("snapshot book_id mismatch")
    if account_snapshot.as_of_utc != positions_snapshot.as_of_utc or account_snapshot.as_of_utc != orders_snapshot.as_of_utc:
        raise ValueError("snapshot as_of_utc mismatch")
    ny_date = ny_date_from_as_of(account_snapshot.as_of_utc)
    path = ledger_path(repo_root, account_snapshot.book_id, ny_date)
    existing = _load_existing_snapshot_ids(path)

    records: list[tuple[str, dict]] = []
    account_payload = serialize_balance_snapshot(account_snapshot)
    positions_payload = serialize_positions_snapshot(positions_snapshot)
    orders_payload = serialize_orders_snapshot(orders_snapshot)
    records.append((RECORD_TYPE_ACCOUNT, _build_snapshot_record(account_payload, record_type=RECORD_TYPE_ACCOUNT, ny_date=ny_date)))
    records.append((RECORD_TYPE_POSITIONS, _build_snapshot_record(positions_payload, record_type=RECORD_TYPE_POSITIONS, ny_date=ny_date)))
    records.append((RECORD_TYPE_ORDERS, _build_snapshot_record(orders_payload, record_type=RECORD_TYPE_ORDERS, ny_date=ny_date)))

    written = 0
    skipped = 0
    for record_type, record in records:
        snapshot_id = record.get("snapshot_id")
        key = (record_type, str(snapshot_id))
        if key in existing:
            skipped += 1
            continue
        _append_record(path, record)
        existing.add(key)
        written += 1

    return SnapshotWriteResult(ledger_path=str(path), records_written=written, skipped=skipped)


def load_snapshot_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("record_type") in {
                RECORD_TYPE_ACCOUNT,
                RECORD_TYPE_POSITIONS,
                RECORD_TYPE_ORDERS,
            }:
                records.append(data)
    return records
