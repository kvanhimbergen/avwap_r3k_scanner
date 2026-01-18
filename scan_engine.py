import csv
import json
import os
import warnings
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytz
import yfinance as yf
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import load_dotenv
from tqdm import tqdm

import cache_store as cs
from anchors import anchored_vwap, get_anchor_candidates
from config import cfg as default_cfg
from indicators import (
    atr,
    get_pivot_targets,
    rolling_percentile,
    slope_last,
    sma,
    trend_strength_score,
)
from setup_context import compute_setup_context, load_setup_rules
from universe import load_universe

# --- Global Config & Tracking ---
BAD_TICKERS: set[str] = set()
PBT_DIAG = Counter()
warnings.filterwarnings("ignore")
EARNINGS_CACHE_PATH = Path("cache/earnings_cache.json")

# ALGO TWEAK CONFIGS
ADV_MIN_SHARES = 750000  # Minimum 750k shares avg daily volume
ATR_MIN_DOLLARS = 0.50   # Minimum $0.50 average daily range
ALGO_CANDIDATE_CAP = 20  # Limit to top 20 for the execution bot

_ACTIVE_CFG = default_cfg

CANDIDATE_COLUMNS = [
    "SchemaVersion",
    "ScanDate",
    "Symbol",
    "Direction",
    "TrendTier",
    "Price",
    "Entry_Level",
    "Entry_DistPct",
    "Stop_Loss",
    "Target_R1",
    "Target_R2",
    "TrendScore",
    "Sector",
    "Anchor",
    "AVWAP_Slope",
    "Setup_VWAP_Control",
    "Setup_VWAP_Reclaim",
    "Setup_VWAP_Acceptance",
    "Setup_VWAP_DistPct",
    "Setup_AVWAP_Control",
    "Setup_AVWAP_Reclaim",
    "Setup_AVWAP_Acceptance",
    "Setup_AVWAP_DistPct",
    "Setup_Extension_State",
    "Setup_Gap_Reset",
    "Setup_Structure_State",
]


def _cfg():
    return _ACTIVE_CFG


def load_bad_tickers() -> set[str]:
    path = Path("cache/bad_tickers.txt")
    if path.exists():
        return set(x.strip().upper() for x in path.read_text().splitlines() if x.strip())
    return set()


def save_bad_tickers(bt_set: set[str]) -> None:
    os.makedirs("cache", exist_ok=True)
    Path("cache/bad_tickers.txt").write_text("\n".join(sorted(list(bt_set))))


def is_valid_ticker(t: str) -> bool:
    return isinstance(t, str) and 1 <= len(t) <= 6 and t.isalpha()


def standardize_alpaca_to_yf(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()

    rename_map = {
        "symbol": "Ticker",
        "timestamp": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(columns=rename_map)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


# TWEAK 1: Market Regime Filter
def get_market_regime(client: StockHistoricalDataClient) -> bool:
    """Checks if SPY is above its 200-day SMA."""
    try:
        spy_req = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=300),
        )
        df = standardize_alpaca_to_yf(client.get_stock_bars(spy_req).df)
        df["SMA200"] = df["Close"].rolling(window=200).mean()
        curr_price = df["Close"].iloc[-1]
        sma200 = df["SMA200"].iloc[-1]
        return curr_price > sma200
    except Exception:
        return True  # Default to True if check fails to avoid blocking scan


# TWEAK 2: Earnings Date Check
def is_near_earnings(ticker: str) -> bool:
    """Excludes stocks reporting earnings in the next 48 hours using robust method."""
    try:
        stock = yf.Ticker(ticker)
        # TWEAK: get_earnings_dates is more reliable than .calendar
        dates = stock.get_earnings_dates()
        if dates is not None and not dates.empty:
            # Check for the closest future earnings date
            future_earnings = dates[dates.index > datetime.now(pytz.utc)]
            if not future_earnings.empty:
                next_earnings = future_earnings.index[0]
                days_to_earnings = (
                    next_earnings.date() - datetime.now().date()
                ).days
                return 0 <= days_to_earnings <= 2
    except Exception:
        return False
    return False


