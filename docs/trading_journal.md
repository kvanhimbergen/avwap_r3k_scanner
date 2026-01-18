# Trading Journal

The trading journal reads the existing `trade_log.csv` and produces scoped performance summaries and diagnostic metrics. Use it to evaluate the strategy by day, month, year, or across all trades.

## Quick Start

```bash
python trading_journal.py --scope day
python trading_journal.py --scope month --month 2024-09
python trading_journal.py --scope year --year 2024
python trading_journal.py --scope all
```

## Metrics Emitted

- **Net PnL**: Total profit/loss across closed trades.
- **Win Rate**: Percent of trades with positive PnL.
- **Profit Factor**: Gross wins divided by gross losses.
- **Expectancy**: Average PnL per trade using win rate and average win/loss.
- **Payoff Ratio**: Average win divided by average loss.
- **Sharpe/Sortino**: Per-trade risk-adjusted returns.
- **Max Drawdown**: Largest equity drawdown in the scoped period.
- **MFE/MAE**: Average maximum favorable/adverse excursion to evaluate exits.
- **Slippage**: Average difference between signal price and execution.

## Continuous Evaluation Suggestions

1. **Segment by market regime**: Compare metrics on days when your regime filter is bullish vs. bearish to validate regime gating.
2. **Track per-ticker edge**: Aggregate metrics by ticker to detect names that consistently underperform.
3. **Evaluate exit logic**: Use MFE/MAE ratio and trailing-stop exits to see whether stops are too tight/loose.
4. **Monitor payoff ratio stability**: A falling payoff ratio often signals position sizing or trim logic needs adjustment.
5. **Review slippage trends**: Rising slippage can indicate liquidity changes or over-aggressive entry timing.
6. **Check drawdown clustering**: If drawdowns cluster, tighten exposure controls or reduce trade count during weak windows.

