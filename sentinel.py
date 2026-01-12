import time
import os
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Import your execution logic
from execution import execute_buy_bracket, execute_partial_sell, get_account_details, trading_client

# Modern Alpaca-py imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import cfg

# --- CONFIGURATION ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WATCHLIST_FILE = "daily_candidates.csv"

# Persistent set to track tickers we've already acted on today
TRADED_TODAY = set()

# Initialize Alpaca Data Client
data_client = StockHistoricalDataClient(
    os.getenv('APCA_API_KEY_ID'), 
    os.getenv('APCA_API_SECRET_KEY')
)

def send_telegram(message):
    """Sends a formatted alert to your Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
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

def get_alpaca_intraday(ticker):
    """Fetches 5-minute bars and standardizes for indicator logic."""
    try:
        start_time = datetime.now() - timedelta(days=2)
        request_params = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute * 5, start=start_time)
        bars = data_client.get_stock_bars(request_params).df
        if bars is None or bars.empty: return None
        
        df = bars.reset_index().rename(columns={
            'symbol': 'Ticker', 'timestamp': 'Date', 'open': 'Open',
            'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
        return df
    except Exception as e:
        print(f"Alpaca Fetch Error for {ticker}: {e}")
        return None

def monitor_watchlist():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sentinel Pulse Started...")
    
    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except FileNotFoundError:
        print(f"❌ {WATCHLIST_FILE} not found. Run run_scan.py first.")
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        avwap_floor = row['AVWAP_Floor']
        r1_target = row['R1_Trim']
        r2_target = row.get('R2_Target', r1_target * 1.05) # Fallback if R2 missing
        
        df = get_alpaca_intraday(ticker) 
        if df is None or len(df) < 2: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        
        # 1. Brian Shannon Reclaim Signal
        reclaimed = (prev_price <= avwap_floor) and (curr_price > avwap_floor)
        
        # 2. Trim Target (within 0.2% of R1)
        near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
        
        # --- EXECUTION LOGIC ---
        
        if reclaimed and ticker not in TRADED_TODAY:
            # Avoid duplicate orders by checking current positions
            try:
                trading_client.get_open_position(ticker)
                print(f"ℹ️ Position already exists for {ticker}. Skipping buy.")
                TRADED_TODAY.add(ticker) 
            except:
                # Setup trade parameters
                stop_loss = avwap_floor * 0.985 # 1.5% wiggle room below floor
                
                print(f"🚀 Signal: {ticker} reclaimed AVWAP. Placing bracket order...")
                execute_buy_bracket(ticker, stop_loss, r2_target)
                
                send_telegram(
                    f"✅ *TRADE EXECUTED: BUY {ticker}*\n"
                    f"💰 Price: ${curr_price:.2f}\n"
                    f"🛡️ Stop: ${stop_loss:.2f}\n"
                    f"🎯 Target: ${r2_target:.2f}"
                )
                TRADED_TODAY.add(ticker)

        if near_r1:
            try:
                # Only trim if we actually have a position
                pos = trading_client.get_open_position(ticker)
                print(f"💰 {ticker} hit R1 target. Executing partial trim...")
                execute_partial_sell(ticker, sell_percentage=0.5)
                
                send_telegram(
                    f"✂️ *TRADE EXECUTED: TRIM {ticker}*\n"
                    f"📈 Hit R1 Target: ${r1_target:.2f}\n"
                    f"💵 Sold 50% of position."
                )
            except:
                # No position found, nothing to trim
                pass

def main():
    print("Sentinel Active. Monitoring Russell 3000 AVWAP Reclaims...")
    while True:
        if is_market_open():
            monitor_watchlist()
            time.sleep(900) # 15 min pulse
        else:
            # Clear the trade tracker when the market is closed
            if len(TRADED_TODAY) > 0: TRADED_TODAY.clear()
            time.sleep(300)

if __name__ == "__main__":
    main()