def check_weekly_alignment(df: pd.DataFrame) -> bool:
    if len(df) < 200:
        return True
    weekly = df["Close"].resample("W-FRI").last()
    if len(weekly) < 40:
        return True
    return (
        weekly.rolling(10).mean().iloc[-1]
        > weekly.rolling(40).mean().iloc[-1]
    )


def shannon_quality_gates(
    df: pd.DataFrame,
    direction: str,
    *,
    is_weekend: bool | None = None,
) -> dict | None:
    if df is None or len(df) < 80:
        return None
    close, px = df["Close"], float(df["Close"].iloc[-1])
    if is_weekend is None:
        is_weekend = datetime.now().weekday() >= 5

    s20, s50 = sma(close, 20), sma(close, 50)
    s20n, s50n = float(s20.iloc[-1]), float(s50.iloc[-1])
    s50_slope = slope_last(s50, n=10)

    # TWEAK 3: ATR Minimum check
    atr14 = atr(df, 14)
    atr_now = float(atr14.iloc[-1])
    if atr_now < ATR_MIN_DOLLARS:
        return None

    atr_pct = (atr14 / close) * 100.0
    atr_pct_now = float(atr_pct.iloc[-1])
    atr_pct_p50 = float(rolling_percentile(atr_pct, 120, 0.50).iloc[-1])

    if direction == "Long":
        tier_a = (px > s20n) and (s20n >= s50n)
        tier_b = (px > s50n) and (s50_slope > 0)
        trend_ok = tier_a or (is_weekend and tier_b)
        label = "A" if tier_a else "B"
    else:
        tier_a = (px < s20n) and (s20n <= s50n)
        tier_b = (px < s50n) and (s50_slope < 0)
        trend_ok = tier_a or (is_weekend and tier_b)
        label = "A" if tier_a else "B"

    vol_mult = 1.25 if is_weekend else 1.0
    if not (
        trend_ok
        and atr_pct_now <= (6.5 if is_weekend else 6.0)
        and atr_pct_now <= (atr_pct_p50 * vol_mult)
    ):
        return None

    return {
        "TrendTier": label,
        "SMA20": round(s20n, 2),
        "SMA50": round(s50n, 2),
        "ATR%": round(atr_pct_now, 2),
    }


def _get_avwap_slope_threshold(direction: str, is_weekend: bool) -> float:
    cfg = _cfg()
    if direction == "Long":
        default = -0.03 if not is_weekend else -0.05
        return float(getattr(cfg, "MIN_AVWAP_SLOPE_LONG", default))
    return float(getattr(cfg, "MIN_AVWAP_SLOPE_SHORT", 0.03 if not is_weekend else 0.05))


def pick_best_anchor(
    df: pd.DataFrame,
    direction: str,
    *,
    is_weekend: bool | None = None,
) -> tuple | None:
    cfg = _cfg()
    if df is None or len(df) < 2:
        return None
    px, prev_px = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    trend_score = trend_strength_score(df)
    if is_weekend is None:
        is_weekend = datetime.now().weekday() >= 5
    best, best_score = None, -1e18

    slope_n = int(getattr(cfg, "AVWAP_SLOPE_LOOKBACK", 5))
    slope_thr = _get_avwap_slope_threshold(direction, is_weekend)
    reclaim_bypass = bool(getattr(cfg, "AVWAP_SLOPE_BYPASS_ON_RECLAIM", True))

    for a in get_anchor_candidates(df):
        av = anchored_vwap(df, a["loc"])
        if len(av) <= slope_n:
            continue
        av_clean = av.dropna()
        if len(av_clean) < (slope_n + 1):
            continue

        av_now = float(av_clean.iloc[-1])
        av_s = slope_last(av_clean, n=slope_n)
        if np.isnan(av_s):
            continue

        is_reclaim = (
            (prev_px <= av_now and px > av_now)
            if direction == "Long"
            else (prev_px >= av_now and px < av_now)
        )
        dist = (
            (px - av_now) / av_now * 100.0
            if direction == "Long"
            else (av_now - px) / av_now * 100.0
        )

        if direction == "Long":
            if not (px > av_now or is_reclaim):
                continue
            if not (av_s >= slope_thr) and not (reclaim_bypass and is_reclaim):
                continue
        else:
            if not (px < av_now or is_reclaim):
                continue
            if not (av_s <= slope_thr) and not (reclaim_bypass and is_reclaim):
                continue

        if dist > cfg.MAX_DIST_FROM_AVWAP_PCT:
            continue

        score = (
            a["priority"]
            + (trend_score * 1.5)
            - abs(dist)
            + (50.0 if 0.1 <= dist <= 1.5 else 0.0)
            + (40.0 if is_reclaim else 0.0)
        )
        if score > best_score:
            best_score, best = score, (a["name"], av_now, av_s, trend_score, dist)
    return best


