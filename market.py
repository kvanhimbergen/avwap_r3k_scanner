import pandas as pd
from anchors import anchored_vwap, anchor_swing_low
from config import cfg

def spy_avwap_regime(index_df: pd.DataFrame, chop_band_pct: float = 0.01) -> tuple[str, float]:
    """
    Returns (Regime, DistPct) based on SPY vs its swing-low anchored AVWAP.
    """
    loc = anchor_swing_low(index_df, cfg.SWING_LOOKBACK)
    av = anchored_vwap(index_df, loc)
    px = float(index_df["Close"].iloc[-1])
    av_now = float(av.iloc[-1])
    dist = (px - av_now) / av_now

    if dist > chop_band_pct:
        return "Risk-On", dist * 100
    if dist < -chop_band_pct:
        return "Risk-Off", dist * 100
    return "Chop", dist * 100
