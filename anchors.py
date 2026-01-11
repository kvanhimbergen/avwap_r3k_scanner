import numpy as np
import pandas as pd
from config import cfg

def anchored_vwap(df: pd.DataFrame, anchor_loc: int) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    vol = df["Volume"].astype(float)

    out = pd.Series(index=df.index, dtype=float)
    out.iloc[:anchor_loc] = np.nan
    tp2 = tp.iloc[anchor_loc:]
    v2 = vol.iloc[anchor_loc:]
    out.iloc[anchor_loc:] = (tp2 * v2).cumsum() / v2.cumsum()
    return out

def _loc_of_idx(df: pd.DataFrame, idx) -> int:
    return int(df.index.get_loc(idx))

def anchor_swing_low(df: pd.DataFrame, lookback: int) -> int:
    idx = df["Low"].iloc[-lookback:].idxmin()
    return _loc_of_idx(df, idx)

def anchor_swing_high(df: pd.DataFrame, lookback: int) -> int:
    idx = df["High"].iloc[-lookback:].idxmax()
    return _loc_of_idx(df, idx)

def anchor_gap_day(df: pd.DataFrame, lookback: int, gap_pct: float):
    d = df.iloc[-lookback:].copy()
    prev_close = d["Close"].shift(1)
    gap = (d["Open"] - prev_close).abs() / prev_close
    cand = gap[gap >= gap_pct]
    if cand.empty:
        return None
    return _loc_of_idx(df, cand.index[-1])

def anchor_vol_breakout(df: pd.DataFrame, lookback: int, vol_mult: float):
    d = df.iloc[-lookback:].copy()
    
    # 1. Volume Spike: Must be significantly higher than the 20-day average
    vavg = d["Volume"].rolling(20).mean()
    vol_spike = d["Volume"] > (vavg * vol_mult)

    # 2. Price Strength (Range): Close must be in the top 30% of the day's range
    rng = (d["High"] - d["Low"]).replace(0, np.nan)
    close_in_upper_range = ((d["Close"] - d["Low"]) / rng) > 0.7

    # 3. ENHANCEMENT: Price must also close above the highest high of the last 5 days
    # This ensures the 'breakout' is actually breaking out of a recent range.
    highest_high_5d = d["High"].shift(1).rolling(5).max()
    is_new_high = d["Close"] > highest_high_5d

    # Combine all logic
    idxs = d.index[vol_spike & close_in_upper_range & is_new_high]
    
    if len(idxs) == 0:
        return None
        
    return _loc_of_idx(df, idxs[-1])

def anchor_calendar_start(df: pd.DataFrame, freq='YS') -> int:
    """
    Finds the first trading day of the year (YS) or month (MS).
    """
    try:
        # Get the start date of the period
        start_date = df.index[-1].to_period(freq).to_timestamp()
        # Find the first available trading day on or after that start_date
        actual_start_idx = df.index[df.index >= start_date][0]
        return _loc_of_idx(df, actual_start_idx)
    except Exception:
        # Fallback to the very beginning of the dataframe if calculation fails
        return 0

def get_anchor_candidates(df: pd.DataFrame) -> list[dict]:
    # FIX: Initialize the list inside the function
    anchors = []
    
    # 1. Calendar Anchors (High Priority)
    ytd_loc = anchor_calendar_start(df, 'YS')
    anchors.append({"name": "YTD", "loc": ytd_loc, "priority": 100})
    
    mtd_loc = anchor_calendar_start(df, 'MS')
    anchors.append({"name": "MTD", "loc": mtd_loc, "priority": 70})

    # 2. Event Anchors
    g = anchor_gap_day(df, cfg.ANCHOR_LOOKBACK, cfg.GAP_PCT)
    if g is not None:
        anchors.append({"name": f"Gap{int(cfg.GAP_PCT*100)}%", "loc": g, "priority": 90})

    b = anchor_vol_breakout(df, cfg.ANCHOR_LOOKBACK, cfg.VOL_SPIKE_MULT)
    if b is not None:
        anchors.append({"name": "VolBreakout", "loc": b, "priority": 80})

    # 3. Structural Anchors
    anchors.append({"name": f"SwingLow{cfg.SWING_LOOKBACK}", "loc": anchor_swing_low(df, cfg.SWING_LOOKBACK), "priority": 50})
    anchors.append({"name": f"SwingHigh{cfg.SWING_LOOKBACK}", "loc": anchor_swing_high(df, cfg.SWING_LOOKBACK), "priority": 40})

    # De-duplicate by location, keeping the highest priority anchor at that spot
    by_loc = {}
    for a in anchors:
        if (a["loc"] not in by_loc) or (a["priority"] > by_loc[a["loc"]]["priority"]):
            by_loc[a["loc"]] = a
            
    return sorted(by_loc.values(), key=lambda x: x["priority"], reverse=True)