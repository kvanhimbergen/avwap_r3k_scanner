"""Historical backtest for RAEC 401(k) V4 strategy."""

from __future__ import annotations

import argparse

from data.prices import PriceProvider
from strategies import raec_401k_v4  # noqa: F401 — ensure registration
from strategies.raec_401k_backtest import print_backtest_results, run_single_backtest
from strategies.raec_401k_registry import get


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    provider: PriceProvider | None = None,
) -> None:
    result = run_single_backtest(
        strategy=get("RAEC_401K_V4"),
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        provider=provider,
    )
    if result is not None:
        print_backtest_results(
            result,
            title="RAEC 401(k) V4 — Global Macro Backtest Results",
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest RAEC 401(k) V4 strategy.")
    parser.add_argument("--start", default="2022-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-14", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    args = parser.parse_args()
    run_backtest(start_date=args.start, end_date=args.end, initial_capital=args.capital)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
