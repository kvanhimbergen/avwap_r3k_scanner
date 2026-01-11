from backtest import backtest_symbol, summarize

# Start small first, then scale:
symbols = ["AAPL", "MSFT", "NVDA", "AMD", "XOM", "JPM"]

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
    print(summarize(trades))
    trades.to_csv("backtest_trades.csv", index=False)
    print("\nSaved: backtest_trades.csv")
else:
    print("No backtest trades produced (check date range / symbols).")
