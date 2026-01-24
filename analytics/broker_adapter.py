from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol

from analytics.schemas import BrokerOrder, BrokerPosition
from analytics.util import normalize_side, normalize_symbol


class BrokerAdapter(Protocol):
    def fetch_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    def fetch_orders(self) -> list[BrokerOrder]:
        raise NotImplementedError


def _coerce_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_qty(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_positions(raw: Iterable[dict[str, object]]) -> list[BrokerPosition]:
    positions: list[BrokerPosition] = []
    for entry in raw:
        symbol = normalize_symbol(entry.get("symbol"))
        if not symbol:
            continue
        positions.append(
            BrokerPosition(
                symbol=symbol,
                qty=_coerce_qty(entry.get("qty")),
                avg_entry_price=_coerce_float(entry.get("avg_entry_price")),
                market_value=_coerce_float(entry.get("market_value")),
                last_price=_coerce_float(entry.get("last_price")),
            )
        )
    return sorted(positions, key=lambda item: item.symbol)


def _parse_orders(raw: Iterable[dict[str, object]]) -> list[BrokerOrder]:
    orders: list[BrokerOrder] = []
    for entry in raw:
        order_id = str(entry.get("order_id") or "").strip()
        symbol = normalize_symbol(entry.get("symbol"))
        if not order_id or not symbol:
            continue
        orders.append(
            BrokerOrder(
                order_id=order_id,
                symbol=symbol,
                side=normalize_side(entry.get("side")),
                qty=_coerce_qty(entry.get("qty")),
                filled_qty=_coerce_float(entry.get("filled_qty")),
                status=str(entry.get("status") or "").strip() or None,
                submitted_at=str(entry.get("submitted_at") or "").strip() or None,
            )
        )
    return sorted(orders, key=lambda item: (item.symbol, item.order_id))


@dataclass(frozen=True)
class AlpacaFixtureAdapter:
    positions_path: Optional[str] = None
    orders_path: Optional[str] = None

    def fetch_positions(self) -> list[BrokerPosition]:
        if not self.positions_path:
            return []
        with open(self.positions_path, "r") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("fixture positions payload must be a list")
        return _parse_positions(data)

    def fetch_orders(self) -> list[BrokerOrder]:
        if not self.orders_path:
            return []
        with open(self.orders_path, "r") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("fixture orders payload must be a list")
        return _parse_orders(data)


@dataclass(frozen=True)
class AlpacaBrokerAdapter:
    fetch_positions_payload: Callable[[], Iterable[dict[str, object]]]
    fetch_orders_payload: Optional[Callable[[], Iterable[dict[str, object]]]] = None

    def fetch_positions(self) -> list[BrokerPosition]:
        return _parse_positions(self.fetch_positions_payload())

    def fetch_orders(self) -> list[BrokerOrder]:
        if self.fetch_orders_payload is None:
            return []
        return _parse_orders(self.fetch_orders_payload())
