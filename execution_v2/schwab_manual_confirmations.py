"""Schwab manual Slack confirmation parsing + ledger helpers.

Confirmation grammar (case-insensitive, order-insensitive):
  - Intent ID: <64-hex sha256>            (required)
  - Status: EXECUTED|PARTIAL|SKIPPED|ERROR (required)
  - Qty: <integer>                         (optional)
  - Avg Price: <number>                    (optional)
  - Fill Price: <number>                   (optional)
  - Notes: <freeform>                      (optional)

Examples:
  Intent ID: <hash>
  Status: EXECUTED
  Qty: 10
  Avg Price: 123.45
  Notes: filled in two lots
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from execution_v2 import book_ids
from execution_v2.schwab_manual_adapter import MANUAL_EVENT_TYPE

NY_TZ = ZoneInfo("America/New_York")

CONFIRMATION_STATUSES = {"EXECUTED", "PARTIAL", "SKIPPED", "ERROR"}

INTENT_ID_RE = re.compile(r"\bintent[\s_-]*id\b\s*[:=]\s*([a-fA-F0-9]{64})\b", re.IGNORECASE)
STATUS_RE = re.compile(r"\bstatus\b\s*[:=]\s*(EXECUTED|PARTIAL|SKIPPED|ERROR)\b", re.IGNORECASE)
QTY_RE = re.compile(r"\b(qty|quantity)\b\s*[:=]\s*(\d+)\b", re.IGNORECASE)
PRICE_RE = re.compile(
    r"\b(avg[\s_-]*price|fill[\s_-]*price)\b\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)
NOTES_RE = re.compile(r"\bnotes?\b\s*[:=]\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ConfirmationParseResult:
    ok: bool
    intent_id: str | None = None
    status: str | None = None
    qty: int | None = None
    avg_price: Decimal | None = None
    notes: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _unique_matches(matches: Iterable[str]) -> list[str]:
    values = []
    for value in matches:
        if value not in values:
            values.append(value)
    return values


def parse_confirmation(text: str) -> ConfirmationParseResult:
    intent_matches = _unique_matches([match.lower() for match in INTENT_ID_RE.findall(text)])
    if not intent_matches:
        return ConfirmationParseResult(
            ok=False,
            error_code="MISSING_INTENT_ID",
            error_message="intent id not found",
        )
    if len(intent_matches) > 1:
        return ConfirmationParseResult(
            ok=False,
            error_code="AMBIGUOUS_INTENT_ID",
            error_message="multiple intent ids found",
        )
    intent_id = intent_matches[0]

    status_matches = _unique_matches([match.upper() for match in STATUS_RE.findall(text)])
    if not status_matches:
        return ConfirmationParseResult(
            ok=False,
            error_code="MISSING_STATUS",
            error_message="status not found",
        )
    if len(status_matches) > 1:
        return ConfirmationParseResult(
            ok=False,
            error_code="AMBIGUOUS_STATUS",
            error_message="multiple statuses found",
        )
    status = status_matches[0]
    if status not in CONFIRMATION_STATUSES:
        return ConfirmationParseResult(
            ok=False,
            error_code="INVALID_STATUS",
            error_message="status not recognized",
        )

    qty_matches = _unique_matches([match[1] for match in QTY_RE.findall(text)])
    qty: int | None = None
    if qty_matches:
        if len(qty_matches) > 1:
            return ConfirmationParseResult(
                ok=False,
                error_code="AMBIGUOUS_QTY",
                error_message="multiple qty values found",
            )
        try:
            qty = int(qty_matches[0])
        except ValueError:
            return ConfirmationParseResult(
                ok=False,
                error_code="INVALID_QTY",
                error_message="qty is not an integer",
            )
        if qty <= 0:
            return ConfirmationParseResult(
                ok=False,
                error_code="INVALID_QTY",
                error_message="qty must be positive",
            )

    price_matches = _unique_matches([match[1] for match in PRICE_RE.findall(text)])
    avg_price: Decimal | None = None
    if price_matches:
        if len(price_matches) > 1:
            return ConfirmationParseResult(
                ok=False,
                error_code="AMBIGUOUS_PRICE",
                error_message="multiple price values found",
            )
        try:
            avg_price = Decimal(price_matches[0])
        except InvalidOperation:
            return ConfirmationParseResult(
                ok=False,
                error_code="INVALID_PRICE",
                error_message="avg price is invalid",
            )
        if avg_price <= 0:
            return ConfirmationParseResult(
                ok=False,
                error_code="INVALID_PRICE",
                error_message="avg price must be positive",
            )

    notes_match = NOTES_RE.search(text)
    notes = notes_match.group(1).strip() if notes_match else None

    return ConfirmationParseResult(
        ok=True,
        intent_id=intent_id,
        status=status,
        qty=qty,
        avg_price=avg_price,
        notes=notes,
    )


def format_decimal(value: Decimal, *, places: int = 4) -> str:
    quant = Decimal("1").scaleb(-places)
    return f"{value.quantize(quant, rounding=ROUND_HALF_UP):.{places}f}"


def datetime_from_slack_ts(slack_ts: str) -> datetime:
    seconds = Decimal(slack_ts)
    whole = int(seconds)
    micros = int((seconds - Decimal(whole)) * Decimal("1000000"))
    dt_utc = datetime.fromtimestamp(whole, tz=timezone.utc).replace(microsecond=micros)
    return dt_utc.astimezone(NY_TZ)


def ny_date_from_slack_ts(slack_ts: str) -> str:
    return datetime_from_slack_ts(slack_ts).date().isoformat()


def ledger_path(repo_root: Path, ny_date: str) -> Path:
    return book_ids.ledger_path(repo_root, book_ids.SCHWAB_401K_MANUAL, ny_date)


def load_existing_event_ids(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    event_ids: set[tuple[str, str]] = set()
    try:
        with path.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                slack = data.get("slack", {})
                team_id = slack.get("team_id")
                event_id = slack.get("event_id")
                if team_id and event_id:
                    event_ids.add((str(team_id), str(event_id)))
    except json.JSONDecodeError as exc:
        raise RuntimeError("ledger invalid") from exc
    except Exception as exc:
        raise RuntimeError("ledger unreadable") from exc
    return event_ids


def intent_id_exists(path: Path, intent_id: str) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("event") != MANUAL_EVENT_TYPE:
                    continue
                if str(data.get("intent_id")) == intent_id:
                    return True
    except json.JSONDecodeError as exc:
        raise RuntimeError("ledger invalid") from exc
    except Exception as exc:
        raise RuntimeError("ledger unreadable") from exc
    return False


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True)
    with path.open("a") as handle:
        handle.write(line + "\n")
