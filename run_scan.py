import os
import gc
import time
import warnings
import pandas as pd
import numpy as np
import yfinance as yf
from tqdm import tqdm
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

from config import cfg
from universe import load_universe
from anchors import anchored_vwap, get_anchor_candidates
from indicators import slope_last, sma, atr, rolling_percentile, get_pivot_targets
from market import spy_avwap_regime
from rs import relative_strength
import cache_store as cs

# --- Global Config & Tracking ---
BAD_TICKERS = set()
PBT_DIAG = Counter()
warnings.filterwarnings("ignore")

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

def standardize_ohlcv(df):
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Adj Close": "Close"})
    cols = ["Open", "High", "Low", "Close", "Volume"]
    return df[cols] if all(c in df.columns for c in cols) else df

def check_weekly_alignment(df):
    if len(df) < 200:
        return True
    weekly = df["Close"].resample("W-FRI").last()
    if len(weekly) < 40:
        return True
    return weekly.rolling(10).mean().iloc[-1] > weekly.rolling(40).mean().iloc[-1]

def shannon_quality_gates(df, direction):
    if df is None or len(df) < 80:
        return None
    close, px = df["Close"], float(df["Close"].iloc[-1])
    is_weekend = datetime.now().weekday() >= 5

    s20, s50 = sma(close, 20), sma(close, 50)
    s20n, s50n = float(s20.iloc[-1]), float(s50.iloc[-1])
    s50_slope = slope_last(s50, n=10)

    atr14 = atr(df, 14)
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
    if not (
        trend_ok
        and atr_pct_now <= (6.5 if is_weekend else 6.0)
        and atr_pct_now <= (atr_pct_p50 * vol_mult)
    ):
        return None

    return {
        "TrendTier": label,
        "SMA20": round(s20n, 2),
        "SMA50": round(s50n, 2),
        "ATR%": round(atr_pct_now, 2),
    }

def _get_avwap_slope_threshold(direction: str, is_weekend: bool) -> float:
    """
    Configurable AVWAP slope thresholds:
      - If you add MIN_AVWAP_SLOPE_LONG / MIN_AVWAP_SLOPE_SHORT to cfg, they'll be used.
      - Otherwise sensible defaults apply.
    """
    if direction == "Long":
        # Default: allow slightly negative slope (broadens list materially)
        default = -0.03 if not is_weekend else -0.05
        return float(getattr(cfg, "MIN_AVWAP_SLOPE_LONG", default))
    else:
        # Default: allow slightly positive slope for shorts (mirrors long logic)
        default = 0.03 if not is_weekend else 0.05
        return float(getattr(cfg, "MIN_AVWAP_SLOPE_SHORT", default))

