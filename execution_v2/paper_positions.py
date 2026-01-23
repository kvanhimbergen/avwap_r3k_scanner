"""
Execution V2 – Paper Simulation Positions
"""

from __future__ import annotations

from typing import Iterable


def positions_from_fills(fills: Iterable[dict]) -> dict[str, dict]:
    positions: dict[str, dict] = {}
    for fill in fills:
        symbol = str(fill.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        qty = int(fill.get("qty", 0) or 0)
        if qty == 0:
            continue
        side = str(fill.get("side", "BUY")).upper()
        price = float(fill.get("price", 0.0) or 0.0)

        if symbol not in positions:
            positions[symbol] = {"qty": 0, "avg_cost": 0.0}

        pos = positions[symbol]
        current_qty = int(pos["qty"])
        current_avg = float(pos["avg_cost"])

        if side == "SELL":
            new_qty = current_qty - qty
            if new_qty <= 0:
                pos["qty"] = 0
                pos["avg_cost"] = 0.0
            else:
                pos["qty"] = new_qty
            continue

        new_qty = current_qty + qty
        if new_qty <= 0:
            pos["qty"] = 0
            pos["avg_cost"] = 0.0
            continue

        weighted_cost = (current_qty * current_avg) + (qty * price)
        pos["qty"] = new_qty
        pos["avg_cost"] = weighted_cost / new_qty

    return positions


def mark_to_market(positions: dict[str, dict], price_map: dict[str, float]) -> dict[str, dict]:
    marked: dict[str, dict] = {}
    for symbol, pos in positions.items():
        qty = int(pos.get("qty", 0) or 0)
        avg_cost = float(pos.get("avg_cost", 0.0) or 0.0)
        mark_price = price_map.get(symbol)
        unrealized = None
        if mark_price is not None:
            unrealized = (float(mark_price) - avg_cost) * qty
        marked[symbol] = {
            "qty": qty,
            "avg_cost": avg_cost,
            "mark_price": mark_price,
            "unrealized_pnl": unrealized,
        }
    return marked
