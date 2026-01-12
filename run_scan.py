import os
import warnings
import pandas as pd
import numpy as np
import yfinance as yf  # Added for earnings check
import pytz
from tqdm import tqdm
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

# Modern Alpaca-py imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Your local modules
from config import cfg
from universe import load_universe
from anchors import anchored_vwap, get_anchor_candidates
from indicators import slope_last, sma, atr, rolling_percentile, get_pivot_targets
from rs import relative_strength
import cache_store as cs

# --- Global Config & Tracking ---
BAD_TICKERS = set()
PBT_DIAG = Counter()
warnings.filterwarnings("ignore")

# ALGO TWEAK CONFIGS
ADV_MIN_SHARES = 750000  # Minimum 750k shares avg daily volume
ATR_MIN_DOLLARS = 0.50   # Minimum $0.50 average daily range
ALGO_CANDIDATE_CAP = 20  # Limit to top 20 for the execution bot

def load_bad_tickers():
    path = Path("cache/bad_tickers.txt")
    if path.exists():
        return set(x.strip().upper() for x in path.read_text().splitlines() if x.strip())
    return set()

def save_bad_tickers(bt_set):
    os.makedirs("cache", exist_ok=True)
    Path("cache/bad_tickers.txt").write_text("\n".join(sorted(list(bt_set))))

def is_valid_ticker(t):
    return isinstance(t, str) and 1 <= len(t) <= 6 and t.isalpha()

