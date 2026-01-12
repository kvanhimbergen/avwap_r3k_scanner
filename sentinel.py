import time
import os
import pandas as pd
import requests
import csv  # NEW: Required for trade logging
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
TRADE_LOG = "trade_log.csv"  # NEW: Analytics file path

# State Tracking
SUMMARY_SENT_TODAY = False
TRADED_TODAY = set()
# NEW: State for tracking Max Favorable/Adverse Excursion
OPEN_TRADE_STATS = {} 

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

# NEW: Logging function for analytics.py
def log_trade_to_csv(ticker, side, price, signal_price, mfe=0, mae=0, pnl=0):
    """Logs detailed trade metrics for robust post-trade analysis."""
    file_exists = os.path.isfile(TRADE_LOG)
    with open(TRADE_LOG, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Timestamp', 'Ticker', 'Side', 'Price', 'Signal_Price', 'Slippage', 'MFE', 'MAE', 'PnL'])
        
        # Slippage is the difference between your signal price and actual fill
        slippage = price - signal_price if side == 'BUY' else signal_price - price
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
            ticker, side, price, signal_price, 
            round(slippage, 4), round(mfe, 2), round(mae, 2), round(pnl, 2)
        ])

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

def get_market_regime():
    """Checks if SPY is above its 200-day SMA."""
    try:
        spy_req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=datetime.now() - timedelta(days=300))
        bars = data_client.get_stock_bars(spy_req).df
        if bars is None or bars.empty: return True
        df = bars.reset_index()
        df['SMA200'] = df['close'].rolling(window=200).mean()
        return df['close'].iloc[-1] > df['SMA200'].iloc[-1]
    except:
        return True 

def get_alpaca_intraday(ticker):
    """Fetches 5-minute bars and standardizes columns."""
    try:
        start_time = datetime.now() - timedelta(days=2)
        request_params = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute * 5, start=start_time)
        bars = data_client.get_stock_bars(request_params).df
        if bars is None or bars.empty: return None
        return bars.reset_index().rename(columns={
            'symbol': 'Ticker', 'timestamp': 'Date', 'open': 'Open',
            'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
    except Exception as e:
        print(f"Alpaca Fetch Error for {ticker}: {e}")
        return None

def monitor_watchlist():
    """Core pulse logic for monitoring reclaims and trim targets."""
    is_bullish = get_market_regime()
    if not is_bullish:
        print(f"🛑 Market Regime Bearish. Suspending new buys.")
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sentinel Pulse Started...")
    
    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except FileNotFoundError:
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        avwap_floor = float(row['AVWAP_Floor'])
        r1_target = float(row['R1_Trim'])
        structural_stop = float(row['Stop_Loss'])
        r2_target = float(row.get('R2_Target', r1_target * 1.05))
        
        df = get_alpaca_intraday(ticker) 
        if df is None or len(df) < 2: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]

        # NEW: Intra-trade price tracking for MFE/MAE
        if ticker in OPEN_TRADE_STATS:
            OPEN_TRADE_STATS[ticker]['max_high'] = max(OPEN_TRADE_STATS[ticker]['max_high'], curr_price)
            OPEN_TRADE_STATS[ticker]['min_low'] = min(OPEN_TRADE_STATS[ticker]['min_low'], curr_price)
        
        reclaimed = (prev_price <= avwap_floor) and (curr_price > avwap_floor)
        near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
        
        if reclaimed and ticker not in TRADED_TODAY and is_bullish:
            try:
                trading_client.get_open_position(ticker)
                TRADED_TODAY.add(ticker) 
            except:
                # EXECUTION: Uses the Shannon-style structural stop
                print(f"🚀 Signal: {ticker} reclaimed. Stop set at structural floor: ${structural_stop}")
                execute_buy_bracket(ticker, structural_stop, r2_target)
                
                OPEN_TRADE_STATS[ticker] = {
                    'entry': curr_price, 'max_high': curr_price, 'min_low': curr_price, 'signal': avwap_floor
                }
                log_trade_to_csv(ticker, 'BUY', curr_price, avwap_floor)
                
                send_telegram(f"✅ *BUY {ticker}* @ ${curr_price:.2f} | 🛡️ Stop: ${structural_stop:.2f}")
                TRADED_TODAY.add(ticker)
        if near_r1:
            try:
                trading_client.get_open_position(ticker)
                execute_partial_sell(ticker, sell_percentage=0.5)
                
                # NEW: Calculate and log MFE/MAE on Trim
                if ticker in OPEN_TRADE_STATS:
                    s = OPEN_TRADE_STATS[ticker]
                    log_trade_to_csv(ticker, 'TRIM', curr_price, r1_target, 
                                     s['max_high'] - s['entry'], s['entry'] - s['min_low'], curr_price - s['entry'])
                
                send_telegram(f"✂️ *TRIM {ticker}* @ ${curr_price:.2f}")
            except:
                pass 

def main():
    global SUMMARY_SENT_TODAY
    print("Sentinel Active. Monitoring Russell 3000 AVWAP Reclaims...")
    while True:
        tz = pytz.timezone('US/Eastern')
        now = datetime.now(tz)
        if is_market_open():
            monitor_watchlist()
            time.sleep(900) 
        else:
            if now.hour >= 16 and not SUMMARY_SENT_TODAY and now.weekday() <= 4:
                send_daily_summary()
                SUMMARY_SENT_TODAY = True
            if now.hour == 0:
                SUMMARY_SENT_TODAY = False
                TRADED_TODAY.clear() 
                OPEN_TRADE_STATS.clear()  # NEW: Reset analytics daily
            time.sleep(300)

if __name__ == "__main__":
    main()