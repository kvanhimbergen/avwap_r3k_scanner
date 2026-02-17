"""Historical backtest for RAEC 401(k) V4 strategy."""

from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

from data.prices import PriceProvider, get_default_price_provider
from strategies import raec_401k_v4


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


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    provider: PriceProvider | None = None,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if provider is None:
        provider = get_default_price_provider(str(repo_root))

    start = raec_401k_v4._parse_date(start_date)
    end = raec_401k_v4._parse_date(end_date)
    trading_days = _trading_days(provider, start, end)

    if len(trading_days) < 2:
        print("Not enough trading days in range.")
        return

    # Preload daily returns for all universe symbols
    all_symbols = list(raec_401k_v4.DEFAULT_UNIVERSE) + ["VTI"]
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
    max_drawdown = 0.0
    regime_history: list[tuple[date, str]] = []
    equity_curve: list[tuple[date, float, float]] = []
    rebalance_count = 0
    monthly_returns: dict[str, float] = {}

    for day in trading_days:
        # 1. Apply daily returns to current allocations
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
        max_drawdown = min(max_drawdown, dd)
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
            prior = raec_401k_v4._parse_date(last_eval_date)
            should_eval = prior != day

        if not should_eval:
            continue

        # 3. Run strategy logic
        asof_str = day.strftime("%Y-%m-%d")
        try:
            vti_series = raec_401k_v4._sorted_series(
                provider.get_daily_close_series("VTI"), asof=day
            )
            signal = raec_401k_v4._compute_anchor_signal(vti_series)
        except ValueError:
            continue

        cash_symbol = "BIL"
        feature_map = raec_401k_v4._load_symbol_features(
            provider=provider, asof=day, cash_symbol=cash_symbol
        )
        targets = raec_401k_v4._targets_for_regime(
            signal=signal, feature_map=feature_map, cash_symbol=cash_symbol
        )

        # Check rebalance conditions
        do_rebalance = False
        if not last_eval_date or last_regime != signal.regime:
            do_rebalance = True
        else:
            drift = raec_401k_v4._compute_drift(allocations, targets)
            if any(abs(d) > raec_401k_v4.DRIFT_THRESHOLD_PCT for d in drift.values()):
                do_rebalance = True
            else:
                do_rebalance = True  # daily eval always triggers

        if do_rebalance:
            deltas = {
                sym: targets.get(sym, 0.0) - allocations.get(sym, 0.0)
                for sym in set(targets) | set(allocations)
            }
            deltas = {s: d for s, d in deltas.items() if abs(d) >= raec_401k_v4.MIN_TRADE_PCT}
            capped = raec_401k_v4._apply_turnover_cap(
                deltas, max_weekly_turnover=raec_401k_v4.MAX_WEEKLY_TURNOVER_PCT
            )

            new_allocs = dict(allocations)
            for sym, delta in capped.items():
                if abs(delta) >= raec_401k_v4.MIN_TRADE_PCT:
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
        last_eval_date = asof_str

    # Results
    total_return = (equity / initial_capital) - 1.0
    n_years = len(trading_days) / 252
    cagr = (equity / initial_capital) ** (1 / max(n_years, 0.01)) - 1.0 if n_years > 0 else 0.0

    eq_returns = []
    for i in range(1, len(equity_curve)):
        eq_returns.append(equity_curve[i][1] / equity_curve[i - 1][1] - 1)
    if len(eq_returns) > 1:
        from statistics import stdev
        ann_vol = stdev(eq_returns) * math.sqrt(252)
    else:
        ann_vol = 0.0

    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0

    monthly_rets = [v - 1.0 for v in monthly_returns.values()]
    worst_month = min(monthly_rets) if monthly_rets else 0.0
    best_month = max(monthly_rets) if monthly_rets else 0.0
    positive_months = sum(1 for r in monthly_rets if r > 0)
    total_months = len(monthly_rets)

    print("=" * 65)
    print("  RAEC 401(k) V4 — Global Macro Backtest Results")
    print("=" * 65)
    print(f"  Period:            {start_date} to {end_date}")
    print(f"  Trading days:      {len(trading_days)}")
    print(f"  Initial capital:   ${initial_capital:,.2f}")
    print(f"  Final equity:      ${equity:,.2f}")
    print("-" * 65)
    print(f"  Total return:      {total_return * 100:+.1f}%")
    print(f"  CAGR:              {cagr * 100:+.1f}%")
    print(f"  Annualized vol:    {ann_vol * 100:.1f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print(f"  Max drawdown:      {max_drawdown * 100:.1f}%")
    print("-" * 65)
    print(f"  Rebalance events:  {rebalance_count}")
    print(f"  Regime changes:    {len(regime_history)}")
    print(f"  Best month:        {best_month * 100:+.1f}%")
    print(f"  Worst month:       {worst_month * 100:+.1f}%")
    print(f"  Positive months:   {positive_months}/{total_months}"
          f" ({positive_months / max(total_months, 1) * 100:.0f}%)")
    print("-" * 65)
    print("  Regime history:")
    for d, r in regime_history:
        print(f"    {d}  {r}")
    print("-" * 65)
    print("  Worst drawdown periods:")
    dd_points = [(d, eq, dd) for d, eq, dd in equity_curve if dd < -0.05]
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
    print("=" * 65)


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
