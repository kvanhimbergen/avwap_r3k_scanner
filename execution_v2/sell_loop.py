"""
Execution V2 – Sell Loop
Evaluates positions for trim / stop logic using R1/R2 levels.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from execution_v2 import buy_loop
from execution_v2.config_types import PositionState, StopMode
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


@dataclass(frozen=True)
class SellLoopConfig:
    candidates_csv: str = "daily_candidates.csv"
    r1_trim_pct: float = 0.5
    r2_trim_pct: float = 0.5
    trail_move_fraction: float = 0.5


def _candidate_map(cfg: SellLoopConfig) -> dict[str, buy_loop.Candidate]:
    candidates = buy_loop.load_candidates(cfg.candidates_csv)
    return {c.symbol: c for c in candidates}


def _measured_move(entry_level: float, r2_level: float) -> float:
    move = r2_level - entry_level
    return move if move > 0 else 0.0


def evaluate_positions(store, trading_client, cfg: SellLoopConfig) -> None:
    """
    Evaluate positions using Shannon-style R1/R2 trims and trailing stops.
    """
    candidates = _candidate_map(cfg)
    if not candidates:
        return

    positions = trading_client.get_all_positions()
    now_ts = time.time()

    for pos in positions:
        symbol = str(pos.symbol).upper()
        candidate = candidates.get(symbol)
        if not candidate:
            continue

        try:
            current_price = float(getattr(pos, "current_price", pos.market_value))
        except Exception:
            continue

        existing = store.get_position(symbol)
        if existing is None:
            stop_price = candidate.stop_loss
            high_water = current_price
            state = PositionState(
                strategy_id=DEFAULT_STRATEGY_ID,
                symbol=symbol,
                size_shares=int(float(pos.qty)),
                avg_price=float(pos.avg_entry_price),
                pivot_level=candidate.entry_level,
                r1_level=candidate.target_r1 or candidate.entry_level,
                r2_level=candidate.target_r2,
                stop_mode=StopMode.OPEN,
                last_update_ts=now_ts,
                stop_price=stop_price,
                high_water=high_water,
                trimmed_r1=False,
                trimmed_r2=False,
            )
        else:
            state = existing
            state.size_shares = int(float(pos.qty))
            state.avg_price = float(pos.avg_entry_price)
            state.last_update_ts = now_ts

        if current_price > state.high_water:
            state.high_water = current_price

        measured_move = _measured_move(state.pivot_level, state.r2_level)
        if measured_move <= 0:
            store.upsert_position(state)
            continue

        if current_price >= state.r1_level and not state.trimmed_r1:
            store.add_trim_intent(symbol, cfg.r1_trim_pct, "r1_trim")
            state.trimmed_r1 = True
            state.stop_price = max(state.stop_price, state.pivot_level)

        if current_price >= state.r2_level and not state.trimmed_r2:
            store.add_trim_intent(symbol, cfg.r2_trim_pct, "r2_trim")
            state.trimmed_r2 = True
            state.stop_mode = StopMode.CAUTION

        if state.trimmed_r2:
            trail_distance = measured_move * cfg.trail_move_fraction
            state.stop_price = max(state.stop_price, state.high_water - trail_distance)

        if current_price <= state.stop_price:
            store.add_trim_intent(symbol, 1.0, "stop_exit")
            state.stop_mode = StopMode.EXITING

        store.upsert_position(state)
