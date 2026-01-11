import time
import os
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Modern Alpaca-py imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import cfg
from anchors import anchored_vwap
from indicators import get_pivot_targets

# --- CONFIGURATION ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WATCHLIST_FILE = "daily_candidates.csv"

# Initialize Alpaca Data Client
data_client = StockHistoricalDataClient(
    os.getenv('APCA_API_KEY_ID'), 
    os.getenv('APCA_API_SECRET_KEY')
)

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
    # 0=Monday, 6=Sunday
    if now.weekday() > 4: return False
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= now <= close_time

def get_alpaca_intraday(ticker):
    """Fetches 5-minute bars for the current day and standardizes columns."""
    try:
        # Look back 2 days to ensure we have enough data for the 'previous price' check
        start_time = datetime.now() - timedelta(days=2)
        
        request_params = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Minute * 5,
            start=start_time
        )
        bars = data_client.get_stock_bars(request_params).df
        
        if bars is None or bars.empty:
            return None
            
        # Standardize: Alpaca-py returns lowercase; your logic needs Title Case
        df = bars.reset_index().rename(columns={
            'symbol': 'Ticker',
            'timestamp': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })
        return df
    except Exception as e:
        print(f"Alpaca Fetch Error for {ticker}: {e}")
        return None

def monitor_watchlist():
    print(f"[{datetime.now()}] Sentinel Pulse Started...")
    
    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except FileNotFoundError:
        print(f"No watchlist found at {WATCHLIST_FILE}. Run run_scan.py first.")
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        avwap_floor = row['AVWAP_Floor']
        r1_target = row['R1_Trim']
        
        # 1. Fetch Intraday 5-Min Data
        df = get_alpaca_intraday(ticker) 
        if df is None or df.empty: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        
        # 2. Check for "The Reclaim" 
        # Price crosses back ABOVE the AVWAP floor
        reclaimed = prev_price <= avwap_floor and curr_price > avwap_floor
        
        # 3. Check if we are near the R1 target for a trim (within 0.2%)
        near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
        
        if reclaimed:
            msg = f"🚀 *RECLAIM ALERT: {ticker}*\nPrice: ${curr_price:.2f}\nAVWAP Floor: ${avwap_floor:.2f}\nTarget R1: ${r1_target:.2f}"
            print(f"Alert sent for {ticker} reclaim.")
            send_telegram(msg)
            
        if near_r1:
            msg = f"💰 *TRIM ALERT: {ticker}*\nPrice hit R1 Target: ${r1_target:.2f}\nConsider locking in 50% profit."
            print(f"Alert sent for {ticker} target.")
            send_telegram(msg)

def main():
    print("Sentinel Active. Waiting for market hours...")
    while True:
        if is_market_open():
            monitor_watchlist()
            # Wait 15 minutes between pulses to respect rate limits
            time.sleep(900) 
        else:
            # Check every 5 minutes if market has opened
            time.sleep(300)

if __name__ == "__main__":
    main()