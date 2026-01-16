"""
Execution V2 – Order Construction Helpers

Responsibilities:
- Build marketable limit orders with bounded slippage
- Apply light randomization to reduce determinism
- Generate idempotency keys (caller persists via StateStore)

NO broker submission happens here.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Literal


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class OrderSpec:
    symbol: str
    side: Side
    qty: int
    limit_price: float
    tif: str                  # e.g., "day"
    idempotency_key: str


@dataclass(frozen=True)
class SlippageConfig:
    # Maximum slippage allowed, expressed as percent of reference price
    max_slippage_pct: float = 0.25    # 0.25%

    # Randomization band within the cap (uniform)
    randomization_pct: float = 0.10   # ±0.10%


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def generate_idempotency_key(
    symbol: str,
    side: Side,
    qty: int,
    ref_price: float,
    ts_bucket_sec: int = 60,
) -> str:
    """
    Generate a stable idempotency key within a time bucket.
    Prevents duplicate orders on restarts while allowing retries later.
    """
    bucket = int(time.time() // ts_bucket_sec)
    raw = f"{symbol}|{side}|{qty}|{round(ref_price,4)}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


def build_marketable_limit(
    *,
    symbol: str,
    side: Side,
    qty: int,
    ref_price: float,
    cfg: SlippageConfig,
) -> OrderSpec:
    """
    Build a marketable limit order.

    BUY:
      limit = ref_price * (1 + slippage)
    SELL:
      limit = ref_price * (1 - slippage)

    slippage is randomized but capped.
    """
    if qty <= 0:
        raise ValueError("qty must be positive")
    if ref_price <= 0:
        raise ValueError("ref_price must be positive")

    # Random slippage within band
    rand = random.uniform(-cfg.randomization_pct, cfg.randomization_pct)
    slippage = _clamp(rand, -cfg.max_slippage_pct, cfg.max_slippage_pct)

    if side == "buy":
        limit_price = ref_price * (1.0 + abs(slippage))
    elif side == "sell":
        limit_price = ref_price * (1.0 - abs(slippage))
    else:
        raise ValueError(f"Invalid side: {side}")

    key = generate_idempotency_key(symbol, side, qty, ref_price)

    return OrderSpec(
        symbol=symbol,
        side=side,
        qty=int(qty),
        limit_price=round(limit_price, 2),
        tif="day",
        idempotency_key=key,
    )
# Execution V2 placeholder: orders.py
