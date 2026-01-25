"""
Execution V2 – Portfolio Decision Contract Helpers
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from execution_v2.clocks import ET
from utils.atomic_write import atomic_write_text


LEDGER_DIR = Path("ledger") / "PORTFOLIO_DECISIONS"


def resolve_portfolio_decisions_path(now_ny: datetime) -> Path:
    """Resolve the NY-date decision ledger path for the provided NY timestamp."""
    if now_ny.tzinfo is None:
        raise ValueError("now_ny must be timezone-aware")
    date_ny = now_ny.astimezone(ET).date().isoformat()
    return LEDGER_DIR / f"{date_ny}.jsonl"


def build_decision_id(
    *,
    ny_date: str,
    execution_mode: str,
    candidates_path: str,
    candidates_mtime_utc: str | None,
    pid: int,
    ts_utc: str,
) -> str:
    payload = "|".join(
        [
            ny_date,
            execution_mode,
            candidates_path,
            candidates_mtime_utc or "null",
            str(pid),
            ts_utc,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dumps_portfolio_decision(record: dict[str, Any]) -> str:
    normalized = _normalize_record(record)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def write_portfolio_decision(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps_portfolio_decision(record)
    lines: list[str] = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        if existing:
            lines.extend([line for line in existing.splitlines() if line])
    lines.append(payload)
    data = "\n".join(lines) + "\n"
    atomic_write_text(path, data)


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(record)

    intents = _ensure_list(normalized.get("intents", {}).get("intents"))
    normalized.setdefault("intents", {})["intents"] = _sort_items(
        intents, ("symbol", "side", "client_order_id")
    )

    actions = normalized.setdefault("actions", {})
    actions["submitted_orders"] = _sort_items(
        _ensure_list(actions.get("submitted_orders")),
        ("symbol", "side", "client_order_id"),
    )
    actions["skipped"] = _sort_items(
        _ensure_list(actions.get("skipped")),
        ("symbol", "side", "client_order_id"),
    )
    actions["errors"] = _sort_items(
        _ensure_list(actions.get("errors")),
        ("where", "message"),
    )

    gates = normalized.setdefault("gates", {})
    gates["blocks"] = _sort_items(
        _ensure_list(gates.get("blocks")),
        ("code", "message"),
    )

    constraints = normalized.get("inputs", {}).get("constraints_snapshot", {})
    allowlist = constraints.get("allowlist_symbols")
    if isinstance(allowlist, list):
        constraints["allowlist_symbols"] = sorted(allowlist)

    artifacts = normalized.setdefault("artifacts", {})
    artifacts["ledgers_written"] = sorted(_ensure_list(artifacts.get("ledgers_written")))

    return normalized


def _ensure_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, bytes)):
        return []
    return list(value) if isinstance(value, Iterable) else []


def _sort_items(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    def _key(item: dict[str, Any]) -> tuple[str, ...]:
        parts = []
        for key in keys:
            value = item.get(key)
            if value is None:
                parts.append("")
            else:
                parts.append(str(value))
        return tuple(parts)

    return sorted(items, key=_key)
