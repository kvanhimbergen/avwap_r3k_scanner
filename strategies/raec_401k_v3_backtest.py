"""Historical backtest for RAEC 401(k) V3 strategy."""

from __future__ import annotations

import argparse

from pathlib import Path

from data.prices import PriceProvider, get_default_price_provider
from strategies import raec_401k_v3  # noqa: F401 — ensure registration
from strategies.raec_401k_backtest import (
    _compute_benchmark_metrics,
    print_backtest_results,
    run_single_backtest,
)
from strategies.raec_401k_registry import get

# VTTHX (Vanguard Target Retirement 2035) — age-appropriate peer for a 51yo
# 401(k) investor. ~70/30 equity/bond today, glides toward 50/50 by 2035.
DEFAULT_BENCHMARK = "VTTHX"


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    provider: PriceProvider | None = None,
    benchmark: str | None = DEFAULT_BENCHMARK,
) -> None:
    if provider is None:
        repo_root = Path(__file__).resolve().parents[1]
        provider = get_default_price_provider(str(repo_root), period="10y")
    result = run_single_backtest(
        strategy=get("RAEC_401K_V3"),
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        provider=provider,
    )
    if result is not None:
        benchmark_metrics = None
        if benchmark:
            benchmark_metrics = _compute_benchmark_metrics(
                provider, benchmark, result.equity_curve, initial_capital
            )
            if benchmark_metrics is None:
                print(f"NOTE: benchmark '{benchmark}' unavailable from price provider; skipping comparison.")
        print_backtest_results(
            result,
            title="RAEC 401(k) V3 — Historical Backtest Results",
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            benchmark=benchmark_metrics,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest RAEC 401(k) V3 strategy.")
    parser.add_argument("--start", default="2022-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-14", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    parser.add_argument(
        "--benchmark",
        default=DEFAULT_BENCHMARK,
        help=f"Benchmark symbol for excess return / tracking error (default: {DEFAULT_BENCHMARK}). "
             "Pass empty string to skip.",
    )
    args = parser.parse_args()
    run_backtest(
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        benchmark=args.benchmark or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
