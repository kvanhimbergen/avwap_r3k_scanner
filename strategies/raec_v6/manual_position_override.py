"""Manually override the Schwab readonly snapshot when the API is stale.

When Schwab's read-only API lags reality (known 401k PCRA issue —
executed trades don't appear in the positions endpoint for hours/days),
this helper appends a synthetic SCHWAB_READONLY_*_SNAPSHOT record to
the day's ledger with the user-supplied positions. Because the v6
coordinator reads the LATEST snapshot by as_of_utc, the synthetic one
wins, and tomorrow's intent diff is computed against reality.

Usage:
    python -m strategies.raec_v6.manual_position_override \\
        --ny-date 2026-06-11 \\
        --equity 248500 \\
        --cash 1968 \\
        --positions SGOV=0 PDBC=1041 EEM=203 XME=68 ERX=6 AMD=1 SMH=37 \\
                    XLK=212 SPY=35 QQQ=19 XLE=206 SHY=151 AIQ=181 HACK=120 \\
                    ARKG=329 BITI=367 IEF=60

Sanity check: the helper computes market_value = shares × today's close
for every symbol you give it, then verifies cash + sum(MV) ≈ stated
equity. If they're off by more than 1%, it refuses (you probably
mistyped a share count). Override the threshold with --equity-tolerance.

Symbols with shares=0 are dropped — convenient for "I sold all of X."

Pairs with: `python -m analytics.schwab_readonly_runner --live ...` —
which writes the REAL API snapshot. This override appends ON TOP of
that, and because we use a later as_of_utc the v6 coordinator picks
ours up.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


_LEDGER_DIR = Path("ledger") / "SCHWAB_401K_MANUAL"
_BOOK_ID = "SCHWAB_401K_MANUAL"


def _parse_positions(pairs: list[str]) -> dict[str, float]:
    """Parse SYM=SHARES pairs into {SYM: shares}."""
    out: dict[str, float] = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"Bad --positions entry {p!r} — use SYM=SHARES")
        sym, qty = p.split("=", 1)
        sym = sym.strip().upper()
        if not sym:
            raise ValueError(f"Bad --positions entry {p!r} — empty symbol")
        try:
            out[sym] = float(qty)
        except ValueError:
            raise ValueError(f"Bad share count {qty!r} for {sym}")
    return out


def _fetch_close_prices(symbols: list[str]) -> dict[str, float]:
    """Get today's close for each symbol via the project's PriceProvider."""
    from data.prices import get_default_price_provider

    provider = get_default_price_provider(".", period="5d")
    prices: dict[str, float] = {}
    missing: list[str] = []
    for sym in symbols:
        series = provider.get_daily_close_series(sym)
        if series:
            prices[sym] = float(series[-1][1])
        else:
            missing.append(sym)
    if missing:
        raise RuntimeError(
            f"Could not fetch prices for: {missing}. "
            f"Check the symbols and your network."
        )
    return prices


def build_records(
    *,
    ny_date: str,
    equity: float,
    cash: float,
    positions: dict[str, float],
    prices: dict[str, float],
    equity_tolerance: float = 0.01,
) -> tuple[dict, dict]:
    """Return (account_snapshot, positions_snapshot) records ready to write.

    Validates that `cash + sum(shares × price)` is within tolerance of
    `equity`. Raises ValueError if not — you probably mistyped a share count.
    """
    # Drop zero-share entries (convenient for "sold all of X").
    positions = {s: q for s, q in positions.items() if abs(q) > 1e-6}

    position_values: dict[str, float] = {
        sym: qty * prices[sym] for sym, qty in positions.items()
    }
    sum_mv = sum(position_values.values())
    derived_equity = cash + sum_mv
    drift = abs(derived_equity - equity) / max(equity, 1.0)
    if drift > equity_tolerance:
        raise ValueError(
            f"Stated equity ${equity:,.2f} disagrees with derived "
            f"(cash + sum(MV)) = ${derived_equity:,.2f} by {drift:.2%} "
            f"(tolerance {equity_tolerance:.2%}). "
            f"Check share counts; one of them is likely off."
        )

    as_of_utc = datetime.now(timezone.utc).isoformat()
    account = {
        "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
        "as_of_utc": as_of_utc,
        "book_id": _BOOK_ID,
        "ny_date": ny_date,
        "cash": f"{cash:.4f}",
        "market_value": f"{sum_mv:.4f}",
        "total_value": f"{equity:.4f}",
        "provenance": {"module": "strategies.raec_v6.manual_position_override"},
        "schema_version": 1,
    }
    positions_rec = {
        "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
        "as_of_utc": as_of_utc,
        "book_id": _BOOK_ID,
        "ny_date": ny_date,
        "positions": [
            {
                "as_of_utc": as_of_utc,
                "book_id": _BOOK_ID,
                "symbol": sym,
                "qty": f"{positions[sym]:.6f}",
                "market_value": f"{position_values[sym]:.4f}",
                "cost_basis": "0.0000",  # unknown; the coordinator doesn't use this
            }
            for sym in sorted(positions)
        ],
        "provenance": {"module": "strategies.raec_v6.manual_position_override"},
        "schema_version": 1,
    }
    return account, positions_rec


def write_records(
    repo_root: Path,
    ny_date: str,
    account: dict,
    positions_rec: dict,
) -> Path:
    """Append both records to the day's Schwab ledger file."""
    path = repo_root / _LEDGER_DIR / f"{ny_date}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(account) + "\n")
        f.write(json.dumps(positions_rec) + "\n")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Override stale Schwab snapshot for v6 (use only when Schwab API "
            "lag prevents the live snapshot from reflecting executed trades)."
        )
    )
    parser.add_argument("--ny-date", required=True,
                        help="NY date this snapshot applies to (YYYY-MM-DD)")
    parser.add_argument("--equity", required=True, type=float,
                        help="Stated total account equity in dollars")
    parser.add_argument("--cash", required=True, type=float,
                        help="Stated cash balance in dollars")
    parser.add_argument("--positions", required=True, nargs="+",
                        help="SYM=SHARES pairs, e.g. SGOV=0 XLK=212 SPY=35")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--equity-tolerance", type=float, default=0.01,
                        help="Max fractional difference between stated and "
                             "derived equity before refusing (default 1%%)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; don't append.")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        positions = _parse_positions(args.positions)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Fetching prices for {len(positions)} symbols...", flush=True)
    try:
        prices = _fetch_close_prices(list(positions))
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        account, positions_rec = build_records(
            ny_date=args.ny_date,
            equity=args.equity,
            cash=args.cash,
            positions=positions,
            prices=prices,
            equity_tolerance=args.equity_tolerance,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"\nWill append two records to ledger for {args.ny_date}:")
    print(f"  Total equity: ${args.equity:,.2f}")
    print(f"  Cash:         ${args.cash:,.2f}")
    print(f"  Positions ({len(positions_rec['positions'])}):")
    for p in positions_rec["positions"]:
        print(
            f"    {p['symbol']:<6}  qty={float(p['qty']):>8.0f}  "
            f"mv=${float(p['market_value']):>11,.2f}  "
            f"(px ${prices[p['symbol']]:>8.2f})"
        )

    if args.dry_run:
        print("\n[dry-run] No ledger write.")
        return 0

    path = write_records(args.repo_root, args.ny_date, account, positions_rec)
    print(f"\nAppended to {path}")
    print(
        "Tomorrow's 08:35 v6 coordinator will use this override "
        "(it picks the latest as_of_utc snapshot in the day's ledger)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
