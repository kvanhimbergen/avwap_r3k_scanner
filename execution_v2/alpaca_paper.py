"""
Execution V2 – Alpaca Paper Trading Utilities
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from execution_v2.clocks import ET
from execution_v2 import book_ids
from execution_v2 import live_gate


LEDGER_DIR = Path("ledger") / book_ids.ALPACA_PAPER


def ledger_path(repo_root: Path, date_ny: str) -> Path:
    return book_ids.ledger_path(repo_root, book_ids.ALPACA_PAPER, date_ny)


def _load_existing_intent_ids(path: Path) -> set[str]:
    existing: set[str] = set()
    if not path.exists():
        return existing
    try:
        with path.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                intent_id = data.get("intent_id")
                if intent_id:
                    existing.add(str(intent_id))
    except Exception:
        return existing
    return existing


def _normalize_ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    try:
        return str(value)
    except Exception:
        return None


def build_order_event(
    *,
    intent_id: str,
    symbol: str,
    qty: int,
    ref_price: float,
    order,
    now_utc: datetime,
) -> dict:
    order_id = getattr(order, "id", None) or getattr(order, "order_id", None)
    status = getattr(order, "status", None)
    filled_qty_raw = getattr(order, "filled_qty", None)
    filled_avg_price_raw = getattr(order, "filled_avg_price", None)
    filled_at = _normalize_ts(getattr(order, "filled_at", None))
    created_at = _normalize_ts(getattr(order, "created_at", None))
    updated_at = _normalize_ts(getattr(order, "updated_at", None))

    filled_qty = 0.0
    if filled_qty_raw is not None:
        try:
            filled_qty = float(filled_qty_raw)
        except Exception:
            filled_qty = 0.0

    filled_avg_price = None
    if filled_avg_price_raw is not None:
        try:
            filled_avg_price = float(filled_avg_price_raw)
        except Exception:
            filled_avg_price = None

    fills = []
    if filled_qty > 0 and filled_avg_price is not None:
        fills.append({
            "price": filled_avg_price,
            "qty": filled_qty,
            "ts": filled_at,
        })

    notional = float(qty) * float(ref_price)

    return {
        "ts_utc": now_utc.astimezone(timezone.utc).isoformat(),
        "date_ny": now_utc.astimezone(ET).date().isoformat(),
        "execution_mode": "ALPACA_PAPER",
        "book_id": book_ids.ALPACA_PAPER,
        "event_type": "ORDER_STATUS",
        "intent_id": intent_id,
        "alpaca_order_id": order_id,
        "symbol": symbol,
        "qty": qty,
        "ref_price": ref_price,
        "notional": notional,
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "fills": fills,
        "filled_at": filled_at,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def append_events(path: Path, events: Iterable[dict]) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_intent_ids(path)
    written = 0
    skipped = 0
    with path.open("a") as handle:
        for event in events:
            intent_id = event.get("intent_id")
            if not intent_id:
                skipped += 1
                continue
            if intent_id in existing:
                skipped += 1
                continue
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            existing.add(str(intent_id))
            written += 1
    return written, skipped


def load_caps_ledger(repo_root: Path, date_ny: str) -> live_gate.LiveLedger:
    path = ledger_path(repo_root, date_ny)
    entries: list[dict] = []
    if path.exists():
        try:
            with path.open("r") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("date_ny") != date_ny:
                        continue
                    symbol = str(data.get("symbol", "")).upper()
                    notional = data.get("notional")
                    order_id = data.get("alpaca_order_id") or data.get("intent_id")
                    if not symbol:
                        continue
                    try:
                        notional_value = float(notional)
                    except Exception:
                        continue
                    entries.append(
                        {
                            "order_id": str(order_id),
                            "symbol": symbol,
                            "notional": notional_value,
                            "timestamp": data.get("ts_utc"),
                        }
                    )
        except Exception:
            entries = []

    return live_gate.LiveLedger(str(path), date_ny, entries, was_reset=False)


def summarize_ledger(path: Path, date_ny: str) -> dict:
    orders = 0
    fills = 0
    if not path.exists():
        return {"orders": 0, "fills": 0, "ledger_path": str(path)}
    try:
        with path.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("date_ny") != date_ny:
                    continue
                orders += 1
                filled_qty = data.get("filled_qty")
                try:
                    if filled_qty and float(filled_qty) > 0:
                        fills += 1
                except Exception:
                    continue
    except Exception:
        return {"orders": 0, "fills": 0, "ledger_path": str(path)}

    return {"orders": orders, "fills": fills, "ledger_path": str(path)}
