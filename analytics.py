import pandas as pd
import numpy as np

def generate_robust_report():
    try:
        df = pd.read_csv("trade_log.csv")
    except FileNotFoundError:
        print("No trade log found yet.")
        return

    # Filter for closing trades (TRIM/SELL) to calculate performance
    closed = df[df['Side'] != 'BUY'].copy()
    if closed.empty: return

    # Metrics Calculations
    wins = closed[closed['PnL'] > 0]
    losses = closed[closed['PnL'] <= 0]
    
    win_rate = len(wins) / len(closed)
    profit_factor = wins['PnL'].sum() / abs(losses['PnL'].sum()) if not losses.empty else 100.0
    expectancy = (win_rate * wins['PnL'].mean()) - ((1-win_rate) * abs(losses['PnL'].mean()))
    
    # SQN Calculation
    sqn = (closed['PnL'].mean() / closed['PnL'].std()) * np.sqrt(len(closed)) if len(closed) > 1 else 0

    print("\n--- ROBUST STRATEGY REPORT ---")
    print(f"✅ Win Rate: {win_rate:.2%}")
    print(f"💰 Profit Factor: {profit_factor:.2f}")
    print(f"📊 Expectancy: ${expectancy:.2f} per trade")
    print(f"🏆 SQN Score: {sqn:.2f} " + ("(Excellent)" if sqn > 3 else "(Good)" if sqn > 2 else "(Poor)"))
    print(f"⏱️ Avg Slippage: {df['Slippage'].mean():.4f}")
    print(f"📉 Avg MAE (Risk Taken): ${closed['MAE'].mean():.2f}")
    print(f"📈 Avg MFE (Max Potential): ${closed['MFE'].mean():.2f}")

if __name__ == "__main__":
    generate_robust_report()