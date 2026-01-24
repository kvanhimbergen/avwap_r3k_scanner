from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

SCHEMA_VERSION = 1
QTY_PLACES = 6
VALUE_PLACES = 4


def _to_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    raw = str(value).strip()
    if raw == "":
        return None
    return Decimal(raw)


def _format_decimal(value: Optional[Decimal], *, places: int) -> Optional[str]:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-places)
    return f"{value.quantize(quant, rounding=ROUND_HALF_UP):.{places}f}"


def format_qty(value: Optional[Decimal]) -> Optional[str]:
    return _format_decimal(value, places=QTY_PLACES)


def format_value(value: Optional[Decimal]) -> Optional[str]:
    return _format_decimal(value, places=VALUE_PLACES)


def stable_json_dumps(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_snapshot_id(payload: dict) -> str:
    packed = stable_json_dumps(payload)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SchwabBalanceSnapshot:
    schema_version: int
    book_id: str
    as_of_utc: str
    cash: Optional[Decimal]
    market_value: Optional[Decimal]
    total_value: Optional[Decimal]


@dataclass(frozen=True)
class SchwabPosition:
    book_id: str
    as_of_utc: str
    symbol: str
    qty: Decimal
    cost_basis: Optional[Decimal]
    market_value: Optional[Decimal]


@dataclass(frozen=True)
class SchwabPositionsSnapshot:
    schema_version: int
    book_id: str
    as_of_utc: str
    positions: list[SchwabPosition]


@dataclass(frozen=True)
class SchwabOrder:
    book_id: str
    as_of_utc: str
    order_id: str
    symbol: str
    side: str
    qty: Decimal
    filled_qty: Optional[Decimal]
    status: Optional[str]
    submitted_at: Optional[str]
    filled_at: Optional[str]


@dataclass(frozen=True)
class SchwabOrdersSnapshot:
    schema_version: int
    book_id: str
    as_of_utc: str
    orders: list[SchwabOrder]


def serialize_balance_snapshot(snapshot: SchwabBalanceSnapshot) -> dict[str, object]:
    return {
        "schema_version": int(snapshot.schema_version),
        "book_id": snapshot.book_id,
        "as_of_utc": snapshot.as_of_utc,
        "cash": format_value(snapshot.cash),
        "market_value": format_value(snapshot.market_value),
        "total_value": format_value(snapshot.total_value),
    }


def serialize_positions_snapshot(snapshot: SchwabPositionsSnapshot) -> dict[str, object]:
    positions = sorted(snapshot.positions, key=lambda item: (item.symbol, item.book_id, item.as_of_utc))
    return {
        "schema_version": int(snapshot.schema_version),
        "book_id": snapshot.book_id,
        "as_of_utc": snapshot.as_of_utc,
        "positions": [
            {
                "book_id": position.book_id,
                "as_of_utc": position.as_of_utc,
                "symbol": position.symbol,
                "qty": format_qty(position.qty),
                "cost_basis": format_value(position.cost_basis),
                "market_value": format_value(position.market_value),
            }
            for position in positions
        ],
    }


def serialize_orders_snapshot(snapshot: SchwabOrdersSnapshot) -> dict[str, object]:
    orders = sorted(snapshot.orders, key=lambda item: (item.symbol, item.order_id, item.book_id))
    return {
        "schema_version": int(snapshot.schema_version),
        "book_id": snapshot.book_id,
        "as_of_utc": snapshot.as_of_utc,
        "orders": [
            {
                "book_id": order.book_id,
                "as_of_utc": order.as_of_utc,
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": format_qty(order.qty),
                "filled_qty": format_qty(order.filled_qty),
                "status": order.status,
                "submitted_at": order.submitted_at,
                "filled_at": order.filled_at,
            }
            for order in orders
        ],
    }


def parse_decimal(value: object) -> Optional[Decimal]:
    return _to_decimal(value)
