"""CLI to log manual RAEC 401(k) fills into a JSONL ledger.

Usage:
    python -m tools.log_fills --date 2026-02-17 \
        "BUY XLI 100@132.50" "SELL BIL 200@91.20"

    python -m tools.log_fills --date 2026-02-17 \
        --strategy RAEC_401K_V3 --fees 4.95 --notes "morning session" \
        "BUY TQQQ 50@65.00"

    # Price-only (no qty):
    python -m tools.log_fills --date 2026-02-17 "BUY XLI @132.50"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from execution_v2 import book_ids

RECORD_TYPE = "MANUAL_FILL"
SCHEMA_VERSION = 1
LEDGER_SUBDIR = "MANUAL_FILLS"
DEFAULT_STRATEGY = "RAEC_401K_COORD"

_FILL_RE = re.compile(
    r"^(BUY|SELL)\s+"
    r"([A-Z0-9.]+)\s+"
    r"(?:([0-9]+(?:\.[0-9]+)?)\s*)?@\s*([0-9]+(?:\.[0-9]+)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedFill:
    side: str
    symbol: str
    qty: Optional[float]
    price: float


def parse_fill(raw: str) -> ParsedFill:
    """Parse a fill string like 'BUY XLI 100@132.50' or 'BUY XLI @132.50'."""
    m = _FILL_RE.match(raw.strip())
    if not m:
        raise ValueError(f"invalid fill string: {raw!r}")
    side = m.group(1).upper()
    symbol = m.group(2).upper()
    qty = float(m.group(3)) if m.group(3) else None
    price = float(m.group(4))
    if price <= 0:
        raise ValueError(f"price must be positive: {raw!r}")
    return ParsedFill(side=side, symbol=symbol, qty=qty, price=price)


def build_manual_fill_id(
    *,
    date_ny: str,
    book_id: str,
    strategy_id: str,
    symbol: str,
    side: str,
    qty: Optional[float],
    price: float,
) -> str:
    """Deterministic SHA256 fill ID for deduplication."""
    parts = "|".join([
        date_ny,
        book_id,
        strategy_id,
        symbol,
        side,
        repr(qty),
        repr(price),
    ])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def _ledger_path(repo_root: Path, date_ny: str) -> Path:
    return repo_root / "ledger" / LEDGER_SUBDIR / f"{date_ny}.jsonl"


def load_existing_fill_ids(path: Path) -> set[str]:
    """Read fill_ids already present in a day's ledger file."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            fill_id = record.get("fill_id")
            if fill_id:
                ids.add(str(fill_id))
    return ids


def _stable_json_dumps(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def append_records(path: Path, records: list[dict]) -> None:
    """Append JSONL records to the ledger file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(_stable_json_dumps(record) + "\n")


def print_summary(records: list[dict], skipped: int) -> None:
    """Print a human-readable summary of logged fills."""
    if records:
        print(f"Logged {len(records)} fill(s):")
        for r in records:
            qty_str = f" {r['qty']}" if r["qty"] is not None else ""
            print(f"  {r['side']} {r['symbol']}{qty_str} @ {r['price']}  [{r['fill_id'][:12]}...]")
    if skipped:
        print(f"Skipped {skipped} duplicate(s).")
    if not records and not skipped:
        print("No fills to log.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Log manual RAEC 401(k) fills to JSONL ledger.",
    )
    parser.add_argument("fills", nargs="+", help='Fill strings: "SIDE SYMBOL [QTY]@PRICE"')
    parser.add_argument("--date", required=True, help="NY trade date (YYYY-MM-DD)")
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY, help="Strategy ID tag")
    parser.add_argument("--fees", type=float, default=0.0, help="Per-trade fees")
    parser.add_argument("--notes", default=None, help="Free-form annotation")
    parser.add_argument("--repo-root", default=".", help=argparse.SUPPRESS)
    parser.add_argument("--now-utc", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    # Validate date
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"error: invalid date format: {args.date!r} (expected YYYY-MM-DD)", file=sys.stderr)
        return 1

    # Resolve timestamp
    if args.now_utc:
        ts_utc = datetime.fromisoformat(args.now_utc).astimezone(timezone.utc)
    else:
        ts_utc = datetime.now(timezone.utc)

    # Parse fills
    parsed: list[ParsedFill] = []
    for raw in args.fills:
        try:
            parsed.append(parse_fill(raw))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    repo_root = Path(args.repo_root)
    book_id = book_ids.SCHWAB_401K_MANUAL
    strategy_id = args.strategy
    date_ny = args.date

    path = _ledger_path(repo_root, date_ny)
    existing_ids = load_existing_fill_ids(path)

    records: list[dict] = []
    skipped = 0
    for fill in parsed:
        fill_id = build_manual_fill_id(
            date_ny=date_ny,
            book_id=book_id,
            strategy_id=strategy_id,
            symbol=fill.symbol,
            side=fill.side,
            qty=fill.qty,
            price=fill.price,
        )
        if fill_id in existing_ids:
            skipped += 1
            continue
        existing_ids.add(fill_id)
        record = {
            "book_id": book_id,
            "date_ny": date_ny,
            "fees": args.fees,
            "fill_id": fill_id,
            "notes": args.notes,
            "price": fill.price,
            "qty": fill.qty,
            "record_type": RECORD_TYPE,
            "schema_version": SCHEMA_VERSION,
            "side": fill.side,
            "strategy_id": strategy_id,
            "symbol": fill.symbol,
            "ts_utc": ts_utc.isoformat(),
        }
        records.append(record)

    if records:
        append_records(path, records)

    print_summary(records, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
