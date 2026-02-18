"""Unified backtest engine for RAEC 401(k) strategies (V3/V4/V5 + Coordinator)."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import stdev

from data.prices import PriceProvider, get_default_price_provider
from strategies.raec_401k_base import BaseRAECStrategy


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _trading_days(provider: PriceProvider, start: date, end: date) -> list[date]:
    """Get trading days from VTI price history."""
    series = provider.get_daily_close_series("VTI")
    return sorted(d for d, _ in series if start <= d <= end)


def _daily_returns(provider: PriceProvider, symbol: str, days: list[date]) -> dict[date, float]:
    """Get daily returns for a symbol keyed by date."""
    series = dict(provider.get_daily_close_series(symbol))
    returns: dict[date, float] = {}
    sorted_days = sorted(series.keys())
    day_set = set(days)
    for i in range(1, len(sorted_days)):
        d = sorted_days[i]
        if d in day_set:
            prev = series[sorted_days[i - 1]]
            if prev > 0:
                returns[d] = (series[d] / prev) - 1.0
    return returns


# ---------------------------------------------------------------------------
# Core single-strategy backtest
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    equity_curve: list[tuple[date, float, float]]  # (date, equity, drawdown)
    rebalance_count: int
    regime_history: list[tuple[date, str]]
    monthly_returns: dict[str, float]  # month_key -> cumulative factor


def run_single_backtest(
    *,
    strategy: BaseRAECStrategy,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    provider: PriceProvider | None = None,
) -> BacktestResult | None:
    """Run a historical backtest for a single BaseRAECStrategy instance."""
    repo_root = Path(__file__).resolve().parents[1]
    if provider is None:
        provider = get_default_price_provider(str(repo_root))

    start = strategy._parse_date(start_date)
    end = strategy._parse_date(end_date)
    trading_days = _trading_days(provider, start, end)

    if len(trading_days) < 2:
        print("Not enough trading days in range.")
        return None

    # Preload daily returns for all universe symbols + anchors
    all_symbols = list(strategy.DEFAULT_UNIVERSE) + ["VTI", "QQQ"]
    all_symbols = list(dict.fromkeys(all_symbols))
    symbol_returns: dict[str, dict[date, float]] = {}
    for sym in all_symbols:
        symbol_returns[sym] = _daily_returns(provider, sym, trading_days)

    # State
    equity = initial_capital
    allocations: dict[str, float] = {"BIL": 100.0}  # start 100% cash
    last_regime = ""
    last_eval_date = ""
    peak_equity = equity
    regime_history: list[tuple[date, str]] = []
    equity_curve: list[tuple[date, float, float]] = []
    rebalance_count = 0
    monthly_returns: dict[str, float] = {}

    for day in trading_days:
        # 1. Apply daily returns to current allocations
        day_return = 0.0
        for sym, pct in allocations.items():
            if sym == "BIL":
                day_return += (pct / 100.0) * (5.0 / 252 / 100)  # ~5% annual cash yield
            else:
                sym_ret = symbol_returns.get(sym, {}).get(day, 0.0)
                day_return += (pct / 100.0) * sym_ret

        equity *= (1 + day_return)
        peak_equity = max(peak_equity, equity)
        dd = (equity / peak_equity) - 1.0
        equity_curve.append((day, equity, dd))

        # Track monthly returns
        month_key = f"{day.year}-{day.month:02d}"
        if month_key not in monthly_returns:
            monthly_returns[month_key] = 1.0
        monthly_returns[month_key] *= (1 + day_return)

        # 2. Check if we should run strategy today
        should_eval = False
        if not last_eval_date:
            should_eval = True
        else:
            prior = strategy._parse_date(last_eval_date)
            should_eval = prior != day

        if not should_eval:
            continue

        # 3. Run strategy logic via the strategy's compute_anchor_signal hook
        asof_str = day.strftime("%Y-%m-%d")
        try:
            signal = strategy.compute_anchor_signal(provider, day)
        except ValueError:
            continue  # insufficient history

        cash_symbol = "BIL"
        feature_map = strategy._load_symbol_features(
            provider=provider, asof=day, cash_symbol=cash_symbol
        )
        targets = strategy._targets_for_regime(
            signal=signal, feature_map=feature_map, cash_symbol=cash_symbol
        )

        # Rebalance: daily eval always triggers
        deltas = {
            sym: targets.get(sym, 0.0) - allocations.get(sym, 0.0)
            for sym in set(targets) | set(allocations)
        }
        deltas = {s: d for s, d in deltas.items() if abs(d) >= strategy.MIN_TRADE_PCT}
        capped = strategy._apply_turnover_cap(
            deltas, max_weekly_turnover=strategy.MAX_WEEKLY_TURNOVER_PCT
        )

        new_allocs = dict(allocations)
        for sym, delta in capped.items():
            if abs(delta) >= strategy.MIN_TRADE_PCT:
                new_allocs[sym] = new_allocs.get(sym, 0.0) + delta

        # Clean up and renormalize
        new_allocs = {s: p for s, p in new_allocs.items() if p > 0.1}
        total = sum(new_allocs.values())
        if total > 0:
            new_allocs = {s: p / total * 100 for s, p in new_allocs.items()}
        allocations = new_allocs
        rebalance_count += 1

        if not regime_history or regime_history[-1][1] != signal.regime:
            regime_history.append((day, signal.regime))

        last_regime = signal.regime
        last_eval_date = asof_str

    return BacktestResult(
        equity_curve=equity_curve,
        rebalance_count=rebalance_count,
        regime_history=regime_history,
        monthly_returns=monthly_returns,
    )


# ---------------------------------------------------------------------------
# Results printing
# ---------------------------------------------------------------------------

def print_backtest_results(
    result: BacktestResult,
    *,
    title: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    width: int = 65,
) -> None:
    """Print formatted backtest results."""
    equity_curve = result.equity_curve
    if not equity_curve:
        print("No equity curve data.")
        return

    final_equity = equity_curve[-1][1]
    max_drawdown = min(dd for _, _, dd in equity_curve)
    total_return = (final_equity / initial_capital) - 1.0
    n_days = len(equity_curve)
    n_years = n_days / 252
    cagr = (final_equity / initial_capital) ** (1 / max(n_years, 0.01)) - 1.0 if n_years > 0 else 0.0

    # Annualized vol from equity curve
    eq_returns = []
    for i in range(1, len(equity_curve)):
        eq_returns.append(equity_curve[i][1] / equity_curve[i - 1][1] - 1)
    ann_vol = stdev(eq_returns) * math.sqrt(252) if len(eq_returns) > 1 else 0.0
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0

    # Monthly return stats
    monthly_rets = [v - 1.0 for v in result.monthly_returns.values()]
    worst_month = min(monthly_rets) if monthly_rets else 0.0
    best_month = max(monthly_rets) if monthly_rets else 0.0
    positive_months = sum(1 for r in monthly_rets if r > 0)
    total_months = len(monthly_rets)

    print("=" * width)
    print(f"  {title}")
    print("=" * width)
    print(f"  Period:            {start_date} to {end_date}")
    print(f"  Trading days:      {n_days}")
    print(f"  Initial capital:   ${initial_capital:,.2f}")
    print(f"  Final equity:      ${final_equity:,.2f}")
    print("-" * width)
    print(f"  Total return:      {total_return * 100:+.1f}%")
    print(f"  CAGR:              {cagr * 100:+.1f}%")
    print(f"  Annualized vol:    {ann_vol * 100:.1f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print(f"  Max drawdown:      {max_drawdown * 100:.1f}%")
    print("-" * width)
    print(f"  Rebalance events:  {result.rebalance_count}")
    print(f"  Regime changes:    {len(result.regime_history)}")
    print(f"  Best month:        {best_month * 100:+.1f}%")
    print(f"  Worst month:       {worst_month * 100:+.1f}%")
    print(f"  Positive months:   {positive_months}/{total_months}"
          f" ({positive_months / max(total_months, 1) * 100:.0f}%)")
    print("-" * width)
    print("  Regime history:")
    for d, r in result.regime_history:
        print(f"    {d}  {r}")
    print("-" * width)
    print("  Worst drawdown periods:")
    dd_points = [(d, eq, dd) for d, eq, dd in equity_curve if dd < -0.05]
    dd_points.sort(key=lambda x: x[2])
    shown: set[str] = set()
    for d, eq, dd in dd_points[:5]:
        month = f"{d.year}-{d.month:02d}"
        if month not in shown:
            print(f"    {d}  dd={dd * 100:.1f}%  equity=${eq:,.0f}")
            shown.add(month)
        if len(shown) >= 3:
            break
    if not shown:
        print("    None > 5%")
    print("=" * width)


# ---------------------------------------------------------------------------
# Coordinator backtest
# ---------------------------------------------------------------------------

DEFAULT_CAPITAL_SPLIT = {"v3": 0.40, "v4": 0.30, "v5": 0.30}


def run_coordinator_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    capital_split: dict[str, float] | None = None,
    provider: PriceProvider | None = None,
) -> None:
    """Run a combined backtest for the coordinator (V3+V4+V5)."""
    from strategies.raec_401k_registry import get
    # Ensure sub-strategy modules are imported (triggers registration)
    from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5  # noqa: F401

    repo_root = Path(__file__).resolve().parents[1]
    if provider is None:
        provider = get_default_price_provider(str(repo_root))
    split = capital_split or dict(DEFAULT_CAPITAL_SPLIT)

    strategies = {
        "v3": get("RAEC_401K_V3"),
        "v4": get("RAEC_401K_V4"),
        "v5": get("RAEC_401K_V5"),
    }

    start = strategies["v3"]._parse_date(start_date)
    end = strategies["v3"]._parse_date(end_date)
    trading_days = _trading_days(provider, start, end)

    if len(trading_days) < 2:
        print("Not enough trading days in range.")
        return

    # Preload returns for all symbols across all universes
    all_symbols: set[str] = set()
    for strat in strategies.values():
        all_symbols.update(strat.DEFAULT_UNIVERSE)
    all_symbols.update(["VTI", "QQQ"])
    symbol_returns: dict[str, dict[date, float]] = {}
    for sym in all_symbols:
        symbol_returns[sym] = _daily_returns(provider, sym, trading_days)

    # Run each sub-strategy independently
    sub_results: dict[str, BacktestResult] = {}
    for key, strat in strategies.items():
        sub_capital = initial_capital * split.get(key, 0.0)
        result = run_single_backtest(
            strategy=strat,
            start_date=start_date,
            end_date=end_date,
            initial_capital=sub_capital,
            provider=provider,
        )
        if result is None:
            print(f"Sub-strategy {key} returned no result.")
            return
        sub_results[key] = result

    # Combine equity curves
    combined_curve: list[tuple[date, float, float]] = []
    combined_peak = initial_capital
    for i in range(len(trading_days)):
        combined_eq = 0.0
        for key in strategies:
            curve = sub_results[key].equity_curve
            if i < len(curve):
                combined_eq += curve[i][1]
        combined_peak = max(combined_peak, combined_eq)
        dd = (combined_eq / combined_peak) - 1.0
        combined_curve.append((trading_days[i], combined_eq, dd))

    final_equity = combined_curve[-1][1] if combined_curve else initial_capital
    max_drawdown = min(dd for _, _, dd in combined_curve) if combined_curve else 0.0

    total_return = (final_equity / initial_capital) - 1.0
    n_years = len(trading_days) / 252
    cagr = (final_equity / initial_capital) ** (1 / max(n_years, 0.01)) - 1.0 if n_years > 0 else 0.0

    eq_returns = []
    for i in range(1, len(combined_curve)):
        eq_returns.append(combined_curve[i][1] / combined_curve[i - 1][1] - 1)
    ann_vol = stdev(eq_returns) * math.sqrt(252) if len(eq_returns) > 1 else 0.0
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0

    # Monthly returns
    monthly_returns: dict[str, float] = {}
    for i in range(1, len(combined_curve)):
        d = combined_curve[i][0]
        month_key = f"{d.year}-{d.month:02d}"
        day_ret = combined_curve[i][1] / combined_curve[i - 1][1] - 1
        if month_key not in monthly_returns:
            monthly_returns[month_key] = 1.0
        monthly_returns[month_key] *= (1 + day_ret)

    monthly_rets = [v - 1.0 for v in monthly_returns.values()]
    worst_month = min(monthly_rets) if monthly_rets else 0.0
    best_month = max(monthly_rets) if monthly_rets else 0.0
    positive_months = sum(1 for r in monthly_rets if r > 0)
    total_months = len(monthly_rets)

    width = 70
    print("=" * width)
    print("  RAEC 401(k) Coordinator — Combined Backtest Results")
    print("=" * width)
    print(f"  Period:            {start_date} to {end_date}")
    print(f"  Trading days:      {len(trading_days)}")
    print(f"  Initial capital:   ${initial_capital:,.2f}")
    print(f"  Capital split:     V3={split['v3']:.0%} V4={split['v4']:.0%} V5={split['v5']:.0%}")
    print(f"  Final equity:      ${final_equity:,.2f}")
    print("-" * width)
    print(f"  Total return:      {total_return * 100:+.1f}%")
    print(f"  CAGR:              {cagr * 100:+.1f}%")
    print(f"  Annualized vol:    {ann_vol * 100:.1f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print(f"  Max drawdown:      {max_drawdown * 100:.1f}%")
    print("-" * width)
    print(f"  Best month:        {best_month * 100:+.1f}%")
    print(f"  Worst month:       {worst_month * 100:+.1f}%")
    print(f"  Positive months:   {positive_months}/{total_months}"
          f" ({positive_months / max(total_months, 1) * 100:.0f}%)")

    # Per-strategy breakdown
    print("-" * width)
    print("  Per-strategy breakdown:")
    for key in ("v3", "v4", "v5"):
        curve = sub_results[key].equity_curve
        sub_init = initial_capital * split.get(key, 0.0)
        sub_final = curve[-1][1] if curve else sub_init
        sub_ret = (sub_final / sub_init) - 1.0 if sub_init > 0 else 0.0
        sub_max_dd = min(dd for _, _, dd in curve) if curve else 0.0
        print(f"    {key.upper()}: final=${sub_final:,.0f} return={sub_ret * 100:+.1f}% "
              f"maxDD={sub_max_dd * 100:.1f}% rebals={sub_results[key].rebalance_count}")

    print("-" * width)
    print("  Worst drawdown periods (combined):")
    dd_points = [(d, eq, dd) for d, eq, dd in combined_curve if dd < -0.05]
    dd_points.sort(key=lambda x: x[2])
    shown: set[str] = set()
    for d, eq, dd in dd_points[:5]:
        month = f"{d.year}-{d.month:02d}"
        if month not in shown:
            print(f"    {d}  dd={dd * 100:.1f}%  equity=${eq:,.0f}")
            shown.add(month)
        if len(shown) >= 3:
            break
    if not shown:
        print("    None > 5%")
    print("=" * width)


# ---------------------------------------------------------------------------
# Strategy name -> title mapping for single-strategy printing
# ---------------------------------------------------------------------------

_STRATEGY_TITLES = {
    "RAEC_401K_V3": "RAEC 401(k) V3 — Historical Backtest Results",
    "RAEC_401K_V4": "RAEC 401(k) V4 — Global Macro Backtest Results",
    "RAEC_401K_V5": "RAEC 401(k) V5 — AI/Future Tech Backtest Results",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest RAEC 401(k) strategies.")
    parser.add_argument(
        "--strategy",
        default="v3",
        choices=["v3", "v4", "v5", "coordinator"],
        help="Strategy to backtest (default: v3)",
    )
    parser.add_argument("--start", default="2022-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-14", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    args = parser.parse_args()

    if args.strategy == "coordinator":
        run_coordinator_backtest(
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
        )
        return 0

    from strategies.raec_401k_registry import get
    # Ensure sub-strategy modules are imported (triggers registration)
    from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5  # noqa: F401

    strategy_id_map = {
        "v3": "RAEC_401K_V3",
        "v4": "RAEC_401K_V4",
        "v5": "RAEC_401K_V5",
    }
    strategy_id = strategy_id_map[args.strategy]
    strategy = get(strategy_id)
    title = _STRATEGY_TITLES.get(strategy_id, f"RAEC 401(k) {args.strategy.upper()} Backtest Results")

    result = run_single_backtest(
        strategy=strategy,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
    )
    if result is not None:
        print_backtest_results(
            result,
            title=title,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
