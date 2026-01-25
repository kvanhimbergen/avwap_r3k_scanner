from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterable, Optional

from analytics.schemas import Fill, IngestResult
from analytics.util import (
    build_fill_id,
    compact_json,
    date_ny,
    normalize_side,
    normalize_symbol,
    parse_timestamp,
    sort_fills,
    to_iso_ny,
    to_iso_utc,
)
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


class LedgerParseError(RuntimeError):
    pass


def _load_json(path: str) -> Any:
    if not os.path.exists(path):
        raise LedgerParseError(f"ledger missing: {path}")
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise LedgerParseError(f"ledger unreadable ({type(exc).__name__}): {path}") from exc
    except OSError as exc:
        raise LedgerParseError(f"ledger unreadable ({type(exc).__name__}): {path}") from exc


def _load_jsonl_entries(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        raise LedgerParseError(f"ledger missing: {path}")
    entries: list[dict[str, Any]] = []
    try:
        with open(path, "r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerParseError(f"ledger unreadable ({type(exc).__name__}): {path}") from exc
                if not isinstance(data, dict):
                    raise LedgerParseError(f"ledger invalid entries: {path}")
                entries.append(data)
    except OSError as exc:
        raise LedgerParseError(f"ledger unreadable ({type(exc).__name__}): {path}") from exc
    return entries


def _normalize_entries(data: Any, *, source_path: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    metadata: dict[str, str] = {}
    if isinstance(data, list):
        return data, metadata
    if isinstance(data, dict):
        if "entries" in data:
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise LedgerParseError(f"ledger invalid entries: {source_path}")
            if "date_ny" in data:
                metadata["date_ny"] = str(data.get("date_ny"))
            return entries, metadata
        entries = list(data.values())
        metadata["entries_from"] = "dict_values"
        return entries, metadata
    raise LedgerParseError(f"ledger invalid root: {source_path}")


def _entry_timestamp(entry: dict[str, Any], *, source_path: str, entry_index: int) -> Any:
    for key in ("ts", "timestamp", "time", "created_at", "executed_at"):
        if key in entry:
            return entry.get(key)
    raise LedgerParseError(f"missing timestamp at index {entry_index} in {source_path}")


def _entry_order_id(entry: dict[str, Any], fallback: str) -> str:
    for key in ("order_id", "id", "orderId", "order"):
        raw = entry.get(key)
        if raw:
            return str(raw).strip()
    return fallback


def _entry_side(entry: dict[str, Any]) -> str:
    for key in ("side", "action", "order_side"):
        if key in entry:
            return normalize_side(entry.get(key))
    return "unknown"


def _entry_price(entry: dict[str, Any], warnings: list[str], *, entry_index: int) -> Optional[float]:
    for key in ("price", "avg_price", "fill_price", "limit_price"):
        if key in entry:
            value = entry.get(key)
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                warnings.append(f"invalid price at index {entry_index}; defaulting to None")
                return None
    return None


def _entry_qty(entry: dict[str, Any], warnings: list[str], *, entry_index: int) -> float:
    for key in ("qty", "quantity", "shares", "notional"):
        if key in entry:
            value = entry.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                warnings.append(f"invalid qty at index {entry_index}; defaulting to 0")
                return 0.0
    warnings.append(f"missing qty at index {entry_index}; defaulting to 0")
    return 0.0


def _entry_fees(entry: dict[str, Any], warnings: list[str], *, entry_index: int) -> float:
    for key in ("fees", "fee"):
        if key in entry:
            value = entry.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                warnings.append(f"invalid fees at index {entry_index}; defaulting to 0")
                return 0.0
    return 0.0


def _build_fills(
    entries: Iterable[dict[str, Any]],
    *,
    venue: str,
    source_path: str,
    warnings: list[str],
) -> list[Fill]:
    fills: list[Fill] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise LedgerParseError(f"entry invalid at index {idx} in {source_path}")
        symbol = normalize_symbol(entry.get("symbol"))
        if not symbol:
            raise LedgerParseError(f"missing symbol at index {idx} in {source_path}")
        ts_value = _entry_timestamp(entry, source_path=source_path, entry_index=idx)
        try:
            ts_dt = parse_timestamp(ts_value, source_path=source_path, entry_index=idx)
        except ValueError as exc:
            raise LedgerParseError(str(exc)) from exc
        ts_utc = to_iso_utc(ts_dt)
        ts_ny = to_iso_ny(ts_dt)
        date_ny_value = date_ny(ts_dt)
        order_id = _entry_order_id(entry, fallback=f"{venue.lower()}-{idx}")
        side = _entry_side(entry)
        qty = _entry_qty(entry, warnings, entry_index=idx)
        price = _entry_price(entry, warnings, entry_index=idx)
        fees = _entry_fees(entry, warnings, entry_index=idx)
        raw_json = compact_json(entry)
        if raw_json is None:
            warnings.append(f"entry {idx} could not be serialized; raw_json omitted")
        fill_id = build_fill_id(
            venue=venue,
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            ts_utc=ts_utc,
            source_path=source_path,
            raw_json=raw_json,
        )
        fills.append(
            Fill(
                fill_id=fill_id,
                venue=venue,
                order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                fees=fees,
                ts_utc=ts_utc,
                ts_ny=ts_ny,
                date_ny=date_ny_value,
                source_path=source_path,
                raw_json=raw_json,
                strategy_id=DEFAULT_STRATEGY_ID,
                sleeve_id="default",
            )
        )
    return sort_fills(fills)


def parse_dry_run_ledger(path: str) -> IngestResult:
    data = _load_json(path)
    entries, metadata = _normalize_entries(data, source_path=path)
    warnings: list[str] = []
    fills = _build_fills(entries, venue="DRY_RUN", source_path=path, warnings=warnings)
    metadata["ledger_type"] = "dry_run"
    return IngestResult(fills=fills, warnings=warnings, source_metadata=metadata)


def parse_live_ledger(path: str) -> IngestResult:
    try:
        data = _load_json(path)
        entries, metadata = _normalize_entries(data, source_path=path)
    except LedgerParseError as exc:
        if "JSONDecodeError" not in str(exc):
            raise
        entries = _load_jsonl_entries(path)
        metadata = {}
    warnings: list[str] = []
    fills = _build_fills(entries, venue="LIVE", source_path=path, warnings=warnings)
    metadata["ledger_type"] = "live"
    return IngestResult(fills=fills, warnings=warnings, source_metadata=metadata)


def parse_ledgers(*, dry_run_path: Optional[str], live_path: Optional[str]) -> list[IngestResult]:
    results: list[IngestResult] = []
    if dry_run_path:
        results.append(parse_dry_run_ledger(dry_run_path))
    if live_path:
        results.append(parse_live_ledger(live_path))
    return results


def _summarize(results: Iterable[IngestResult]) -> list[str]:
    fills: list[Fill] = []
    venue_counts: dict[str, int] = {}
    for result in results:
        fills.extend(result.fills)
        for fill in result.fills:
            venue_counts[fill.venue] = venue_counts.get(fill.venue, 0) + 1
    lines: list[str] = []
    if venue_counts:
        summary = " ".join(
            f"{venue}={venue_counts[venue]}" for venue in sorted(venue_counts)
        )
    else:
        summary = "none"
    lines.append(f"fills: {summary}")
    if fills:
        fills_sorted = sort_fills(fills)
        dates = sorted({fill.date_ny for fill in fills_sorted})
        date_range = dates[0] if len(dates) == 1 else f"{dates[0]}..{dates[-1]}"
        lines.append(f"date_ny range: {date_range}")
        lines.append(f"first fill_id: {fills_sorted[0].fill_id}")
        lines.append(f"last fill_id: {fills_sorted[-1].fill_id}")
    else:
        lines.append("date_ny range: n/a")
        lines.append("first fill_id: n/a")
        lines.append("last fill_id: n/a")
    return lines


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest ledgers into canonical fills")
    parser.add_argument("--dry-run-ledger", dest="dry_run_ledger", help="Path to dry-run ledger")
    parser.add_argument("--live-ledger", dest="live_ledger", help="Path to live ledger")
    args = parser.parse_args(argv)
    if not args.dry_run_ledger and not args.live_ledger:
        parser.error("at least one ledger path is required")
    try:
        results = parse_ledgers(
            dry_run_path=args.dry_run_ledger,
            live_path=args.live_ledger,
        )
    except LedgerParseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"unexpected error ({type(exc).__name__})", file=sys.stderr)
        return 2
    for line in _summarize(results):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
