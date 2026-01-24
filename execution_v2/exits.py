"""
Execution V2 – Exit and Stop Management

Provides structural stop calculations and stop order reconciliation utilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import importlib.util
from typing import Callable, Optional

if importlib.util.find_spec("alpaca.common.exceptions") is not None:
    from alpaca.common.exceptions import APIError
else:
    class APIError(Exception):
        code = None


@dataclass
class ExitPositionState:
    symbol: str
    qty: int
    stop_price: Optional[float] = None
    stop_order_id: Optional[str] = None
    stop_basis: Optional[str] = None
    last_stop_update_ts: Optional[float] = None


def _get_value(bar, key: str, default: float | None = None) -> float | None:
    if isinstance(bar, dict):
        return bar.get(key, default)
    return getattr(bar, key, default)


def _find_swing_lows(bars: list, *, low_key: str = "low") -> list[tuple[int, float]]:
    """
    A swing low index i satisfies low[i] < low[i-1] and low[i] < low[i+1].
    Return list of (i, low_value) in chronological order.
    """
    swing_lows: list[tuple[int, float]] = []
    for i in range(1, len(bars) - 1):
        low_prev = _get_value(bars[i - 1], low_key)
        low_curr = _get_value(bars[i], low_key)
        low_next = _get_value(bars[i + 1], low_key)
        if low_prev is None or low_curr is None or low_next is None:
            continue
        if low_curr < low_prev and low_curr < low_next:
            swing_lows.append((i, float(low_curr)))
    return swing_lows


def compute_intraday_higher_low_stop(
    bars: list,
    *,
    stop_buffer_dollars: float,
    min_bars: int = 6,
) -> Optional[float]:
    """
    Determine most recent CONFIRMED higher low:
    - need at least min_bars total
    - compute swing lows
    - choose the most recent swing low whose low is higher than the previous swing low (a higher-low step)
    - stop = round(higher_low - stop_buffer_dollars, 2)
    Return None if no such structure.
    """
    if len(bars) < min_bars:
        return None

    swing_lows = _find_swing_lows(bars)
    if len(swing_lows) < 2:
        return None

    higher_low = None
    for i in range(1, len(swing_lows)):
        prev_low = swing_lows[i - 1][1]
        curr_low = swing_lows[i][1]
        if curr_low > prev_low:
            higher_low = curr_low

    if higher_low is None:
        return None

    return round(float(higher_low) - float(stop_buffer_dollars), 2)


def compute_daily_swing_low_stop(
    bars: list,
    *,
    stop_buffer_dollars: float,
) -> Optional[float]:
    swing_lows = _find_swing_lows(bars)
    if not swing_lows:
        return None
    return round(float(swing_lows[-1][1]) - float(stop_buffer_dollars), 2)


def resolve_structural_stop(
    intraday_bars: list,
    daily_bars: list,
    *,
    stop_buffer_dollars: float,
    min_intraday_bars: int = 6,
) -> tuple[Optional[float], Optional[str]]:
    intraday_stop = compute_intraday_higher_low_stop(
        intraday_bars,
        stop_buffer_dollars=stop_buffer_dollars,
        min_bars=min_intraday_bars,
    )
    if intraday_stop is not None:
        return intraday_stop, "intraday_hl"

    daily_stop = compute_daily_swing_low_stop(
        daily_bars,
        stop_buffer_dollars=stop_buffer_dollars,
    )
    if daily_stop is not None:
        return daily_stop, "daily_swing_low"

    return None, None


def apply_trailing_stop(
    existing_stop: Optional[float],
    candidate_stop: Optional[float],
) -> Optional[float]:
    if candidate_stop is None:
        return existing_stop
    if existing_stop is None:
        return candidate_stop
    return max(existing_stop, candidate_stop)


def _order_attr(order, name: str, default=None):
    if isinstance(order, dict):
        return order.get(name, default)
    return getattr(order, name, default)


def _order_status(order) -> str:
    return str(_order_attr(order, "status", "") or "").lower()


def _order_side(order) -> str:
    return str(_order_attr(order, "side", "") or "").lower()


def _order_type(order) -> str:
    return str(_order_attr(order, "order_type", _order_attr(order, "type", "")) or "").lower()


def _order_qty(order) -> int:
    raw = _order_attr(order, "qty", 0)
    try:
        return int(float(raw))
    except Exception:
        return 0


def _order_stop_price(order) -> Optional[float]:
    raw = _order_attr(order, "stop_price", None)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _is_open_status(status: str) -> bool:
    return status in {"open", "accepted", "new"}


def _matching_stop_order(order, desired_qty: int, desired_stop: float) -> bool:
    if _order_side(order) != "sell":
        return False
    if not _is_open_status(_order_status(order)):
        return False
    if _order_type(order) not in {"stop", "stop_limit"}:
        return False
    if _order_qty(order) != int(desired_qty):
        return False
    stop_price = _order_stop_price(order)
    if stop_price is None:
        return False
    return round(stop_price, 2) == round(float(desired_stop), 2)


def _api_error_is_insufficient_qty(exc: APIError) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    if code is not None:
        try:
            if int(code) == 40310000:
                return True
        except Exception:
            pass
    return "insufficient qty available" in str(exc).lower()


def _submit_stop_order(trading_client, symbol: str, qty: int, stop_price: float):
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import StopLossRequest, MarketOrderRequest

    return trading_client.submit_order(
        MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            order_class=None,
            stop_loss=StopLossRequest(stop_price=round(float(stop_price), 2)),
        )
    )


def reconcile_stop_order(
    *,
    trading_client,
    state: ExitPositionState,
    desired_qty: int,
    desired_stop: float,
    log: Callable[[str], None] | None = None,
    append_event: Callable[[dict], None] | None = None,
) -> ExitPositionState:
    log = log or (lambda msg: None)
    append_event = append_event or (lambda event: None)

    open_orders = list(trading_client.get_orders())
    sell_orders = [o for o in open_orders if _order_side(o) == "sell" and _is_open_status(_order_status(o))]

    for order in sell_orders:
        if _matching_stop_order(order, desired_qty, desired_stop):
            state.stop_order_id = str(_order_attr(order, "id", "")) or state.stop_order_id
            return state

    mismatched_stops = [
        o
        for o in sell_orders
        if _order_type(o) in {"stop", "stop_limit"}
        and not _matching_stop_order(o, desired_qty, desired_stop)
    ]
    for order in mismatched_stops:
        order_id = _order_attr(order, "id", None)
        if order_id is None:
            continue
        try:
            trading_client.cancel_order_by_id(order_id)
        except Exception:
            continue

    if mismatched_stops:
        open_orders = list(trading_client.get_orders())
        sell_orders = [o for o in open_orders if _order_side(o) == "sell" and _is_open_status(_order_status(o))]

    for order in sell_orders:
        if _matching_stop_order(order, desired_qty, desired_stop):
            state.stop_order_id = str(_order_attr(order, "id", "")) or state.stop_order_id
            return state

    holding_orders = [
        o for o in sell_orders
        if _order_qty(o) >= int(desired_qty)
    ]
    if holding_orders:
        related = [
            {
                "id": str(_order_attr(o, "id", "")),
                "side": _order_side(o),
                "type": _order_type(o),
                "qty": _order_qty(o),
            }
            for o in holding_orders
        ]
        log(
            f"STOP_SKIP_HELD {state.symbol}: existing sell order holds qty; not submitting new stop"
        )
        append_event(
            {
                "event": "STOP_SKIP_HELD",
                "symbol": state.symbol,
                "related_orders": related,
            }
        )
        for order in holding_orders:
            if _order_type(order) in {"stop", "stop_limit"}:
                state.stop_order_id = str(_order_attr(order, "id", "")) or state.stop_order_id
                break
        return state

    try:
        order = _submit_stop_order(trading_client, state.symbol, desired_qty, desired_stop)
    except APIError as exc:
        if _api_error_is_insufficient_qty(exc):
            related_orders = [
                {
                    "id": str(_order_attr(o, "id", "")),
                    "side": _order_side(o),
                    "type": _order_type(o),
                    "qty": _order_qty(o),
                }
                for o in sell_orders
            ]
            append_event(
                {
                    "event": "STOP_SUBMIT_BLOCKED",
                    "symbol": state.symbol,
                    "reason": str(exc),
                    "related_orders": related_orders,
                }
            )
            log(f"STOP_SUBMIT_BLOCKED {state.symbol}: {exc}")
            return state
        raise

    order_id = _order_attr(order, "id", None)
    if order_id:
        state.stop_order_id = str(order_id)
    state.stop_price = desired_stop
    state.last_stop_update_ts = datetime.utcnow().timestamp()
    return state
