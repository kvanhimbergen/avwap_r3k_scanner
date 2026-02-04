"""
Execution V2 – Exit and Stop Management

Provides structural stop calculations and stop order reconciliation utilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import Enum
import importlib.util
import os
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from execution_v2.exit_events import (
    ExitEventContext,
    append_exit_event,
    build_exit_event,
    build_exit_event_from_legacy,
)

NY_TZ = ZoneInfo("America/New_York")


def _resolve_api_error() -> type[Exception]:
    try:
        spec = importlib.util.find_spec("alpaca.common.exceptions")
    except ModuleNotFoundError:
        spec = None
    if spec is not None:
        from alpaca.common.exceptions import APIError as AlpacaAPIError

        return AlpacaAPIError

    class APIError(Exception):
        code = None

    return APIError


APIError = _resolve_api_error()


@dataclass
class ExitPositionState:
    symbol: str
    qty: int
    stop_price: Optional[float] = None
    stop_order_id: Optional[str] = None
    stop_basis: Optional[str] = None
    last_stop_update_ts: Optional[float] = None


@dataclass(frozen=True)
class ExitConfig:
    stop_buffer_dollars: float = 0.10
    max_risk_per_share: float = 3.00
    min_intraday_bars: int = 6
    intraday_minutes: int = 5
    intraday_lookback_days: int = 3
    daily_lookback_days: int = 320
    min_stop_delay_seconds: int = 20 * 60
    min_bars_since_entry: int = 4
    min_stop_pct: float = 0.015
    telemetry_source: str = "execution_v2"

    @classmethod
    def from_env(cls) -> "ExitConfig":
        import os

        return cls(
            stop_buffer_dollars=float(os.getenv("STOP_BUFFER_DOLLARS", "0.10")),
            max_risk_per_share=float(os.getenv("MAX_RISK_PER_SHARE_DOLLARS", "3.00")),
            min_intraday_bars=int(os.getenv("EXIT_MIN_INTRADAY_BARS", "6")),
            intraday_minutes=int(os.getenv("EXIT_INTRADAY_MINUTES", "5")),
            intraday_lookback_days=int(os.getenv("EXIT_INTRADAY_LOOKBACK_DAYS", "3")),
            daily_lookback_days=int(os.getenv("EXIT_DAILY_LOOKBACK_DAYS", "320")),
            min_stop_delay_seconds=int(os.getenv("EXIT_MIN_STOP_DELAY_SECONDS", "1200")),
            min_bars_since_entry=int(os.getenv("EXIT_MIN_BARS_SINCE_ENTRY", "4")),
            min_stop_pct=float(os.getenv("EXIT_MIN_STOP_PCT", "0.015")),
            telemetry_source=os.getenv("EXIT_TELEMETRY_SOURCE", "execution_v2"),
        )


class SessionPhase(str, Enum):
    OPEN_NOISE = "OPEN_NOISE"
    EARLY_TREND = "EARLY_TREND"
    NORMAL_SESSION = "NORMAL_SESSION"
    CLOSE_PROTECT = "CLOSE_PROTECT"


def classify_session_phase(ts: datetime) -> SessionPhase:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=NY_TZ)
    ts_ny = ts.astimezone(NY_TZ)
    clock = ts_ny.time()
    if time(9, 30) <= clock < time(9, 45):
        return SessionPhase.OPEN_NOISE
    if time(9, 45) <= clock < time(10, 30):
        return SessionPhase.EARLY_TREND
    if time(10, 30) <= clock < time(15, 30):
        return SessionPhase.NORMAL_SESSION
    if time(15, 30) <= clock < time(16, 0):
        return SessionPhase.CLOSE_PROTECT
    return SessionPhase.OPEN_NOISE


def entry_day_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(NY_TZ).date().isoformat()


def _bar_date_ny(bar) -> Optional[str]:
    ts_value = _get_value(bar, "ts")
    if ts_value is None:
        return None
    if isinstance(ts_value, datetime):
        ts = ts_value
    else:
        try:
            ts = datetime.fromtimestamp(float(ts_value), tz=timezone.utc)
        except Exception:
            return None
    return ts.astimezone(NY_TZ).date().isoformat()


def compute_stop_price(
    daily_bars: list,
    *,
    entry_day: str,
    buffer_dollars: float,
) -> Optional[float]:
    if not daily_bars:
        return None
    eligible = []
    for bar in daily_bars:
        bar_date = _bar_date_ny(bar)
        if bar_date is None or bar_date > entry_day:
            continue
        eligible.append(bar)
    if not eligible:
        eligible = daily_bars
    return compute_daily_swing_low_stop(eligible, stop_buffer_dollars=buffer_dollars)


def validate_risk(entry_price: float, stop_price: float, max_risk_per_share: float) -> bool:
    try:
        entry = float(entry_price)
        stop = float(stop_price)
    except Exception:
        return False
    risk = entry - stop
    if risk <= 0:
        return False
    return risk <= float(max_risk_per_share)


def _get_value(bar, key: str, default: float | None = None) -> float | None:
    if isinstance(bar, dict):
        return bar.get(key, default)
    return getattr(bar, key, default)


def _coerce_timestamp(value: object | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _position_entry_ts(position) -> Optional[datetime]:
    for attr in (
        "entry_ts_utc",
        "entry_ts",
        "entry_time",
        "entry_timestamp",
        "filled_at",
        "created_at",
    ):
        if hasattr(position, attr):
            ts = _coerce_timestamp(getattr(position, attr))
            if ts is not None:
                return ts
    return None


def _bars_since_entry(intraday_bars: list, entry_ts: Optional[datetime]) -> Optional[int]:
    if entry_ts is None:
        return None
    count = 0
    for bar in intraday_bars or []:
        ts_value = _get_value(bar, "ts")
        ts = _coerce_timestamp(ts_value)
        if ts is None:
            continue
        if ts > entry_ts:
            count += 1
    return count


def _stop_distance_pct(entry_price: Optional[float], stop_price: Optional[float]) -> Optional[float]:
    if entry_price is None or stop_price is None:
        return None
    try:
        entry = float(entry_price)
        stop = float(stop_price)
    except Exception:
        return None
    if entry <= 0:
        return None
    return (entry - stop) / entry


def select_stop_candidate(
    *,
    intraday_stop: Optional[float],
    daily_stop: Optional[float],
    existing_stop: Optional[float],
    entry_price: Optional[float],
    entry_ts: Optional[datetime],
    intraday_bars: list,
    now_utc: datetime,
    cfg: ExitConfig,
    phase: SessionPhase,
    symbol: str,
    qty: Optional[float],
    source: str,
    emit_event: Optional[Callable[[dict], None]] = None,
) -> tuple[Optional[float], Optional[str], bool]:
    emit_event = emit_event or (lambda event: None)
    seconds_since_entry = None
    if entry_ts is not None:
        seconds_since_entry = max(0.0, (now_utc - entry_ts).total_seconds())
    bars_since_entry = _bars_since_entry(intraday_bars, entry_ts)

    def _emit_guardrail(event_type: str, *, stop_price: Optional[float], basis: str, metadata: dict) -> None:
        event = build_exit_event(
            event_type=event_type,
            symbol=symbol,
            ts=now_utc,
            qty=qty,
            stop_price=stop_price,
            stop_basis=basis,
            entry_price=entry_price,
            source=source,
            metadata=metadata,
        )
        emit_event(event)

    def _min_stop_ok(stop_price: Optional[float], basis: str) -> bool:
        distance_pct = _stop_distance_pct(entry_price, stop_price)
        if distance_pct is None or distance_pct < float(cfg.min_stop_pct):
            _emit_guardrail(
                "STOP_TOO_CLOSE_SKIPPED",
                stop_price=stop_price,
                basis=basis,
                metadata={
                    "phase": phase.value,
                    "entry_price": entry_price,
                    "candidate_stop": stop_price,
                    "distance_pct": distance_pct,
                    "min_stop_pct": cfg.min_stop_pct,
                },
            )
            return False
        return True

    def _intraday_allowed() -> bool:
        if phase in {SessionPhase.OPEN_NOISE, SessionPhase.CLOSE_PROTECT}:
            return False
        if seconds_since_entry is None or bars_since_entry is None:
            _emit_guardrail(
                "STOP_TOO_EARLY_SKIPPED",
                stop_price=intraday_stop,
                basis="intraday_hl",
                metadata={
                    "phase": phase.value,
                    "seconds_since_entry": seconds_since_entry,
                    "bars_since_entry": bars_since_entry,
                    "min_stop_delay_seconds": cfg.min_stop_delay_seconds,
                    "min_bars_since_entry": cfg.min_bars_since_entry,
                    "reason": "entry_time_missing",
                },
            )
            return False
        if seconds_since_entry < float(cfg.min_stop_delay_seconds) or bars_since_entry < int(
            cfg.min_bars_since_entry
        ):
            _emit_guardrail(
                "STOP_TOO_EARLY_SKIPPED",
                stop_price=intraday_stop,
                basis="intraday_hl",
                metadata={
                    "phase": phase.value,
                    "seconds_since_entry": seconds_since_entry,
                    "bars_since_entry": bars_since_entry,
                    "min_stop_delay_seconds": cfg.min_stop_delay_seconds,
                    "min_bars_since_entry": cfg.min_bars_since_entry,
                },
            )
            return False
        return True

    allow_trailing = phase not in {SessionPhase.OPEN_NOISE, SessionPhase.CLOSE_PROTECT}

    def _select_from(candidates: list[tuple[str, Optional[float]]]) -> tuple[Optional[float], Optional[str]]:
        for basis, stop in candidates:
            if stop is None:
                continue
            if not _min_stop_ok(stop, basis):
                continue
            return stop, basis
        return None, None

    if phase == SessionPhase.OPEN_NOISE:
        return (*_select_from([("daily_swing_low", daily_stop)]), allow_trailing)

    if phase == SessionPhase.CLOSE_PROTECT:
        return None, None, allow_trailing

    if phase == SessionPhase.EARLY_TREND:
        stop, basis = _select_from([("daily_swing_low", daily_stop)])
        if stop is not None:
            return stop, basis, allow_trailing
        if intraday_stop is not None and _intraday_allowed() and _min_stop_ok(
            intraday_stop, "intraday_hl"
        ):
            return intraday_stop, "intraday_hl", allow_trailing
        return None, None, allow_trailing

    if intraday_stop is not None and _intraday_allowed() and _min_stop_ok(
        intraday_stop, "intraday_hl"
    ):
        return intraday_stop, "intraday_hl", allow_trailing

    return (*_select_from([("daily_swing_low", daily_stop)]), allow_trailing)


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

    # Sanity: an intraday higher-low stop must be BELOW the most recent tape.
    # If price has already pulled back below the computed stop, submitting it would trigger immediately.
    try:
        last_close = float(_get_value(bars[-1], "close", None))
    except Exception:
        last_close = None

    stop = round(float(higher_low) - float(stop_buffer_dollars), 2)
    if last_close is not None and stop >= float(last_close):
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


def _order_symbol(order) -> str:
    return str(_order_attr(order, "symbol", "") or "").upper()


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


def _order_timestamp(order) -> Optional[float]:
    raw = _order_attr(order, "submitted_at", None) or _order_attr(order, "created_at", None)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.timestamp()
    try:
        value = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def _stop_selection_enabled() -> bool:
    return os.getenv("EXIT_STOP_SELECTION_V2", "0").strip() == "1"


def _select_preferred_stop_order(
    orders: list,
    *,
    desired_qty: Optional[int],
    desired_stop: Optional[float],
):
    if not orders:
        return None

    def _key(order) -> tuple[float, float, float]:
        qty = _order_qty(order)
        if desired_qty is None:
            qty_diff = float("inf")
        else:
            qty_diff = abs(qty - int(desired_qty))
        ts = _order_timestamp(order)
        ts_rank = -ts if ts is not None else float("inf")
        stop_price = _order_stop_price(order)
        if desired_stop is None or stop_price is None:
            stop_diff = float("inf")
        else:
            stop_diff = abs(stop_price - float(desired_stop))
        return (qty_diff, ts_rank, stop_diff)

    return sorted(orders, key=_key)[0]


def _is_open_status(status: str) -> bool:
    s = str(status or "").strip().lower()
    # normalize enum-ish strings: "OrderStatus.NEW" -> "new"
    if "." in s:
        s = s.split(".")[-1]
    # alpaca sometimes uses variants like "pending_new"
    return s in {"open", "accepted", "new", "pending_new", "partially_filled"}


def _matching_stop_order(order, desired_symbol: str, desired_qty: int, desired_stop: float) -> bool:
    if _order_symbol(order) != str(desired_symbol or "").upper():
        return False
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
    from alpaca.trading.requests import StopOrderRequest

    return trading_client.submit_order(
        StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(float(stop_price), 2),
        )
    )


def _get_open_orders_for_symbol(trading_client, symbol: str):
    """Best-effort: fetch OPEN orders for a single symbol.

    Critical: Alpaca get_orders() can be limited/paginated when unfiltered,
    which can cause us to miss the stop order that is holding shares.
    """
    sym = str(symbol or "").upper()
    if not sym:
        return []
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        # limit is important to avoid missing older-but-still-open orders
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, symbols=[sym], limit=500)
        try:
            return list(trading_client.get_orders(filter=req))
        except TypeError:
            # some client versions accept request directly
            return list(trading_client.get_orders(req))
    except Exception:
        # Fallback: local filtering (may still be limited by API defaults)
        try:
            orders = list(trading_client.get_orders())
        except Exception:
            return []
        out = []
        for o in orders:
            try:
                if _order_symbol(o) != sym:
                    continue
                if not _is_open_status(_order_status(o)):
                    continue
                out.append(o)
            except Exception:
                continue
        return out

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

    open_orders = _get_open_orders_for_symbol(trading_client, state.symbol)
    sell_orders = [o for o in open_orders if _order_side(o) == "sell" and _is_open_status(_order_status(o)) and _order_symbol(o) == state.symbol.upper()]

    matching_orders = [
        order
        for order in sell_orders
        if _matching_stop_order(order, state.symbol, desired_qty, desired_stop)
    ]
    if matching_orders:
        preferred = matching_orders[0]
        if _stop_selection_enabled() and len(matching_orders) > 1:
            preferred = _select_preferred_stop_order(
                matching_orders,
                desired_qty=desired_qty,
                desired_stop=desired_stop,
            ) or preferred
        state.stop_order_id = str(_order_attr(preferred, "id", "")) or state.stop_order_id
        return state

    mismatched_stops = [
        o
        for o in sell_orders
        if _order_type(o) in {"stop", "stop_limit"}
        and not _matching_stop_order(o, state.symbol, desired_qty, desired_stop)
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
        open_orders = _get_open_orders_for_symbol(trading_client, state.symbol)
        sell_orders = [o for o in open_orders if _order_side(o) == "sell" and _is_open_status(_order_status(o)) and _order_symbol(o) == state.symbol.upper()]

    for order in sell_orders:
        if _matching_stop_order(order, state.symbol, desired_qty, desired_stop):
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
        stop_holding_orders = [o for o in holding_orders if _order_type(o) in {"stop", "stop_limit"}]
        if stop_holding_orders:
            preferred = stop_holding_orders[0]
            if _stop_selection_enabled() and len(stop_holding_orders) > 1:
                preferred = _select_preferred_stop_order(
                    stop_holding_orders,
                    desired_qty=desired_qty,
                    desired_stop=desired_stop,
                ) or preferred
            state.stop_order_id = str(_order_attr(preferred, "id", "")) or state.stop_order_id
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


def _read_existing_stop(
    trading_client,
    symbol: str,
    *,
    desired_qty: Optional[int] = None,
    desired_stop: Optional[float] = None,
) -> Optional[float]:
    try:
        orders = _get_open_orders_for_symbol(trading_client, symbol)
    except Exception:
        return None
    stop_orders = []
    for order in orders:
        if _order_side(order) != "sell":
            continue
        if not _is_open_status(_order_status(order)):
            continue
        if _order_type(order) not in {"stop", "stop_limit"}:
            continue
        if str(_order_attr(order, "symbol", "")).upper() != symbol.upper():
            continue
        stop_orders.append(order)
    if not stop_orders:
        return None
    if _stop_selection_enabled() and len(stop_orders) > 1:
        preferred = _select_preferred_stop_order(
            stop_orders,
            desired_qty=desired_qty,
            desired_stop=desired_stop,
        )
        if preferred is None:
            return None
        return _order_stop_price(preferred)
    return _order_stop_price(stop_orders[0])


def manage_positions(
    *,
    trading_client,
    md,
    cfg: ExitConfig,
    repo_root,
    dry_run: bool,
    log: Callable[[str], None] | None = None,
) -> None:
    log = log or (lambda msg: None)
    try:
        positions = list(trading_client.get_all_positions())
    except Exception as exc:
        log(f"EXIT: positions unavailable ({type(exc).__name__}: {exc})")
        return

    for pos in positions:
        symbol = str(getattr(pos, "symbol", "")).upper()
        if not symbol:
            continue

        try:
            qty = int(float(getattr(pos, "qty", 0)))
        except Exception:
            continue
        if qty <= 0:
            continue

        try:
            avg_entry = float(getattr(pos, "avg_entry_price", 0))
        except Exception:
            avg_entry = None

        intraday_bars = md.get_intraday_bars(
            symbol,
            minutes=cfg.intraday_minutes,
            lookback_days=cfg.intraday_lookback_days,
        )
        daily_bars = md.get_daily_bars(symbol, lookback_days=cfg.daily_lookback_days)
        intraday_stop = compute_intraday_higher_low_stop(
            intraday_bars,
            stop_buffer_dollars=cfg.stop_buffer_dollars,
            min_bars=cfg.min_intraday_bars,
        )
        daily_stop = compute_daily_swing_low_stop(
            daily_bars,
            stop_buffer_dollars=cfg.stop_buffer_dollars,
        )

        existing_stop = _read_existing_stop(
            trading_client,
            symbol,
            desired_qty=qty,
            desired_stop=candidate_stop,
        )
        now_utc = datetime.now(timezone.utc)
        entry_ts = _position_entry_ts(pos)
        phase = classify_session_phase(now_utc)

        def _safe_append(event: dict) -> None:
            try:
                append_exit_event(repo_root, event)
            except Exception as exc:
                log(f"EXIT: telemetry append failed ({type(exc).__name__}: {exc})")

        candidate_stop, stop_basis, allow_trailing = select_stop_candidate(
            intraday_stop=intraday_stop,
            daily_stop=daily_stop,
            existing_stop=existing_stop,
            entry_price=avg_entry,
            entry_ts=entry_ts,
            intraday_bars=intraday_bars,
            now_utc=now_utc,
            cfg=cfg,
            phase=phase,
            symbol=symbol,
            qty=float(qty),
            source=cfg.telemetry_source,
            emit_event=_safe_append,
        )

        if allow_trailing:
            desired_stop = apply_trailing_stop(existing_stop, candidate_stop)
        else:
            desired_stop = existing_stop if existing_stop is not None else candidate_stop
        if desired_stop is None:
            continue
        # --- Guardrails: never place a sell stop at/above the tape; initial stop must be below entry ---
        try:
            current_price = float(getattr(pos, "current_price", 0) or 0)
        except Exception:
            current_price = 0.0

        # Guardrail A: stop must be strictly below current market price (or it will trigger immediately)
        if current_price > 0 and float(desired_stop) >= current_price:
            event = build_exit_event(
                event_type="STOP_INVALID_SKIPPED",
                symbol=symbol,
                qty=float(qty),
                stop_price=desired_stop,
                stop_basis=stop_basis,
                stop_action="skip>=current",
                entry_price=avg_entry,
                source=cfg.telemetry_source,
            )
            try:
                append_exit_event(repo_root, event)
            except Exception as exc:
                log(f"EXIT: telemetry append failed ({type(exc).__name__}: {exc})")
            log(
                f"EXIT: skip invalid stop {symbol} qty={qty} "
                f"stop={desired_stop} >= current={current_price} basis={stop_basis}"
            )
            continue

        # Guardrail B: if we're creating the initial stop, it must be below entry
        if existing_stop is None and avg_entry is not None:
            try:
                if float(desired_stop) >= float(avg_entry):
                    event = build_exit_event(
                        event_type="STOP_INVALID_SKIPPED",
                        symbol=symbol,
                        qty=float(qty),
                        stop_price=desired_stop,
                        stop_basis=stop_basis,
                        stop_action="skip>=entry",
                        entry_price=avg_entry,
                        source=cfg.telemetry_source,
                    )
                    try:
                        append_exit_event(repo_root, event)
                    except Exception as exc:
                        log(f"EXIT: telemetry append failed ({type(exc).__name__}: {exc})")
                    log(
                        f"EXIT: skip invalid initial stop {symbol} qty={qty} "
                        f"stop={desired_stop} >= entry={avg_entry} basis={stop_basis}"
                    )
                    continue
            except Exception:
                pass


        context = ExitEventContext(
            symbol=symbol,
            qty=float(qty),
            entry_price=avg_entry,
        )
        if existing_stop is None:
            event = build_exit_event(
                event_type="STOP_RESOLVED",
                symbol=symbol,
                qty=float(qty),
                stop_price=desired_stop,
                stop_basis=stop_basis,
                stop_action="initial",
                entry_price=avg_entry,
                source=cfg.telemetry_source,
            )
            _safe_append(event)
        elif desired_stop > float(existing_stop):
            event = build_exit_event(
                event_type="STOP_RATCHET",
                symbol=symbol,
                qty=float(qty),
                stop_price=desired_stop,
                stop_basis=stop_basis,
                stop_action="ratchet",
                entry_price=avg_entry,
                source=cfg.telemetry_source,
            )
            _safe_append(event)

        if dry_run:
            log(f"DRY_RUN: would reconcile stop {symbol} qty={qty} stop={desired_stop}")
            continue

        def _append_legacy(event: dict) -> None:
            wrapped = build_exit_event_from_legacy(
                event,
                symbol=symbol,
                source=cfg.telemetry_source,
                context=context,
            )
            _safe_append(wrapped)

        state = ExitPositionState(symbol=symbol, qty=qty, stop_price=existing_stop)
        try:
            reconcile_stop_order(
                trading_client=trading_client,
                state=state,
                desired_qty=qty,
                desired_stop=desired_stop,
                log=log,
                append_event=_append_legacy,
            )
        except Exception as exc:
            log(f"EXIT: reconcile failed for {symbol} ({type(exc).__name__}: {exc})")
