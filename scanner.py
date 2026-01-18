import warnings
import numpy as np
import pandas as pd
from datetime import datetime

from anchors import anchored_vwap, get_anchor_candidates
from indicators import slope_last, trend_strength_score
from config import cfg

warnings.warn(
    "scanner.py is deprecated. Use run_scan.py for the active scan pipeline.",
    DeprecationWarning,
    stacklevel=2,
)


# -----------------------------
# Diagnostics (opt-in, no impact unless you pass stats=...)
# -----------------------------
def init_scan_stats() -> dict:
    """
    Create a mutable stats dict for scan diagnostics.

    Pass the returned dict into score_candidate(..., stats=stats) (or pick_best_anchor(..., stats=stats))
    to collect counts of where symbols are being filtered out.

    This is opt-in and will not affect behavior unless you pass stats.
    """
    return {
        # Top-level
        "start": 0,
        "basic_filters_pass": 0,
        "basic_filters_fail": 0,

        # Anchor pipeline
        "anchor_candidates_total": 0,
        "anchors_evaluated": 0,
        "anchors_skipped_insufficient_av": 0,
        "anchors_skipped_nan_slope": 0,

        # Gates
        "direction_gate_fail": 0,
        "slope_gate_fail": 0,
        "dist_gate_fail": 0,

        # Results
        "anchor_found": 0,
        "final_pass": 0,
    }


def format_scan_stats(stats: dict) -> str:
    """Format scan diagnostics in a stable, human-readable way."""
    if not stats:
        return "SCAN STATS: <none>"

    order = [
        "start",
        "basic_filters_pass",
        "basic_filters_fail",
        "anchor_candidates_total",
        "anchors_evaluated",
        "anchors_skipped_insufficient_av",
        "anchors_skipped_nan_slope",
        "direction_gate_fail",
        "slope_gate_fail",
        "dist_gate_fail",
        "anchor_found",
        "final_pass",
    ]
    lines = ["SCAN STATS:"]
    for k in order:
        if k in stats:
            lines.append(f"{k}: {stats.get(k, 0)}")
    return "\n".join(lines)


def _stat_inc(stats: dict | None, key: str, n: int = 1) -> None:
    if stats is None:
        return
    try:
        stats[key] = int(stats.get(key, 0)) + int(n)
    except Exception:
        # never allow diagnostics to break the scan
        pass


# -----------------------------
# Core helpers
# -----------------------------
def avg_dollar_vol(df: pd.DataFrame) -> float:
    """20-day average dollar volume using Close * Volume."""
    if df is None or df.empty or "Close" not in df.columns or "Volume" not in df.columns:
        return 0.0
    dv = (df["Close"] * df["Volume"]).rolling(20).mean().iloc[-1]
    return float(dv) if pd.notna(dv) else 0.0


def basic_filters(df: pd.DataFrame) -> bool:
    """
    Minimal safety + liquidity gates.
    Kept intentionally conservative and aligned to cfg fields already in your project.
    """
    if df is None or df.empty or len(df) < 80:
        return False

    # Ensure expected columns exist
    for c in ("Close", "Volume"):
        if c not in df.columns:
            return False

    px = float(df["Close"].iloc[-1])
    if px < float(getattr(cfg, "MIN_PRICE", 0)):
        return False

    if avg_dollar_vol(df) < float(getattr(cfg, "MIN_AVG_DOLLAR_VOL", 0)):
        return False

    return True


def _get_avwap_slope_threshold(direction: str, is_weekend: bool) -> float:
    """
    Optional config hooks:
      - cfg.MIN_AVWAP_SLOPE_LONG / cfg.MIN_AVWAP_SLOPE_SHORT
      - Defaults mirror the logic you implemented in run_scan.py.
    """
    if direction == "Long":
        default = -0.03 if not is_weekend else -0.05
        return float(getattr(cfg, "MIN_AVWAP_SLOPE_LONG", default))
    default = 0.03 if not is_weekend else 0.05
    return float(getattr(cfg, "MIN_AVWAP_SLOPE_SHORT", default))


