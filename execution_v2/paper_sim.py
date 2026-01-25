"""
Execution V2 – Paper Simulation (deterministic fills)
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from execution_v2.clocks import ET
from utils.atomic_write import atomic_write_text


LEDGER_DIR = Path("ledger") / "PAPER_SIM"


def _intent_entry_price(intent) -> float | None:
    for attr in ("entry_price", "entry_level", "ref_price"):
        if hasattr(intent, attr):
            value = getattr(intent, attr)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _entry_level_from_candidates(repo_root: Path, date_ny: str, symbol: str) -> float | None:
    candidates_path = repo_root / "daily_candidates.csv"
    if not candidates_path.exists():
        return None

    with candidates_path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("ScanDate", "")).strip() != date_ny:
                continue
            if str(row.get("Symbol", "")).strip().upper() != symbol:
                continue
            entry_level = row.get("Entry_Level")
            if entry_level is None:
                return None
            try:
                return float(entry_level)
            except (TypeError, ValueError):
                return None
    return None


def _latest_close_from_cache(repo_root: Path, symbol: str) -> float | None:
    if importlib.util.find_spec("pandas") is None:
        return None

    if importlib.util.find_spec("cache_store") is None:
        return None

    import pandas as pd  # type: ignore
    import cache_store as cs

    history_path = repo_root / cs.HISTORY_PATH
    if not history_path.exists():
        return None

    df = cs.read_parquet(str(history_path))
    if df is None or df.empty:
        return None

    df = df.copy()
    if "Ticker" not in df.columns or "Close" not in df.columns:
        return None

    df["Ticker"] = df["Ticker"].astype(str).str.upper()
    symbol_df = df[df["Ticker"] == symbol]
    if symbol_df.empty:
        return None

    if "Date" in symbol_df.columns:
        symbol_df = symbol_df.sort_values("Date")
    close_value = symbol_df["Close"].iloc[-1]
    if pd.isna(close_value):
        return None

    try:
        return float(close_value)
    except (TypeError, ValueError):
        return None


def _intent_qty(intent) -> int:
    for attr in ("size_shares", "qty"):
        if hasattr(intent, attr):
            try:
                return int(getattr(intent, attr))
            except (TypeError, ValueError):
                return 0
    return 0


def _intent_symbol(intent) -> str:
    symbol = getattr(intent, "symbol", "")
    return str(symbol).strip().upper()


def _intent_side(intent) -> str:
    side = getattr(intent, "side", "buy")
    return str(side).strip().upper()


def _intent_id(intent) -> str | None:
    intent_id = getattr(intent, "intent_id", None)
    if intent_id:
        return str(intent_id)
    return None


def _hash_intent_id(date_ny: str, symbol: str, side: str, qty: int, price: float) -> str:
    rounded_price = round(float(price), 4)
    payload = f"{date_ny}|{symbol}|{side}|{qty}|{rounded_price:.4f}|PAPER_SIM"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_existing_intent_ids(ledger_path: Path) -> set[str]:
    existing_ids: set[str] = set()
    if not ledger_path.exists():
        return existing_ids

    try:
        with ledger_path.open("r") as handle:
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
                    existing_ids.add(str(intent_id))
    except Exception:
        return existing_ids

    return existing_ids


def _read_jsonl_lines(ledger_path: Path) -> list[str]:
    if not ledger_path.exists():
        return []
    try:
        existing = ledger_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    if not existing:
        return []
    return [line for line in existing.splitlines() if line]


def _resolve_price(intent, repo_root: Path, date_ny: str) -> tuple[float, str]:
    intent_price = _intent_entry_price(intent)
    if intent_price is not None:
        return intent_price, "intent_entry_price"

    symbol = _intent_symbol(intent)
    entry_level = _entry_level_from_candidates(repo_root, date_ny, symbol)
    if entry_level is not None:
        return entry_level, "daily_candidates_entry_level"

    fallback = _latest_close_from_cache(repo_root, symbol)
    if fallback is None:
        raise RuntimeError(
            f"PAPER_SIM: unable to resolve price for {symbol} on {date_ny} "
            "(no intent price, no daily_candidates.csv match, no cache close)"
        )
    return fallback, "latest_close_cache"


def simulate_fills(
    intents: Iterable[object],
    *,
    date_ny: str,
    now_utc: datetime,
    repo_root: Path,
) -> list[dict]:
    """
    Deterministically simulate fills for intents and append to a JSONL ledger.
    """
    ledger_dir = repo_root / LEDGER_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{date_ny}.jsonl"
    existing_ids = _load_existing_intent_ids(ledger_path)

    fills: list[dict] = []
    for intent in intents:
        symbol = _intent_symbol(intent)
        if not symbol:
            continue

        qty = _intent_qty(intent)
        if qty <= 0:
            continue

        side = _intent_side(intent)
        price, source = _resolve_price(intent, repo_root, date_ny)
        intent_id = _intent_id(intent)
        if intent_id is None:
            intent_id = _hash_intent_id(date_ny, symbol, side, qty, price)

        if intent_id in existing_ids:
            continue

        fill = {
            "ts_utc": now_utc.astimezone(timezone.utc).isoformat(),
            "date_ny": date_ny,
            "mode": "PAPER_SIM",
            "event_type": "FILL_SIMULATED",
            "intent_id": intent_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": round(float(price), 4),
            "source": source,
        }
        fills.append(fill)
        existing_ids.add(intent_id)

    if fills:
        lines = _read_jsonl_lines(ledger_path)
        lines.extend([json.dumps(fill, sort_keys=True) for fill in fills])
        data = "\n".join(lines) + "\n"
        atomic_write_text(ledger_path, data)

    return fills


def resolve_date_ny(now_utc: datetime) -> str:
    return now_utc.astimezone(ET).strftime("%Y-%m-%d")


def latest_close_price(repo_root: Path, symbol: str) -> float | None:
    return _latest_close_from_cache(repo_root, symbol)
