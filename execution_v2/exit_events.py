from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from utils.atomic_write import atomic_write_text

NY_TZ = ZoneInfo("America/New_York")
SCHEMA_VERSION = 1
LEDGER_DIR = Path("ledger") / "EXIT_EVENTS"


@dataclass(frozen=True)
class ExitEventContext:
    symbol: str
    qty: Optional[float] = None
    entry_id: Optional[str] = None
    entry_price: Optional[float] = None
    entry_ts_utc: Optional[str] = None
    entry_ts_ny: Optional[str] = None
    entry_date_ny: Optional[str] = None
    position_id: Optional[str] = None
    trade_id: Optional[str] = None


def _format_float(value: float) -> str:
    return repr(float(value))


def _format_optional_float(value: Optional[float]) -> str:
    if value is None:
        return ""
    return _format_float(value)


def _hash_payload(parts: list[str]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_dt(value: Optional[object]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    raise TypeError(f"unsupported timestamp type: {type(value).__name__}")


def _iso_utc(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


def _iso_ny(ts: datetime) -> str:
    return ts.astimezone(NY_TZ).isoformat()


def _date_ny(ts: datetime) -> str:
    return ts.astimezone(NY_TZ).date().isoformat()


def build_position_id(
    *,
    symbol: str,
    entry_ts_utc: str,
    qty: float,
    entry_price: Optional[float],
    strategy_id: str = "default",
    sleeve_id: str = "default",
    entry_id: Optional[str] = None,
) -> str:
    parts = [
        symbol,
        entry_ts_utc,
        _format_float(qty),
        _format_optional_float(entry_price),
        strategy_id,
        sleeve_id,
    ]
    if entry_id:
        parts.append(entry_id)
    return _hash_payload(parts)


def build_trade_id(
    *,
    position_id: str,
    exit_ts_utc: str,
    qty: float,
    exit_price: Optional[float],
) -> str:
    return _hash_payload(
        [
            position_id,
            exit_ts_utc,
            _format_float(qty),
            _format_optional_float(exit_price),
        ]
    )


def build_exit_event(
    *,
    event_type: str,
    symbol: str,
    ts: Optional[object] = None,
    source: str = "unknown",
    qty: Optional[float] = None,
    price: Optional[float] = None,
    stop_price: Optional[float] = None,
    stop_basis: Optional[str] = None,
    stop_action: Optional[str] = None,
    reason: Optional[str] = None,
    entry_id: Optional[str] = None,
    entry_price: Optional[float] = None,
    entry_ts_utc: Optional[str] = None,
    entry_ts_ny: Optional[str] = None,
    entry_date_ny: Optional[str] = None,
    exit_ts_utc: Optional[str] = None,
    exit_ts_ny: Optional[str] = None,
    exit_date_ny: Optional[str] = None,
    position_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    strategy_id: str = "default",
    sleeve_id: str = "default",
) -> dict[str, Any]:
    ts_dt = _parse_dt(ts)
    ts_utc = _iso_utc(ts_dt)
    ts_ny = _iso_ny(ts_dt)
    date_ny = _date_ny(ts_dt)

    resolved_entry_ts_utc = entry_ts_utc
    resolved_entry_ts_ny = entry_ts_ny
    resolved_entry_date_ny = entry_date_ny
    if entry_ts_utc and not entry_ts_ny:
        entry_dt = _parse_dt(entry_ts_utc)
        resolved_entry_ts_ny = _iso_ny(entry_dt)
        resolved_entry_date_ny = _date_ny(entry_dt)

    resolved_exit_ts_utc = exit_ts_utc
    resolved_exit_ts_ny = exit_ts_ny
    resolved_exit_date_ny = exit_date_ny
    if exit_ts_utc and not exit_ts_ny:
        exit_dt = _parse_dt(exit_ts_utc)
        resolved_exit_ts_ny = _iso_ny(exit_dt)
        resolved_exit_date_ny = _date_ny(exit_dt)

    resolved_position_id = position_id
    if not resolved_position_id and resolved_entry_ts_utc and qty is not None:
        resolved_position_id = build_position_id(
            symbol=symbol,
            entry_ts_utc=resolved_entry_ts_utc,
            qty=qty,
            entry_price=entry_price,
            strategy_id=strategy_id,
            sleeve_id=sleeve_id,
            entry_id=entry_id,
        )

    resolved_trade_id = trade_id
    if (
        not resolved_trade_id
        and resolved_position_id
        and resolved_exit_ts_utc
        and qty is not None
    ):
        resolved_trade_id = build_trade_id(
            position_id=resolved_position_id,
            exit_ts_utc=resolved_exit_ts_utc,
            qty=qty,
            exit_price=price,
        )

    metadata_payload = dict(metadata or {})
    event_id = _hash_payload(
        [
            event_type,
            symbol,
            resolved_position_id or "",
            resolved_trade_id or "",
            ts_utc,
            _format_optional_float(stop_price),
            _format_optional_float(price),
            _format_optional_float(qty),
            source,
        ]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "symbol": symbol,
        "position_id": resolved_position_id,
        "trade_id": resolved_trade_id,
        "entry_id": entry_id,
        "qty": qty,
        "price": price,
        "stop_price": stop_price,
        "stop_basis": stop_basis,
        "stop_action": stop_action,
        "reason": reason,
        "entry_price": entry_price,
        "entry_ts_utc": resolved_entry_ts_utc,
        "entry_ts_ny": resolved_entry_ts_ny,
        "entry_date_ny": resolved_entry_date_ny,
        "exit_ts_utc": resolved_exit_ts_utc,
        "exit_ts_ny": resolved_exit_ts_ny,
        "exit_date_ny": resolved_exit_date_ny,
        "ts_utc": ts_utc,
        "ts_ny": ts_ny,
        "date_ny": date_ny,
        "source": source,
        "strategy_id": strategy_id,
        "sleeve_id": sleeve_id,
        "metadata": metadata_payload,
    }


def build_exit_event_from_legacy(
    legacy: dict[str, Any],
    *,
    symbol: str,
    ts: Optional[object] = None,
    source: str = "unknown",
    context: Optional[ExitEventContext] = None,
) -> dict[str, Any]:
    event_type = str(legacy.get("event_type") or legacy.get("event") or "UNKNOWN")
    ctx = context or ExitEventContext(symbol=symbol)
    return build_exit_event(
        event_type=event_type,
        symbol=symbol,
        ts=ts,
        source=source,
        qty=ctx.qty,
        entry_id=ctx.entry_id,
        entry_price=ctx.entry_price,
        entry_ts_utc=ctx.entry_ts_utc,
        entry_ts_ny=ctx.entry_ts_ny,
        entry_date_ny=ctx.entry_date_ny,
        position_id=ctx.position_id,
        trade_id=ctx.trade_id,
        metadata=legacy,
    )


def serialize_exit_event(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def exit_ledger_path(repo_root: Path, date_ny: str) -> Path:
    return repo_root / LEDGER_DIR / f"{date_ny}.jsonl"


def append_exit_event(repo_root: Path, event: dict[str, Any]) -> Path:
    date_ny = event.get("date_ny")
    if not date_ny:
        raise ValueError("exit event missing date_ny")
    ledger_dir = repo_root / LEDGER_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{date_ny}.jsonl"
    payload = serialize_exit_event(event)
    lines: list[str] = []
    if ledger_path.exists():
        try:
            existing = ledger_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        if existing:
            lines.extend([line for line in existing.splitlines() if line])
    lines.append(payload)
    data = "\n".join(lines) + "\n"
    atomic_write_text(ledger_path, data)
    return ledger_path
