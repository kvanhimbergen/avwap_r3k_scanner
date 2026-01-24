from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from execution_v2 import book_ids
from execution_v2.schwab_manual_adapter import (
    build_intent_id,
    canonical_intent_payload,
    send_manual_tickets,
)


class _SlackRecorder:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"channel": payload.get("channel"), "ts": "12345.678", "permalink": "https://example"}


def _sample_intent(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "side": "buy",
        "qty": 10,
        "ref_price": 123.4567,
        "pivot_level": 120.0,
        "stop_loss": 115.5,
        "take_profit": 140.0,
        "dist_pct": 0.1234,
    }


def test_intent_id_deterministic() -> None:
    payload_a = canonical_intent_payload(_sample_intent("aapl"))
    payload_b = canonical_intent_payload(_sample_intent("AAPL"))

    intent_a = build_intent_id(payload_a, book_id=book_ids.SCHWAB_401K_MANUAL, ny_date="2026-01-20")
    intent_b = build_intent_id(payload_b, book_id=book_ids.SCHWAB_401K_MANUAL, ny_date="2026-01-20")

    assert intent_a == intent_b


def test_manual_ticket_idempotency_and_ledger(tmp_path: Path) -> None:
    intents = [_sample_intent("AAPL"), _sample_intent("MSFT")]
    slack = _SlackRecorder()
    now = datetime(2026, 1, 20, 13, 0, 0, tzinfo=timezone.utc)

    result = send_manual_tickets(
        intents,
        ny_date="2026-01-20",
        repo_root=tmp_path,
        now_utc=now,
        slack_sender=slack,
        post_enabled=True,
    )

    ledger_path = tmp_path / "ledger" / book_ids.SCHWAB_401K_MANUAL / "2026-01-20.jsonl"
    assert result.sent == 2
    assert ledger_path.exists()
    assert len(slack.payloads) == 2

    second = send_manual_tickets(
        intents,
        ny_date="2026-01-20",
        repo_root=tmp_path,
        now_utc=now,
        slack_sender=slack,
        post_enabled=True,
    )
    assert second.sent == 0
    assert len(slack.payloads) == 2

    lines = ledger_path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        data = json.loads(line)
        assert data["event"] == "MANUAL_TICKET_SENT"
        assert data["book_id"] == book_ids.SCHWAB_401K_MANUAL
        assert data["ny_date"] == "2026-01-20"
        assert data["intent_id"]
        assert data["symbol"] in {"AAPL", "MSFT"}
        assert data["slack"]["permalink"] == "https://example"
        assert line == json.dumps(data, sort_keys=True)
