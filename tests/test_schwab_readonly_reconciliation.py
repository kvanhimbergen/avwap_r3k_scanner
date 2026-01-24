from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from analytics.schwab_readonly_reconciliation import (
    REASON_BROKER_NO_CONFIRMATION,
    REASON_CONFIRMED_NO_POSITION,
    REASON_PARTIAL_FILL_MISMATCH,
    REASON_QTY_MISMATCH,
    REASON_UNKNOWN_SYMBOL,
    build_reconciliation_report,
    serialize_reconciliation_report,
    write_reconciliation_record,
)
from analytics.schwab_readonly_schemas import (
    SCHEMA_VERSION,
    SchwabBalanceSnapshot,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
)
from analytics.schwab_readonly_storage import write_snapshot_records


def _append_line(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def test_reconciliation_drift_reason_codes(tmp_path: Path) -> None:
    balance = SchwabBalanceSnapshot(
        schema_version=SCHEMA_VERSION,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
        cash=Decimal("10000.00"),
        market_value=Decimal("15000.00"),
        total_value=Decimal("25000.00"),
    )
    positions = SchwabPositionsSnapshot(
        schema_version=SCHEMA_VERSION,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
        positions=[
            SchwabPosition(
                book_id="SCHWAB_401K_MANUAL",
                as_of_utc="2026-01-20T16:00:00+00:00",
                symbol="AAPL",
                qty=Decimal("0"),
                cost_basis=None,
                market_value=None,
            ),
            SchwabPosition(
                book_id="SCHWAB_401K_MANUAL",
                as_of_utc="2026-01-20T16:00:00+00:00",
                symbol="TSLA",
                qty=Decimal("2"),
                cost_basis=None,
                market_value=None,
            ),
            SchwabPosition(
                book_id="SCHWAB_401K_MANUAL",
                as_of_utc="2026-01-20T16:00:00+00:00",
                symbol="MSFT",
                qty=Decimal("5"),
                cost_basis=None,
                market_value=None,
            ),
        ],
    )
    orders = SchwabOrdersSnapshot(
        schema_version=SCHEMA_VERSION,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
        orders=[
            SchwabOrder(
                book_id="SCHWAB_401K_MANUAL",
                as_of_utc="2026-01-20T16:00:00+00:00",
                order_id="ord-1",
                symbol="AAPL",
                side="buy",
                qty=Decimal("10"),
                filled_qty=Decimal("10"),
                status="FILLED",
                submitted_at="2026-01-20T14:30:00+00:00",
                filled_at="2026-01-20T14:31:00+00:00",
            )
        ],
    )

    snapshot_result = write_snapshot_records(
        repo_root=tmp_path,
        account_snapshot=balance,
        positions_snapshot=positions,
        orders_snapshot=orders,
    )
    ledger_path = Path(snapshot_result.ledger_path)

    _append_line(
        ledger_path,
        {
            "event": "MANUAL_TICKET_SENT",
            "intent_id": "intent-aapl",
            "symbol": "AAPL",
            "side": "BUY",
            "qty": 10,
        },
    )
    _append_line(
        ledger_path,
        {
            "event": "MANUAL_TICKET_SENT",
            "intent_id": "intent-tsla",
            "symbol": "TSLA",
            "side": "BUY",
            "qty": 4,
        },
    )
    _append_line(
        ledger_path,
        {
            "record_type": "SCHWAB_MANUAL_CONFIRMATION",
            "intent_id": "intent-aapl",
            "status": "EXECUTED",
            "qty": 10,
        },
    )
    _append_line(
        ledger_path,
        {
            "record_type": "SCHWAB_MANUAL_CONFIRMATION",
            "intent_id": "intent-tsla",
            "status": "PARTIAL",
            "qty": 3,
        },
    )
    _append_line(
        ledger_path,
        {
            "record_type": "SCHWAB_MANUAL_CONFIRMATION",
            "intent_id": "intent-unknown",
            "status": "EXECUTED",
            "qty": 1,
        },
    )

    report = build_reconciliation_report(ledger_path=ledger_path)
    serialized = serialize_reconciliation_report(report)

    intent_codes = {
        item["intent_id"]: set(item["drift_reason_codes"]) for item in serialized["intents"]
    }
    assert REASON_CONFIRMED_NO_POSITION in intent_codes["intent-aapl"]
    assert REASON_QTY_MISMATCH in intent_codes["intent-tsla"]
    assert REASON_PARTIAL_FILL_MISMATCH in intent_codes["intent-tsla"]
    assert REASON_UNKNOWN_SYMBOL in intent_codes["intent-unknown"]

    symbol_codes = {item["symbol"]: set(item["drift_reason_codes"]) for item in serialized["symbols"]}
    assert REASON_BROKER_NO_CONFIRMATION in symbol_codes["MSFT"]
    assert REASON_UNKNOWN_SYMBOL in symbol_codes["MSFT"]

    result = write_reconciliation_record(ledger_path=ledger_path, report=report)
    assert result.written is True

    second = write_reconciliation_record(ledger_path=ledger_path, report=report)
    assert second.written is False
