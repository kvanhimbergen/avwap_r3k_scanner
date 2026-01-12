import io
import requests
import pandas as pd
import os
from pathlib import Path
from config import cfg

# --- CONFIGURATION ---
LOCAL_CACHE_PATH = "cache/iwv_holdings.csv"

def _clean_ishares_data(raw_text: str) -> pd.DataFrame:
    """Helper to find the 'Ticker' header and clean the iShares CSV structure."""
    raw = raw_text.splitlines()
    
    # Search for the actual table header row (usually line 10)
    header_row_idx = None
    for i, line in enumerate(raw[:80]):
        if line.lower().startswith("ticker,"):
            header_row_idx = i
            break
            
    if header_row_idx is None:
        raise RuntimeError("Could not find 'Ticker' header in the CSV data. Check file formatting.")

    # Parse starting from the header row
    df = pd.read_csv(io.StringIO("\n".join(raw[header_row_idx:])))
    df.columns = [c.strip() for c in df.columns]

    # Normalize columns
    rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
    df = df.rename(columns=rename_map)
    
    keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
    df = df[keep].copy()
    
    # Standardize Tickers
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
    df = df[df["Ticker"] != "-"]
    df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])

    if "Sector" not in df.columns:
        df["Sector"] = "Unknown"
        
    return df.reset_index(drop=True)

def load_r3k_universe_from_iwv() -> pd.DataFrame:
    """Fetches Russell 3000 universe with a robust fallback to cleaned local cache."""
    url = f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/ishares-russell-3000-etf/1467271812596.ajax?dataType=fund&fileName={cfg.IWV_TICKER}_holdings&fileType=csv"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print("🌐 Attempting to fetch live Russell 3000 universe...")
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        
        # Clean and save to cache
        df = _clean_ishares_data(r.text)
        os.makedirs("cache", exist_ok=True)
        # Note: We save the cleaned version so the fallback is even faster next time
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df

    except Exception as e:
        print(f"⚠️ Live fetch failed ({e}). Checking local cache...")
        if Path(LOCAL_CACHE_PATH).exists():
            print("📦 Loading universe from local cache.")
            # Read the raw cache file and clean it
            with open(LOCAL_CACHE_PATH, 'r') as f:
                cache_text = f.read()
            return _clean_ishares_data(cache_text)
        else:
            raise RuntimeError("❌ No live data and no local cache found.")

def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()

if __name__ == "__main__":
    u = load_universe()
    print(u.head())
    print(f"Universe Loaded: {len(u)} tickers.")