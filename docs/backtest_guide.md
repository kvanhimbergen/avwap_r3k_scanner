# Backtest Guide

This repository ships with a lightweight AVWAP backtest engine plus a portfolio simulator. Use this guide to run the backtest, interpret the outputs, and improve robustness.

## 1. Run the backtest

1. (Optional) Decide how to source tickers in `config.py`:
   - `BACKTEST_TICKER_SOURCE = "manual"` uses the hard-coded list in `run_backtest.py`.
   - `BACKTEST_TICKER_SOURCE = "screen"` loads symbols from `daily_candidates.csv`.
   - `BACKTEST_TICKER_SOURCE = "universe"` loads the Russell 3000 universe.
2. (Optional) Adjust backtest settings in `config.py`:
   - `BACKTEST_INITIAL_EQUITY`, `BACKTEST_RISK_PCT`, `BACKTEST_MAX_CONCURRENT`
   - `BACKTEST_SLIPPAGE_BPS`, `BACKTEST_COMMISSION_PER_TRADE`
   - `BACKTEST_BOOTSTRAP_SAMPLES`, rolling window settings
   - `BACKTEST_TICKER_LIMIT`, `BACKTEST_CANDIDATES_PATH`, `BACKTEST_BENCHMARK_SYMBOL`
3. Execute:

```bash
python run_backtest.py
```

## 2. Output artifacts

Running `run_backtest.py` produces the following files:

| File | Description |
| --- | --- |
| `backtest_trades.csv` | Raw trade signals with AVWAP/trend context. |
| `backtest_executed_trades.csv` | Executed trades after portfolio constraints (position sizing, concurrency). |
| `backtest_equity_curve.csv` | Portfolio equity at each exit. |
| `backtest_portfolio_metrics.csv` | Portfolio-level performance metrics. |
| `backtest_rolling_windows.csv` | Rolling window stability summary. |
| `backtest_bootstrap_summary.csv` | Bootstrap distribution summary for mean return & win rate. |
| `backtest_control_groups.csv` | Benchmark buy/hold plus randomized entry baseline. |

## 3. Evaluate performance

### Portfolio metrics
`backtest_portfolio_metrics.csv` includes:

- **CAGR**: Compounded annual growth rate from the first entry to the last exit.
- **Max drawdown**: Worst peak-to-trough decline in the equity curve.
- **Sharpe/Sortino**: Risk-adjusted return, using trade-level returns.
- **Profit factor**: Gross wins / gross losses.
- **Expectancy**: Mean trade return (as % of equity at entry).

### Regime & signal context
Inspect `backtest_trades.csv` and pivot by:

- `Regime`, `TrendBucket`, `AVWAPSlopeBucket`
- `Direction` (Long/Short)

This highlights which environments are most favorable.

### Stability checks

1. **Rolling windows** (`backtest_rolling_windows.csv`):
   - Look for consistent win rates and R-multiples across time windows.
2. **Bootstrap summary** (`backtest_bootstrap_summary.csv`):
   - Validate that mean returns and win rates remain positive across the 5–95% range.
3. **Control groups** (`backtest_control_groups.csv`):
   - Compare your strategy CAGR and drawdown against the benchmark buy/hold.
   - Check whether randomized entry baseline is materially worse than your signals.

## 4. Learn from the results

- **If drawdowns are too large**:
  - Reduce `BACKTEST_RISK_PCT`.
  - Lower `BACKTEST_MAX_CONCURRENT` to reduce overlap.
- **If results are highly regime-dependent**:
  - Add filters to only trade during the favorable regime.
- **If win rate is fine but expectancy is low**:
  - Consider exiting on partial targets or widening max hold.
- **If performance is unstable in rolling windows**:
  - Increase the number of symbols or lengthen the testing period to reduce variance.

## 5. Robustness checklist

Use this checklist before trusting results:

- [ ] Include realistic transaction costs (slippage + commissions).
- [ ] Use adjusted prices or clean data to avoid split/dividend distortions.
- [ ] Validate across multiple market regimes and time windows.
- [ ] Compare multiple parameter sets to avoid overfitting.
- [ ] Confirm improvements hold up under bootstrap resampling.
- [ ] Confirm outperformance vs the benchmark and randomized baselines.

## 6. Extending the analysis

Ideas to extend:

- Add sector caps or volatility targeting.
- Track exposure by regime or trend bucket.
- Add benchmark comparison (e.g., SPY buy-and-hold).
- Export equity curve and trades into a dedicated reporting notebook.
