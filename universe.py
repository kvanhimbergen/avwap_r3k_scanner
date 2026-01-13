import io
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from config import cfg

# --- CONFIGURATION (script-relative cache path) ---
_BASE_DIR = Path(__file__).resolve().parent
LOCAL_CACHE_PATH = str(_BASE_DIR / "cache" / "iwv_holdings.csv")


def _cache_is_fresh(path: str, max_age_days: int = 7) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return datetime.now() - mtime <= timedelta(days=max_age_days)


def _clean_ishares_data(raw_text: str) -> pd.DataFrame:
    """Helper to find the 'Ticker' header and clean data with auto-delimiter detection."""
    raw = raw_text.splitlines()

    # 1) Flexible Header Search: Find a plausible header row containing 'Ticker'
    header_row_idx = None
    for i, line in enumerate(raw[:120]):
        clean_line = line.strip().lower()
        # Make header detection slightly stricter to avoid matching disclaimers
        if "ticker" in clean_line and ("name" in clean_line or "sector" in clean_line):
            header_row_idx = i
            break

    # Fallback: original behavior if strict match not found
    if header_row_idx is None:
        for i, line in enumerate(raw[:120]):
            if "ticker" in line.strip().lower():
                header_row_idx = i
                break

    if header_row_idx is None:
        raise RuntimeError(
            "Could not find 'Ticker' header. Check your cache/iwv_holdings.csv file formatting."
        )

    # 2) Auto-Detect Delimiter: Handles commas or tabs automatically
    df = pd.read_csv(
        io.StringIO("\n".join(raw[header_row_idx:])),
        sep=None,
        engine="python",
    )

#3 Standardize Columns
    df.columns = [c.strip() for c in df.columns]
    rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
    df = df.rename(columns=rename_map)

    keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
    df = df[keep].copy()

    # 4) Filter for Valid Tickers
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
    df = df[df["Ticker"] != "-"]
    df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])

    if "Sector" not in df.columns:
        df["Sector"] = "Unknown"

    return df.reset_index(drop=True)


def load_r3k_universe_from_iwv() -> pd.DataFrame:
    """Fetches Russell 3000 universe with live fetch and a flexible local fallback."""
    url = (
        f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/"
        f"ishares-russell-3000-etf/1467271812596.ajax"
        f"?dataType=fund&fileName={cfg.IWV_TICKER}_holdings&fileType=csv"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/csv,*/*",
        "Referer": f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/",
    }

    try:
        print("🌐 Attempting to fetch live Russell 3000 universe...")
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        df = _clean_ishares_data(r.text)
        Path(LOCAL_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
        # Save the cleaned version to the cache (script-relative)
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df

    except Exception as e:
        print(f"⚠️ Live fetch failed ({e}). Checking local cache...")

        if Path(LOCAL_CACHE_PATH).exists():
            if not _cache_is_fresh(LOCAL_CACHE_PATH, max_age_days=7):
                print("⚠️ Local universe cache is stale (>7 days). Using it anyway; refresh recommended.")
            print("📦 Loading universe from local cache.")
            cache_text = Path(LOCAL_CACHE_PATH).read_text()
            return _clean_ishares_data(cache_text)

        raise RuntimeError("❌ No live data and no local cache found.")


def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()
import io
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from config import cfg

# --- CONFIGURATION (script-relative cache path) ---
_BASE_DIR = Path(__file__).resolve().parent
LOCAL_CACHE_PATH = str(_BASE_DIR / "cache" / "iwv_holdings.csv")


def _cache_is_fresh(path: str, max_age_days: int = 7) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return datetime.now() - mtime <= timedelta(days=max_age_days)


def _clean_ishares_data(raw_text: str) -> pd.DataFrame:
    """Helper to find the 'Ticker' header and clean data with auto-delimiter detection."""
    raw = raw_text.splitlines()

    # 1) Flexible Header Search: Find a plausible header row containing 'Ticker'
    header_row_idx = None
    for i, line in enumerate(raw[:120]):
        clean_line = line.strip().lower()
        if "ticker" in clean_line and ("name" in clean_line or "sector" in clean_line):
            header_row_idx = i
            break

    # Fallback: original behavior if strict match not found
    if header_row_idx is None:
        for i, line in enumerate(raw[:120]):
            if "ticker" in line.strip().lower():
                header_row_idx = i
                break

    if header_row_idx is None:
        raise RuntimeError(
            "Could not find 'Ticker' header. Check your cache/iwv_holdings.csv file formatting."
        )

    # 2) Auto-Detect Delimiter: Handles commas or tabs automatically
    df = pd.read_csv(
        io.StringIO("\n".join(raw[header_row_idx:])),
        sep=None,
        engine="python",
    )

    # 3) Clean and Standardize Columns
    df.columns = [c.strip() for c in df.columns]
    rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
    df = df.rename(columns=rename_map)

    keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
    df = df[keep].copy()

    # 4) Filter for Valid Tickers
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
    df = df[df["Ticker"] != "-"]
    df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])

    if "Sector" not in df.columns:
        df["Sector"] = "Unknown"

    return df.reset_index(drop=True)


def _fetch_ishares_csv_requests(url: str, headers: dict) -> str:
    """Primary fetch using requests."""
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def _fetch_ishares_csv_curl_cffi(url: str, headers: dict) -> str:
    """
    Fallback fetch using curl_cffi, which can impersonate a real browser TLS fingerprint.
    This often bypasses 403 blocks from sites that reject typical bot TLS/client signatures.
    """
    try:
        from curl_cffi import requests as crequests  # type: ignore
    except Exception as e:
        raise RuntimeError(f"curl_cffi not available: {e}")

    # impersonate="chrome" provides a realistic browser signature
    r = crequests.get(url, headers=headers, timeout=30, impersonate="chrome")
    r.raise_for_status()
    return r.text


def load_r3k_universe_from_iwv() -> pd.DataFrame:
    """Fetches Russell 3000-ish universe from iShares IWV holdings; uses robust fallback and local cache."""
    url = (
        f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/"
        f"ishares-russell-3000-etf/1467271812596.ajax"
        f"?dataType=fund&fileName={cfg.IWV_TICKER}_holdings&fileType=csv"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/csv,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.ishares.com/us/products/{cfg.IWV_PRODUCT_ID}/",
    }

    # Ensure cache dir exists up front
    Path(LOCAL_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)

    # 1) Try plain requests
    try:
        print("🌐 Attempting to fetch live Russell 3000 universe (requests)...")
        text = _fetch_ishares_csv_requests(url, headers=headers)
        df = _clean_ishares_data(text)
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df
    except Exception as e1:
        print(f"⚠️ requests fetch failed ({e1}). Trying curl_cffi browser impersonation...")

    # 2) Try curl_cffi impersonation
    try:
        text = _fetch_ishares_csv_curl_cffi(url, headers=headers)
        df = _clean_ishares_data(text)
        df.to_csv(LOCAL_CACHE_PATH, index=False)
        return df
    except Exception as e2:
        print(f"⚠️ curl_cffi fetch failed ({e2}). Checking local cache...")

    # 3) Cache fallback
    if Path(LOCAL_CACHE_PATH).exists():
        if not _cache_is_fresh(LOCAL_CACHE_PATH, max_age_days=7):
            print("⚠️ Local universe cache is stale (>7 days). Using it anyway; refresh recommended.")
        print("📦 Loading universe from local cache.")
        cache_text = Path(LOCAL_CACHE_PATH).read_text()
        return _clean_ishares_data(cache_text)

    raise RuntimeError("❌ No live data and no local cache found.")


def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()
