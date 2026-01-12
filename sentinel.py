import time
import os
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Import execution logic and shared trading client
from execution import (
    execute_buy_bracket, 
    execute_partial_sell, 
    get_account_details, 
    trading_client, 
    get_daily_summary_data
)

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

# State Tracking
SUMMARY_SENT_TODAY = False
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
        # Added timeout to prevent script hanging on network issues
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_daily_summary():
    """Formats and sends the account snapshot to Telegram at market close."""
    try:
        data = get_daily_summary_data()
        
        pnl_emoji = "📈" if data['daily_pnl'] >= 0 else "📉"
        msg = (
            f"📊 *DAILY ACCOUNT SUMMARY*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 *Total Equity:* ${data['equity']:,.2f}\n"
            f"{pnl_emoji} *Daily PnL:* ${data['daily_pnl']:,.2f} ({data['pnl_pct']:.2f}%)\n\n"
            f"📋 *Open Positions:*\n"
        )
        
        if not data['positions']:
            msg += "_No open positions._"
        for pos in data['positions']:
            pos_pnl_emoji = "🟢" if pos['pnl'] >= 0 else "🔴"
            msg += (
                f"• *{pos['symbol']}*: {pos['qty']} shares\n"
                f"  Val: ${pos['val']:,.2f} | {pos_pnl_emoji} ${pos['pnl']:,.2f} ({pos['pnl_pct']:.2f}%)\n"
            )
        
        send_telegram(msg)
    except Exception as e:
        print(f"Error generating daily summary: {e}")

def is_market_open():
    """Checks if NYSE is currently open (9:30 AM - 4:00 PM EST)."""
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() > 4: return False
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= now <= close_time

# ALGO-READY TWEAK: Market Regime Check
def get_market_regime():
    """Checks if SPY is above its 200-day SMA (Bullish Trend)."""
    try:
        spy_req = StockBarsRequest(
            symbol_or_symbols="SPY", 
            timeframe=TimeFrame.Day, 
            start=datetime.now() - timedelta(days=300)
        )
        bars = data_client.get_stock_bars(spy_req).df
        if bars is None or bars.empty: return True
        
        df = bars.reset_index()
        df['SMA200'] = df['close'].rolling(window=200).mean()
        curr_price = df['close'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        
        return curr_price > sma200
    except Exception as e:
        print(f"Regime Check Error: {e}")
        return True # Default to True to avoid blocking if API fails

def get_alpaca_intraday(ticker):
    """Fetches 5-minute bars and standardizes columns for Title Case logic."""
    try:
        start_time = datetime.now() - timedelta(days=2)
        request_params = StockBarsRequest(
            symbol_or_symbols=ticker, 
            timeframe=TimeFrame.Minute * 5, 
            start=start_time
        )
        bars = data_client.get_stock_bars(request_params).df
        if bars is None or bars.empty: return None
        
        # Normalize columns for indicators.py and anchors.py compatibility
        df = bars.reset_index().rename(columns={
            'symbol': 'Ticker', 'timestamp': 'Date', 'open': 'Open',
            'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
        return df
    except Exception as e:
        print(f"Alpaca Fetch Error for {ticker}: {e}")
        return None

def monitor_watchlist():
    """Core pulse logic for monitoring reclaims and trim targets."""
    
    # ALGO-READY TWEAK: Refuse new buys if market regime turns bearish mid-day
    is_bullish = get_market_regime()
    if not is_bullish:
        print(f"🛑 Market Regime Bearish (SPY < 200 SMA). Suspending new buys.")
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sentinel Pulse Started...")
    
    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except FileNotFoundError:
        print(f"❌ {WATCHLIST_FILE} not found. Run run_scan.py first.")
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        # Explicitly cast to float for safety
        avwap_floor = float(row['AVWAP_Floor'])
        r1_target = float(row['R1_Trim'])
        r2_target = float(row.get('R2_Target', r1_target * 1.05))
        
        df = get_alpaca_intraday(ticker) 
        if df is None or len(df) < 2: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        
        # 1. Check for Brian Shannon "Reclaim"
        reclaimed = (prev_price <= avwap_floor) and (curr_price > avwap_floor)
        
        # 2. Check for R1 Trim Target
        near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
        
        # --- AUTOMATED EXECUTION ---
        
        # Only execute reclaims if the market regime is bullish
        if reclaimed and ticker not in TRADED_TODAY and is_bullish:
            try:
                # Check if we are already in the position
                trading_client.get_open_position(ticker)
                print(f"ℹ️ Position already exists for {ticker}. Skipping buy.")
                TRADED_TODAY.add(ticker) 
            except:
                # Setup trade parameters: Stop at 1.5% below floor, Target at R2
                stop_loss = avwap_floor * 0.985 
                
                print(f"🚀 Signal: {ticker} reclaimed floor. Placing bracket order...")
                execute_buy_bracket(ticker, stop_loss, r2_target)
                
                send_telegram(
                    f"✅ *TRADE EXECUTED: BUY {ticker}*\n"
                    f"💰 Entry: ${curr_price:.2f}\n"
                    f"🛡️ Stop: ${stop_loss:.2f}\n"
                    f"🎯 Target: ${r2_target:.2f}"
                )
                TRADED_TODAY.add(ticker)

        # Trims are executed regardless of regime (always bank profits)
        if near_r1:
            try:
                # Only attempt trim if a position is actually held
                trading_client.get_open_position(ticker)
                print(f"💰 {ticker} hit R1 target. Trimming 50%...")
                execute_partial_sell(ticker, sell_percentage=0.5)
                
                send_telegram(
                    f"✂️ *TRADE EXECUTED: TRIM {ticker}*\n"
                    f"📈 Hit R1 Target: ${r1_target:.2f}\n"
                    f"💵 Sold 50% for profit."
                )
            except:
                pass # No position to trim

def main():
    global SUMMARY_SENT_TODAY
    print("Sentinel Active. Monitoring Russell 3000 AVWAP Reclaims...")
    
    while True:
        tz = pytz.timezone('US/Eastern')
        now = datetime.now(tz)

        if is_market_open():
            monitor_watchlist()
            # Wait 15 minutes between pulses to respect rate limits
            time.sleep(900) 
        else:
            # Send the Daily Summary after 4:00 PM EST
            if now.hour >= 16 and not SUMMARY_SENT_TODAY and now.weekday() <= 4:
                print("Market closed. Sending daily report...")
                send_daily_summary()
                SUMMARY_SENT_TODAY = True
            
            # Reset state trackers at midnight
            if now.hour == 0:
                SUMMARY_SENT_TODAY = False
                TRADED_TODAY.clear() 
                print("Midnight reset performed. Ready for next session.")
                
            # Sleep for 5 minutes during off-hours
            time.sleep(300)

if __name__ == "__main__":
    main()