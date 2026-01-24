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
    strategy_id: str = "default"
    sleeve_id: str = "default"


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
    strategy_id: str = "default"
    sleeve_id: str = "default"


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
    strategy_id: str = "default"
    sleeve_id: str = "default"


@dataclass(frozen=True)
class ReconstructionResult:
    trades: list[Trade]
    open_lots: list[Lot]
    warnings: list[str]
    source_metadata: dict[str, str]


@dataclass(frozen=True)
class DailyAggregate:
    date_ny: str
    trade_count: int
    closed_qty: float
    gross_notional_closed: float
    realized_pnl: Optional[float]
    missing_price_trade_count: int
    fees_total: float
    symbols_traded: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class CumulativeAggregate:
    through_date_ny: str
    trade_count: int
    closed_qty: float
    gross_notional_closed: float
    realized_pnl: Optional[float]
    missing_price_trade_count: int
    fees_total: float
    symbols_traded: list[str]


@dataclass(frozen=True)
class ExitEvent:
    event_id: str
    schema_version: int
    event_type: str
    symbol: str
    position_id: Optional[str]
    trade_id: Optional[str]
    entry_id: Optional[str]
    qty: Optional[float]
    price: Optional[float]
    stop_price: Optional[float]
    stop_basis: Optional[str]
    stop_action: Optional[str]
    reason: Optional[str]
    entry_price: Optional[float]
    entry_ts_utc: Optional[str]
    entry_ts_ny: Optional[str]
    entry_date_ny: Optional[str]
    exit_ts_utc: Optional[str]
    exit_ts_ny: Optional[str]
    exit_date_ny: Optional[str]
    ts_utc: str
    ts_ny: str
    date_ny: str
    source: str
    strategy_id: str
    sleeve_id: str
    metadata: dict


@dataclass(frozen=True)
class ExitIngestResult:
    events: list[ExitEvent]
    warnings: list[str]
    source_metadata: dict[str, str]


@dataclass(frozen=True)
class ExitTrade:
    trade_id: str
    position_id: Optional[str]
    symbol: str
    direction: str
    entry_ts_utc: str
    exit_ts_utc: str
    entry_date_ny: str
    exit_date_ny: str
    qty: float
    entry_price: Optional[float]
    exit_price: Optional[float]
    stop_price: Optional[float]
    stop_basis: Optional[str]
    reason: Optional[str]
    source: str
    strategy_id: str
    sleeve_id: str


@dataclass(frozen=True)
class ExitReconstructionResult:
    trades: list[ExitTrade]
    warnings: list[str]
    source_metadata: dict[str, str]


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    qty: float
    avg_price: Optional[float]
    mark_price: Optional[float]
    notional: float


@dataclass(frozen=True)
class PortfolioSnapshot:
    schema_version: int
    date_ny: str
    run_id: str
    capital: dict[str, Optional[float]]
    gross_exposure: float
    net_exposure: float
    positions: list[PortfolioPosition]
    pnl: dict[str, Optional[float] | list[str]]
    metrics: dict[str, object]
    provenance: dict[str, object]
