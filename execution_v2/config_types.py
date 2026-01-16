"""
Execution V2 – Canonical Types and Contracts

This file defines the immutable data contracts for the execution engine.
All execution logic must conform to these types.

DO NOT add strategy logic here.
DO NOT add defaults that imply strategy changes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Literal


# -------------------------
# Regime definitions
# -------------------------

class GlobalRegime(Enum):
    OFF = "off"            # No new entries or adds
    DEFENSIVE = "defensive"  # Hold + reduce only
    NORMAL = "normal"        # Full execution allowed


class SymbolRegime(Enum):
    ENTER = "enter"        # Fresh entries allowed
    ADD = "add"            # Adds allowed to existing position
    HOLD_ONLY = "hold_only"  # No new risk


# -------------------------
# Stop / risk state machine
# -------------------------

class StopMode(Enum):
    OPEN = "open"          # Trade behaving normally
    CAUTION = "caution"    # Monitoring invalidation signals
    EXITING = "exiting"    # Exit in progress


# -------------------------
# Execution intent + state
# -------------------------

@dataclass(frozen=True)
class EntryIntent:
    symbol: str
    pivot_level: float
    boh_confirmed_at: float      # epoch seconds
    scheduled_entry_at: float   # epoch seconds (randomized delay)
    size_shares: int


@dataclass
class PositionState:
    symbol: str
    size_shares: int
    avg_price: float
    stop_mode: StopMode
    last_update_ts: float

    # Behavioral tracking
    last_boh_level: Optional[float] = None
    invalidation_count: int = 0

    # Trim tracking
    trimmed_r1: bool = False
    trimmed_r2: bool = False


# -------------------------
# Market context snapshots
# -------------------------

@dataclass(frozen=True)
class MarketContext:
    now_ts: float
    market_open: bool
    entry_window_open: bool      # 09:45–15:30 ET
    global_regime: GlobalRegime

