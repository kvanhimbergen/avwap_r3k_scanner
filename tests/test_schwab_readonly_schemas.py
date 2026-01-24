from __future__ import annotations

import json
from decimal import Decimal

from analytics.schwab_readonly_schemas import (
    SCHEMA_VERSION,
    SchwabBalanceSnapshot,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
    serialize_balance_snapshot,
    serialize_orders_snapshot,
    serialize_positions_snapshot,
    stable_json_dumps,
)


def test_schwab_snapshot_serialization_deterministic() -> None:
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
                symbol="MSFT",
                qty=Decimal("5"),
                cost_basis=Decimal("1000.50"),
                market_value=Decimal("1100.75"),
            ),
            SchwabPosition(
                book_id="SCHWAB_401K_MANUAL",
                as_of_utc="2026-01-20T16:00:00+00:00",
                symbol="AAPL",
                qty=Decimal("10"),
                cost_basis=Decimal("1500.00"),
                market_value=Decimal("1700.00"),
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

    balance_payload = serialize_balance_snapshot(balance)
    positions_payload = serialize_positions_snapshot(positions)
    orders_payload = serialize_orders_snapshot(orders)

    assert stable_json_dumps(balance_payload) == stable_json_dumps(balance_payload)
    assert stable_json_dumps(positions_payload) == stable_json_dumps(positions_payload)
    assert stable_json_dumps(orders_payload) == stable_json_dumps(orders_payload)

    serialized = json.dumps(balance_payload, sort_keys=True, separators=(",", ":"))
    assert (
        serialized
        == "{\"as_of_utc\":\"2026-01-20T16:00:00+00:00\",\"book_id\":\"SCHWAB_401K_MANUAL\",\"cash\":\"10000.0000\",\"market_value\":\"15000.2500\",\"schema_version\":1,\"total_value\":\"25000.2500\"}"
    )
