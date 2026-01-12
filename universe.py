import io
import requests
import pandas as pd
import os
from pathlib import Path
from config import cfg

# --- CONFIGURATION ---
LOCAL_CACHE_PATH = "cache/iwv_holdings.csv"

def _clean_ishares_data(raw_text: str) -> pd.DataFrame:
    """Helper to find the 'Ticker' header and clean data with auto-delimiter detection."""
    raw = raw_text.splitlines()
    
    # 1. Flexible Header Search: Find the row containing 'Ticker'
    header_row_idx = None
    for i, line in enumerate(raw[:80]):
        # Strip whitespace and check for the word 'ticker' to handle both CSV and TSV
        clean_line = line.strip().lower()
        if "ticker" in clean_line:
            header_row_idx = i
            break
            
    if header_row_idx is None:
        raise RuntimeError(
            "Could not find 'Ticker' header. Check your cache/iwv_holdings.csv file formatting."
        )

    # 2. Auto-Detect Delimiter: Handles commas or tabs automatically
    # sep=None tells pandas to guess the separator; engine='python' is required for this feature
    df = pd.read_csv(
        io.StringIO("\n".join(raw[header_row_idx:])), 
        sep=None, 
        engine='python'
    )
    
    # 3. Clean and Standardize Columns
    df.columns = [c.strip() for c in df.columns]
    rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
    df = df.rename(columns=rename_map)
    
    keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
    df = df[keep].copy()
    
    # 4. Filter for Valid Tickers
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
    df = df[df["Ticker"] != "-"]
    df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])

    if "Sector" not in df.columns:
        df["Sector"] = "Unknown"
        
    return df.reset_index(drop=True)

def load_r3k_universe_from_iwv() -> pd.DataFrame:
    """Fetches Russell 3000 universe with live fetch and a flexible local fallback."""
    url = f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/ishares-russell-3000-etf/1467271812596.ajax?dataType=fund&fileName={cfg.IWV_TICKER}_holdings&fileType=csv"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print("🌐 Attempting to fetch live Russell 3000 universe...")
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        
        df = _clean_ishares_data(r.text)
        os.makedirs("cache", exist_ok=True)
        # We save the cleaned version to the cache
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df

    except Exception as e:
        print(f"⚠️ Live fetch failed ({e}). Checking local cache...")
        if Path(LOCAL_CACHE_PATH).exists():
            print("📦 Loading universe from local cache.")
            with open(LOCAL_CACHE_PATH, 'r') as f:
                cache_text = f.read()
            return _clean_ishares_data(cache_text)
        else:
            raise RuntimeError("❌ No live data and no local cache found.")

def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()