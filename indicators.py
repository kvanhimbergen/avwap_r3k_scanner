import pandas as pd
import numpy as np

def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple Moving Average"""
    return series.rolling(n).mean()

def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential Moving Average - used for PBT logic (9/20 EMA)"""
    return s.ewm(span=n, adjust=False, min_periods=n).mean()

def true_range(df: pd.DataFrame) -> pd.Series:
    """Calculates True Range using a DataFrame input."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        (df["High"] - df["Low"]).abs(),
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr

def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range"""
    return true_range(df).rolling(n).mean()

def slope_last(s, n=5):
    s = s.dropna()
    if s is None or len(s) < n + 1:
        return np.nan
    start_val = s.iloc[-1 - n]
    end_val = s.iloc[-1]
    if start_val == 0 or pd.isna(start_val) or pd.isna(end_val):
        return np.nan
    return (end_val - start_val) / abs(start_val)


def slope(series: pd.Series, lookback: int = 20) -> pd.Series:
    """Linear Regression slope over a rolling window."""
    idx = np.arange(lookback)

    def _slope(y: np.ndarray) -> float:
        if np.any(np.isnan(y)):
            return np.nan
        x = idx
        x_mean = x.mean()
        y_mean = y.mean()
        num = ((x - x_mean) * (y - y_mean)).sum()
        den = ((x - x_mean) ** 2).sum()
        return num / den if den != 0 else np.nan

    return series.rolling(lookback, min_periods=lookback).apply(lambda y: _slope(y.values), raw=False)

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index"""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    roll_down = down.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average Directional Index - Fixed for DataFrame input"""
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr_n = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr_n
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr_n

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

def rolling_percentile(series: pd.Series, window: int, q: float) -> pd.Series:
    """Returns the q-th quantile (0-1) over a rolling window."""
    return series.rolling(window).quantile(q)

def trend_strength_score(
    df: pd.DataFrame,
    sma_len: int = 50,
    slope_lookback: int = 10,
    adx_len: int = 14,
    atr_len: int = 14,
    atr_window: int = 120,
) -> float:
    """
    Composite trend score that blends SMA slope direction, ADX strength,
    and volatility compression (ATR percentile vs. median).
    """
    if df is None or df.empty:
        return np.nan
    if "Close" not in df.columns:
        return np.nan

    close = df["Close"]
    sma_series = sma(close, sma_len)
    slope_pct = slope_last(sma_series, n=slope_lookback) * 100.0
    if np.isnan(slope_pct):
        return np.nan

    adx_series = adx(df, n=adx_len)
    if adx_series is None or adx_series.empty:
        return np.nan
    adx_now = float(adx_series.iloc[-1])

    atr_series = atr(df, n=atr_len)
    if atr_series is None or atr_series.empty:
        return np.nan
    atr_pct = (atr_series / close) * 100.0
    atr_pct_p50 = rolling_percentile(atr_pct, atr_window, 0.5)
    atr_pct_now = float(atr_pct.iloc[-1])
    atr_pct_med = float(atr_pct_p50.iloc[-1]) if not atr_pct_p50.empty else np.nan
    vol_ratio = atr_pct_now / atr_pct_med if atr_pct_med and not np.isnan(atr_pct_med) else 1.0

    slope_sign = 1.0 if slope_pct > 0 else (-1.0 if slope_pct < 0 else 0.0)
    score = (slope_pct * 2.0) + (adx_now * 0.7 * slope_sign) - (vol_ratio * 10.0)
    return float(score)


def trend_strength_series(
    df: pd.DataFrame,
    sma_len: int = 50,
    slope_lookback: int = 10,
    adx_len: int = 14,
    atr_len: int = 14,
    atr_window: int = 120,
) -> pd.Series:
    """
    Rolling trend-strength score series (same math as trend_strength_score).
    """
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float)

    close = df["Close"]
    sma_series = sma(close, sma_len)
    slope_pct = (sma_series - sma_series.shift(slope_lookback)) / sma_series.shift(slope_lookback)
    slope_pct = slope_pct * 100.0

    adx_series = adx(df, n=adx_len)
    atr_series = atr(df, n=atr_len)
    atr_pct = (atr_series / close) * 100.0
    atr_pct_p50 = rolling_percentile(atr_pct, atr_window, 0.5)
    vol_ratio = atr_pct / atr_pct_p50
    vol_ratio = vol_ratio.replace([np.inf, -np.inf], np.nan).fillna(1.0)

    slope_sign = slope_pct.apply(lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0))
    score = (slope_pct * 2.0) + (adx_series * 0.7 * slope_sign) - (vol_ratio * 10.0)
    return score

def get_pivot_targets(df: pd.DataFrame):
    """
    Calculates Daily R1 and R2 based on the previous session's H/L/C.
    Standard Floor Pivot formula:
    P = (H + L + C) / 3
    R1 = (2 * P) - L
    R2 = P + (H - L)
    """
    if df is None or len(df) < 2:
        return 0.0, 0.0
        
    # Get the most recent completed candle (Friday's data if running on Sunday)
    prev_day = df.iloc[-1]
    h = float(prev_day['High'])
    l = float(prev_day['Low'])
    c = float(prev_day['Close'])
    
    pivot = (h + l + c) / 3
    r1 = (2 * pivot) - l
    r2 = pivot + (h - l)
    
    return round(r1, 2), round(r2, 2)

