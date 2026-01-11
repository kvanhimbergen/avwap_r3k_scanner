import pandas as pd
from anchors import anchored_vwap, get_anchor_candidates
from indicators import slope_last
from rs import relative_strength
from config import cfg

def avg_dollar_vol(df: pd.DataFrame) -> float:
    dv = (df["Close"] * df["Volume"]).rolling(20).mean().iloc[-1]
    return float(dv) if pd.notna(dv) else 0.0

def basic_filters(df: pd.DataFrame) -> bool:
    if df.empty or len(df) < 80:
        return False
    if float(df["Close"].iloc[-1]) < cfg.MIN_PRICE:
        return False
    if avg_dollar_vol(df) < cfg.MIN_AVG_DOLLAR_VOL:
        return False
    return True

def pick_best_anchor(df: pd.DataFrame, index_df: pd.DataFrame, direction: str):
    rs_now = relative_strength(df, index_df)
    px = float(df["Close"].iloc[-1])

    best = None
    best_score = -1e18

    for a in get_anchor_candidates(df):
        av = anchored_vwap(df, a["loc"])
        av_now = float(av.iloc[-1])
        av_slope = slope_last(av, n=5)

        if direction == "Long":
            if not (px > av_now and av_slope > 0 and rs_now > 0):
                continue
            dist_pct = (px - av_now) / av_now * 100
            if dist_pct > cfg.MAX_DIST_FROM_AVWAP_PCT:
                continue
            score = a["priority"] + (rs_now * 100) - abs(dist_pct)
        else:
            if not (px < av_now and av_slope < 0 and rs_now < 0):
                continue
            dist_pct = (av_now - px) / av_now * 100
            if dist_pct > cfg.MAX_DIST_FROM_AVWAP_PCT:
                continue
            score = a["priority"] + (-rs_now * 100) - abs(dist_pct)

        if score > best_score:
            best_score = score
            best = {
                "Anchor": a["name"],
                "AVWAP": av_now,
                "AVWAP_Slope": av_slope,
                "RS": rs_now,
                "Price": px,
                "DistFromAVWAP%": dist_pct,
            }

    return best

def score_candidate(df: pd.DataFrame, index_df: pd.DataFrame, direction: str):
    if not basic_filters(df):
        return None

    best = pick_best_anchor(df, index_df, direction)
    if not best:
        return None

    out = {
        "Direction": direction,
        "Price": round(best["Price"], 2),
        "AVWAP": round(best["AVWAP"], 2),
        "AVWAP_Slope": round(best["AVWAP_Slope"], 6),
        "RS": round(best["RS"], 6),
        "DistFromAVWAP%": round(best["DistFromAVWAP%"], 2),
        "Anchor": best["Anchor"],
        "AvgDollarVol20": round(avg_dollar_vol(df), 0),
    }
    return out
