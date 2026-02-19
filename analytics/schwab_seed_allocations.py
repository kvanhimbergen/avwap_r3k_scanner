"""Seed RAEC strategy state files from Schwab live positions.

Reads the latest Schwab account + positions snapshot from the ledger,
converts them to allocation percentages, and writes those to each
strategy's ``last_known_allocations`` in its state JSON.

Usage:
    python -m analytics.schwab_seed_allocations                        # today
    python -m analytics.schwab_seed_allocations --ny-date 2026-02-18   # explicit
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from zoneinfo import ZoneInfo

from analytics.schwab_readonly_storage import (
    RECORD_TYPE_ACCOUNT,
    RECORD_TYPE_POSITIONS,
    ledger_path,
    load_snapshot_records,
)

DEFAULT_BOOK_ID = "SCHWAB_401K_MANUAL"
DEFAULT_STRATEGY_IDS = ["RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5"]
CASH_SYMBOL = "BIL"
SUM_TOLERANCE = 2.0  # max allowed deviation from 100%


def positions_to_allocations(
    account_record: dict,
    positions_record: dict,
    cash_symbol: str = CASH_SYMBOL,
) -> dict[str, float]:
    """Convert account + positions snapshot records to allocation percentages.

    Returns ``{symbol: pct, ...}`` where pct values sum to ~100.
    Cash balance is mapped to *cash_symbol* (default ``BIL``).
    """
    total_value = float(account_record.get("total_value", 0))
    if total_value <= 0:
        return {}

    cash = float(account_record.get("cash", 0))
    positions = positions_record.get("positions", [])

    allocs: dict[str, float] = {}
    for pos in positions:
        symbol = pos["symbol"]
        mv = float(pos.get("market_value", 0))
        allocs[symbol] = round((mv / total_value) * 100, 1)

    if cash > 0:
        allocs[cash_symbol] = round((cash / total_value) * 100, 1)

    return allocs


def load_allocations_from_ledger(
    repo_root: Path,
    book_id: str,
    ny_date: str,
) -> Optional[dict[str, float]]:
    """Load the latest Schwab snapshot from the ledger and convert to allocs.

    Returns ``None`` if the ledger file is missing or has no matching records.
    Uses the **last** account/positions records in the file (most recent sync).
    """
    path = ledger_path(repo_root, book_id, ny_date)
    records = load_snapshot_records(path)
    if not records:
        return None

    account_record = None
    positions_record = None
    for rec in records:
        if rec["record_type"] == RECORD_TYPE_ACCOUNT:
            account_record = rec
        elif rec["record_type"] == RECORD_TYPE_POSITIONS:
            positions_record = rec

    if account_record is None or positions_record is None:
        return None

    return positions_to_allocations(account_record, positions_record)


def seed_strategy_states(
    repo_root: Path,
    allocations: dict[str, float],
    strategy_ids: list[str],
    book_id: str,
) -> list[str]:
    """Write *allocations* into each strategy's state file.

    Preserves all other state fields.  Creates the state dir/file if missing.
    Returns list of strategy_ids that were updated.
    """
    updated: list[str] = []
    state_dir = repo_root / "state" / "strategies" / book_id
    state_dir.mkdir(parents=True, exist_ok=True)

    for sid in strategy_ids:
        state_path = state_dir / f"{sid}.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
        else:
            state = {"book_id": book_id, "strategy_id": sid}

        state["last_known_allocations"] = allocations
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        updated.append(sid)

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed RAEC strategy state from Schwab live positions",
    )
    parser.add_argument(
        "--ny-date",
        default=None,
        help="NY date (YYYY-MM-DD). Defaults to today in America/New_York.",
    )
    parser.add_argument(
        "--book-id",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID (default: {DEFAULT_BOOK_ID})",
    )
    parser.add_argument(
        "--strategy-ids",
        nargs="+",
        default=DEFAULT_STRATEGY_IDS,
        help="Strategy IDs to seed (default: V3 V4 V5)",
    )
    args = parser.parse_args()
    ny_date = args.ny_date or datetime.now(tz=ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    repo_root = Path(__file__).resolve().parent.parent
    allocs = load_allocations_from_ledger(repo_root, args.book_id, ny_date)
    if allocs is None:
        print(f"No Schwab snapshot found for {ny_date} in {args.book_id}", file=sys.stderr)
        sys.exit(1)

    cash_pct = allocs.get(CASH_SYMBOL, 0.0)
    updated = seed_strategy_states(repo_root, allocs, args.strategy_ids, args.book_id)
    print(
        f"Seeded {len(updated)} strategies from Schwab positions "
        f"({len(allocs)} positions, cash={cash_pct}%)",
    )
    for sid in updated:
        print(f"  {sid}")


if __name__ == "__main__":
    main()
