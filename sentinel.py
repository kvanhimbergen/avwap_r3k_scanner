import time
import os
import pandas as pd
import csv
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from alerts.slack import slack_alert

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
WATCHLIST_FILE = "daily_candidates.csv"
TRADE_LOG = "trade_log.csv"
TZ_ET = pytz.timezone("US/Eastern")

def now_et_str() -> str:
    return datetime.now(TZ_ET).strftime("%Y-%m-%d %H:%M:%S %Z")

# State Tracking
SUMMARY_SENT_TODAY = False
TRADED_TODAY = set()
OPEN_TRADE_STATS = {} 

# Initialize Alpaca Data Client
data_client = StockHistoricalDataClient(
    os.getenv('APCA_API_KEY_ID'), 
    os.getenv('APCA_API_SECRET_KEY')
)

def log_trade_to_csv(ticker, side, price, signal_price, mfe=0, mae=0, pnl=0):
    file_exists = os.path.isfile(TRADE_LOG)
    with open(TRADE_LOG, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Timestamp', 'Ticker', 'Side', 'Price', 'Signal_Price', 'Slippage', 'MFE', 'MAE', 'PnL'])
        slippage = price - signal_price if side == 'BUY' else signal_price - price
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
            ticker, side, price, signal_price, 
            round(slippage, 4), round(mfe, 2), round(mae, 2), round(pnl, 2)
        ])

def send_daily_summary():
    try:
        data = get_daily_summary_data()
        pnl_emoji = "📈" if data['daily_pnl'] >= 0 else "📉"
        msg = f"Equity: ${data['equity']:,.2f} | {pnl_emoji} PnL: ${data['daily_pnl']:,.2f}"
        slack_alert(
            "INFO",
            "Daily summary",
            msg,
            component="SENTINEL",
            throttle_key=f"summary_{datetime.now(TZ_ET).date()}",
            throttle_seconds=3600,
        )
    except Exception as e:
        print(f"Summary Error: {e}")

def is_market_open():
    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    if now.weekday() > 4: return False
    return now.replace(hour=9, minute=30) <= now <= now.replace(hour=16, minute=0)

def get_market_regime():
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
    try:
        req = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute * 5, start=datetime.now() - timedelta(days=2))
        bars = data_client.get_stock_bars(req).df
        if bars is None or bars.empty: return None
        return bars.reset_index().rename(columns={'close': 'Close'})
    except:
        return None

