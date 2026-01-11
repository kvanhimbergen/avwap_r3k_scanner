import pandas as pd
from config import cfg

def relative_strength(stock_df: pd.DataFrame, index_df: pd.DataFrame) -> float:
    stock_ret = stock_df["Close"].pct_change(cfg.RS_LOOKBACK).iloc[-1]
    idx_ret = index_df["Close"].pct_change(cfg.RS_LOOKBACK).iloc[-1]
    if pd.isna(stock_ret) or pd.isna(idx_ret):
        return 0.0
    return float(stock_ret - idx_ret)
