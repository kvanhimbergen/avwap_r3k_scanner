"""CLI helper to set current allocations for RAEC 401(k) manual strategy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategies.raec_401k import (
    BOOK_ID,
    DEFAULT_UNIVERSE,
    FALLBACK_CASH_SYMBOL,
    STRATEGY_ID,
    _save_state,
    _state_path,
)


def _parse_allocations(items: list[str]) -> dict[str, float]:
    allocations: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid allocation '{item}', expected SYMBOL=NUM")
        symbol, value = item.split("=", 1)
        allocations[symbol.strip().upper()] = float(value)
    return allocations


def _load_allocations_from_json(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("JSON allocations must be an object of SYMBOL: pct")
    return {str(symbol).upper(): float(value) for symbol, value in data.items()}


def _filter_universe(allocations: dict[str, float]) -> dict[str, float]:
    allowed = set(DEFAULT_UNIVERSE) | {FALLBACK_CASH_SYMBOL}
    filtered: dict[str, float] = {}
    for symbol, pct in allocations.items():
        if symbol in allowed:
            filtered[symbol] = pct
        else:
            print(f"Ignoring non-universe symbol: {symbol}")
    return filtered


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set current allocations for RAEC 401(k) strategy.")
    parser.add_argument("--set", nargs="*", default=None, help="Allocations as SYMBOL=NUM ...")
    parser.add_argument("--from-json", default=None, help="Path to JSON {symbol: pct}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.set and not args.from_json:
        raise SystemExit("Provide --set SYMBOL=NUM ... or --from-json PATH")

    allocations: dict[str, float]
    if args.from_json:
        allocations = _load_allocations_from_json(Path(args.from_json))
    else:
        allocations = _parse_allocations(args.set or [])

    allocations = _filter_universe(allocations)
    repo_root = Path(__file__).resolve().parents[1]
    state_path = _state_path(repo_root)
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text())
    state["book_id"] = BOOK_ID
    state["strategy_id"] = STRATEGY_ID
    state["last_known_allocations"] = allocations
    _save_state(state_path, state)
    print(f"Updated allocations for {BOOK_ID}/{STRATEGY_ID}: {allocations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
