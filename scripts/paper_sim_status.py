"""Paper simulation ledger status."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from execution_v2.paper_positions import positions_from_fills, mark_to_market
from execution_v2.paper_sim import resolve_date_ny, latest_close_price


def _load_fills(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []

    fills: list[dict] = []
    with ledger_path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                fills.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return fills


def _build_price_map(repo_root: Path, fills: list[dict]) -> dict[str, float]:
    price_map: dict[str, float] = {}
    for fill in fills:
        symbol = str(fill.get("symbol", "")).upper().strip()
        if not symbol or symbol in price_map:
            continue
        latest = latest_close_price(repo_root, symbol)
        if latest is not None:
            price_map[symbol] = latest
            continue
        try:
            price_map[symbol] = float(fill.get("price", 0.0))
        except (TypeError, ValueError):
            continue
    return price_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper sim ledger status")
    parser.add_argument("--date-ny", default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if args.date_ny:
        date_ny = args.date_ny
    else:
        date_ny = resolve_date_ny(datetime.now(timezone.utc))

    ledger_path = repo_root / "ledger" / "PAPER_SIM" / f"{date_ny}.jsonl"
    fills = _load_fills(ledger_path)
    symbols = sorted({fill.get("symbol") for fill in fills if fill.get("symbol")})

    print(f"Ledger: {ledger_path}")
    print(f"Fill events: {len(fills)}")
    print(f"Symbols: {', '.join(symbols) if symbols else 'none'}")

    positions = positions_from_fills(fills)
    if not positions:
        print("Positions: none")
        return

    print("Positions:")
    for symbol, pos in sorted(positions.items()):
        print(f"  {symbol}: qty={pos['qty']} avg_cost={pos['avg_cost']:.4f}")

    price_map = _build_price_map(repo_root, fills)
    marked = mark_to_market(positions, price_map)
    if marked:
        print("Unrealized PnL:")
        for symbol, info in sorted(marked.items()):
            mark_price = info.get("mark_price")
            pnl = info.get("unrealized_pnl")
            if mark_price is None or pnl is None:
                continue
            print(f"  {symbol}: mark={mark_price:.4f} pnl={pnl:.2f}")


if __name__ == "__main__":
    main()
