"""
Execution V2 – Exit Management (system-managed R1/R2 + protective stop)

Responsibilities:
- Compute DAILY swing-low stop anchors (L=5)
- Build per-position exit state and persist to JSON
- Manage protective stop + R1/R2 exits via polling loop
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Optional

from execution_v2.clocks import ET
from execution_v2.pivots import DailyBar


STOP_SUBMIT_AFTER = time(9, 35)


@dataclass(frozen=True)
class ExitConfig:
    stop_buffer_dollars: float
    r1_mult: float
    r2_mult: float
    r1_trim_pct: float
    max_risk_per_share: float

    @staticmethod
    def from_env() -> "ExitConfig":
        return ExitConfig(
            stop_buffer_dollars=float(os.getenv("STOP_BUFFER_DOLLARS", "0.10")),
            r1_mult=float(os.getenv("R1_MULT", "1.0")),
            r2_mult=float(os.getenv("R2_MULT", "2.0")),
            r1_trim_pct=float(os.getenv("R1_TRIM_PCT", "0.5")),
            max_risk_per_share=float(os.getenv("MAX_RISK_PER_SHARE_DOLLARS", "3.00")),
        )


@dataclass
class ExitPositionState:
    symbol: str
    entry_time: float
    entry_price: float
    entry_qty: int
    stop_price: float
    stop_order_id: Optional[str]
    r_value: float
    r1_price: float
    r2_price: float
    r1_qty: int
    r2_qty: int
    stage: str
    qty_remaining: int

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "entry_qty": self.entry_qty,
            "stop_price": self.stop_price,
            "stop_order_id": self.stop_order_id,
            "r_value": self.r_value,
            "r1_price": self.r1_price,
            "r2_price": self.r2_price,
            "r1_qty": self.r1_qty,
            "r2_qty": self.r2_qty,
            "stage": self.stage,
            "qty_remaining": self.qty_remaining,
        }

    @staticmethod
    def from_dict(data: dict) -> "ExitPositionState":
        return ExitPositionState(
            symbol=str(data.get("symbol", "")),
            entry_time=float(data.get("entry_time", 0.0)),
            entry_price=float(data.get("entry_price", 0.0)),
            entry_qty=int(data.get("entry_qty", 0)),
            stop_price=float(data.get("stop_price", 0.0)),
            stop_order_id=data.get("stop_order_id"),
            r_value=float(data.get("r_value", 0.0)),
            r1_price=float(data.get("r1_price", 0.0)),
            r2_price=float(data.get("r2_price", 0.0)),
            r1_qty=int(data.get("r1_qty", 0)),
            r2_qty=int(data.get("r2_qty", 0)),
            stage=str(data.get("stage", "OPEN")),
            qty_remaining=int(data.get("qty_remaining", 0)),
        )


class PositionStateStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.base_dir / f"{symbol.upper()}.json"

    def load(self, symbol: str) -> Optional[ExitPositionState]:
        path = self._path(symbol)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except Exception:
            return None
        return ExitPositionState.from_dict(data)

    def save(self, state: ExitPositionState) -> None:
        path = self._path(state.symbol)
        path.write_text(json.dumps(state.to_dict(), sort_keys=True, indent=2))

    def delete(self, symbol: str) -> None:
        path = self._path(symbol)
        if path.exists():
            path.unlink(missing_ok=True)


def resolve_state_dir(repo_root: Path) -> Path:
    return repo_root / "state" / "positions"


def resolve_event_ledger(repo_root: Path) -> Path:
    return repo_root / "state" / "positions" / "events.jsonl"


def append_event(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts_utc": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def entry_day_from_ts(ts: float) -> datetime.date:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET).date()


def prior_swing_low(
    bars: list[DailyBar],
    entry_day,
    pivot_len: int = 5,
) -> Optional[float]:
    if pivot_len <= 0:
        raise ValueError("pivot_len must be positive")
    if len(bars) < (pivot_len * 2 + 1):
        return None

    eligible: list[DailyBar] = []
    for bar in bars:
        bar_day = entry_day_from_ts(bar.ts)
        if bar_day < entry_day:
            eligible.append(bar)

    if len(eligible) < (pivot_len * 2 + 1):
        return None

    for idx in range(len(eligible) - pivot_len - 1, pivot_len - 1, -1):
        candidate = eligible[idx].low
        left = eligible[idx - pivot_len:idx]
        right = eligible[idx + 1: idx + 1 + pivot_len]
        if len(left) < pivot_len or len(right) < pivot_len:
            continue
        if all(candidate < bar.low for bar in left) and all(candidate < bar.low for bar in right):
            return candidate
    return None


def compute_stop_price(
    bars: list[DailyBar],
    entry_day,
    buffer_dollars: float,
) -> Optional[float]:
    pivot = prior_swing_low(bars, entry_day=entry_day, pivot_len=5)
    if pivot is None:
        return None
    stop_price = float(pivot) - float(buffer_dollars)
    if stop_price <= 0:
        return None
    return round(stop_price, 2)


def compute_exit_levels(
    *,
    entry_price: float,
    entry_qty: int,
    stop_price: float,
    cfg: ExitConfig,
) -> Optional[ExitPositionState]:
    if entry_price <= 0 or stop_price <= 0 or entry_qty <= 0:
        return None
    r_value = entry_price - stop_price
    if r_value <= 0:
        return None

    r1_price = entry_price + cfg.r1_mult * r_value
    r2_price = entry_price + cfg.r2_mult * r_value
    r1_qty = int(entry_qty * cfg.r1_trim_pct)
    if r1_qty < 1:
        r1_qty = 1
    if r1_qty > entry_qty:
        r1_qty = entry_qty
    r2_qty = entry_qty - r1_qty

    return ExitPositionState(
        symbol="",
        entry_time=0.0,
        entry_price=entry_price,
        entry_qty=entry_qty,
        stop_price=stop_price,
        stop_order_id=None,
        r_value=round(r_value, 4),
        r1_price=round(r1_price, 2),
        r2_price=round(r2_price, 2),
        r1_qty=r1_qty,
        r2_qty=r2_qty,
        stage="OPEN",
        qty_remaining=entry_qty,
    )


def validate_risk(entry_price: float, stop_price: float, max_risk: float) -> bool:
    if entry_price <= 0 or stop_price <= 0 or max_risk <= 0:
        return False
    risk = entry_price - stop_price
    return 0 < risk <= max_risk


def apply_r1_transition(state: ExitPositionState, last_price: float) -> ExitPositionState:
    if state.stage != "OPEN":
        return state
    if last_price < state.r1_price:
        return state

    new_qty = max(state.qty_remaining - state.r1_qty, 0)
    new_stop = max(state.stop_price, state.entry_price)
    new_stage = "R1_TAKEN" if new_qty > 0 else "CLOSED"
    return replace(state, qty_remaining=new_qty, stop_price=new_stop, stage=new_stage)


def should_submit_stop(now_et: datetime) -> bool:
    return now_et.time() >= STOP_SUBMIT_AFTER


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _is_stop_order(order) -> bool:
    order_type = str(getattr(order, "order_type", getattr(order, "type", ""))).lower()
    if order_type in {"stop", "stop_limit"}:
        return True
    return False


def _load_open_orders(trading_client, symbol: str) -> list:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
    return list(trading_client.get_orders(filter=req))


def _submit_stop_order(trading_client, symbol: str, qty: int, stop_price: float) -> Optional[str]:
    from alpaca.trading.requests import StopOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    order = StopOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        stop_price=round(float(stop_price), 2),
    )
    response = trading_client.submit_order(order)
    return getattr(response, "id", None)


def reconcile_stop_order(
    *,
    trading_client,
    symbol: str,
    qty: int,
    stop_price: float,
    now_et: datetime,
    dry_run: bool,
    log,
    event_path: Path,
    state: ExitPositionState,
) -> ExitPositionState:
    if qty <= 0 or stop_price <= 0:
        return state
    if not should_submit_stop(now_et):
        return state

    open_orders = _load_open_orders(trading_client, symbol)
    stop_orders = [o for o in open_orders if _is_stop_order(o)]

    desired_stop = round(float(stop_price), 2)
    desired_qty = int(qty)

    matching = None
    had_existing = bool(stop_orders)
    for order in stop_orders:
        order_qty = _safe_int(getattr(order, "qty", getattr(order, "quantity", None)))
        order_stop = _safe_float(getattr(order, "stop_price", None))
        if order_qty == desired_qty and order_stop is not None and round(order_stop, 2) == desired_stop:
            matching = order
        else:
            if not dry_run:
                try:
                    trading_client.cancel_order_by_id(order.id)
                except Exception:
                    pass

    if matching is not None:
        return replace(state, stop_order_id=getattr(matching, "id", None))

    action = "STOP_REPLACE" if had_existing else "STOP_SUBMIT"

    if dry_run:
        log(f"{action} {symbol}: qty={desired_qty} stop={desired_stop} (dry_run)")
        append_event(
            event_path,
            {
                "event": action,
                "symbol": symbol,
                "qty": desired_qty,
                "stop_price": desired_stop,
                "order_id": None,
                "dry_run": True,
            },
        )
        return replace(state, stop_order_id=None)

    order_id = _submit_stop_order(trading_client, symbol, desired_qty, desired_stop)
    log(f"{action} {symbol}: qty={desired_qty} stop={desired_stop} order_id={order_id}")
    append_event(
        event_path,
        {
            "event": action,
            "symbol": symbol,
            "qty": desired_qty,
            "stop_price": desired_stop,
            "order_id": order_id,
            "dry_run": False,
        },
    )
    return replace(state, stop_order_id=order_id)


def cancel_stop_order(
    *,
    trading_client,
    symbol: str,
    dry_run: bool,
    log,
    event_path: Path,
) -> None:
    open_orders = _load_open_orders(trading_client, symbol)
    for order in open_orders:
        if not _is_stop_order(order):
            continue
        if dry_run:
            log(f"STOP_CANCEL {symbol}: order_id={getattr(order, 'id', None)} (dry_run)")
            append_event(
                event_path,
                {
                    "event": "STOP_CANCEL",
                    "symbol": symbol,
                    "order_id": getattr(order, "id", None),
                    "dry_run": True,
                },
            )
            continue
        try:
            trading_client.cancel_order_by_id(order.id)
            append_event(
                event_path,
                {
                    "event": "STOP_CANCEL",
                    "symbol": symbol,
                    "order_id": getattr(order, "id", None),
                    "dry_run": False,
                },
            )
        except Exception:
            continue


def submit_market_sell(trading_client, symbol: str, qty: int) -> Optional[str]:
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    response = trading_client.submit_order(order)
    return getattr(response, "id", None)


def manage_positions(
    *,
    trading_client,
    md,
    cfg: ExitConfig,
    repo_root: Path,
    dry_run: bool,
    log,
) -> None:
    positions = trading_client.get_all_positions()
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    state_store = PositionStateStore(resolve_state_dir(repo_root))
    event_path = resolve_event_ledger(repo_root)

    for pos in positions:
        symbol = str(pos.symbol).upper()
        qty = _safe_int(getattr(pos, "qty", None))
        if qty is None or qty <= 0:
            continue
        current_price = _safe_float(getattr(pos, "current_price", None))
        if current_price is None:
            current_price = _safe_float(getattr(pos, "market_value", None))
        if current_price is None:
            continue

        state = state_store.load(symbol)
        if state is None:
            entry_price = _safe_float(getattr(pos, "avg_entry_price", None))
            if entry_price is None:
                log(f"WARNING: missing entry price for {symbol}; skipping state creation")
                continue
            bars = md.get_daily_bars(symbol)
            entry_day = now_et.date()
            stop_price = compute_stop_price(bars, entry_day, cfg.stop_buffer_dollars)
            if stop_price is None:
                log(f"ERROR: no pivot low found for {symbol}; cannot create state")
                continue
            if (entry_price - stop_price) > cfg.max_risk_per_share:
                log(f"ERROR: risk per share too large for {symbol}; cannot create state")
                continue
            template = compute_exit_levels(
                entry_price=entry_price,
                entry_qty=qty,
                stop_price=stop_price,
                cfg=cfg,
            )
            if template is None:
                log(f"ERROR: invalid exit levels for {symbol}; cannot create state")
                continue
            state = replace(
                template,
                symbol=symbol,
                entry_time=now_utc.timestamp(),
                entry_qty=qty,
                qty_remaining=qty,
            )
            log(
                f"ENTER_PLANNED {symbol}: entry={state.entry_price} stop={state.stop_price} "
                f"R={state.r_value} r1={state.r1_price} r2={state.r2_price}"
            )
            append_event(
                event_path,
                {
                    "event": "ENTER_PLANNED",
                    "symbol": symbol,
                    "entry": state.entry_price,
                    "stop": state.stop_price,
                    "r_value": state.r_value,
                    "r1": state.r1_price,
                    "r2": state.r2_price,
                },
            )
            log(
                f"POSITION_STATE {symbol}: stage={state.stage} qty_remaining={state.qty_remaining}"
            )
            append_event(
                event_path,
                {
                    "event": "POSITION_STATE",
                    "symbol": symbol,
                    "stage": state.stage,
                    "qty_remaining": state.qty_remaining,
                },
            )

        state = replace(state, qty_remaining=qty, entry_qty=max(state.entry_qty, qty))

        if state.stage != "CLOSED":
            state = reconcile_stop_order(
                trading_client=trading_client,
                symbol=symbol,
                qty=state.qty_remaining,
                stop_price=state.stop_price,
                now_et=now_et,
                dry_run=dry_run,
                log=log,
                event_path=event_path,
                state=state,
            )

        if state.stage in {"OPEN", "R1_TAKEN"} and current_price >= state.r2_price:
            log(f"R2_HIT {symbol}: price={current_price} target={state.r2_price}")
            append_event(
                event_path,
                {
                    "event": "R2_HIT",
                    "symbol": symbol,
                    "price": current_price,
                    "target": state.r2_price,
                },
            )
            if state.qty_remaining > 0:
                if dry_run:
                    log(f"R2_SELL_SUBMIT {symbol}: qty={state.qty_remaining} (dry_run)")
                    append_event(
                        event_path,
                        {
                            "event": "R2_SELL_SUBMIT",
                            "symbol": symbol,
                            "qty": state.qty_remaining,
                            "order_id": None,
                            "dry_run": True,
                        },
                    )
                else:
                    order_id = submit_market_sell(trading_client, symbol, state.qty_remaining)
                    log(
                        f"R2_SELL_SUBMIT {symbol}: qty={state.qty_remaining} order_id={order_id}"
                    )
                    append_event(
                        event_path,
                        {
                            "event": "R2_SELL_SUBMIT",
                            "symbol": symbol,
                            "qty": state.qty_remaining,
                            "order_id": order_id,
                            "dry_run": False,
                        },
                    )
                cancel_stop_order(
                    trading_client=trading_client,
                    symbol=symbol,
                    dry_run=dry_run,
                    log=log,
                    event_path=event_path,
                )
                state = replace(state, stage="CLOSED", qty_remaining=0)
                state_store.save(state)
            continue

        if state.stage == "OPEN" and current_price >= state.r1_price:
            log(f"R1_HIT {symbol}: price={current_price} target={state.r1_price}")
            append_event(
                event_path,
                {
                    "event": "R1_HIT",
                    "symbol": symbol,
                    "price": current_price,
                    "target": state.r1_price,
                },
            )
            r1_qty = min(state.r1_qty, state.qty_remaining)
            if r1_qty > 0:
                if dry_run:
                    log(f"R1_SELL_SUBMIT {symbol}: qty={r1_qty} (dry_run)")
                    append_event(
                        event_path,
                        {
                            "event": "R1_SELL_SUBMIT",
                            "symbol": symbol,
                            "qty": r1_qty,
                            "order_id": None,
                            "dry_run": True,
                        },
                    )
                else:
                    order_id = submit_market_sell(trading_client, symbol, r1_qty)
                    log(f"R1_SELL_SUBMIT {symbol}: qty={r1_qty} order_id={order_id}")
                    append_event(
                        event_path,
                        {
                            "event": "R1_SELL_SUBMIT",
                            "symbol": symbol,
                            "qty": r1_qty,
                            "order_id": order_id,
                            "dry_run": False,
                        },
                    )
                state = apply_r1_transition(state, current_price)
                if state.stage != "CLOSED":
                    state = reconcile_stop_order(
                        trading_client=trading_client,
                        symbol=symbol,
                        qty=state.qty_remaining,
                        stop_price=state.stop_price,
                        now_et=now_et,
                        dry_run=dry_run,
                        log=log,
                        event_path=event_path,
                        state=state,
                    )
            state_store.save(state)
            continue

        state_store.save(state)
