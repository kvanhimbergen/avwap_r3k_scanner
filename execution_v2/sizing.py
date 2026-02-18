"""
Execution V2 – Position Sizing (Volatility Proxy Based)

Principles:
- No fixed price or ATR stops
- Size scaled by extension / volatility proxy
- Hard cap per position as % of account equity
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SizingConfig:
    # Max capital per position (account-level cap)
    max_position_pct: float = 0.10   # 10% of equity

    # Base sizing multiplier
    base_risk_pct: float = 0.02      # 2% reference risk unit

    # Extension penalty
    max_dist_pct: float = 6.0        # scanner already enforces this for ENTER


def compute_size_shares(
    *,
    account_equity: float,
    price: float,
    dist_pct: float,
    cfg: SizingConfig,
    atr_pct: Optional[float] = None,
    correlation_penalty: float = 0.0,
) -> int:
    """
    Returns integer share quantity.

    dist_pct and atr_pct are used as volatility proxies.
    Larger extension => smaller size.

    correlation_penalty: float in [0, 1). Reduces allocation by (1 - penalty).
    Default 0.0 preserves backward compatibility.
    """
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")

    # Volatility proxy
    vol_proxy = dist_pct
    if atr_pct is not None and atr_pct > 0:
        vol_proxy = max(dist_pct, atr_pct)

    # Normalize volatility against max_dist_pct
    norm = min(vol_proxy / cfg.max_dist_pct, 1.0)

    # Risk scaler: more extended => smaller allocation
    risk_scale = max(0.25, 1.0 - norm)

    # Clamp correlation penalty to valid range
    corr_pen = max(0.0, min(float(correlation_penalty), 1.0))

    # Dollar allocation
    dollar_alloc = account_equity * cfg.base_risk_pct * risk_scale * (1.0 - corr_pen)

    # Hard cap
    max_dollars = account_equity * cfg.max_position_pct
    dollar_alloc = min(dollar_alloc, max_dollars)

    shares = int(dollar_alloc // price)
    return max(shares, 0)
# Execution V2 placeholder: sizing.py