def standardize_alpaca_to_yf(df):
    if df.empty: return df
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
    
    rename_map = {
        'symbol': 'Ticker', 'timestamp': 'Date', 'open': 'Open',
        'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    }
    df = df.rename(columns=rename_map)
    df['Date'] = pd.to_datetime(df['Date'])
    return df

# TWEAK 1: Market Regime Filter
def get_market_regime(client):
    """Checks if SPY is above its 200-day SMA."""
    try:
        spy_req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=datetime.now() - timedelta(days=300))
        df = standardize_alpaca_to_yf(client.get_stock_bars(spy_req).df)
        df['SMA200'] = df['Close'].rolling(window=200).mean()
        curr_price = df['Close'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        return curr_price > sma200
    except:
        return True # Default to True if check fails to avoid blocking scan

# TWEAK 2: Earnings Date Check
def is_near_earnings(ticker):
    """Excludes stocks reporting earnings in the next 48 hours using robust method."""
    try:
        stock = yf.Ticker(ticker)
        # TWEAK: get_earnings_dates is more reliable than .calendar
        dates = stock.get_earnings_dates()
        if dates is not None and not dates.empty:
            # Check for the closest future earnings date
            future_earnings = dates[dates.index > datetime.now(pytz.utc)]
            if not future_earnings.empty:
                next_earnings = future_earnings.index[0]
                days_to_earnings = (next_earnings.date() - datetime.now().date()).days
                return 0 <= days_to_earnings <= 2
    except:
        return False
    return False

def check_weekly_alignment(df):
    if len(df) < 200: return True
    weekly = df["Close"].resample("W-FRI").last()
    if len(weekly) < 40: return True
    return weekly.rolling(10).mean().iloc[-1] > weekly.rolling(40).mean().iloc[-1]

def shannon_quality_gates(df, direction):
    if df is None or len(df) < 80: return None
    close, px = df["Close"], float(df["Close"].iloc[-1])
    is_weekend = datetime.now().weekday() >= 5

    s20, s50 = sma(close, 20), sma(close, 50)
    s20n, s50n = float(s20.iloc[-1]), float(s50.iloc[-1])
    s50_slope = slope_last(s50, n=10)

    # TWEAK 3: ATR Minimum check
    atr14 = atr(df, 14)
    atr_now = float(atr14.iloc[-1])
    if atr_now < ATR_MIN_DOLLARS: return None

    atr_pct = (atr14 / close) * 100.0
    atr_pct_now = float(atr_pct.iloc[-1])
    atr_pct_p50 = float(rolling_percentile(atr_pct, 120, 0.50).iloc[-1])

    if direction == "Long":
        tier_a = (px > s20n) and (s20n >= s50n)
        tier_b = (px > s50n) and (s50_slope > 0)
        trend_ok = tier_a or (is_weekend and tier_b)
        label = "A" if tier_a else "B"
    else:
        tier_a = (px < s20n) and (s20n <= s50n)
        tier_b = (px < s50n) and (s50_slope < 0)
        trend_ok = tier_a or (is_weekend and tier_b)
        label = "A" if tier_a else "B"

    vol_mult = 1.25 if is_weekend else 1.0
    if not (trend_ok and atr_pct_now <= (6.5 if is_weekend else 6.0) and atr_pct_now <= (atr_pct_p50 * vol_mult)):
        return None

    return {"TrendTier": label, "SMA20": round(s20n, 2), "SMA50": round(s50n, 2), "ATR%": round(atr_pct_now, 2)}

def _get_avwap_slope_threshold(direction: str, is_weekend: bool) -> float:
    if direction == "Long":
        default = -0.03 if not is_weekend else -0.05
        return float(getattr(cfg, "MIN_AVWAP_SLOPE_LONG", default))
    return float(getattr(cfg, "MIN_AVWAP_SLOPE_SHORT", 0.03 if not is_weekend else 0.05))

def pick_best_anchor(df: pd.DataFrame, index_df: pd.DataFrame, direction: str):
    if df is None or len(df) < 2: return None
    px, prev_px = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    rs_now = relative_strength(df, index_df)
    is_weekend = datetime.now().weekday() >= 5
    best, best_score = None, -1e18

    slope_n = int(getattr(cfg, "AVWAP_SLOPE_LOOKBACK", 5))
    slope_thr = _get_avwap_slope_threshold(direction, is_weekend)
    reclaim_bypass = bool(getattr(cfg, "AVWAP_SLOPE_BYPASS_ON_RECLAIM", True))

    for a in get_anchor_candidates(df):
        av = anchored_vwap(df, a["loc"])
        if len(av) <= slope_n: continue
        av_clean = av.dropna()
        if len(av_clean) < (slope_n + 1): continue

        av_now = float(av_clean.iloc[-1])
        av_s = slope_last(av_clean, n=slope_n)
        if np.isnan(av_s): continue

        is_reclaim = (prev_px <= av_now and px > av_now) if direction == "Long" else (prev_px >= av_now and px < av_now)
        dist = (px - av_now) / av_now * 100.0 if direction == "Long" else (av_now - px) / av_now * 100.0

        if direction == "Long":
            if not (px > av_now or is_reclaim): continue
            if not (av_s >= slope_thr) and not (reclaim_bypass and is_reclaim): continue
        else:
            if not (px < av_now or is_reclaim): continue
            if not (av_s <= slope_thr) and not (reclaim_bypass and is_reclaim): continue
        
        if dist > cfg.MAX_DIST_FROM_AVWAP_PCT: continue

        score = a["priority"] + (rs_now * 100.0) - abs(dist) + (50.0 if 0.1 <= dist <= 1.5 else 0.0) + (40.0 if is_reclaim else 0.0)
        if score > best_score:
            best_score, best = score, (a["name"], av_now, av_s, rs_now, dist)
    return best

def build_liquidity_snapshot(universe, index_df, data_client):
    is_weekend = datetime.now().weekday() >= 5
    tickers = [t.upper() for t in universe["Ticker"].tolist() if is_valid_ticker(t) and t not in BAD_TICKERS]
    rows = []
    batch_size = 100
    start_date = datetime.now() - timedelta(days=45)
    
    for i in tqdm(range(0, len(tickers), batch_size), desc="Snapshot"):
        batch = tickers[i : i + batch_size]
        try:
            req = StockBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=start_date)
            bars_data = data_client.get_stock_bars(req)
            if not bars_data: continue
            df_all = standardize_alpaca_to_yf(bars_data.df)
            for t in batch:
                sub = df_all[df_all['Ticker'] == t].copy()
                if len(sub) < 15: continue
                
                # TWEAK 3: Share Volume floor
                avg_vol_shares = sub["Volume"].tail(20).mean()
                if avg_vol_shares < ADV_MIN_SHARES: continue

                dv = (sub["Close"] * sub["Volume"]).mean()
                if dv < (10_000_000 if is_weekend else cfg.MIN_AVG_DOLLAR_VOL): continue
                
                rows.append({
                    "Ticker": t, "AvgDollarVol20": dv,
                    "Sector": universe.loc[universe["Ticker"] == t, "Sector"].values[0],
                    "RS20": relative_strength(sub.set_index('Date'), index_df),
                })
        except: continue
    snap = pd.DataFrame(rows)
    if snap.empty: return snap
    if is_weekend: return snap.sort_values("AvgDollarVol20", ascending=False).head(cfg.SNAPSHOT_MAX_TICKERS)
    sector_rank = snap.groupby("Sector")["RS20"].mean().sort_values(ascending=False).head(cfg.TOP_SECTORS_TO_SCAN).index
    return snap[snap["Sector"].isin(sector_rank)].sort_values("AvgDollarVol20", ascending=False).head(cfg.SNAPSHOT_MAX_TICKERS)

