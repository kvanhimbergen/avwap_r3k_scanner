"""Historical backtest for RAEC 401(k) Coordinator (V3+V4+V5 combined)."""

from __future__ import annotations

import argparse

from data.prices import PriceProvider
from strategies.raec_401k_backtest import run_coordinator_backtest


DEFAULT_CAPITAL_SPLIT = {"v3": 0.40, "v4": 0.30, "v5": 0.30}


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    capital_split: dict[str, float] | None = None,
    provider: PriceProvider | None = None,
) -> None:
    run_coordinator_backtest(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        capital_split=capital_split,
        provider=provider,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest RAEC 401(k) Coordinator (V3+V4+V5).")
    parser.add_argument("--start", default="2022-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-14", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=237_757.0, help="Total initial capital")
    args = parser.parse_args()
    run_backtest(start_date=args.start, end_date=args.end, initial_capital=args.capital)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
