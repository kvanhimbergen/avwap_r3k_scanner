"""Historical backtest for RAEC 401(k) Coordinator (V3+V4+V5 combined)."""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path
from statistics import stdev

from data.prices import PriceProvider, get_default_price_provider
from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5


DEFAULT_CAPITAL_SPLIT = {"v3": 0.40, "v4": 0.30, "v5": 0.30}


def _trading_days(provider: PriceProvider, start: date, end: date) -> list[date]:
    series = provider.get_daily_close_series("VTI")
    return sorted(d for d, _ in series if start <= d <= end)


def _daily_returns(provider: PriceProvider, symbol: str, days: list[date]) -> dict[date, float]:
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


def _run_single_strategy_backtest(
    *,
    module,
    provider: PriceProvider,
    trading_days: list[date],
    symbol_returns: dict[str, dict[date, float]],
    initial_capital: float,
    is_dual_anchor: bool = False,
) -> tuple[list[tuple[date, float, float]], int, list[tuple[date, str]]]:
    """Run backtest for a single sub-strategy, return equity curve, rebalance count, regime history."""
    equity = initial_capital
    allocations: dict[str, float] = {"BIL": 100.0}
    last_regime = ""
    last_eval_date = ""
    peak_equity = equity
    equity_curve: list[tuple[date, float, float]] = []
    rebalance_count = 0
    regime_history: list[tuple[date, str]] = []

    for day in trading_days:
        day_return = 0.0
        for sym, pct in allocations.items():
            if sym == "BIL":
                day_return += (pct / 100.0) * (5.0 / 252 / 100)
            else:
                sym_ret = symbol_returns.get(sym, {}).get(day, 0.0)
                day_return += (pct / 100.0) * sym_ret

        equity *= (1 + day_return)
        peak_equity = max(peak_equity, equity)
        dd = (equity / peak_equity) - 1.0
        equity_curve.append((day, equity, dd))

        should_eval = False
        if not last_eval_date:
            should_eval = True
        else:
            prior = module._parse_date(last_eval_date)
            should_eval = prior != day

        if not should_eval:
            continue

        try:
            vti_series = module._sorted_series(
                provider.get_daily_close_series("VTI"), asof=day
            )
            if is_dual_anchor:
                qqq_series = module._sorted_series(
                    provider.get_daily_close_series("QQQ"), asof=day
                )
                signal = module._compute_anchor_signal(vti_series, qqq_series)
            else:
                signal = module._compute_anchor_signal(vti_series)
        except ValueError:
            continue

        cash_symbol = "BIL"
        feature_map = module._load_symbol_features(
            provider=provider, asof=day, cash_symbol=cash_symbol
        )
        targets = module._targets_for_regime(
            signal=signal, feature_map=feature_map, cash_symbol=cash_symbol
        )

        do_rebalance = True  # daily eval always triggers

        if do_rebalance:
            deltas = {
                sym: targets.get(sym, 0.0) - allocations.get(sym, 0.0)
                for sym in set(targets) | set(allocations)
            }
            deltas = {s: d for s, d in deltas.items() if abs(d) >= module.MIN_TRADE_PCT}
            capped = module._apply_turnover_cap(
                deltas, max_weekly_turnover=module.MAX_WEEKLY_TURNOVER_PCT
            )

            new_allocs = dict(allocations)
            for sym, delta in capped.items():
                if abs(delta) >= module.MIN_TRADE_PCT:
                    new_allocs[sym] = new_allocs.get(sym, 0.0) + delta

            new_allocs = {s: p for s, p in new_allocs.items() if p > 0.1}
            total = sum(new_allocs.values())
            if total > 0:
                new_allocs = {s: p / total * 100 for s, p in new_allocs.items()}
            allocations = new_allocs
            rebalance_count += 1

        if not regime_history or regime_history[-1][1] != signal.regime:
            regime_history.append((day, signal.regime))

        last_regime = signal.regime
        last_eval_date = day.strftime("%Y-%m-%d")

    return equity_curve, rebalance_count, regime_history


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    capital_split: dict[str, float] | None = None,
    provider: PriceProvider | None = None,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if provider is None:
        provider = get_default_price_provider(str(repo_root))
    split = capital_split or dict(DEFAULT_CAPITAL_SPLIT)

    start = raec_401k_v3._parse_date(start_date)
    end = raec_401k_v3._parse_date(end_date)
    trading_days = _trading_days(provider, start, end)

    if len(trading_days) < 2:
        print("Not enough trading days in range.")
        return

    # Preload returns for all symbols across all universes
    all_symbols = set()
    all_symbols.update(raec_401k_v3.DEFAULT_UNIVERSE)
    all_symbols.update(raec_401k_v4.DEFAULT_UNIVERSE)
    all_symbols.update(raec_401k_v5.DEFAULT_UNIVERSE)
    all_symbols.update(["VTI", "QQQ"])
    symbol_returns: dict[str, dict[date, float]] = {}
    for sym in all_symbols:
        symbol_returns[sym] = _daily_returns(provider, sym, trading_days)

    strategies = {
        "v3": (raec_401k_v3, False),
        "v4": (raec_401k_v4, False),
        "v5": (raec_401k_v5, True),
    }

    sub_curves: dict[str, list[tuple[date, float, float]]] = {}
    sub_rebals: dict[str, int] = {}
    sub_regimes: dict[str, list[tuple[date, str]]] = {}

    for key, (module, is_dual) in strategies.items():
        sub_capital = initial_capital * split.get(key, 0.0)
        curve, rebal_count, regime_hist = _run_single_strategy_backtest(
            module=module,
            provider=provider,
            trading_days=trading_days,
            symbol_returns=symbol_returns,
            initial_capital=sub_capital,
            is_dual_anchor=is_dual,
        )
        sub_curves[key] = curve
        sub_rebals[key] = rebal_count
        sub_regimes[key] = regime_hist

    # Combine equity curves
    combined_curve: list[tuple[date, float, float]] = []
    combined_peak = initial_capital
    for i in range(len(trading_days)):
        combined_eq = 0.0
        for key in strategies:
            if i < len(sub_curves[key]):
                combined_eq += sub_curves[key][i][1]
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

    print("=" * 70)
    print("  RAEC 401(k) Coordinator — Combined Backtest Results")
    print("=" * 70)
    print(f"  Period:            {start_date} to {end_date}")
    print(f"  Trading days:      {len(trading_days)}")
    print(f"  Initial capital:   ${initial_capital:,.2f}")
    print(f"  Capital split:     V3={split['v3']:.0%} V4={split['v4']:.0%} V5={split['v5']:.0%}")
    print(f"  Final equity:      ${final_equity:,.2f}")
    print("-" * 70)
    print(f"  Total return:      {total_return * 100:+.1f}%")
    print(f"  CAGR:              {cagr * 100:+.1f}%")
    print(f"  Annualized vol:    {ann_vol * 100:.1f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print(f"  Max drawdown:      {max_drawdown * 100:.1f}%")
    print("-" * 70)
    print(f"  Best month:        {best_month * 100:+.1f}%")
    print(f"  Worst month:       {worst_month * 100:+.1f}%")
    print(f"  Positive months:   {positive_months}/{total_months}"
          f" ({positive_months / max(total_months, 1) * 100:.0f}%)")

    # Per-strategy breakdown
    print("-" * 70)
    print("  Per-strategy breakdown:")
    for key in ("v3", "v4", "v5"):
        curve = sub_curves[key]
        sub_init = initial_capital * split.get(key, 0.0)
        sub_final = curve[-1][1] if curve else sub_init
        sub_ret = (sub_final / sub_init) - 1.0 if sub_init > 0 else 0.0
        sub_max_dd = min(dd for _, _, dd in curve) if curve else 0.0
        print(f"    {key.upper()}: final=${sub_final:,.0f} return={sub_ret * 100:+.1f}% "
              f"maxDD={sub_max_dd * 100:.1f}% rebals={sub_rebals[key]}")

    print("-" * 70)
    print("  Worst drawdown periods (combined):")
    dd_points = [(d, eq, dd) for d, eq, dd in combined_curve if dd < -0.05]
    dd_points.sort(key=lambda x: x[2])
    shown = set()
    for d, eq, dd in dd_points[:5]:
        month = f"{d.year}-{d.month:02d}"
        if month not in shown:
            print(f"    {d}  dd={dd * 100:.1f}%  equity=${eq:,.0f}")
            shown.add(month)
        if len(shown) >= 3:
            break
    if not shown:
        print("    None > 5%")
    print("=" * 70)


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
