from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from execution_v2.exit_events import build_exit_event
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID
from execution_v2.exits import apply_trailing_stop, resolve_structural_stop


def _bar_ts(bar: Any) -> Optional[datetime]:
    if isinstance(bar, dict):
        raw = bar.get("ts") or bar.get("timestamp") or bar.get("time") or bar.get("t")
    else:
        raw = getattr(bar, "ts", None) or getattr(bar, "timestamp", None)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    return None


def _bar_low(bar: Any) -> Optional[float]:
    if isinstance(bar, dict):
        raw = bar.get("low")
    else:
        raw = getattr(bar, "low", None)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def simulate_exit(
    *,
    symbol: str,
    entry_price: float,
    qty: float,
    entry_ts_utc: str,
    intraday_bars: list,
    daily_bars: list,
    stop_buffer_dollars: float,
    min_intraday_bars: int = 6,
    source: str = "simulation",
    strategy_id: str = DEFAULT_STRATEGY_ID,
    sleeve_id: str = "default",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    stop_price: Optional[float] = None
    stop_basis: Optional[str] = None
    exit_price: Optional[float] = None
    exit_ts: Optional[str] = None

    for idx, bar in enumerate(intraday_bars):
        candidate_stop, candidate_basis = resolve_structural_stop(
            intraday_bars[: idx + 1],
            daily_bars,
            stop_buffer_dollars=stop_buffer_dollars,
            min_intraday_bars=min_intraday_bars,
        )
        desired_stop = apply_trailing_stop(stop_price, candidate_stop)
        if desired_stop is not None and stop_price is None:
            stop_price = desired_stop
            stop_basis = candidate_basis
            events.append(
                build_exit_event(
                    event_type="STOP_RESOLVED",
                    symbol=symbol,
                    ts=_bar_ts(bar),
                    source=source,
                    qty=qty,
                    stop_price=stop_price,
                    stop_basis=stop_basis,
                    stop_action="initial",
                    entry_price=entry_price,
                    entry_ts_utc=entry_ts_utc,
                    strategy_id=strategy_id,
                    sleeve_id=sleeve_id,
                )
            )
        elif desired_stop is not None and stop_price is not None and desired_stop > stop_price:
            stop_price = desired_stop
            stop_basis = candidate_basis or stop_basis
            events.append(
                build_exit_event(
                    event_type="STOP_RATCHET",
                    symbol=symbol,
                    ts=_bar_ts(bar),
                    source=source,
                    qty=qty,
                    stop_price=stop_price,
                    stop_basis=stop_basis,
                    stop_action="ratchet",
                    entry_price=entry_price,
                    entry_ts_utc=entry_ts_utc,
                    strategy_id=strategy_id,
                    sleeve_id=sleeve_id,
                )
            )

        if stop_price is None:
            continue

        low = _bar_low(bar)
        if low is None:
            continue
        if low <= stop_price:
            exit_price = stop_price
            ts = _bar_ts(bar) or datetime.now(timezone.utc)
            exit_ts = ts.astimezone(timezone.utc).isoformat()
            events.append(
                build_exit_event(
                    event_type="EXIT_FILLED",
                    symbol=symbol,
                    ts=ts,
                    source=source,
                    qty=qty,
                    price=exit_price,
                    stop_price=stop_price,
                    stop_basis=stop_basis,
                    stop_action="triggered",
                    reason="stop_hit",
                    entry_price=entry_price,
                    entry_ts_utc=entry_ts_utc,
                    exit_ts_utc=exit_ts,
                    strategy_id=strategy_id,
                    sleeve_id=sleeve_id,
                )
            )
            break

    if exit_price is None and stop_price is not None:
        ts = _bar_ts(intraday_bars[-1]) if intraday_bars else datetime.now(timezone.utc)
        events.append(
            build_exit_event(
                event_type="STOP_HELD",
                symbol=symbol,
                ts=ts,
                source=source,
                qty=qty,
                stop_price=stop_price,
                stop_basis=stop_basis,
                stop_action="held",
                entry_price=entry_price,
                entry_ts_utc=entry_ts_utc,
                strategy_id=strategy_id,
                sleeve_id=sleeve_id,
            )
        )

    return events