def pick_best_anchor(df: pd.DataFrame, index_df: pd.DataFrame, direction: str):
    if df is None or len(df) < 2:
        return None

    px, prev_px = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    rs_now = relative_strength(df, index_df)
    is_weekend = datetime.now().weekday() >= 5
    best, best_score = None, -1e18

    # AVWAP slope settings
    slope_n = int(getattr(cfg, "AVWAP_SLOPE_LOOKBACK", 5))
    slope_thr = _get_avwap_slope_threshold(direction, is_weekend)

    # Reclaim bypass toggle (defaults to True if not present in config)
    reclaim_bypass = bool(getattr(cfg, "AVWAP_SLOPE_BYPASS_ON_RECLAIM", True))

    for a in get_anchor_candidates(df):
        av = anchored_vwap(df, a["loc"])

        # Need enough bars to compute slope robustly
        if len(av) <= slope_n:
            continue

        av_clean = av.dropna()
        # slope_last needs at least n+1 points
        if len(av_clean) < (slope_n + 1):
            continue

        av_now = float(av_clean.iloc[-1])

        av_s = slope_last(av_clean, n=slope_n)
        if np.isnan(av_s):
            continue


        # Reclaim and Distance Logic
        is_reclaim = (
            (prev_px <= av_now and px > av_now) if direction == "Long"
            else (prev_px >= av_now and px < av_now)
        )

        dist = (
            (px - av_now) / av_now * 100.0 if direction == "Long"
            else (av_now - px) / av_now * 100.0
        )

        # Core relationship to AVWAP: must be above (or reclaim) for longs; below (or reclaim) for shorts
        if direction == "Long":
            if not (px > av_now or is_reclaim):
                PBT_DIAG["drop_not_above_or_reclaim"] += 1
                continue
            slope_ok = (av_s >= slope_thr)
            # Broadening: allow reclaims to pass even if slope is not yet positive/acceptable
            if not slope_ok and not (reclaim_bypass and is_reclaim):
                PBT_DIAG["drop_avwap_slope_fail"] += 1
                continue
            if dist > cfg.MAX_DIST_FROM_AVWAP_PCT:
                PBT_DIAG["drop_dist_too_far"] += 1
                continue
        else:
            if not (px < av_now or is_reclaim):
                PBT_DIAG["drop_not_below_or_reclaim"] += 1
                continue
            slope_ok = (av_s <= slope_thr)
            if not slope_ok and not (reclaim_bypass and is_reclaim):
                PBT_DIAG["drop_avwap_slope_fail"] += 1
                continue
            if dist > cfg.MAX_DIST_FROM_AVWAP_PCT:
                PBT_DIAG["drop_dist_too_far"] += 1
                continue

        # Scoring
        score = (
            a["priority"]
            + (rs_now * 100.0)
            - abs(dist)
            + (50.0 if 0.1 <= dist <= 1.5 else 0.0)
            + (40.0 if is_reclaim else 0.0)
        )

        if score > best_score:
            best_score, best = score, (a["name"], av_now, av_s, rs_now, dist)

    return best

def build_liquidity_snapshot(universe, index_df):
    is_weekend = datetime.now().weekday() >= 5
    tickers = [
        t.upper() for t in universe["Ticker"].tolist()
        if is_valid_ticker(t) and t not in BAD_TICKERS
    ]
    rows = []

    # SAFE BATCHING: Smaller chunks to avoid Yahoo rate limits
    batch_size = 50
    for i in tqdm(range(0, len(tickers), batch_size), desc="Snapshot"):
        batch = tickers[i : i + batch_size]
        try:
            dfb = yf.download(batch, period="2mo", group_by="ticker", progress=False, threads=False)
            if dfb.empty:
                continue
            for t in batch:
                try:
                    sub = dfb[t] if len(batch) > 1 else dfb
                    sub = standardize_ohlcv(sub).dropna()
                    if len(sub) < 15:
                        BAD_TICKERS.add(t)
                        continue
                    dv = (sub["Close"] * sub["Volume"]).mean()
                    if dv < (10_000_000 if is_weekend else cfg.MIN_AVG_DOLLAR_VOL):
                        continue
                    rows.append(
                        {
                            "Ticker": t,
                            "AvgDollarVol20": dv,
                            "Sector": universe.loc[universe["Ticker"] == t, "Sector"].values[0],
                            "RS20": relative_strength(sub, index_df),
                        }
                    )
                except:
                    continue
            time.sleep(0.5)  # Anti-bot pause
        except:
            continue

    snap = pd.DataFrame(rows)
    if snap.empty:
        return snap

    if is_weekend:
        # WEEKEND SOP: Maximum Breadth. Take the top N by liquidity, period.
        print(f"Weekend Mode: Scanning top {cfg.SNAPSHOT_MAX_TICKERS} liquid stocks across all sectors.")
        return snap.sort_values("AvgDollarVol20", ascending=False).head(cfg.SNAPSHOT_MAX_TICKERS)

    # WEEKDAY SOP: Precision. Only look at top sectors.
    sector_rank = (
        snap.groupby("Sector")["RS20"]
        .mean()
        .sort_values(ascending=False)
        .head(cfg.TOP_SECTORS_TO_SCAN)
        .index
    )
    return (
        snap[snap["Sector"].isin(sector_rank)]
        .sort_values("AvgDollarVol20", ascending=False)
        .head(cfg.SNAPSHOT_MAX_TICKERS)
    )

