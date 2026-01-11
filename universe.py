import io
import requests
import pandas as pd
from config import cfg

def _ishares_holdings_url(product_id: str, slug: str, file_name: str) -> str:
    # IMPORTANT: iShares requires the fund slug segment in the URL path.
    # Example (IWV): /us/products/239714/ishares-russell-3000-etf/1467271812596.ajax?... :contentReference[oaicite:1]{index=1}
    return (
        f"https://www.ishares.com/us/products/{product_id}/{slug}/"
        f"1467271812596.ajax?dataType=fund&fileName={file_name}&fileType=csv"
    )

def load_r3k_universe_from_iwv() -> pd.DataFrame:
    url = _ishares_holdings_url(
        cfg.IWV_PRODUCT_ID,
        "ishares-russell-3000-etf",
        f"{cfg.IWV_TICKER}_holdings",
    )

    headers = {
        # Some sites block requests without a UA; this reduces random failures.
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
    }

    r = requests.get(url, headers=headers, timeout=60)
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

    df = pd.read_csv(io.StringIO("\n".join(raw[header_row_idx:])))
    df.columns = [c.strip() for c in df.columns]

    # Normalize expected columns
    rename_map = {}
    if "Weight (%)" in df.columns:
        rename_map["Weight (%)"] = "WeightPct"
    df = df.rename(columns=rename_map)

    keep = [c for c in ["Ticker", "Name", "Sector", "WeightPct"] if c in df.columns]
    df = df[keep].copy()

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()

    # NEW: remove non-ticker artifacts and obviously invalid symbols
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]
    df = df[df["Ticker"] != "-"]

    df = df.dropna(subset=["Ticker"]).drop_duplicates(subset=["Ticker"])


    if "Sector" not in df.columns:
        df["Sector"] = "Unknown"

    return df.reset_index(drop=True)

def load_universe() -> pd.DataFrame:
    return load_r3k_universe_from_iwv()

if __name__ == "__main__":
    u = load_universe()
    print(u.head())
    print("Count:", len(u))
