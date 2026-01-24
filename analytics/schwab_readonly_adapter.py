from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from analytics.schwab_readonly_schemas import (
    SCHEMA_VERSION,
    SchwabBalanceSnapshot,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
    parse_decimal,
)
from analytics.util import normalize_side, normalize_symbol


class FixtureFormatError(RuntimeError):
    pass


def _load_json(path: Path) -> object:
    if not path.exists():
        raise FixtureFormatError(f"fixture missing: {path}")
    try:
        with path.open("r") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise FixtureFormatError(f"fixture invalid json: {path}") from exc


def _coerce_qty(value: object, *, context: str) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FixtureFormatError(f"invalid qty in {context}")


def _coerce_str(value: object) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


@dataclass(frozen=True)
class SchwabReadonlyFixtureAdapter:
    book_id: str
    as_of_utc: str
    balances_path: Optional[Path] = None
    positions_path: Optional[Path] = None
    orders_path: Optional[Path] = None

    @classmethod
    def from_fixture_dir(
        cls,
        fixture_dir: Path,
        *,
        book_id: str,
        as_of_utc: str,
        balances_filename: str = "balances.json",
        positions_filename: str = "positions.json",
        orders_filename: str = "orders.json",
    ) -> "SchwabReadonlyFixtureAdapter":
        return cls(
            book_id=book_id,
            as_of_utc=as_of_utc,
            balances_path=fixture_dir / balances_filename,
            positions_path=fixture_dir / positions_filename,
            orders_path=fixture_dir / orders_filename,
        )

    def load_balance_snapshot(self) -> SchwabBalanceSnapshot:
        if not self.balances_path:
            raise FixtureFormatError("balances fixture path required")
        data = _load_json(self.balances_path)
        if not isinstance(data, dict):
            raise FixtureFormatError("balances fixture must be an object")
        return SchwabBalanceSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            cash=parse_decimal(data.get("cash")),
            market_value=parse_decimal(data.get("market_value")),
            total_value=parse_decimal(data.get("total_value")),
        )

    def load_positions_snapshot(self) -> SchwabPositionsSnapshot:
        if not self.positions_path:
            raise FixtureFormatError("positions fixture path required")
        data = _load_json(self.positions_path)
        if not isinstance(data, list):
            raise FixtureFormatError("positions fixture must be a list")
        positions: list[SchwabPosition] = []
        for entry in data:
            if not isinstance(entry, dict):
                raise FixtureFormatError("positions entry must be an object")
            symbol = normalize_symbol(entry.get("symbol"))
            if not symbol:
                raise FixtureFormatError("positions entry missing symbol")
            qty = _coerce_qty(entry.get("qty"), context=f"positions {symbol}")
            positions.append(
                SchwabPosition(
                    book_id=self.book_id,
                    as_of_utc=self.as_of_utc,
                    symbol=symbol,
                    qty=parse_decimal(qty) or parse_decimal("0"),
                    cost_basis=parse_decimal(entry.get("cost_basis")),
                    market_value=parse_decimal(entry.get("market_value")),
                )
            )
        positions.sort(key=lambda item: item.symbol)
        return SchwabPositionsSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            positions=positions,
        )

    def load_orders_snapshot(self) -> SchwabOrdersSnapshot:
        if not self.orders_path:
            raise FixtureFormatError("orders fixture path required")
        data = _load_json(self.orders_path)
        if not isinstance(data, list):
            raise FixtureFormatError("orders fixture must be a list")
        orders: list[SchwabOrder] = []
        for entry in data:
            if not isinstance(entry, dict):
                raise FixtureFormatError("orders entry must be an object")
            order_id = _coerce_str(entry.get("order_id"))
            if not order_id:
                raise FixtureFormatError("orders entry missing order_id")
            symbol = normalize_symbol(entry.get("symbol"))
            if not symbol:
                raise FixtureFormatError("orders entry missing symbol")
            qty = _coerce_qty(entry.get("qty"), context=f"orders {symbol}")
            filled_qty_raw = entry.get("filled_qty")
            orders.append(
                SchwabOrder(
                    book_id=self.book_id,
                    as_of_utc=self.as_of_utc,
                    order_id=order_id,
                    symbol=symbol,
                    side=normalize_side(entry.get("side")),
                    qty=parse_decimal(qty) or parse_decimal("0"),
                    filled_qty=parse_decimal(filled_qty_raw),
                    status=_coerce_str(entry.get("status")),
                    submitted_at=_coerce_str(entry.get("submitted_at")),
                    filled_at=_coerce_str(entry.get("filled_at")),
                )
            )
        orders.sort(key=lambda item: (item.symbol, item.order_id))
        return SchwabOrdersSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            orders=orders,
        )

    def load_all_snapshots(
        self,
    ) -> tuple[SchwabBalanceSnapshot, SchwabPositionsSnapshot, SchwabOrdersSnapshot]:
        return (
            self.load_balance_snapshot(),
            self.load_positions_snapshot(),
            self.load_orders_snapshot(),
        )

    def fixture_paths(self) -> list[str]:
        paths: list[str] = []
        for path in (self.balances_path, self.positions_path, self.orders_path):
            if path is not None:
                paths.append(str(path))
        return paths
