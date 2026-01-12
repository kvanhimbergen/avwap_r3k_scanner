import sys
import pandas as pd
import os

def add_manual_ticker(ticker, floor, stop):
    file = "daily_candidates.csv"
    if not os.path.exists(file):
        print(f"❌ Error: {file} not found. Run a scan first.")
        return

    df = pd.read_csv(file)
    ticker = ticker.upper().strip()

    # Remove if ticker already exists to avoid duplicates
    df = df[df['Ticker'] != ticker]

    new_row = {
        "Ticker": ticker,
        "TrendTier": "Manual",
        "Price": 0.0,
        "AVWAP_Floor": float(floor),
        "Stop_Loss": float(stop),
        "R1_Trim": float(floor) * 1.03,  # Sets a default 3% trim target
        "R2_Target": float(floor) * 1.07, # Sets a default 7% final target
        "RS": 0.0,
        "Sector": "Manual Entry"
    }
    
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(file, index=False)
    print(f"✅ Added {ticker} to watchlist | Floor: ${floor} | Stop: ${stop}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python add_ticker.py [TICKER] [FLOOR] [STOP]")
        print("Example: python add_ticker.py NVDA 130.50 126.25")
    else:
        add_manual_ticker(sys.argv[1], sys.argv[2], sys.argv[3])