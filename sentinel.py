import time
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz

from config import cfg
from anchors import anchored_vwap, get_anchor_candidates
from indicators import get_pivot_targets
# from execution import create_schwab_order  # We will build this next

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
WATCHLIST_FILE = "daily_candidates.csv"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def is_market_open():
    """Checks if NYSE is currently open (9:30 AM - 4:00 PM EST)."""
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() > 4: return False
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= now <= close_time

def monitor_watchlist():
    print(f"[{datetime.now()}] Sentinel Pulse Started...")
    
    # Load your Sunday scan results
    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except FileNotFoundError:
        print("No watchlist found. Run run_scan.py first.")
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        avwap_floor = row['AVWAP_Floor']
        r1_target = row['R1_Trim']
        
        # 1. Fetch Intraday 5-Min Data from Alpaca
        # (Assuming you've added the Alpaca fetcher to your indicators/utils)
        df = get_alpaca_intraday(ticker) 
        if df is None or df.empty: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        
        # 2. Check for "The Reclaim" (Brian Shannon Signal)
        # Price crosses back ABOVE the AVWAP floor on an intraday basis
        reclaimed = prev_price <= avwap_floor and curr_price > avwap_floor
        
        # 3. Check if we are near the R1 target for a trim
        near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
        
        if reclaimed:
            msg = f"🚀 *RECLAIM ALERT: {ticker}*\nPrice: ${curr_price}\nAVWAP Floor: ${avwap_floor}\nTarget R1: ${r1_target}"
            send_telegram(msg)
            # Optional: create_schwab_order(ticker, "BUY", ...)
            
        if near_r1:
            msg = f"💰 *TRIM ALERT: {ticker}*\nPrice hit R1 Target: ${r1_target}\nConsider locking in 50% profit."
            send_telegram(msg)

def main():
    print("Sentinel Active. Waiting for market hours...")
    while True:
        if is_market_open():
            monitor_watchlist()
            # Wait 15 minutes between checks to avoid rate limits
            time.sleep(900) 
        else:
            # Check every 5 minutes if market has opened yet
            time.sleep(300)

if __name__ == "__main__":
    main()