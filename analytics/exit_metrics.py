from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from analytics.schemas import ExitTrade
from analytics.util import parse_timestamp


def _bar_ts_utc(bar: Any) -> datetime | None:
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


def _bar_high_low(bar: Any) -> tuple[float | None, float | None]:
    if isinstance(bar, dict):
        high = bar.get("high")
        low = bar.get("low")
    else:
        high = getattr(bar, "high", None)
        low = getattr(bar, "low", None)
    try:
        high_val = float(high) if high is not None else None
    except Exception:
        high_val = None
    try:
        low_val = float(low) if low is not None else None
    except Exception:
        low_val = None
    return high_val, low_val


def compute_mae_mfe(
    *,
    entry_price: float,
    bars: list[Any],
    direction: str = "long",
    entry_ts_utc: str | None = None,
    exit_ts_utc: str | None = None,
) -> tuple[float | None, float | None]:
    if entry_price is None or not bars:
        return None, None
    entry = float(entry_price)
    max_favorable = None
    max_adverse = None

    start_ts = parse_timestamp(entry_ts_utc, source_path="entry_ts", entry_index=0) if entry_ts_utc else None
    end_ts = parse_timestamp(exit_ts_utc, source_path="exit_ts", entry_index=0) if exit_ts_utc else None

    for bar in bars:
        ts = _bar_ts_utc(bar)
        if ts is None:
            continue
        if start_ts and ts < start_ts:
            continue
        if end_ts and ts > end_ts:
            continue
        high, low = _bar_high_low(bar)
        if high is None or low is None:
            continue

        if direction == "long":
            favorable = high - entry
            adverse = low - entry
        else:
            favorable = entry - low
            adverse = entry - high

        max_favorable = favorable if max_favorable is None else max(max_favorable, favorable)
        max_adverse = adverse if max_adverse is None else min(max_adverse, adverse)

    return max_adverse, max_favorable


def compute_stop_efficiency(
    *,
    entry_price: float | None,
    exit_price: float | None,
    mfe: float | None,
    direction: str = "long",
) -> float | None:
    if entry_price is None or exit_price is None or mfe is None or mfe <= 0:
        return None
    entry = float(entry_price)
    exit_val = float(exit_price)
    realized = exit_val - entry if direction == "long" else entry - exit_val
    return realized / mfe


def compute_time_to_stop(entry_ts_utc: str, exit_ts_utc: str) -> float | None:
    try:
        entry_dt = parse_timestamp(entry_ts_utc, source_path="entry_ts", entry_index=0)
        exit_dt = parse_timestamp(exit_ts_utc, source_path="exit_ts", entry_index=0)
    except Exception:
        return None
    return (exit_dt - entry_dt).total_seconds()


def _aggregate(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def compute_exit_metrics(
    *,
    trades: list[ExitTrade],
    price_series_by_symbol: dict[str, list[Any]],
) -> dict[str, Any]:
    trade_rows: list[dict[str, Any]] = []
    per_symbol: dict[str, list[dict[str, Any]]] = {}

    for trade in trades:
        bars = price_series_by_symbol.get(trade.symbol, [])
        if trade.entry_price is None:
            mae, mfe = None, None
        else:
            mae, mfe = compute_mae_mfe(
                entry_price=trade.entry_price,
                bars=bars,
                direction=trade.direction,
                entry_ts_utc=trade.entry_ts_utc,
                exit_ts_utc=trade.exit_ts_utc,
            )
        efficiency = compute_stop_efficiency(
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            mfe=mfe,
            direction=trade.direction,
        )
        time_to_stop = None
        if trade.entry_ts_utc and trade.exit_ts_utc:
            time_to_stop = compute_time_to_stop(trade.entry_ts_utc, trade.exit_ts_utc)

        row = {
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry_ts_utc": trade.entry_ts_utc,
            "exit_ts_utc": trade.exit_ts_utc,
            "qty": trade.qty,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "mae": mae,
            "mfe": mfe,
            "stop_efficiency": efficiency,
            "time_to_stop_sec": time_to_stop,
            "stop_price": trade.stop_price,
            "stop_basis": trade.stop_basis,
            "reason": trade.reason,
            "source": trade.source,
            "strategy_id": trade.strategy_id,
            "sleeve_id": trade.sleeve_id,
        }
        trade_rows.append(row)
        per_symbol.setdefault(trade.symbol, []).append(row)

    trade_rows_sorted = sorted(
        trade_rows,
        key=lambda row: (row["exit_ts_utc"], row["symbol"], row["trade_id"]),
    )

    symbol_rows = []
    for symbol in sorted(per_symbol):
        rows = per_symbol[symbol]
        symbol_rows.append(
            {
                "symbol": symbol,
                "trade_count": len(rows),
                "avg_mae": _aggregate([r["mae"] for r in rows]),
                "avg_mfe": _aggregate([r["mfe"] for r in rows]),
                "avg_stop_efficiency": _aggregate([r["stop_efficiency"] for r in rows]),
                "avg_time_to_stop_sec": _aggregate([r["time_to_stop_sec"] for r in rows]),
            }
        )

    portfolio = {
        "trade_count": len(trade_rows),
        "avg_mae": _aggregate([r["mae"] for r in trade_rows]),
        "avg_mfe": _aggregate([r["mfe"] for r in trade_rows]),
        "avg_stop_efficiency": _aggregate([r["stop_efficiency"] for r in trade_rows]),
        "avg_time_to_stop_sec": _aggregate([r["time_to_stop_sec"] for r in trade_rows]),
    }

    return {
        "trades": trade_rows_sorted,
        "symbols": symbol_rows,
        "portfolio": portfolio,
    }


def write_exit_metrics_json(path: str, metrics: dict[str, Any]) -> None:
    with open(path, "w") as handle:
        handle.write(json.dumps(metrics, sort_keys=True, separators=(",", ":")))