def build_liquidity_snapshot(
    universe: pd.DataFrame,
    data_client: StockHistoricalDataClient,
) -> pd.DataFrame:
    cfg = _cfg()
    is_weekend = datetime.now().weekday() >= 5
    tickers = [
        t.upper()
        for t in universe["Ticker"].tolist()
        if is_valid_ticker(t) and t not in BAD_TICKERS
    ]
    rows = []
    batch_size = 100
    start_date = datetime.now() - timedelta(days=45)

    for i in tqdm(range(0, len(tickers), batch_size), desc="Snapshot"):
        batch = tickers[i : i + batch_size]
        try:
            req = StockBarsRequest(
                symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=start_date
            )
            bars_data = data_client.get_stock_bars(req)
            if not bars_data:
                continue
            df_all = standardize_alpaca_to_yf(bars_data.df)
            for t in batch:
                sub = df_all[df_all["Ticker"] == t].copy()
                if len(sub) < 15:
                    continue

                # TWEAK 3: Share Volume floor
                avg_vol_shares = sub["Volume"].tail(20).mean()
                if avg_vol_shares < ADV_MIN_SHARES:
                    continue

                dv = (sub["Close"] * sub["Volume"]).mean()
                if dv < (10_000_000 if is_weekend else cfg.MIN_AVG_DOLLAR_VOL):
                    continue

                rows.append(
                    {
                        "Ticker": t,
                        "AvgDollarVol20": dv,
                        "Sector": universe.loc[universe["Ticker"] == t, "Sector"].values[
                            0
                        ],
                        "TrendScore": trend_strength_score(sub.set_index("Date")),
                    }
                )
        except Exception:
            continue
    snap = pd.DataFrame(rows)
    if snap.empty:
        return snap
    if is_weekend:
        return snap.sort_values("AvgDollarVol20", ascending=False).head(
            cfg.SNAPSHOT_MAX_TICKERS
        )
    sector_rank = (
        snap.groupby("Sector")["TrendScore"]
        .mean()
        .sort_values(ascending=False)
        .head(cfg.TOP_SECTORS_TO_SCAN)
        .index
    )
    return snap[snap["Sector"].isin(sector_rank)].sort_values(
        "AvgDollarVol20", ascending=False
    ).head(cfg.SNAPSHOT_MAX_TICKERS)


