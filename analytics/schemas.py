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
