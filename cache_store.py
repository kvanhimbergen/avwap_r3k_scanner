import os
import time
import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

SNAPSHOT_PATH = os.path.join(CACHE_DIR, "liquidity_snapshot.parquet")
HISTORY_PATH = os.path.join(CACHE_DIR, "ohlcv_history.parquet")
META_PATH = os.path.join(CACHE_DIR, "meta.json")

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _load_meta():
    if os.path.exists(META_PATH):
        with open(META_PATH, "r") as f:
            return json.load(f)
    return {}

def _save_meta(meta):
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

def file_age_days(path: str) -> float:
    if not os.path.exists(path):
        return 1e9
    return (time.time() - os.path.getmtime(path)) / 86400.0

def read_parquet(path: str) -> pd.DataFrame:
    try:
        if not os.path.exists(path):
            return pd.DataFrame()
        return pd.read_parquet(path, engine="pyarrow")
    except Exception:
        return pd.DataFrame()


def write_parquet(df: pd.DataFrame, path: str):
    """
    Optimized write with atomic saving and memory-efficient types.
    """
    if df is None or df.empty:
        return

    # SOP: Downcast types to save memory/space
    df = df.copy()
    float_cols = ["Open", "High", "Low", "Close"]
    for col in float_cols:
        if col in df.columns:
            df[col] = df[col].astype("float32")
    
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].astype("float64") 
    
    if "Ticker" in df.columns:
        df["Ticker"] = df["Ticker"].astype("category")

    # Atomic write: Save to .tmp then rename to prevent corruption
    tmp_path = f"{path}.tmp"
    df.to_parquet(tmp_path, index=False, engine="pyarrow", compression="snappy")
    os.replace(tmp_path, path)

def upsert_history(existing: pd.DataFrame | None, newdata: pd.DataFrame) -> pd.DataFrame:
    """
    Merges new OHLCV data into the existing cache safely.
    """
    newdata = newdata.copy()
    newdata["Ticker"] = newdata["Ticker"].astype(str).str.upper()
    newdata["Date"] = pd.to_datetime(newdata["Date"]).dt.tz_localize(None)

    if existing is None or existing.empty:
        out = newdata
    else:
        existing = existing.copy()
        existing["Ticker"] = existing["Ticker"].astype(str).str.upper()
        existing["Date"] = pd.to_datetime(existing["Date"]).dt.tz_localize(None)
        out = pd.concat([existing, newdata], ignore_index=True)

    # Keep the most recent data if duplicates exist
    out = out.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    out = out.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return out

def set_meta(key: str, value):
    meta = _load_meta()
    meta[key] = value
    meta["updated_utc"] = _utc_now_iso()
    _save_meta(meta)

def get_meta(key: str, default=None):
    meta = _load_meta()
    return meta.get(key, default)
