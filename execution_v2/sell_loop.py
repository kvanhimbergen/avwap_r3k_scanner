"""
Execution V2 – Sell Loop (Behavioral Risk Management)

PRD constraints enforced:
- NO fixed price or ATR stops
- Risk managed via behavioral invalidation
- Partial exits are CONDITIONAL
- Longs only

This module:
- Evaluates existing positions
- Escalates internal stop_mode state
- Creates conditional trim intents (R1 / R2)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from execution_v2.alerts import send_alert
from execution_v2.boh import Bar10m
from execution_v2.clocks import now_snapshot
from execution_v2.config_types import StopMode
from execution_v2.market_data import MarketData
from execution_v2.state_store import StateStore


@dataclass(frozen=True)
class SellLoopConfig:
    # Conditional trim percentages
    r1_trim_pct: float = 0.30    # 25–35% range, midpoint default
    r2_trim_pct: float = 0.30

    # Extension thresholds (behavioral, not stops)
    climactic_extension_mult: float = 1.8   # relative to pivot→R1 range

    # Min bars required to judge continuation
    min_bars_post_entry: int = 2


def _is_rejection(bar: Bar10m, level: float) -> bool:
    """
    Rejection heuristic:
    - Trades above level but closes back below
    """
    return bar.high > level and bar.close < level


def _failed_continuation(bars: list[Bar10m], level: float) -> bool:
    """
    Failed continuation:
    - Multiple attempts above level with inability to hold
    """
    if len(bars) < 2:
        return False
    return all(b.close < level for b in bars[-2:])


def _climactic_extension(bar: Bar10m, pivot: float, r1: float, cfg: SellLoopConfig) -> bool:
    """
    Detect climactic expansion beyond R1.
    """
    if r1 <= pivot:
        return False
    ext = bar.high - pivot
    base = r1 - pivot
    return ext >= cfg.climactic_extension_mult * base


def evaluate_positions(
    *,
    store: StateStore,
    md: MarketData,
    cfg: SellLoopConfig,
) -> int:
    """
    Main sell-loop evaluation.

    Returns number of actions (state changes or intents).
    """
    snap = now_snapshot()
    if not snap.market_open:
        return 0

    acted = 0

    positions = store.list_positions()
    for pos in positions:
        sym = pos.symbol

        bars = md.get_last_two_closed_10m(sym)
        if len(bars) < 2:
            continue

        last = bars[-1]

        # --- Behavioral invalidation ---
        if pos.stop_mode == StopMode.OPEN:
            if _failed_continuation(bars, pos.pivot_level):
                store.update_stop_mode(sym, StopMode.CAUTION)
                send_alert(
                    title="Behavioral invalidation",
                    message=f"{sym} failed continuation above pivot → TIGHT mode",
                    level="warning",
                    symbol=sym,
                )
                acted += 1
                continue

        # --- R1 conditional trim ---
        if not pos.trimmed_r1:
            if _is_rejection(last, pos.r1_level):
                store.create_trim_intent(
                    symbol=sym,
                    pct=cfg.r1_trim_pct,
                    reason="R1 rejection",
                )
                store.mark_trimmed(sym, "r1")
                send_alert(
                    title="R1 trim scheduled",
                    message=f"{sym} rejection at R1 → trim {int(cfg.r1_trim_pct*100)}%",
                    level="info",
                    symbol=sym,
                )
                acted += 1
                continue

        # --- R2 conditional trim ---
        if pos.trimmed_r1 and not pos.trimmed_r2:
            if _failed_continuation(bars, pos.r2_level) or _climactic_extension(last, pos.pivot_level, pos.r1_level, cfg):
                store.create_trim_intent(
                    symbol=sym,
                    pct=cfg.r2_trim_pct,
                    reason="R2 failure or climactic expansion",
                )
                store.mark_trimmed(sym, "r2")
                send_alert(
                    title="R2 trim scheduled",
                    message=f"{sym} R2 failure / climactic → trim {int(cfg.r2_trim_pct*100)}%",
                    level="info",
                    symbol=sym,
                )
                acted += 1
                continue

    return acted
# Execution V2 placeholder: sell_loop.py