def pick_best_anchor(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    direction: str,
    stats: dict | None = None,
):
    """
    Find the best anchor for the given symbol based on AVWAP structure and trend strength.
    Backward compatible: returns either None or a dict describing the best anchor.
    """
    if df is None or len(df) < 2:
        return None

    # Defensive: allow either DateTimeIndex or a Date column already set as index upstream
    if "Close" not in df.columns:
        return None

    px = float(df["Close"].iloc[-1])
    prev_px = float(df["Close"].iloc[-2])

    trend_score = trend_strength_score(df)
    is_weekend = datetime.now().weekday() >= 5

    slope_n = int(getattr(cfg, "AVWAP_SLOPE_LOOKBACK", 5))
    slope_thr = _get_avwap_slope_threshold(direction, is_weekend)
    reclaim_bypass = bool(getattr(cfg, "AVWAP_SLOPE_BYPASS_ON_RECLAIM", True))

    best = None
    best_score = -1e18

    candidates = get_anchor_candidates(df)
    _stat_inc(stats, "anchor_candidates_total", len(candidates))

    for a in candidates:
        _stat_inc(stats, "anchors_evaluated", 1)

        av = anchored_vwap(df, a["loc"])
        if av is None or len(av) <= slope_n:
            _stat_inc(stats, "anchors_skipped_insufficient_av", 1)
            continue

        av_clean = av.dropna()
        if len(av_clean) < (slope_n + 1):
            _stat_inc(stats, "anchors_skipped_insufficient_av", 1)
            continue

        av_now = float(av_clean.iloc[-1])
        av_s = slope_last(av_clean, n=slope_n)
        if np.isnan(av_s):
            _stat_inc(stats, "anchors_skipped_nan_slope", 1)
            continue

        # "Reclaim" logic (matches your run_scan flavor)
        is_reclaim = (
            (prev_px <= av_now and px > av_now) if direction == "Long"
            else (prev_px >= av_now and px < av_now)
        )

        dist = (
            (px - av_now) / av_now * 100.0 if direction == "Long"
            else (av_now - px) / av_now * 100.0
        )

        # Direction gate (price relative to AVWAP; reclaim allowed)
        if direction == "Long":
            if not (px > av_now or is_reclaim):
                _stat_inc(stats, "direction_gate_fail", 1)
                continue
            # Slope gate (with optional bypass on reclaim)
            if not (av_s >= slope_thr) and not (reclaim_bypass and is_reclaim):
                _stat_inc(stats, "slope_gate_fail", 1)
                continue
        else:
            if not (px < av_now or is_reclaim):
                _stat_inc(stats, "direction_gate_fail", 1)
                continue
            if not (av_s <= slope_thr) and not (reclaim_bypass and is_reclaim):
                _stat_inc(stats, "slope_gate_fail", 1)
                continue

        # Distance gate
        if dist > float(getattr(cfg, "MAX_DIST_FROM_AVWAP_PCT", 9999)):
            _stat_inc(stats, "dist_gate_fail", 1)
            continue

        # Scoring (kept consistent with your run_scan approach, but safe if trend_score is NaN)
        trend_term = 0.0 if (trend_score is None or np.isnan(trend_score)) else float(trend_score)
        score = (
            float(a.get("priority", 0))
            + (trend_term if direction == "Long" else -trend_term)
            - abs(dist)
            + (50.0 if 0.1 <= dist <= 1.5 else 0.0)
            + (40.0 if is_reclaim else 0.0)
        )

        if score > best_score:
            best_score = score
            best = {
                "Anchor": a.get("name", ""),
                "AVWAP": av_now,
                "AVWAP_Slope": float(av_s),
                "TrendScore": float(trend_score) if trend_score is not None and not np.isnan(trend_score) else 0.0,
                "Price": px,
                "DistFromAVWAP%": float(dist),
            }

    if best is not None:
        _stat_inc(stats, "anchor_found", 1)

    return best


def score_candidate(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    direction: str,
    stats: dict | None = None,
):
    """
    Backward-compatible candidate scoring:
    Returns:
      - None if it doesn't qualify
      - dict with stable keys if it qualifies

    This function is safe to call even if you don't use diagnostics.
    """
    _stat_inc(stats, "start", 1)

    if not basic_filters(df):
        _stat_inc(stats, "basic_filters_fail", 1)
        return None

    _stat_inc(stats, "basic_filters_pass", 1)

    best = pick_best_anchor(df, index_df, direction, stats=stats)
    if not best:
        return None

    _stat_inc(stats, "final_pass", 1)

    # Stable output schema (do not add extra keys unless you explicitly want them later)
    out = {
        "Direction": direction,
        "Price": round(float(best["Price"]), 2),
        "AVWAP": round(float(best["AVWAP"]), 2),
        "AVWAP_Slope": round(float(best["AVWAP_Slope"]), 6),
        "TrendScore": round(float(best["TrendScore"]), 6),
        "DistFromAVWAP%": round(float(best["DistFromAVWAP%"]), 2),
        "Anchor": best["Anchor"],
        "AvgDollarVol20": round(avg_dollar_vol(df), 0),
    }
    return out