def monitor_watchlist():
    is_bullish = get_market_regime()

    # --- Watchlist staleness + load diagnostics ---
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(WATCHLIST_FILE), TZ_ET)
    except FileNotFoundError:
        print(f"[{now_et_str()}] WATCHLIST missing: {WATCHLIST_FILE} (skipping)", flush=True)
        return
    except Exception as e:
        print(f"[{now_et_str()}] WATCHLIST stat error: {WATCHLIST_FILE} | {e}", flush=True)
        return

    today_et = datetime.now(TZ_ET).date()
    if mtime.date() != today_et:
        print(
            f"[{now_et_str()}] WATCHLIST stale: {WATCHLIST_FILE} | mtime={mtime.strftime('%Y-%m-%d %H:%M:%S %Z')} | today={today_et} (skipping trades)",
            flush=True,
        )
        return

    try:
        watchlist = pd.read_csv(WATCHLIST_FILE)
    except Exception as e:
        print(f"[{now_et_str()}] WATCHLIST read error: {WATCHLIST_FILE} | {e}", flush=True)
        return

    print(f"[{now_et_str()}] WATCHLIST loaded: {WATCHLIST_FILE} | rows={len(watchlist)} | regime={'BULLISH' if is_bullish else 'BEARISH'}", flush=True)

    if watchlist.empty:
        print(f"[{now_et_str()}] WATCHLIST empty (no candidates).", flush=True)
        return

    for _, row in watchlist.iterrows():
        ticker = row['Ticker']
        avwap_floor = float(row['AVWAP_Floor'])
        r1_target = float(row['R1_Trim'])
        
        # FIX: Use .get() to prevent crash if column is missing
        structural_stop = float(row.get('Stop_Loss', avwap_floor * 0.985))
        r2_target = float(row.get('R2_Target', r1_target * 1.05))
        
        df = get_alpaca_intraday(ticker) 
        if df is None or len(df) < 2: continue
        
        curr_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]

        if ticker in OPEN_TRADE_STATS:
            OPEN_TRADE_STATS[ticker]['max_high'] = max(OPEN_TRADE_STATS[ticker]['max_high'], curr_price)
            OPEN_TRADE_STATS[ticker]['min_low'] = min(OPEN_TRADE_STATS[ticker]['min_low'], curr_price)
        
        reclaimed = (prev_price <= avwap_floor) and (curr_price > avwap_floor)
        
        if reclaimed and ticker not in TRADED_TODAY and is_bullish:
            try:
                trading_client.get_open_position(ticker)
                TRADED_TODAY.add(ticker) 
            except:
                print(f"🚀 Signal: {ticker} reclaimed. Stop: ${structural_stop}")
                execute_buy_bracket(ticker, structural_stop, r2_target)
                OPEN_TRADE_STATS[ticker] = {'entry': curr_price, 'max_high': curr_price, 'min_low': curr_price, 'signal': avwap_floor}
                log_trade_to_csv(ticker, 'BUY', curr_price, avwap_floor)
                slack_alert(
                    "TRADE",
                    f"BUY {ticker}",
                    f"placed @ ${curr_price:.2f} | stop=${structural_stop:.2f} | r2=${r2_target:.2f}",
                    component="SENTINEL",
                    throttle_key=f"buy_{ticker}",
                    throttle_seconds=60,
                )
                TRADED_TODAY.add(ticker)

        # Optimization: Only check for trim if we actually own the stock
        if ticker in OPEN_TRADE_STATS:
            near_r1 = abs(curr_price - r1_target) / r1_target < 0.002
            if near_r1:
                try:
                    execute_partial_sell(ticker, sell_percentage=0.5)
                    s = OPEN_TRADE_STATS[ticker]
                    log_trade_to_csv(ticker, 'TRIM', curr_price, r1_target, s['max_high'] - s['entry'], s['entry'] - s['min_low'], curr_price - s['entry'])
                    slack_alert(
                        "TRADE",
                        f"TRIM {ticker}",
                        f"partial sell @ ${curr_price:.2f} near r1=${r1_target:.2f}",
                        component="SENTINEL",
                        throttle_key=f"trim_{ticker}",
                        throttle_seconds=120,
                    )
                    # Remove from tracking after trim if you wish, or keep for R2 tracking
                except: pass

def main():
    global SUMMARY_SENT_TODAY
    load_dotenv(dotenv_path="/root/avwap_r3k_scanner/.env")

    print(f"[{now_et_str()}] Sentinel Active. Monitoring Russell 3000 AVWAP Reclaims...", flush=True)
    slack_alert(
        "INFO",
        "Sentinel started",
        f"Sentinel active at {now_et_str()} (service start).",
        component="SENTINEL",
        throttle_key="sentinel_start",
        throttle_seconds=300,
    )

    while True:
        if is_market_open():
            monitor_watchlist()
            print(f"[{now_et_str()}] Heartbeat: market OPEN; next check in 900s", flush=True)
            time.sleep(900) 
        else:
            now = datetime.now(pytz.timezone('US/Eastern'))
            if now.hour >= 16 and not SUMMARY_SENT_TODAY and now.weekday() <= 4:
                send_daily_summary()
                SUMMARY_SENT_TODAY = True
            if now.hour == 0:
                SUMMARY_SENT_TODAY = False
                TRADED_TODAY.clear() 
                OPEN_TRADE_STATS.clear()
            print(f"[{now_et_str()}] Heartbeat: market CLOSED; next check in 300s", flush=True)
            time.sleep(300)

if __name__ == "__main__":
    main()
