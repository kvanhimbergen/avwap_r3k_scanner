import io
import requests
import pandas as pd
import os
from pathlib import Path
from config import cfg

# --- CONFIGURATION ---
LOCAL_CACHE_PATH = "cache/iwv_holdings.csv"

def _ishares_holdings_url(product_id: str, slug: str, file_name: str) -> str:
    return (
        f"https://www.ishares.com/us/products/{product_id}/{slug}/"
        f"1467271812596.ajax?dataType=fund&fileName={file_name}&fileType=csv"
    )

def load_r3k_universe_from_iwv() -> pd.DataFrame:
    """Fetches Russell 3000 holdings from iShares with browser-mimicking headers and cache fallback."""
    url = _ishares_holdings_url(
        cfg.IWV_PRODUCT_ID,
        "ishares-russell-3000-etf",
        f"{cfg.IWV_TICKER}_holdings",
    )

    headers = {
        # Comprehensive User-Agent to mimic a modern Chrome browser
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print("🌐 Attempting to fetch live Russell 3000 universe from iShares...")
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        raw = r.text.splitlines()

        # Find the actual table header row
        header_row_idx = None
        for i, line in enumerate(raw[:80]):
            if line.lower().startswith("ticker,"):
                header_row_idx = i
                break
        
        if header_row_idx is None:
            raise RuntimeError("Could not find holdings table header (Ticker,...) in iShares CSV response.")

        # Parse the CSV
        df = pd.read_csv(io.StringIO("\n".join(raw[header_row_idx:])))
        df.columns = [c.strip() for c in df.columns]

        # Standardize and Clean
        rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
        df = df.rename(columns=rename_map)
        
        keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
        df = df[keep].copy()
        df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
        
        # Remove non-ticker artifacts
        df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
        df = df[df["Ticker"] != "-"]
        df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])

        if "Sector" not in df.columns:
            df["Sector"] = "Unknown"

        # TWEAK: Save successful download to local cache
        os.makedirs("cache", exist_ok=True)
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df.reset_index(drop=True)

    except Exception as e:
        print(f"⚠️ Live fetch failed ({e}). Checking local cache...")
        if Path(LOCAL_CACHE_PATH).exists():
            print("📦 Loading universe from local cache.")
            return pd.read_csv(LOCAL_CACHE_PATH)
        else:
            # If no cache exists, the script cannot proceed
            raise RuntimeError("❌ Could not fetch live data and no local cache found. Please check your internet connection or URL.")

def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()

if __name__ == "__main__":
    u = load_universe()
    print(u.head())
    print("Count:", len(u))