def main():
    is_weekend = datetime.now().weekday() >= 5
    if is_weekend:
        cfg.TOP_SECTORS_TO_SCAN = 11
        cfg.SNAPSHOT_MAX_TICKERS = 3000
        cfg.MAX_DIST_FROM_AVWAP_PCT = 6.0
        cfg.PBT_REQUIRE_TRIGGER = False

    global BAD_TICKERS
    BAD_TICKERS = load_bad_tickers()
    universe = load_universe()
    index_df = standardize_ohlcv(yf.download("SPY", period="2y", progress=False))

    # Always rebuild snapshot on weekend to ensure delisted tickers are purged
    snap = build_liquidity_snapshot(universe, index_df)
    filtered = snap["Ticker"].tolist()

    # SAFE HISTORY REFRESH: Progress Bar + Column Stacking
    history = cs.read_parquet("cache/ohlcv_history.parquet")
    batch_size = 100
    for i in tqdm(range(0, len(filtered), batch_size), desc="History Refresh"):
        batch = filtered[i : i + batch_size]
        raw_new = yf.download(batch, period="10d", group_by="ticker", progress=False, threads=False)
        if not raw_new.empty:
            if isinstance(raw_new.columns, pd.MultiIndex):
                # Convert 'wide' columns into 'long' rows with Ticker column
                newdata = raw_new.stack(level=0, future_stack=True).reset_index()
                newdata.rename(columns={"level_1": "Ticker"}, inplace=True)
            else:
                newdata = raw_new.reset_index()
                newdata["Ticker"] = batch[0]
            if "Adj Close" in newdata.columns:
                newdata = newdata.rename(columns={"Adj Close": "Close"})
            history = cs.upsert_history(history, newdata)
        time.sleep(0.5)

    results = []
    for t in tqdm(filtered, desc="Scanning"):
        d_filtered = history[history["Ticker"] == t].copy()
        if d_filtered.empty or len(d_filtered) < 80:
            continue
        df = d_filtered.set_index("Date").sort_index()

        if not is_weekend and not check_weekly_alignment(df): continue

        gates = shannon_quality_gates(df, "Long")
        if not gates:
            PBT_DIAG["drop_shannon_gates"] += 1
            continue

        best = pick_best_anchor(df, index_df, "Long")
        if best:
            name, av, avs, rs, d = best
            r1, r2 = get_pivot_targets(df)
            curr_price = round(df["Close"].iloc[-1], 2)

            results.append(
                {
                    "Ticker": t,
                    "TrendTier": gates["TrendTier"],
                    "Price": curr_price,
                    "AVWAP_Floor": round(av, 2),
                    "Dist%": round(d, 2),
                    "R1_Trim": r1,
                    "R2_Target": r2,
                    "RS": round(rs, 6),
                    "Sector": snap.loc[snap["Ticker"]==t, "Sector"].values[0],
                    "Anchor": name
                }
            )
        else:
            PBT_DIAG["drop_no_anchor_passed_filters"] += 1

    out = pd.DataFrame(results)
    if not out.empty:
        out["TrendTier"] = pd.Categorical(out["TrendTier"], categories=["A", "B"], ordered=True)
        # Sort by RS so the strongest stocks are at the top
        out = out.sort_values(["TrendTier", "RS"], ascending=[True, False]).head(cfg.CANDIDATE_CAP)
        
        out.to_csv("daily_candidates.csv", index=False)
        out[["Ticker"]].to_csv("tos_watchlist_import.csv", index=False)
        print("\n--- TOP CANDIDATES WITH TARGETS ---")
        print(out[["Ticker", "TrendTier", "Price", "AVWAP_Floor", "R1_Trim", "R2_Target"]].head(20))

    # Diagnostics (prints top reasons this run)
    if len(PBT_DIAG) > 0:
        print("\n--- DIAGNOSTICS (Top drop reasons) ---")
        for k, v in PBT_DIAG.most_common(20):
            print(f"{k:34s} {v}")

    save_bad_tickers(BAD_TICKERS)

if __name__ == "__main__":
    main()
