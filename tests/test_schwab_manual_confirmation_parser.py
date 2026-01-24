from __future__ import annotations

from decimal import Decimal

from execution_v2.schwab_manual_confirmations import parse_confirmation


def test_parse_confirmation_success_statuses() -> None:
    base = "Intent ID: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
    for status in ("EXECUTED", "PARTIAL", "SKIPPED", "ERROR"):
        text = f"{base}Status: {status}\nQty: 10\nAvg Price: 123.45\nNotes: ok"
        result = parse_confirmation(text)
        assert result.ok
        assert result.intent_id == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        assert result.status == status
        assert result.qty == 10
        assert result.avg_price == Decimal("123.45")
        assert result.notes == "ok"


def test_parse_confirmation_missing_intent() -> None:
    result = parse_confirmation("Status: EXECUTED")
    assert not result.ok
    assert result.error_code == "MISSING_INTENT_ID"


def test_parse_confirmation_missing_status() -> None:
    result = parse_confirmation("Intent ID: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    assert not result.ok
    assert result.error_code == "MISSING_STATUS"


def test_parse_confirmation_ambiguous_status() -> None:
    text = (
        "Intent ID: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
        "Status: EXECUTED\nStatus: SKIPPED"
    )
    result = parse_confirmation(text)
    assert not result.ok
    assert result.error_code == "AMBIGUOUS_STATUS"


def test_parse_confirmation_invalid_qty() -> None:
    text = (
        "Intent ID: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
        "Status: EXECUTED\nQty: 0"
    )
    result = parse_confirmation(text)
    assert not result.ok
    assert result.error_code == "INVALID_QTY"
