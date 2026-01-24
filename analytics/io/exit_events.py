from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analytics.schemas import ExitEvent, ExitIngestResult
from analytics.util import parse_timestamp


class ExitLedgerParseError(ValueError):
    pass


def _require(value: Any, field: str, source_path: str, idx: int) -> Any:
    if value is None:
        raise ExitLedgerParseError(f"exit event missing {field} at index {idx} in {source_path}")
    return value


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_event(raw: dict[str, Any], *, source_path: str, idx: int) -> ExitEvent:
    schema_version = _require(raw.get("schema_version"), "schema_version", source_path, idx)
    if int(schema_version) != 1:
        raise ExitLedgerParseError(
            f"exit event schema_version unsupported ({schema_version}) at index {idx} in {source_path}"
        )

    ts_utc = _require(raw.get("ts_utc"), "ts_utc", source_path, idx)
    parse_timestamp(ts_utc, source_path=source_path, entry_index=idx)

    event = ExitEvent(
        event_id=str(_require(raw.get("event_id"), "event_id", source_path, idx)),
        schema_version=int(schema_version),
        event_type=str(_require(raw.get("event_type"), "event_type", source_path, idx)),
        symbol=str(_require(raw.get("symbol"), "symbol", source_path, idx)),
        position_id=_coerce_str(raw.get("position_id")),
        trade_id=_coerce_str(raw.get("trade_id")),
        entry_id=_coerce_str(raw.get("entry_id")),
        qty=_coerce_float(raw.get("qty")),
        price=_coerce_float(raw.get("price")),
        stop_price=_coerce_float(raw.get("stop_price")),
        stop_basis=_coerce_str(raw.get("stop_basis")),
        stop_action=_coerce_str(raw.get("stop_action")),
        reason=_coerce_str(raw.get("reason")),
        entry_price=_coerce_float(raw.get("entry_price")),
        entry_ts_utc=_coerce_str(raw.get("entry_ts_utc")),
        entry_ts_ny=_coerce_str(raw.get("entry_ts_ny")),
        entry_date_ny=_coerce_str(raw.get("entry_date_ny")),
        exit_ts_utc=_coerce_str(raw.get("exit_ts_utc")),
        exit_ts_ny=_coerce_str(raw.get("exit_ts_ny")),
        exit_date_ny=_coerce_str(raw.get("exit_date_ny")),
        ts_utc=str(ts_utc),
        ts_ny=str(_require(raw.get("ts_ny"), "ts_ny", source_path, idx)),
        date_ny=str(_require(raw.get("date_ny"), "date_ny", source_path, idx)),
        source=str(_require(raw.get("source"), "source", source_path, idx)),
        strategy_id=str(raw.get("strategy_id") or "default"),
        sleeve_id=str(raw.get("sleeve_id") or "default"),
        metadata=dict(raw.get("metadata") or {}),
    )
    return event


def _sort_events(events: list[ExitEvent]) -> list[ExitEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.ts_utc,
            event.symbol,
            event.event_type,
            event.event_id,
        ),
    )


def parse_exit_ledger(path: str) -> ExitIngestResult:
    source_path = str(path)
    ledger_path = Path(source_path)
    if not ledger_path.exists():
        raise ExitLedgerParseError(f"exit ledger missing: {source_path}")
    try:
        raw_text = ledger_path.read_text()
    except Exception as exc:
        raise ExitLedgerParseError(
            f"exit ledger unreadable ({type(exc).__name__}): {source_path}"
        ) from exc

    events: list[ExitEvent] = []
    warnings: list[str] = []
    for idx, line in enumerate(raw_text.splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExitLedgerParseError(
                f"exit ledger invalid JSON at index {idx} in {source_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ExitLedgerParseError(
                f"exit ledger invalid entry at index {idx} in {source_path}"
            )
        events.append(_parse_event(payload, source_path=source_path, idx=idx))

    if not events:
        warnings.append(f"exit ledger empty: {source_path}")

    return ExitIngestResult(
        events=_sort_events(events),
        warnings=warnings,
        source_metadata={"source_path": source_path},
    )
