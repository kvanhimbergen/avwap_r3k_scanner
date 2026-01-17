from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from anchors import anchored_vwap, anchor_gap_day, get_anchor_candidates
from indicators import slope_last, sma


@dataclass(frozen=True)
class SetupContext:
    vwap: float | None
    vwap_control: str
    vwap_reclaim: str
    vwap_acceptance: str
    vwap_dist_pct: float | None
    avwap: float | None
    avwap_control: str
    avwap_reclaim: str
    avwap_acceptance: str
    avwap_dist_pct: float | None
    extension_state: str
    gap_reset: str
    structure_state: str


def _default_rules_path() -> Path:
    return Path(__file__).resolve().parent / "knowledge" / "rules" / "setup_rules.yaml"


_DEFAULT_RULES: dict[str, Any] = {
    "setup": {
        "vwap": {
            "lookback": 20,
            "control_buffer_pct": 0.2,
            "acceptance_bars": 3,
        },
        "avwap": {
            "control_buffer_pct": 0.2,
            "acceptance_bars": 3,
        },
        "extension": {
            "balanced_pct": 1.0,
            "extended_pct": 6.0,
        },
        "gaps": {
            "reset_lookback": 60,
            "gap_pct": 4.0,
            "reset_window": 5,
        },
        "structure": {
            "sma_fast": 20,
            "sma_slow": 50,
            "slope_lookback": 5,
        },
    },
}


