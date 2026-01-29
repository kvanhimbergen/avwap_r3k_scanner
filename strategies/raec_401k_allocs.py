"""CLI helper to set current allocations for RAEC 401(k) manual strategy."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from strategies.raec_401k import (
    BOOK_ID,
    DEFAULT_UNIVERSE,
    FALLBACK_CASH_SYMBOL,
    STRATEGY_ID,
    _save_state,
    _state_path,
)

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9-]{0,5}$")
DEFAULT_DESCRIPTION_MAPPING = {
    "vanguard total stock market index fund": "VTI",
}


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


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _normalize_key(value: str | None) -> str:
    return _normalize_text(value).lower()


def _parse_market_value(raw: str | None) -> float:
    if raw is None:
        return 0.0
    text = raw.strip()
    if not text:
        return 0.0
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    value = float(text)
    return -value if negative else value


def _looks_like_ticker(symbol: str) -> bool:
    return bool(_TICKER_RE.match(symbol))


def _resolve_symbol(
    symbol: str,
    description: str,
    security_type: str,
    description_mapping: dict[str, str],
) -> str | None:
    candidate = symbol.strip().upper()
    if candidate and _looks_like_ticker(candidate):
        return candidate
    normalized_type = _normalize_key(security_type)
    if normalized_type == "cash and money market":
        return "BIL"
    normalized_description = _normalize_key(description)
    if normalized_description in description_mapping:
        return description_mapping[normalized_description].upper()
    return None


def _header_index(header: list[str], needle: str) -> int | None:
    normalized = _normalize_key(needle)
    for idx, column in enumerate(header):
        if _normalize_key(column) == normalized:
            return idx
    return None


def _header_contains(header: list[str], needle: str) -> int | None:
    normalized = _normalize_key(needle)
    for idx, column in enumerate(header):
        if normalized in _normalize_key(column):
            return idx
    return None


def parse_schwab_positions_csv(
    path: Path, *, description_mapping: dict[str, str] | None = None
) -> dict[str, float]:
    rows = list(csv.reader(path.read_text().splitlines()))
    header_index = None
    for idx, row in enumerate(rows):
        if not row:
            continue
        if _header_index(row, "symbol") is not None and _header_contains(row, "mkt val") is not None:
            header_index = idx
            break
    if header_index is None:
        raise ValueError("Could not locate Schwab Positions header row with Symbol and Mkt Val columns.")

    header = rows[header_index]
    symbol_idx = _header_index(header, "symbol")
    description_idx = _header_index(header, "description")
    security_type_idx = _header_index(header, "security type")
    mkt_val_idx = _header_contains(header, "mkt val")

    if symbol_idx is None or description_idx is None or security_type_idx is None or mkt_val_idx is None:
        raise ValueError("Schwab Positions header must include Symbol, Description, Security Type, and Mkt Val.")

    if description_mapping is None:
        description_mapping = DEFAULT_DESCRIPTION_MAPPING

    allocations_mv: dict[str, float] = {}
    unresolved: list[tuple[str, str]] = []

    def _cell_value(row: list[str], index: int, *, join_rest: bool = False) -> str:
        if index >= len(row):
            return ""
        if join_rest and len(row) > len(header):
            return ",".join(row[index:])
        return row[index]

    for row in rows[header_index + 1 :]:
        if not row or not any(cell.strip() for cell in row):
            continue
        symbol_raw = _normalize_text(_cell_value(row, symbol_idx))
        if _normalize_key(symbol_raw) == "account total":
            continue
        description = _normalize_text(_cell_value(row, description_idx))
        security_type = _normalize_text(_cell_value(row, security_type_idx))
        market_value_raw = _cell_value(row, mkt_val_idx, join_rest=True)
        market_value = _parse_market_value(market_value_raw)
        if market_value <= 0:
            continue
        resolved = _resolve_symbol(
            symbol_raw,
            description,
            security_type,
            description_mapping,
        )
        if resolved is None:
            unresolved.append((symbol_raw, description))
            continue
        allocations_mv[resolved] = allocations_mv.get(resolved, 0.0) + market_value

    if unresolved:
        details = ", ".join(
            f"symbol='{symbol}' description='{description}'" for symbol, description in unresolved
        )
        raise ValueError(
            "Unresolved Schwab rows (add mappings in DEFAULT_DESCRIPTION_MAPPING): " + details
        )

    if not allocations_mv:
        raise ValueError("No positive market value positions found in Schwab CSV.")

    total_mv = sum(allocations_mv.values())
    allocations = {
        symbol: round(market_value / total_mv * 100, 1)
        for symbol, market_value in allocations_mv.items()
    }
    total_pct = sum(allocations.values())
    if abs(total_pct - 100.0) > 1.0:
        raise ValueError(f"Rounded allocation total {total_pct:.1f} not close to 100%.")
    return allocations


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
    parser.add_argument("--from-csv", default=None, help="Path to Schwab Positions CSV export")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provided = [args.set is not None, args.from_json is not None, args.from_csv is not None]
    if sum(1 for item in provided if item) != 1:
        raise SystemExit("Provide exactly one of --set, --from-json, or --from-csv")

    allocations: dict[str, float]
    if args.from_csv:
        allocations = parse_schwab_positions_csv(Path(args.from_csv))
    elif args.from_json:
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