def _load_earnings_cache() -> dict:
    try:
        if EARNINGS_CACHE_PATH.exists():
            return json.loads(EARNINGS_CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_earnings_cache(cache: dict) -> None:
    try:
        os.makedirs(EARNINGS_CACHE_PATH.parent, exist_ok=True)
        tmp = str(EARNINGS_CACHE_PATH) + ".tmp"
        Path(tmp).write_text(json.dumps(cache, indent=2, sort_keys=True))
        os.replace(tmp, EARNINGS_CACHE_PATH)
    except Exception:
        # Cache failures should never break the scan
        pass


def is_near_earnings_cached(ticker: str) -> bool:
    """
    Disk-backed cache for is_near_earnings() results.
    Stores: { "AAPL": {"value": false, "asof": "2026-01-13"} , ... }
    TTL-based refresh; safe to use inside the scanning loop.
    """
    # Allow bypass for testing
    if os.getenv("EARNINGS_CACHE_DISABLE", "0") == "1":
        return False

    ttl_days = int(os.getenv("EARNINGS_CACHE_TTL_DAYS", "7"))
    force_refresh = os.getenv("EARNINGS_CACHE_FORCE_REFRESH", "0") == "1"

    t = (ticker or "").upper().strip()
    if not t:
        return False

    cache = _load_earnings_cache()

    today = date.today().isoformat()
    rec = cache.get(t)

    # If we have a record and it's within TTL, use it
    if not force_refresh and isinstance(rec, dict):
        asof = rec.get("asof")
        if asof:
            try:
                age = (date.fromisoformat(today) - date.fromisoformat(asof)).days
                if 0 <= age <= ttl_days:
                    return bool(rec.get("value", False))
            except Exception:
                pass

    # Otherwise compute and update cache
    try:
        val = bool(is_near_earnings(t))
    except Exception:
        val = False

    cache[t] = {"value": val, "asof": today}
    _save_earnings_cache(cache)
    return val


def _build_candidates_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    return pd.DataFrame(rows).reindex(columns=CANDIDATE_COLUMNS)


def _infer_is_weekend(as_of_dt: datetime | None) -> bool:
    if as_of_dt is None:
        return datetime.now().weekday() >= 5
    return as_of_dt.weekday() >= 5


def _candidate_scan_date(as_of_dt: datetime | None) -> str:
    if as_of_dt is None:
        return datetime.now(pytz.timezone("America/New_York")).date().isoformat()
    return as_of_dt.date().isoformat()


def build_candidate_row(
    df: pd.DataFrame,
    ticker: str,
    sector: str,
    setup_rules: dict,
    *,
    as_of_dt: datetime | None = None,
    direction: str = "Long",
) -> dict | None:
    if df.empty:
        return None

    if as_of_dt is not None:
        df = df.loc[:as_of_dt].copy()

    if df.empty or len(df) < 80:
        return None

    is_weekend = _infer_is_weekend(as_of_dt)

    if not is_weekend and not check_weekly_alignment(df):
        return None

    gates = shannon_quality_gates(df, direction, is_weekend=is_weekend)
    if not gates:
        return None

    # NEW: Calculate Structural Stop Levels (Shannon Style)
    df = df.copy()
    df["SMA5"] = sma(df["Close"], 5)
    df["Low5"] = df["Low"].rolling(window=5).min()

    curr_sma5 = float(df["SMA5"].iloc[-1])
    curr_low5 = float(df["Low5"].iloc[-1])

    # Determine logical stop: The lower of the 5-DMA or 5-Day Low with a 0.3% buffer
    structural_stop = min(curr_sma5, curr_low5) * 0.997

    best = pick_best_anchor(df, direction, is_weekend=is_weekend)
    if not best:
        return None

    name, av, avs, trend_score, dist = best
    r1, r2 = get_pivot_targets(df)
    setup_ctx = compute_setup_context(df, name, setup_rules)
    return {
        "SchemaVersion": 1,
        "ScanDate": _candidate_scan_date(as_of_dt),
        "Symbol": ticker,
        "Direction": direction,
        "TrendTier": gates["TrendTier"],
        "Price": round(df["Close"].iloc[-1], 2),
        "Entry_Level": round(av, 2),
        "Entry_DistPct": round(dist, 2),
        "Stop_Loss": round(structural_stop, 2),
        "Target_R1": r1,
        "Target_R2": r2,
        "TrendScore": round(trend_score, 6),
        "Sector": sector,
        "Anchor": name,
        "AVWAP_Slope": round(float(avs), 4),
        "Setup_VWAP_Control": setup_ctx.vwap_control,
        "Setup_VWAP_Reclaim": setup_ctx.vwap_reclaim,
        "Setup_VWAP_Acceptance": setup_ctx.vwap_acceptance,
        "Setup_VWAP_DistPct": None
        if setup_ctx.vwap_dist_pct is None
        else round(setup_ctx.vwap_dist_pct, 2),
        "Setup_AVWAP_Control": setup_ctx.avwap_control,
        "Setup_AVWAP_Reclaim": setup_ctx.avwap_reclaim,
        "Setup_AVWAP_Acceptance": setup_ctx.avwap_acceptance,
        "Setup_AVWAP_DistPct": None
        if setup_ctx.avwap_dist_pct is None
        else round(setup_ctx.avwap_dist_pct, 2),
        "Setup_Extension_State": setup_ctx.extension_state,
        "Setup_Gap_Reset": setup_ctx.gap_reset,
        "Setup_Structure_State": setup_ctx.structure_state,
    }


def run_scan(scan_cfg, as_of_dt: datetime | None = None) -> pd.DataFrame:
    global BAD_TICKERS
    global _ACTIVE_CFG

    _ACTIVE_CFG = scan_cfg

    load_dotenv()
    data_client = StockHistoricalDataClient(
        os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
    )
    setup_rules = load_setup_rules()

    # TWEAK 1: Market Regime Check
    if not get_market_regime(data_client):
        print(
            "⚠️ Market Regime Bearish (SPY < 200 SMA). Skipping scan to protect capital."
        )
        return _build_candidates_dataframe([])

    is_weekend = _infer_is_weekend(as_of_dt)
    if is_weekend:
        scan_cfg.TOP_SECTORS_TO_SCAN, scan_cfg.SNAPSHOT_MAX_TICKERS = 11, 3000

    BAD_TICKERS = load_bad_tickers()
    universe = load_universe()

    snap = build_liquidity_snapshot(universe, data_client)
    filtered = snap["Ticker"].tolist()

    # --- TEST MODE: limit scan universe for faster iteration ---
    TEST_MODE = os.getenv("TEST_MODE", "0") == "1"
    TEST_MAX_TICKERS = int(os.getenv("TEST_MAX_TICKERS", "150"))

    if TEST_MODE:
        print(f"🧪 TEST_MODE enabled. Limiting scan universe to {TEST_MAX_TICKERS} tickers.")
        filtered = filtered[:TEST_MAX_TICKERS]

    hist_path = Path("cache") / "ohlcv_history.parquet"
    history = cs.read_parquet(str(hist_path))
    batch_size = 200

    # First-run / missing-cache backfill: must exceed 80 bars
    if history is None or history.empty:
        print("History cache missing/empty. Backfilling ~2 years...")
        hist_start = datetime.now() - timedelta(days=730)
    else:
        hist_start = datetime.now() - timedelta(days=15)

    for i in tqdm(range(0, len(filtered), batch_size), desc="History Refresh"):
        batch = filtered[i : i + batch_size]
        try:
            req = StockBarsRequest(
                symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=hist_start
            )
            raw_new = data_client.get_stock_bars(req).df
            if raw_new is not None and not raw_new.empty:
                newdata = standardize_alpaca_to_yf(raw_new)
                history = cs.upsert_history(history, newdata)
        except Exception:
            # Do not silently swallow; at least count it
            PBT_DIAG["history_refresh_errors"] += 1
            continue

    ## Persist AFTER refresh
    os.makedirs(hist_path.parent, exist_ok=True)
    cs.write_parquet(history, str(hist_path))
    print(f"Saved history cache: {hist_path} | rows={0 if history is None else len(history):,}")

    results = []
    for t in tqdm(filtered, desc="Scanning"):
        if is_near_earnings_cached(t):
            continue

        d_filtered = history[history["Ticker"] == t].copy()
        if d_filtered.empty or len(d_filtered) < 80:
            continue
        df = d_filtered.set_index("Date").sort_index()

        sector = snap.loc[snap["Ticker"] == t, "Sector"].values[0]
        row = build_candidate_row(
            df,
            t,
            sector,
            setup_rules,
            as_of_dt=as_of_dt,
            direction="Long",
        )
        if row:
            results.append(row)

    return _build_candidates_dataframe(results)


def write_candidates_csv(df: pd.DataFrame, path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_tradingview_watchlist(df_or_symbols, path: Path | str) -> int:
    """
    Builds a TradingView watchlist file (one symbol per line).
    - Sorted
    - De-duplicated
    - Uppercased
    Returns the number of symbols written.
    """
    symbols = set()

    if isinstance(df_or_symbols, pd.DataFrame):
        if "Symbol" not in df_or_symbols.columns:
            raise ValueError("Expected column 'Symbol' not found in candidates DataFrame.")
        source_iter = df_or_symbols["Symbol"].tolist()
    else:
        source_iter = df_or_symbols

    for raw in source_iter:
        s = (raw or "").strip().upper()
        if not s:
            continue
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
        if any(ch not in allowed for ch in s):
            continue
        symbols.add(s)

    sorted_symbols = sorted(symbols)

    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as out:
        for s in sorted_symbols:
            out.write(f"{s}\n")

    os.replace(tmp_path, path)

    return len(sorted_symbols)
