import html
import io
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

from config import cfg

# --- CONFIGURATION (script-relative cache path) ---
_BASE_DIR = Path(__file__).resolve().parent
LOCAL_CACHE_PATH = str(_BASE_DIR / "cache" / "iwv_holdings.csv")
DEFAULT_SNAPSHOT_PATH = "universe/cache/iwv_holdings.csv"

# Default rules path (repo-relative, from universe.py location)
DEFAULT_RULES_PATH = str((_BASE_DIR / "knowledge" / "rules" / "universe_rules.yaml").resolve())


def _cache_is_fresh(path: str, max_age_days: int = 7) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return datetime.now() - mtime <= timedelta(days=max_age_days)


def _clean_ishares_data(raw_text: str) -> pd.DataFrame:
    """Find the 'Ticker' header and clean data with auto-delimiter detection."""
    raw = raw_text.splitlines()

    # 1) Flexible Header Search: Find a plausible header row containing 'Ticker'
    header_row_idx = None
    for i, line in enumerate(raw[:120]):
        if "Ticker" in line:
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

    # 3) Standardize Columns
    df.columns = [c.strip() for c in df.columns]
    rename_map = {"Weight (%)": "WeightPct"} if "Weight (%)" in df.columns else {}
    df = df.rename(columns=rename_map)

    # 4) Ensure we have a Ticker column and normalize it
    if "Ticker" not in df.columns:
        raise RuntimeError("Parsed holdings file but did not find a 'Ticker' column.")

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()

    # 5) Drop empty / invalid tickers
    df = df[df["Ticker"].str.len() > 0]
    df = df[~df["Ticker"].isin(["NAN", "NONE", "NULL"])]

    return df.reset_index(drop=True)


