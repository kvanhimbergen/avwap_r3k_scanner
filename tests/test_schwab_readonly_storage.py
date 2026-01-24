from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from analytics.schwab_readonly_schemas import (
    SCHEMA_VERSION,
    SchwabBalanceSnapshot,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
)
from analytics.schwab_readonly_storage import (
    RECORD_TYPE_ACCOUNT,
    RECORD_TYPE_ORDERS,
    RECORD_TYPE_POSITIONS,
    ny_date_from_as_of,
    write_snapshot_records,
)


def _build_snapshots() -> tuple[SchwabBalanceSnapshot, SchwabPositionsSnapshot, SchwabOrdersSnapshot]:
    balance = SchwabBalanceSnapshot(
        schema_version=SCHEMA_VERSION,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
        cash=Decimal("10000.00"),
        market_value=Decimal("15000.25"),
        total_value=Decimal("25000.25"),
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
                qty=Decimal("10"),
                cost_basis=Decimal("1500.00"),
                market_value=Decimal("1700.00"),
            )
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
    return balance, positions, orders


def test_snapshot_writer_append_only_and_idempotent(tmp_path: Path) -> None:
    balance, positions, orders = _build_snapshots()
    ny_date = ny_date_from_as_of(balance.as_of_utc)

    result_first = write_snapshot_records(
        repo_root=tmp_path,
        account_snapshot=balance,
        positions_snapshot=positions,
        orders_snapshot=orders,
    )
    result_second = write_snapshot_records(
        repo_root=tmp_path,
        account_snapshot=balance,
        positions_snapshot=positions,
        orders_snapshot=orders,
    )

    ledger_path = tmp_path / "ledger" / "SCHWAB_401K_MANUAL" / f"{ny_date}.jsonl"
    lines = ledger_path.read_text().strip().splitlines()

    assert result_first.records_written == 3
    assert result_second.records_written == 0
    assert result_second.skipped == 3
    assert len(lines) == 3

    record_types = [json.loads(line)["record_type"] for line in lines]
    assert sorted(record_types) == sorted([RECORD_TYPE_ACCOUNT, RECORD_TYPE_POSITIONS, RECORD_TYPE_ORDERS])
