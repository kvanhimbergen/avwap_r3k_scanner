from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Fill:
    fill_id: str
    venue: str
    order_id: str
    symbol: str
    side: str
    qty: float
    price: Optional[float]
    fees: float
    ts_utc: str
    ts_ny: str
    date_ny: str
    source_path: str
    raw_json: Optional[str]


@dataclass(frozen=True)
class IngestResult:
    fills: list[Fill]
    warnings: list[str]
    source_metadata: dict[str, str]


@dataclass(frozen=True)
class Lot:
    lot_id: str
    symbol: str
    side: str
    open_fill_id: str
    open_ts_utc: str
    open_date_ny: str
    open_qty: float
    open_price: Optional[float]
    remaining_qty: float
    venue: str
    source_paths: list[str]


@dataclass(frozen=True)
class Trade:
    trade_id: str
    symbol: str
    direction: str
    open_fill_id: str
    close_fill_id: str
    open_ts_utc: str
    close_ts_utc: str
    open_date_ny: str
    close_date_ny: str
    qty: float
    open_price: Optional[float]
    close_price: Optional[float]
    fees: float
    venue: str
    notes: Optional[str]


@dataclass(frozen=True)
class ReconstructionResult:
    trades: list[Trade]
    open_lots: list[Lot]
    warnings: list[str]
    source_metadata: dict[str, str]