def _merge_defaults(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_setup_rules(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return deepcopy(_DEFAULT_RULES)

    if isinstance(data.get("setup"), dict):
        return _merge_defaults(_DEFAULT_RULES, data)

    if isinstance(data.get("setup_rules"), dict):
        normalized = deepcopy(_DEFAULT_RULES)
        ext = data["setup_rules"].get("extension_awareness", {}).get("thresholds_pct", {})
        if isinstance(ext, dict):
            if "compressed" in ext:
                normalized["setup"]["extension"]["balanced_pct"] = ext.get("compressed")
            if "overextended" in ext:
                normalized["setup"]["extension"]["extended_pct"] = ext.get("overextended")
        return normalized

    return deepcopy(_DEFAULT_RULES)


def load_setup_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path is not None else _default_rules_path()
    if not rules_path.exists():
        return deepcopy(_DEFAULT_RULES)
    return _normalize_setup_rules(yaml.safe_load(rules_path.read_text()) or {})


def _rolling_vwap(df: pd.DataFrame, lookback: int) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = tp * df["Volume"].astype(float)
    pv_sum = pv.rolling(lookback, min_periods=lookback).sum()
    vol_sum = df["Volume"].rolling(lookback, min_periods=lookback).sum()
    return pv_sum / vol_sum.replace(0, np.nan)


def _control_label(close: float, ref: float, buffer_pct: float) -> str:
    if ref is None or np.isnan(ref):
        return "unknown"
    buffer = ref * (buffer_pct / 100.0)
    if close > ref + buffer:
        return "bullish"
    if close < ref - buffer:
        return "bearish"
    return "neutral"


def _reclaim_label(prev_close: float, close: float, prev_ref: float, ref: float) -> str:
    if np.isnan(prev_ref) or np.isnan(ref):
        return "none"
    if prev_close <= prev_ref and close > ref:
        return "bullish"
    if prev_close >= prev_ref and close < ref:
        return "bearish"
    return "none"


def _acceptance_label(closes: pd.Series, refs: pd.Series, bars: int) -> str:
    if len(closes) < bars or len(refs) < bars:
        return "none"
    recent_close = closes.iloc[-bars:]
    recent_ref = refs.iloc[-bars:]
    if (recent_close > recent_ref).all():
        return "bullish"
    if (recent_close < recent_ref).all():
        return "bearish"
    return "none"


def _extension_label(dist_pct: float | None, balanced_pct: float, extended_pct: float) -> str:
    if dist_pct is None or np.isnan(dist_pct):
        return "unknown"
    dist_abs = abs(dist_pct)
    if dist_abs <= balanced_pct:
        return "balanced"
    if dist_abs >= extended_pct:
        return "extended"
    return "moderate"


def _structure_label(close: pd.Series, fast_n: int, slow_n: int, slope_n: int) -> str:
    fast = sma(close, fast_n)
    slow = sma(close, slow_n)
    if fast.isna().all() or slow.isna().all():
        return "unknown"
    fast_now = float(fast.iloc[-1])
    slow_now = float(slow.iloc[-1])
    slow_slope = slope_last(slow, n=slope_n)
    if np.isnan(slow_slope):
        return "unknown"
    if fast_now > slow_now and slow_slope > 0:
        return "bullish"
    if fast_now < slow_now and slow_slope < 0:
        return "bearish"
    return "neutral"


def compute_setup_context(
    df: pd.DataFrame,
    anchor_name: str | None,
    rules: dict[str, Any],
) -> SetupContext:
    vwap_rules = rules["setup"]["vwap"]
    avwap_rules = rules["setup"]["avwap"]
    ext_rules = rules["setup"]["extension"]
    gap_rules = rules["setup"]["gaps"]
    struct_rules = rules["setup"]["structure"]

    vwap_series = _rolling_vwap(df, int(vwap_rules["lookback"]))
    vwap_now = float(vwap_series.iloc[-1]) if not vwap_series.empty else np.nan

    close = df["Close"]
    close_now = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else close_now
    prev_vwap = float(vwap_series.iloc[-2]) if len(vwap_series) > 1 else vwap_now

    vwap_control = _control_label(close_now, vwap_now, float(vwap_rules["control_buffer_pct"]))
    vwap_reclaim = _reclaim_label(prev_close, close_now, prev_vwap, vwap_now)
    vwap_acceptance = _acceptance_label(close, vwap_series, int(vwap_rules["acceptance_bars"]))
    vwap_dist = ((close_now - vwap_now) / vwap_now * 100.0) if not np.isnan(vwap_now) else None

    anchor_loc = None
    if anchor_name:
        for candidate in get_anchor_candidates(df):
            if candidate.get("name") == anchor_name:
                anchor_loc = candidate.get("loc")
                break

    avwap_series = None
    if anchor_loc is not None:
        avwap_series = anchored_vwap(df, anchor_loc)

    if avwap_series is None or avwap_series.empty:
        avwap_series = pd.Series(dtype=float)

    avwap_now = float(avwap_series.iloc[-1]) if len(avwap_series) else np.nan
    prev_avwap = float(avwap_series.iloc[-2]) if len(avwap_series) > 1 else avwap_now

    avwap_control = _control_label(close_now, avwap_now, float(avwap_rules["control_buffer_pct"]))
    avwap_reclaim = _reclaim_label(prev_close, close_now, prev_avwap, avwap_now)
    avwap_acceptance = _acceptance_label(close, avwap_series, int(avwap_rules["acceptance_bars"]))
    avwap_dist = ((close_now - avwap_now) / avwap_now * 100.0) if not np.isnan(avwap_now) else None

    extension_state = _extension_label(
        avwap_dist,
        float(ext_rules["balanced_pct"]),
        float(ext_rules["extended_pct"]),
    )

    gap_loc = anchor_gap_day(df, int(gap_rules["reset_lookback"]), float(gap_rules["gap_pct"]))
    gap_reset = "none"
    if gap_loc is not None:
        bars_since_gap = (len(df) - 1) - int(gap_loc)
        if bars_since_gap <= int(gap_rules["reset_window"]):
            gap_reset = "recent"
        else:
            gap_reset = "stale"

    structure_state = _structure_label(
        close,
        int(struct_rules["sma_fast"]),
        int(struct_rules["sma_slow"]),
        int(struct_rules["slope_lookback"]),
    )

    return SetupContext(
        vwap=None if np.isnan(vwap_now) else vwap_now,
        vwap_control=vwap_control,
        vwap_reclaim=vwap_reclaim,
        vwap_acceptance=vwap_acceptance,
        vwap_dist_pct=vwap_dist,
        avwap=None if np.isnan(avwap_now) else avwap_now,
        avwap_control=avwap_control,
        avwap_reclaim=avwap_reclaim,
        avwap_acceptance=avwap_acceptance,
        avwap_dist_pct=avwap_dist,
        extension_state=extension_state,
        gap_reset=gap_reset,
        structure_state=structure_state,
    )
