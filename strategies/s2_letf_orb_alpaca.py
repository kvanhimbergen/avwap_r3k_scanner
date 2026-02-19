"""S2 LETF ORB Alpaca bracket-order runner.

Reads the daily S2 candidate CSV produced by s2_letf_orb_aggro and places
bracket orders via the Alpaca paper trading API.

Usage:
    python -m strategies.s2_letf_orb_alpaca --asof 2026-02-18
    python -m strategies.s2_letf_orb_alpaca --asof 2026-02-18 --dry-run
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from execution_v2 import book_ids, book_router
from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter

BOOK_ID = book_ids.ALPACA_PAPER
STRATEGY_ID = "S2_LETF_ORB_AGGRO"


def _default_candidates_csv(repo_root: Path, asof_date: str) -> Path:
    return (
        repo_root
        / "state"
        / "strategies"
        / book_ids.SCHWAB_401K_MANUAL
        / STRATEGY_ID
        / f"daily_candidates_layered_{asof_date}.csv"
    )


def _load_s2_candidates(csv_path: Path) -> list[dict]:
    """Load and filter candidates to S2_LETF_ORB_AGGRO rows only."""
    if not csv_path.exists():
        return []
    df = pd.read_csv(csv_path)
    if df.empty:
        return []
    if "Strategy_ID" in df.columns:
        df = df[df["Strategy_ID"] == STRATEGY_ID]
    required = {"Symbol", "Entry_Level", "Stop_Loss", "Target_R2"}
    if not required.issubset(set(df.columns)):
        return []
    return df.to_dict("records")


def run(
    *,
    asof_date: str,
    repo_root: Path,
    dry_run: bool = False,
    risk_pct: float = 1.0,
    max_positions: int = 5,
    candidates_csv: Path | None = None,
) -> None:
    csv_path = candidates_csv or _default_candidates_csv(repo_root, asof_date)
    candidates = _load_s2_candidates(csv_path)

    if not candidates:
        print(
            f"S2_ALPACA: asof={asof_date} candidates=0 "
            f"csv={csv_path} dry_run={int(dry_run)}"
        )
        return

    candidate_symbols = {str(c.get("Symbol", "")).upper() for c in candidates}

    if dry_run:
        print(f"S2_ALPACA DRY_RUN: asof={asof_date} candidates={len(candidates)}")
        for c in candidates:
            print(
                f"  {c['Symbol']}: entry={c['Entry_Level']:.2f} "
                f"stop={c['Stop_Loss']:.2f} target_r2={c['Target_R2']:.2f}"
            )
        return

    trading_client = book_router.select_trading_client(BOOK_ID)
    adapter = AlpacaS2BracketAdapter(trading_client)

    cancelled = adapter.cancel_stale_orders(candidate_symbols)
    if cancelled:
        print(f"S2_ALPACA: cancelled {len(cancelled)} stale orders")

    result = adapter.execute_candidates(
        candidates,
        ny_date=asof_date,
        repo_root=repo_root,
        risk_pct=risk_pct,
        max_positions=max_positions,
    )

    print(
        f"S2_ALPACA: asof={asof_date} "
        f"sent={result.sent} skipped={result.skipped} "
        f"errors={len(result.errors)} dry_run=0"
    )
    for err in result.errors:
        print(f"  ERROR: {err}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Place S2 LETF ORB bracket orders via Alpaca paper.",
    )
    parser.add_argument("--asof", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument(
        "--risk-pct", type=float, default=1.0,
        help="Pct of equity risked per trade (default 1.0).",
    )
    parser.add_argument(
        "--max-positions", type=int, default=5,
        help="Max concurrent S2 positions (default 5).",
    )
    parser.add_argument(
        "--candidates-csv", default=None,
        help="Override path to candidates CSV.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    dry_run = args.dry_run or (os.getenv("DRY_RUN", "0") == "1")
    csv_path = Path(args.candidates_csv).resolve() if args.candidates_csv else None
    run(
        asof_date=args.asof,
        repo_root=repo_root,
        dry_run=dry_run,
        risk_pct=args.risk_pct,
        max_positions=args.max_positions,
        candidates_csv=csv_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
