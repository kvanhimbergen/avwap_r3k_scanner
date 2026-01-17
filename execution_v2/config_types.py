"""
Execution V2 – Canonical Types and Contracts

Defines immutable data contracts for execution engine.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# -------------------------
# Global regime
# -------------------------
class GlobalRegime(Enum):
    OFF = "off"
    DEFENSIVE = "defensive"
    NORMAL = "normal"

# -------------------------
# Symbol regime
# -------------------------
class SymbolRegime(Enum):
    ENTER = "enter"
    ADD = "add"
    HOLD_ONLY = "hold_only"

# -------------------------
# Stop / risk mode
# -------------------------
class StopMode(Enum):
    OPEN = "open"
    CAUTION = "caution"
    EXITING = "exiting"
    UNKNOWN = "unknown"

# -------------------------
# Entry intent
# -------------------------
@dataclass(frozen=True)
class EntryIntent:
    symbol: str
    pivot_level: float
    boh_confirmed_at: float
    scheduled_entry_at: float
    size_shares: int

# -------------------------
# Position state
# -------------------------
@dataclass
class PositionState:
    symbol: str
    size_shares: int
    avg_price: float
    pivot_level: float
    r1_level: float
    r2_level: float
    stop_mode: StopMode
    last_update_ts: float
    last_boh_level: Optional[float] = None
    invalidation_count: int = 0
    trimmed_r1: bool = False
    trimmed_r2: bool = False

# -------------------------
# Market context
# -------------------------
@dataclass(frozen=True)
class MarketContext:
    now_ts: float
    market_open: bool
    entry_window_open: bool
    global_regime: GlobalRegime

