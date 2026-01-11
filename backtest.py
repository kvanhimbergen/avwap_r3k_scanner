import pandas as pd
import numpy as np
import yfinance as yf
from config import cfg
from anchors import anchored_vwap, anchor_swing_low
from indicators import slope_last
from rs import relative_strength

def market_regime_series(index_df: pd.DataFrame, chop_band_pct: float = 0.01) -> pd.Series:
    loc = anchor_swing_low(index_df, cfg.SWING_LOOKBACK)
    av = anchored_vwap(index_df, loc)
    dist = (index_df["Close"] - av) / av
    reg = pd.Series(index=index_df.index, dtype="object")
    reg[dist > chop_band_pct] = "Risk-On"
    reg[dist < -chop_band_pct] = "Risk-Off"
    reg[(dist >= -chop_band_pct) & (dist <= chop_band_pct)] = "Chop"
    return reg

def rolling_swing_avwap(df: pd.DataFrame) -> pd.Series:
    av = pd.Series(index=df.index, dtype=float)
    for i in range(cfg.SWING_LOOKBACK, len(df)):
        window = df.iloc[i-cfg.SWING_LOOKBACK:i+1]
        loc = df.index.get_loc(window["Low"].idxmin())
        av.iloc[i] = anchored_vwap(df.iloc[:i+1], loc).iloc[-1]
    return av

def backtest_symbol(symbol: str, start="2022-01-01", end=None, direction="Long", max_hold=20):
    px = yf.download(symbol, start=start, end=end, progress=False)
    idx = yf.download(cfg.INDEX, start=start, end=end, progress=False)
    if px.empty or idx.empty or len(px) < 250:
        return None

    px.columns = [c.title() for c in px.columns]
    idx.columns = [c.title() for c in idx.columns]

    regimes = market_regime_series(idx).reindex(px.index).ffill()

    avwap = rolling_swing_avwap(px)
    # basic RS scalar each day (use lookback return difference)
    rs_series = (px["Close"].pct_change(cfg.RS_LOOKBACK) - idx["Close"].pct_change(cfg.RS_LOOKBACK)).reindex(px.index)

    # signal
    if direction == "Long":
        signal = (px["Close"] > avwap) & (rs_series > 0)
        exit_cond = (px["Close"] < avwap)
    else:
        signal = (px["Close"] < avwap) & (rs_series < 0)
        exit_cond = (px["Close"] > avwap)

    trades = []
    i = cfg.SWING_LOOKBACK + cfg.RS_LOOKBACK

    while i < len(px) - 2:
        if not bool(signal.iloc[i]) or pd.isna(avwap.iloc[i]):
            i += 1
            continue

        entry_i = i + 1
        entry_date = px.index[entry_i]
        entry = float(px["Open"].iloc[entry_i])
        entry_av = float(avwap.iloc[i])
        if np.isnan(entry) or np.isnan(entry_av):
            i += 1
            continue

        # 1R proxy = distance to AVWAP at entry context (structural)
        r = max(abs(entry - entry_av), 0.01)

        exit_i = None
        last_i = min(entry_i + max_hold, len(px) - 1)

        for j in range(entry_i, last_i):
            if bool(exit_cond.iloc[j]):
                exit_i = min(j + 1, len(px) - 1)  # exit next open
                break

        if exit_i is None:
            exit_i = last_i

        exit_date = px.index[exit_i]
        exit_px = float(px["Open"].iloc[exit_i])

        if direction == "Long":
            r_mult = (exit_px - entry) / r
        else:
            r_mult = (entry - exit_px) / r

        trades.append({
            "Symbol": symbol,
            "Direction": direction,
            "EntryDate": entry_date,
            "Entry": entry,
            "ExitDate": exit_date,
            "Exit": exit_px,
            "R": r_mult,
            "Regime": regimes.iloc[i] if pd.notna(regimes.iloc[i]) else "Unknown",
        })

        i = exit_i

    return pd.DataFrame(trades)

def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()

    return (
        trades.groupby(["Direction", "Regime"])
        .agg(
            trades=("R", "count"),
            win_rate=("R", lambda x: float((x > 0).mean())),
            avg_R=("R", "mean"),
            med_R=("R", "median"),
            expectancy=("R", "mean"),
        )
        .reset_index()
        .sort_values(["Direction", "Regime"])
    )
