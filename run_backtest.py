from backtest import (
    backtest_symbol,
    bootstrap_trade_stats,
    buy_and_hold_metrics,
    enhance_trades,
    portfolio_metrics,
    randomized_baseline,
    rolling_window_summary,
    simulate_portfolio,
    summarize,
)
from config import cfg
from universe import load_universe

# Start small first, then scale:
manual_symbols = ["AAPL", "MSFT", "NVDA", "AMD", "XOM", "JPM"]

def load_symbols() -> list[str]:
    source = cfg.BACKTEST_TICKER_SOURCE.lower()
    if source == "screen":
        import pandas as pd
        try:
            candidates = pd.read_csv(cfg.BACKTEST_CANDIDATES_PATH)
        except FileNotFoundError:
            print(
                f"⚠️ Candidates file not found at {cfg.BACKTEST_CANDIDATES_PATH}. "
                "Falling back to manual symbols."
            )
            return manual_symbols

        symbol_col = "Symbol" if "Symbol" in candidates.columns else None
        if symbol_col is None:
            print("⚠️ Candidates file missing Symbol column. Falling back to manual symbols.")
            return manual_symbols

        symbols = (
            candidates[symbol_col]
            .dropna()
            .astype(str)
            .str.upper()
            .unique()
            .tolist()
        )
        return symbols[: cfg.BACKTEST_TICKER_LIMIT]

    if source == "universe":
        universe = load_universe()
        if universe.empty or "Ticker" not in universe.columns:
            print("⚠️ Universe unavailable. Falling back to manual symbols.")
            return manual_symbols
        symbols = (
            universe["Ticker"]
            .dropna()
            .astype(str)
            .str.upper()
            .unique()
            .tolist()
        )
        return symbols[: cfg.BACKTEST_TICKER_LIMIT]

    return manual_symbols

symbols = load_symbols()

all_trades = []
for s in symbols:
    t1 = backtest_symbol(s, direction="Long")
    if t1 is not None and not t1.empty:
        all_trades.append(t1)

    t2 = backtest_symbol(s, direction="Short")
    if t2 is not None and not t2.empty:
        all_trades.append(t2)

if all_trades:
    import pandas as pd

    trades = pd.concat(all_trades, ignore_index=True)
    trades = enhance_trades(trades)
    trades.to_csv("backtest_trades.csv", index=False)
    print("\nSaved: backtest_trades.csv")

    print("\nTrade summary by regime:")
    print(summarize(trades))

    executed, equity_curve, meta = simulate_portfolio(
        trades,
        initial_equity=cfg.BACKTEST_INITIAL_EQUITY,
        risk_pct=cfg.BACKTEST_RISK_PCT,
        max_concurrent=cfg.BACKTEST_MAX_CONCURRENT,
        slippage_bps=cfg.BACKTEST_SLIPPAGE_BPS,
        commission_per_trade=cfg.BACKTEST_COMMISSION_PER_TRADE,
    )

    if not executed.empty:
        executed.to_csv("backtest_executed_trades.csv", index=False)
        equity_curve.to_csv("backtest_equity_curve.csv", index=False)
        print("Saved: backtest_executed_trades.csv")
        print("Saved: backtest_equity_curve.csv")

        metrics = portfolio_metrics(executed, equity_curve)
        metrics_df = pd.DataFrame([metrics])
        metrics_df.to_csv("backtest_portfolio_metrics.csv", index=False)
        print("\nPortfolio metrics:")
        print(metrics_df.T)

        window_summary = rolling_window_summary(
            trades,
            window_months=cfg.BACKTEST_WINDOW_MONTHS,
            step_months=cfg.BACKTEST_WINDOW_STEP_MONTHS,
        )
        if not window_summary.empty:
            window_summary.to_csv("backtest_rolling_windows.csv", index=False)
            print("\nSaved: backtest_rolling_windows.csv")

        bootstrap = bootstrap_trade_stats(
            executed,
            n_samples=cfg.BACKTEST_BOOTSTRAP_SAMPLES,
        )
        if not bootstrap.empty:
            bootstrap.describe(percentiles=[0.05, 0.5, 0.95]).to_csv(
                "backtest_bootstrap_summary.csv"
            )
            print("Saved: backtest_bootstrap_summary.csv")

        benchmark = buy_and_hold_metrics(
            cfg.BACKTEST_BENCHMARK_SYMBOL,
            executed["EntryDate"].min(),
            executed["ExitDate"].max(),
            auto_adjust=cfg.BACKTEST_AUTO_ADJUST,
        )
        benchmark_rows = []
        if benchmark:
            benchmark_rows.append({
                "name": benchmark.name,
                "total_return": benchmark.total_return,
                "cagr": benchmark.cagr,
                "max_drawdown": benchmark.max_drawdown,
                "sharpe": benchmark.sharpe,
            })

        random_baseline = randomized_baseline(
            executed,
            slippage_bps=cfg.BACKTEST_SLIPPAGE_BPS,
            commission_per_trade=cfg.BACKTEST_COMMISSION_PER_TRADE,
            auto_adjust=cfg.BACKTEST_AUTO_ADJUST,
        )
        if random_baseline:
            benchmark_rows.append(random_baseline)

        if benchmark_rows:
            benchmark_df = pd.DataFrame(benchmark_rows)
            benchmark_df.to_csv("backtest_control_groups.csv", index=False)
            print("Saved: backtest_control_groups.csv")
    else:
        print("\nNo executed trades after portfolio constraints.")
else:
    print("No backtest trades produced (check date range / symbols).")
