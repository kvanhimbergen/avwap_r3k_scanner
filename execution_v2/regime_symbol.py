"""
Execution V2 – Symbol Regime Gate (ENTER / ADD / HOLD_ONLY)

Inputs are derived from the daily_candidates.csv output (watchlist):
- AVWAP_Floor (price reference)
- Dist% (distance from AVWAP in percent)
Optionally from scanner outputs if available elsewhere:
- AVWAP_Slope

This module is PURE and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from execution_v2.config_types import SymbolRegime


@dataclass(frozen=True)
class SymbolRegimeConfig:
    # Minimum acceptable AVWAP slope for longs (buyers reasserting control).
    # Repo config shows MIN_AVWAP_SLOPE_LONG often slightly negative; keep explicit.
    min_avwap_slope_long: float = -0.03

    # Extension cap: avoid excessively extended names (durability / slippage control).
    # Uses daily_candidates.csv "Dist%" field.
    max_dist_pct_for_enter: float = 6.0

    # Adds can tolerate slightly more extension (still capped).
    max_dist_pct_for_add: float = 8.0


@dataclass(frozen=True)
class SymbolInputs:
    symbol: str
    dist_pct: float                 # from daily_candidates.csv Dist%
    avwap_slope: Optional[float]    # may be None if not provided
    has_position: bool


def classify_symbol_regime(x: SymbolInputs, cfg: SymbolRegimeConfig) -> SymbolRegime:
    """
    Classification:
    - If extension too large -> HOLD_ONLY
    - If AVWAP slope provided and below threshold -> HOLD_ONLY (no new risk)
    - Else:
        - if has_position -> ADD
        - else -> ENTER
    """
    # Extension gate
    if not x.has_position:
        if x.dist_pct > cfg.max_dist_pct_for_enter:
            return SymbolRegime.HOLD_ONLY
    else:
        if x.dist_pct > cfg.max_dist_pct_for_add:
            return SymbolRegime.HOLD_ONLY

    # AVWAP slope gate (if available)
    if x.avwap_slope is not None and x.avwap_slope < cfg.min_avwap_slope_long:
        return SymbolRegime.HOLD_ONLY

    return SymbolRegime.ADD if x.has_position else SymbolRegime.ENTER
# Execution V2 placeholder: regime_symbol.py
