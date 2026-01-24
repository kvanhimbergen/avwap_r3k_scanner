from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from execution_v2 import book_ids
from execution_v2.slack_events_receiver import handle_slack_event


def _sign_body(secret: str, timestamp: str, body: bytes) -> str:
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), sha256).hexdigest()
    return f"v0={digest}"


def _build_headers(secret: str, timestamp: str, body: bytes) -> dict[str, str]:
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": _sign_body(secret, timestamp, body),
    }


def _write_manual_ticket(tmp_path: Path, intent_id: str) -> None:
    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts_utc": "2026-01-20T13:00:00+00:00",
        "ny_date": "2026-01-20",
        "book_id": book_ids.SCHWAB_401K_MANUAL,
        "event": "MANUAL_TICKET_SENT",
        "intent_id": intent_id,
        "symbol": "AAPL",
        "side": "BUY",
        "qty": 10,
        "ref_price": "100.0000",
        "pivot_level": "99.0000",
        "stop_loss": "95.0000",
        "take_profit": "110.0000",
        "dist_pct": "0.1000",
        "slack": {"channel": "C123", "ts": "123", "permalink": None},
    }
    ledger_path.write_text(json.dumps(event, sort_keys=True) + "\n")


def _build_event_payload(intent_id: str, *, channel: str, event_id: str) -> dict:
    return {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": event_id,
        "event": {
            "type": "message",
            "user": "U123",
            "text": f"Intent ID: {intent_id}\nStatus: EXECUTED\nQty: 10\nAvg Price: 123.45",
            "channel": channel,
            "ts": "1768923600.000100",
            "thread_ts": "1768920000.000000",
        },
    }


def test_signature_verification_failure(tmp_path: Path) -> None:
    payload = {"type": "url_verification", "challenge": "abc"}
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("wrong-secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env={"SLACK_SIGNING_SECRET": "correct-secret"},
    )
    assert response.status_code == 401


def test_url_verification_success() -> None:
    payload = {"type": "url_verification", "challenge": "abc"}
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        env={"SLACK_SIGNING_SECRET": "secret"},
    )
    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8"))["challenge"] == "abc"


def test_channel_and_thread_scope(tmp_path: Path) -> None:
    intent_id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    payload = _build_event_payload(intent_id, channel="C999", event_id="Ev1")
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env={"SLACK_SIGNING_SECRET": "secret", "SLACK_EVENTS_CHANNEL_ID": "C123"},
    )
    assert response.status_code == 200
    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    assert not ledger_path.exists()

    payload = _build_event_payload(intent_id, channel="C123", event_id="Ev2")
    payload["event"].pop("thread_ts")
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env={"SLACK_SIGNING_SECRET": "secret", "SLACK_EVENTS_CHANNEL_ID": "C123"},
    )
    assert response.status_code == 200
    assert not ledger_path.exists()


def test_confirmation_append_and_dedupe(tmp_path: Path) -> None:
    intent_id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    _write_manual_ticket(tmp_path, intent_id)
    payload = _build_event_payload(intent_id, channel="C123", event_id="Ev3")
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    env = {"SLACK_SIGNING_SECRET": "secret", "SLACK_EVENTS_CHANNEL_ID": "C123"}
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env=env,
    )
    assert response.status_code == 200

    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    lines = ledger_path.read_text().splitlines()
    assert len(lines) == 2
    confirmation = json.loads(lines[1])
    assert confirmation["record_type"] == "SCHWAB_MANUAL_CONFIRMATION"
    assert confirmation["matched"] is True
    assert confirmation["intent_id"] == intent_id
    assert lines[1] == json.dumps(confirmation, sort_keys=True)

    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env=env,
    )
    lines = ledger_path.read_text().splitlines()
    assert len(lines) == 2


def test_unmatched_intent_records(tmp_path: Path) -> None:
    intent_id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    payload = _build_event_payload(intent_id, channel="C123", event_id="Ev4")
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env={"SLACK_SIGNING_SECRET": "secret", "SLACK_EVENTS_CHANNEL_ID": "C123"},
    )
    assert response.status_code == 200
    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    lines = ledger_path.read_text().splitlines()
    record = json.loads(lines[0])
    assert record["matched"] is False
    assert record["match_reason"] == "UNMATCHED_INTENT_ID"


def test_parse_error_records_rejection(tmp_path: Path) -> None:
    intent_id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    payload = _build_event_payload(intent_id, channel="C123", event_id="Ev5")
    payload["event"]["text"] = f"Intent ID: {intent_id}\nQty: 10"
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers("secret", "1700000000", body)
    response = handle_slack_event(
        body,
        headers,
        now_utc=datetime.fromtimestamp(1700000000, tz=timezone.utc),
        repo_root=tmp_path,
        env={"SLACK_SIGNING_SECRET": "secret", "SLACK_EVENTS_CHANNEL_ID": "C123"},
    )
    assert response.status_code == 200
    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    record = json.loads(ledger_path.read_text().splitlines()[0])
    assert record["record_type"] == "SCHWAB_MANUAL_CONFIRMATION_REJECTED"
    assert record["reason_code"] == "MISSING_STATUS"