def send_telegram(message):
    """Sends a notification to Telegram when the scan completes."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        import requests
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Notification Error: {e}")

def main():
    load_dotenv()
    data_client = StockHistoricalDataClient(os.getenv('APCA_API_KEY_ID'), os.getenv('APCA_API_SECRET_KEY'))
    
    # TWEAK 1: Market Regime Check
    if not get_market_regime(data_client):
        print("⚠️ Market Regime Bearish (SPY < 200 SMA). Skipping scan to protect capital.")
        return

    is_weekend = datetime.now().weekday() >= 5
    if is_weekend:
        cfg.TOP_SECTORS_TO_SCAN, cfg.SNAPSHOT_MAX_TICKERS = 11, 3000

    global BAD_TICKERS
    BAD_TICKERS = load_bad_tickers()
    universe = load_universe()
    
    spy_req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=datetime.now() - timedelta(days=730))
    index_df = standardize_alpaca_to_yf(data_client.get_stock_bars(spy_req).df).set_index('Date')

    snap = build_liquidity_snapshot(universe, index_df, data_client)
    filtered = snap["Ticker"].tolist()

    history = cs.read_parquet("cache/ohlcv_history.parquet")
    batch_size = 200
    hist_start = datetime.now() - timedelta(days=15)
    
    for i in tqdm(range(0, len(filtered), batch_size), desc="History Refresh"):
        batch = filtered[i : i + batch_size]
        try:
            req = StockBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=hist_start)
            raw_new = data_client.get_stock_bars(req).df
            if not raw_new.empty:
                newdata = standardize_alpaca_to_yf(raw_new)
                history = cs.upsert_history(history, newdata)
        except: continue

    # ... (Keep existing imports and helper functions) ...

    results = []
    for t in tqdm(filtered, desc="Scanning"):
        if is_near_earnings(t): continue

        d_filtered = history[history["Ticker"] == t].copy()
        if d_filtered.empty or len(d_filtered) < 80: continue
        df = d_filtered.set_index("Date").sort_index()

        if not is_weekend and not check_weekly_alignment(df): continue

        gates = shannon_quality_gates(df, "Long")
        if not gates: continue

        # NEW: Calculate Structural Stop Levels (Shannon Style)
        df['SMA5'] = sma(df['Close'], 5)
        df['Low5'] = df['Low'].rolling(window=5).min()
        
        curr_sma5 = float(df['SMA5'].iloc[-1])
        curr_low5 = float(df['Low5'].iloc[-1])
        
        # Determine logical stop: The lower of the 5-DMA or 5-Day Low with a 0.3% buffer
        structural_stop = min(curr_sma5, curr_low5) * 0.997 

        best = pick_best_anchor(df, index_df, "Long")
        if best:
            name, av, avs, rs, d = best
            r1, r2 = get_pivot_targets(df)
            results.append({
                "Ticker": t, 
                "TrendTier": gates["TrendTier"], 
                "Price": round(df["Close"].iloc[-1], 2),
                "AVWAP_Floor": round(av, 2), 
                "Stop_Loss": round(structural_stop, 2),  # NEW: Added structural stop column
                "Dist%": round(d, 2), 
                "R1_Trim": r1, 
                "R2_Target": r2, 
                "RS": round(rs, 6), 
                "Sector": snap.loc[snap["Ticker"]==t, "Sector"].values[0], 
                "Anchor": name
            })

    # ... (Keep sorting and saving logic) ...
    out = pd.DataFrame(results)
    if not out.empty:
        # TWEAK 4 & 5: RS Ranking and Auto-Culling to Top 20
        out = out.sort_values(["TrendTier", "RS"], ascending=[True, False]).head(ALGO_CANDIDATE_CAP)
        out.to_csv("daily_candidates.csv", index=False)
        send_telegram(f"✅ *Scan Complete*: {len(out)} top candidates saved to `daily_candidates.csv` and ready for Sentinel.")
        print("\n--- ALGO-READY TOP CANDIDATES ---")
        print(out[["Ticker", "TrendTier", "Price", "AVWAP_Floor", "R1_Trim", "R2_Target", "RS"]].head(20))
    save_bad_tickers(BAD_TICKERS)

if __name__ == "__main__":
    main()