"""Schwab manual execution adapter (Slack tickets only)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from execution_v2 import book_ids


MANUAL_EVENT_TYPE = "MANUAL_TICKET_SENT"


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def slack_post_enabled() -> bool:
    return _truthy(os.getenv("SLACK_POST_ENABLED", "1"))


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _format_float(value: Any, *, places: int = 4) -> str:
    return f"{float(value):.{places}f}"


def _get_field(intent: Any, name: str, fallback: Any = None) -> Any:
    if isinstance(intent, Mapping):
        return intent.get(name, fallback)
    return getattr(intent, name, fallback)


def canonical_intent_payload(intent: Any) -> dict:
    symbol = _normalize_symbol(_get_field(intent, "symbol"))
    if not symbol:
        raise ValueError("intent symbol missing")
    side = str(_get_field(intent, "side", "BUY")).strip().upper()
    qty = int(_get_field(intent, "size_shares", _get_field(intent, "qty", 0)))
    if qty <= 0:
        raise ValueError(f"intent qty invalid for {symbol}")

    ref_price = _get_field(intent, "ref_price")
    pivot_level = _get_field(intent, "pivot_level")
    stop_loss = _get_field(intent, "stop_loss")
    take_profit = _get_field(intent, "take_profit")
    dist_pct = _get_field(intent, "dist_pct")

    if ref_price is None or pivot_level is None or stop_loss is None or take_profit is None or dist_pct is None:
        raise ValueError(f"intent missing pricing fields for {symbol}")

    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "ref_price": _format_float(ref_price),
        "pivot_level": _format_float(pivot_level),
        "stop_loss": _format_float(stop_loss),
        "take_profit": _format_float(take_profit),
        "dist_pct": _format_float(dist_pct),
    }


def build_intent_id(payload: Mapping[str, Any], *, book_id: str, ny_date: str) -> str:
    canonical = {
        "book_id": book_id,
        "ny_date": ny_date,
        **payload,
    }
    packed = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _slack_channel() -> str | None:
    channel = os.getenv("SLACK_TICKETS_CHANNEL") or os.getenv("SLACK_ALERTS_CHANNEL")
    if channel:
        return channel.strip()
    return None


def _slack_username() -> str | None:
    username = os.getenv("SLACK_TICKETS_USERNAME")
    if username:
        return username.strip()
    return None


def build_ticket_message(payload: Mapping[str, Any], *, intent_id: str, ny_date: str, book_id: str) -> str:
    lines = [
        "Manual Trade Ticket",
        f"Book: {book_id}",
        f"NY Date: {ny_date}",
        f"Intent ID: {intent_id}",
        f"Symbol: {payload['symbol']}",
        f"Side: {payload['side']}",
        f"Qty: {payload['qty']}",
        f"Ref Price: {payload['ref_price']}",
        f"Pivot Level: {payload['pivot_level']}",
        f"Stop Loss: {payload['stop_loss']}",
        f"Take Profit: {payload['take_profit']}",
        f"Dist %: {payload['dist_pct']}",
    ]
    return "\n".join(lines)


def build_slack_payload(message: str) -> dict:
    payload = {"text": message}
    channel = _slack_channel()
    if channel:
        payload["channel"] = channel
    username = _slack_username()
    if username:
        payload["username"] = username
    return payload


def _default_slack_sender(payload: dict) -> dict:
    from alerts import slack as slack_alerts

    slack_alerts._post(payload)
    return {
        "channel": payload.get("channel"),
        "ts": None,
        "permalink": None,
    }


def _normalize_slack_meta(meta: Mapping[str, Any] | None, payload: Mapping[str, Any]) -> dict:
    data = dict(meta or {})
    if "channel" not in data:
        data["channel"] = payload.get("channel")
    data.setdefault("ts", None)
    data.setdefault("permalink", None)
    return data


def _ledger_path(repo_root: Path, ny_date: str) -> Path:
    return book_ids.ledger_path(repo_root, book_ids.SCHWAB_401K_MANUAL, ny_date)


def _load_sent_intent_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()

    sent: set[str] = set()
    try:
        with path.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("ledger entry not a JSON object")
                event = data.get("event")
                if event != MANUAL_EVENT_TYPE:
                    continue
                intent_id = data.get("intent_id")
                if not intent_id:
                    raise ValueError("ledger entry missing intent_id")
                sent.add(str(intent_id))
    except json.JSONDecodeError as exc:
        raise RuntimeError("ledger invalid") from exc
    except Exception as exc:
        raise RuntimeError("ledger unreadable") from exc

    return sent


@dataclass(frozen=True)
class ManualTicketResult:
    ny_date: str
    ledger_path: str | None
    sent: int
    skipped: int
    intent_ids: list[str]
    posting_enabled: bool


@dataclass(frozen=True)
class ManualTicket:
    payload: dict
    intent_id: str
    message: str


def _prepare_tickets(intents: Iterable[Any], *, ny_date: str, book_id: str) -> list[ManualTicket]:
    tickets: list[ManualTicket] = []
    for intent in intents:
        payload = canonical_intent_payload(intent)
        intent_id = build_intent_id(payload, book_id=book_id, ny_date=ny_date)
        message = build_ticket_message(payload, intent_id=intent_id, ny_date=ny_date, book_id=book_id)
        tickets.append(ManualTicket(payload=payload, intent_id=intent_id, message=message))

    tickets.sort(key=lambda item: (item.payload["symbol"], item.intent_id))
    return tickets


def send_manual_tickets(
    intents: Iterable[Any],
    *,
    ny_date: str,
    repo_root: Path,
    now_utc: datetime | None = None,
    slack_sender: Callable[[dict], dict] | None = None,
    post_enabled: bool | None = None,
) -> ManualTicketResult:
    resolved_now = now_utc or datetime.now(timezone.utc)
    enabled = slack_post_enabled() if post_enabled is None else post_enabled
    book_id = book_ids.SCHWAB_401K_MANUAL
    tickets = _prepare_tickets(intents, ny_date=ny_date, book_id=book_id)

    ledger_path = _ledger_path(repo_root, ny_date)
    sent_ids = _load_sent_intent_ids(ledger_path)

    pending = [ticket for ticket in tickets if ticket.intent_id not in sent_ids]
    if not pending:
        return ManualTicketResult(
            ny_date=ny_date,
            ledger_path=str(ledger_path),
            sent=0,
            skipped=len(tickets),
            intent_ids=[],
            posting_enabled=enabled,
        )

    if not enabled:
        return ManualTicketResult(
            ny_date=ny_date,
            ledger_path=None,
            sent=0,
            skipped=len(tickets),
            intent_ids=[ticket.intent_id for ticket in pending],
            posting_enabled=enabled,
        )

    sender = slack_sender or _default_slack_sender
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    sent_count = 0
    recorded_ids: list[str] = []
    with ledger_path.open("a") as handle:
        for ticket in pending:
            payload = build_slack_payload(ticket.message)
            slack_meta = _normalize_slack_meta(sender(payload), payload)
            event = {
                "ts_utc": resolved_now.astimezone(timezone.utc).isoformat(),
                "ny_date": ny_date,
                "book_id": book_id,
                "event": MANUAL_EVENT_TYPE,
                "intent_id": ticket.intent_id,
                **ticket.payload,
                "slack": slack_meta,
            }
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            sent_count += 1
            recorded_ids.append(ticket.intent_id)

    return ManualTicketResult(
        ny_date=ny_date,
        ledger_path=str(ledger_path),
        sent=sent_count,
        skipped=len(tickets) - sent_count,
        intent_ids=recorded_ids,
        posting_enabled=enabled,
    )


def _extract_summary_intent(intent: Any) -> tuple[str, dict]:
    intent_id = _get_field(intent, "intent_id")
    if not intent_id:
        raise ValueError("intent_id missing for summary ticket")
    payload = {
        "symbol": _normalize_symbol(_get_field(intent, "symbol", "")) or "N/A",
        "side": str(_get_field(intent, "side", "INFO")).strip().upper(),
        "target_pct": _get_field(intent, "target_pct"),
        "current_pct": _get_field(intent, "current_pct"),
        "delta_pct": _get_field(intent, "delta_pct"),
        "strategy_id": _get_field(intent, "strategy_id"),
    }
    return str(intent_id), payload


def send_manual_summary_ticket(
    intents: Iterable[Any],
    *,
    message: str,
    ny_date: str,
    repo_root: Path,
    now_utc: datetime | None = None,
    slack_sender: Callable[[dict], dict] | None = None,
    post_enabled: bool | None = None,
) -> ManualTicketResult:
    resolved_now = now_utc or datetime.now(timezone.utc)
    enabled = slack_post_enabled() if post_enabled is None else post_enabled
    book_id = book_ids.SCHWAB_401K_MANUAL
    ledger_path = _ledger_path(repo_root, ny_date)
    sent_ids = _load_sent_intent_ids(ledger_path)

    pending_payloads: list[tuple[str, dict]] = []
    all_ids: list[str] = []
    for intent in intents:
        intent_id, payload = _extract_summary_intent(intent)
        all_ids.append(intent_id)
        if intent_id not in sent_ids:
            pending_payloads.append((intent_id, payload))

    if not pending_payloads:
        return ManualTicketResult(
            ny_date=ny_date,
            ledger_path=str(ledger_path),
            sent=0,
            skipped=len(all_ids),
            intent_ids=[],
            posting_enabled=enabled,
        )

    if not enabled:
        return ManualTicketResult(
            ny_date=ny_date,
            ledger_path=None,
            sent=0,
            skipped=len(all_ids),
            intent_ids=[intent_id for intent_id, _ in pending_payloads],
            posting_enabled=enabled,
        )

    sender = slack_sender or _default_slack_sender
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_slack_payload(message)
    slack_meta = _normalize_slack_meta(sender(payload), payload)
    recorded_ids: list[str] = []
    with ledger_path.open("a") as handle:
        for intent_id, intent_payload in pending_payloads:
            event = {
                "ts_utc": resolved_now.astimezone(timezone.utc).isoformat(),
                "ny_date": ny_date,
                "book_id": book_id,
                "event": MANUAL_EVENT_TYPE,
                "intent_id": intent_id,
                **{k: v for k, v in intent_payload.items() if v is not None},
                "slack": slack_meta,
            }
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            recorded_ids.append(intent_id)

    return ManualTicketResult(
        ny_date=ny_date,
        ledger_path=str(ledger_path),
        sent=len(recorded_ids),
        skipped=len(all_ids) - len(recorded_ids),
        intent_ids=recorded_ids,
        posting_enabled=enabled,
    )


class SchwabManualAdapter:
    book_id = book_ids.SCHWAB_401K_MANUAL

    def send_trade_tickets(
        self,
        intents: Iterable[Any],
        *,
        ny_date: str,
        repo_root: Path,
        now_utc: datetime | None = None,
        slack_sender: Callable[[dict], dict] | None = None,
        post_enabled: bool | None = None,
    ) -> ManualTicketResult:
        return send_manual_tickets(
            intents,
            ny_date=ny_date,
            repo_root=repo_root,
            now_utc=now_utc,
            slack_sender=slack_sender,
            post_enabled=post_enabled,
        )

    def send_summary_ticket(
        self,
        intents: Iterable[Any],
        *,
        message: str,
        ny_date: str,
        repo_root: Path,
        now_utc: datetime | None = None,
        slack_sender: Callable[[dict], dict] | None = None,
        post_enabled: bool | None = None,
    ) -> ManualTicketResult:
        return send_manual_summary_ticket(
            intents,
            message=message,
            ny_date=ny_date,
            repo_root=repo_root,
            now_utc=now_utc,
            slack_sender=slack_sender,
            post_enabled=post_enabled,
        )