def _browser_headers(referer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _request_with_retries(
    url: str,
    *,
    headers: Dict[str, str],
    timeout: int = 30,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 403 or "robot" in resp.text.lower():
                raise RuntimeError(
                    "iShares blocked the request (403/robot detection). "
                    "Please use the cached/snapshot holdings file."
                )
            resp.raise_for_status()
            return resp
        except Exception as exc:
            if isinstance(exc, RuntimeError) and "iShares blocked" in str(exc):
                raise
            last_exc = exc
            if attempt == max_retries:
                break
            sleep_s = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_s)
    raise RuntimeError(f"Failed to fetch URL after {max_retries} attempts: {url}") from last_exc


def _discover_iwv_holdings_url(html_text: str, base_url: str) -> str:
    decoded = html.unescape(html_text)
    ajax_links = re.findall(r'([^\s"\']+\.ajax[^\s"\']*)', decoded)
    for link in ajax_links:
        if all(
            token in link
            for token in (
                "fileType=csv",
                "fileName=IWV_holdings",
                "dataType=fund",
            )
        ):
            return urllib.parse.urljoin(base_url, link)
    raise RuntimeError("Could not discover IWV holdings CSV link in iShares HTML.")


def _download_iwv_holdings_csv() -> str:
    """
    Downloads IWV holdings CSV from iShares using link discovery.
    """
    product_url = "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf"
    product_resp = _request_with_retries(
        product_url,
        headers=_browser_headers(),
        timeout=30,
        max_retries=3,
        backoff_base=1.0,
    )
    holdings_url = _discover_iwv_holdings_url(product_resp.text, product_url)

    csv_headers = _browser_headers(referer=product_url)
    csv_headers["Accept"] = "text/csv,application/csv,text/plain,*/*"

    csv_resp = _request_with_retries(
        holdings_url,
        headers=csv_headers,
        timeout=30,
        max_retries=3,
        backoff_base=1.0,
    )
    return csv_resp.text


def _snapshot_path() -> Path:
    configured = getattr(cfg, "UNIVERSE_SNAPSHOT_PATH", None)
    return Path(configured or DEFAULT_SNAPSHOT_PATH)


def _read_text_if_exists(path: Path) -> Optional[str]:
    if path.exists():
        return path.read_text()
    return None


def load_r3k_universe_from_iwv(
    force_refresh: bool = False,
    allow_network: Optional[bool] = None,
) -> pd.DataFrame:
    """
    Primary universe loader:
      1) Try live download (unless cache is fresh and not forced)
      2) Save to cache
      3) Fallback to cache if live fails
    """
    Path(_BASE_DIR / "cache").mkdir(parents=True, exist_ok=True)

    cache_path = Path(LOCAL_CACHE_PATH)
    snapshot_path = _snapshot_path()

    # 1) Use fresh cache if allowed
    if (not force_refresh) and cache_path.exists() and _cache_is_fresh(LOCAL_CACHE_PATH, max_age_days=7):
        cache_text = cache_path.read_text()
        return _clean_ishares_data(cache_text)

    if allow_network is False:
        cache_text = _read_text_if_exists(cache_path)
        if cache_text is not None:
            return _clean_ishares_data(cache_text)

        snapshot_text = _read_text_if_exists(snapshot_path)
        if snapshot_text is not None:
            return _clean_ishares_data(snapshot_text)

        raise RuntimeError(
            "Network access disabled and no local cache or snapshot found."
        )

    # 2) Try live download
    try:
        raw_text = _download_iwv_holdings_csv()
        cache_path.write_text(raw_text)
        return _clean_ishares_data(raw_text)
    except Exception as e:
        # 3) Cache fallback
        if cache_path.exists():
            # Even if stale, use it (per your prior behavior)
            cache_text = cache_path.read_text()
            return _clean_ishares_data(cache_text)

        snapshot_text = _read_text_if_exists(snapshot_path)
        if snapshot_text is not None:
            return _clean_ishares_data(snapshot_text)

        raise RuntimeError(f"No live data and no local cache found. Last error: {e}") from e


# -------------------------
# Universe Rules (YAML)
# -------------------------

def _safe_load_yaml(path: str) -> Dict[str, Any]:
    """
    Load YAML safely.
    Fail-open: if PyYAML isn't installed or file doesn't exist, return {}.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_universe_rules() -> Dict[str, Any]:
    """
    Determines rules path using (in priority order):
      1) env var UNIVERSE_RULES_PATH
      2) cfg.universe_rules_path (if present)
      3) DEFAULT_RULES_PATH
    """
    path = os.getenv("UNIVERSE_RULES_PATH")
    if not path:
        path = getattr(cfg, "universe_rules_path", None)
    if not path:
        path = DEFAULT_RULES_PATH
    return _safe_load_yaml(path)


def _get_rules_section(rules: Dict[str, Any], section: str) -> Dict[str, Any]:
    u = rules.get("universe") if isinstance(rules.get("universe"), dict) else {}
    s = u.get(section) if isinstance(u.get(section), dict) else {}
    return s if isinstance(s, dict) else {}


def _passes_liquidity_gate(
    ticker: str,
    metrics: Dict[str, Any],
    liquidity_rules: Dict[str, Any],
) -> bool:
    """
    Liquidity Gate v1 (permissive):
      - min_price
      - min_avg_volume_20d
      - min_avg_dollar_volume_20d
    Requires metrics per ticker:
      metrics[ticker] = {
        "last_price": float,
        "avg_vol_20d": float
      }
    """
    try:
        last_price = float(metrics.get("last_price")) if metrics.get("last_price") is not None else None
        avg_vol_20d = float(metrics.get("avg_vol_20d")) if metrics.get("avg_vol_20d") is not None else None
    except Exception:
        last_price = None
        avg_vol_20d = None

    # If we cannot evaluate, fail-open (do not exclude)
    if last_price is None or avg_vol_20d is None:
        return True

    min_price = float(liquidity_rules.get("min_price") or 0.0)
    if last_price < min_price:
        return False

    min_avg_vol = liquidity_rules.get("min_avg_volume_20d", None)
    if min_avg_vol is not None:
        try:
            if avg_vol_20d < float(min_avg_vol):
                return False
        except Exception:
            pass

    min_adv = liquidity_rules.get("min_avg_dollar_volume_20d", None)
    if min_adv is not None:
        try:
            adv = avg_vol_20d * last_price
            if adv < float(min_adv):
                return False
        except Exception:
            pass

    return True


def apply_universe_rules(df: pd.DataFrame, rules: Dict[str, Any]) -> pd.DataFrame:
    """
    Apply YAML-defined universe rules.

    Design:
      - Fail-open if rules missing or metrics unavailable.
      - Liquidity is the only hard gate at this stage.
      - Structure is present in YAML but not enforced as a hard gate here yet
        (kept as a future enhancement / flagging layer).
    """
    if df.empty or "Ticker" not in df.columns:
        return df

    liquidity_rules = _get_rules_section(rules, "liquidity")

    # If no liquidity rules specified, do nothing
    if not liquidity_rules:
        return df

    tickers = df["Ticker"].astype(str).str.upper().tolist()

    # Metrics provider hook (optional)
    # Expected:
    #   cfg.get_universe_metrics(tickers) -> dict[ticker] = {"last_price": ..., "avg_vol_20d": ...}
    metrics_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None
    provider = getattr(cfg, "get_universe_metrics", None)

    if callable(provider):
        try:
            metrics_by_ticker = provider(tickers) or {}
        except Exception:
            metrics_by_ticker = None

    # If no metrics, fail-open: do not filter
    if not metrics_by_ticker:
        return df

    keep = []
    for t in tickers:
        m = metrics_by_ticker.get(t)
        if not m:
            keep.append(True)
            continue

        keep.append(_passes_liquidity_gate(t, m, liquidity_rules))

    out = df.loc[keep].reset_index(drop=True)
    return out    
    
def load_universe(force_refresh: bool = False, allow_network: Optional[bool] = None) -> pd.DataFrame:
    """
    Public entry point used by the scanner.
    Loads IWV-based R3K universe, then applies YAML rules if available.
    """
    df = load_r3k_universe_from_iwv(force_refresh=force_refresh, allow_network=allow_network)

    rules = load_universe_rules()
    df = apply_universe_rules(df, rules)

    return df
