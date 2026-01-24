"""Minimal Slack events receiver for Schwab manual confirmations."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Mapping

from execution_v2 import book_ids
from execution_v2 import schwab_manual_confirmations as confirmations


DEFAULT_TOLERANCE_SEC = 300
RECORD_TYPE_CONFIRMATION = "SCHWAB_MANUAL_CONFIRMATION"
RECORD_TYPE_REJECTED = "SCHWAB_MANUAL_CONFIRMATION_REJECTED"


@dataclass(frozen=True)
class SlackResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


def _get_env(env: Mapping[str, str] | None, key: str, default: str = "") -> str:
    if env is None:
        return os.getenv(key, default)
    return env.get(key, default)


def _json_response(payload: dict, status_code: int = 200) -> SlackResponse:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return SlackResponse(status_code=status_code, body=body, headers={"Content-Type": "application/json"})


def _text_response(payload: str, status_code: int = 200) -> SlackResponse:
    return SlackResponse(status_code=status_code, body=payload.encode("utf-8"), headers={"Content-Type": "text/plain"})


def _normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _verify_signature(
    raw_body: bytes,
    headers: Mapping[str, str],
    *,
    secret: str,
    now_utc: datetime,
    tolerance_sec: int,
) -> tuple[bool, str]:
    normalized = _normalize_headers(headers)
    signature = normalized.get("x-slack-signature", "")
    timestamp = normalized.get("x-slack-request-timestamp", "")
    if not signature or not timestamp:
        return False, "missing_signature_headers"
    try:
        ts_int = int(timestamp)
    except ValueError:
        return False, "invalid_timestamp"
    now_ts = int(now_utc.timestamp())
    if abs(now_ts - ts_int) > tolerance_sec:
        return False, "timestamp_out_of_range"
    base = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), sha256).hexdigest()
    expected = f"v0={digest}"
    if not hmac.compare_digest(expected, signature):
        return False, "signature_mismatch"
    return True, "ok"


def _build_rejection_record(
    *,
    ny_date: str,
    now_utc: datetime,
    slack_meta: dict,
    reason_code: str,
    error_message: str | None = None,
) -> dict:
    record = {
        "record_type": RECORD_TYPE_REJECTED,
        "ny_date": ny_date,
        "book_id": book_ids.SCHWAB_401K_MANUAL,
        "reason_code": reason_code,
        "slack": slack_meta,
        "ingested_at_utc": now_utc.astimezone(timezone.utc).isoformat(),
        "provenance": {
            "module": "execution_v2.slack_events_receiver",
        },
    }
    if error_message:
        record["error_message"] = error_message
    return record


def _build_confirmation_record(
    *,
    ny_date: str,
    now_utc: datetime,
    slack_meta: dict,
    parse_result: confirmations.ConfirmationParseResult,
    matched: bool,
    match_reason: str | None,
) -> dict:
    record = {
        "record_type": RECORD_TYPE_CONFIRMATION,
        "ny_date": ny_date,
        "book_id": book_ids.SCHWAB_401K_MANUAL,
        "intent_id": parse_result.intent_id,
        "status": parse_result.status,
        "matched": matched,
        "slack": slack_meta,
        "ingested_at_utc": now_utc.astimezone(timezone.utc).isoformat(),
        "provenance": {
            "module": "execution_v2.slack_events_receiver",
        },
    }
    if match_reason:
        record["match_reason"] = match_reason
    if parse_result.qty is not None:
        record["qty"] = parse_result.qty
    if parse_result.avg_price is not None:
        record["avg_price"] = confirmations.format_decimal(parse_result.avg_price)
    if parse_result.notes:
        record["notes"] = parse_result.notes
    return record


def handle_slack_event(
    raw_body: bytes,
    headers: Mapping[str, str],
    *,
    now_utc: datetime | None = None,
    repo_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> SlackResponse:
    resolved_now = now_utc or datetime.now(timezone.utc)
    resolved_root = repo_root or Path(__file__).resolve().parents[1]

    secret = _get_env(env, "SLACK_SIGNING_SECRET", "").strip()
    if not secret:
        return _text_response("missing signing secret", status_code=500)

    tolerance = int(_get_env(env, "SLACK_SIGNING_TOLERANCE_SEC", str(DEFAULT_TOLERANCE_SEC)))
    ok, reason = _verify_signature(raw_body, headers, secret=secret, now_utc=resolved_now, tolerance_sec=tolerance)
    if not ok:
        return _text_response(f"invalid signature: {reason}", status_code=401)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return _text_response("invalid json", status_code=400)

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        return _json_response({"challenge": challenge})

    if payload.get("type") != "event_callback":
        return _json_response({"ok": True})

    event = payload.get("event") or {}
    if event.get("type") != "message":
        return _json_response({"ok": True})
    if event.get("subtype"):
        return _json_response({"ok": True})

    allowed_channel = _get_env(env, "SLACK_EVENTS_CHANNEL_ID", "").strip()
    channel = event.get("channel")
    if allowed_channel and channel != allowed_channel:
        return _json_response({"ok": True})

    thread_ts = event.get("thread_ts")
    event_ts = event.get("ts")
    if not thread_ts or thread_ts == event_ts:
        return _json_response({"ok": True})

    event_id = payload.get("event_id")
    team_id = payload.get("team_id")
    if not event_id or not team_id:
        return _text_response("missing event metadata", status_code=400)

    slack_meta = {
        "team_id": str(team_id),
        "channel": str(channel),
        "user": str(event.get("user", "")),
        "ts": str(event_ts),
        "thread_ts": str(thread_ts),
        "event_id": str(event_id),
    }

    try:
        ny_date = confirmations.ny_date_from_slack_ts(str(event_ts))
    except Exception:
        return _text_response("invalid event timestamp", status_code=400)

    ledger_path = confirmations.ledger_path(resolved_root, ny_date)

    try:
        existing = confirmations.load_existing_event_ids(ledger_path)
    except RuntimeError:
        return _text_response("ledger unreadable", status_code=500)
    if (slack_meta["team_id"], slack_meta["event_id"]) in existing:
        return _json_response({"ok": True, "duplicate": True})

    parse_result = confirmations.parse_confirmation(str(event.get("text", "")))
    if not parse_result.ok:
        record = _build_rejection_record(
            ny_date=ny_date,
            now_utc=resolved_now,
            slack_meta=slack_meta,
            reason_code=parse_result.error_code or "PARSE_ERROR",
            error_message=parse_result.error_message,
        )
        try:
            confirmations.append_record(ledger_path, record)
        except RuntimeError:
            return _text_response("ledger write failed", status_code=500)
        return _json_response({"ok": True, "recorded": "rejected"})

    try:
        matched = confirmations.intent_id_exists(ledger_path, parse_result.intent_id or "")
    except RuntimeError:
        return _text_response("ledger unreadable", status_code=500)
    match_reason = None if matched else "UNMATCHED_INTENT_ID"
    record = _build_confirmation_record(
        ny_date=ny_date,
        now_utc=resolved_now,
        slack_meta=slack_meta,
        parse_result=parse_result,
        matched=matched,
        match_reason=match_reason,
    )
    try:
        confirmations.append_record(ledger_path, record)
    except RuntimeError:
        return _text_response("ledger write failed", status_code=500)
    return _json_response({"ok": True, "recorded": "confirmation"})


class SlackEventsHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        response = handle_slack_event(raw_body, self.headers)
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def run_server() -> None:
    host = os.getenv("SLACK_EVENTS_BIND_HOST", "0.0.0.0")
    port = int(os.getenv("SLACK_EVENTS_BIND_PORT", "8081"))
    server = HTTPServer((host, port), SlackEventsHandler)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
