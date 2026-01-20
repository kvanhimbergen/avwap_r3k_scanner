from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from anchors import anchored_vwap, anchor_gap_day, get_anchor_candidates
from indicators import slope_last, sma
from provenance import git_sha


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


def _safe_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if np.isfinite(value):
            return float(value)
        return None
    return value


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _map_control_label(label: str, bullish_label: str, bearish_label: str) -> str:
    mapping = {
        "bullish": bullish_label,
        "bearish": bearish_label,
        "neutral": "balanced_or_indecisive",
        "none": "na",
        "unknown": "na",
    }
    return mapping.get(label, "na")


def _map_reclaim_label(label: str, bullish_label: str, bearish_label: str) -> str:
    mapping = {
        "bullish": bullish_label,
        "bearish": bearish_label,
        "neutral": "na",
        "none": "na",
        "unknown": "na",
    }
    return mapping.get(label, "na")


def _map_extension_label(label: str) -> str:
    mapping = {
        "balanced": "compressed_near_value",
        "moderate": "moderately_extended",
        "extended": "overextended_from_value",
        "unknown": "na",
    }
    return mapping.get(label, "na")


def _map_structure_label(label: str) -> str:
    mapping = {
        "bullish": "buyers_in_control",
        "bearish": "sellers_in_control",
        "neutral": "balanced_or_indecisive",
        "unknown": "na",
    }
    return mapping.get(label, "na")


def _module_enabled(setup_rules: dict[str, Any], module: str, default: bool = True) -> bool:
    if not isinstance(setup_rules, dict):
        return default
    setup_rules_block = setup_rules.get("setup_rules")
    if isinstance(setup_rules_block, dict):
        module_block = setup_rules_block.get(module)
        if isinstance(module_block, dict) and "enabled" in module_block:
            return bool(module_block.get("enabled"))
    return default


def _setup_rules_metadata(path: Path) -> tuple[Any, str]:
    if not path.exists():
        return None, hashlib.sha256(b"").hexdigest()
    raw_text = path.read_text(encoding="utf-8")
    rules_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    parsed = yaml.safe_load(raw_text) or {}
    version = None
    if isinstance(parsed, dict):
        setup_block = parsed.get("setup_rules")
        if isinstance(setup_block, dict):
            version = setup_block.get("version")
    return version, rules_hash


def _isoformat(dt: datetime) -> str:
    if isinstance(dt, pd.Timestamp):
        return dt.isoformat()
    return dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else dt.isoformat()


def compute_setup_context_contract(
    *,
    df: pd.DataFrame,
    symbol: str,
    anchor_name: str | None,
    setup_rules: dict,
    as_of_dt: datetime,
) -> dict:
    rules = _normalize_setup_rules(setup_rules)
    setup_ctx = compute_setup_context(df, anchor_name, rules)

    vwap_rules = rules["setup"]["vwap"]
    avwap_rules = rules["setup"]["avwap"]
    ext_rules = rules["setup"]["extension"]
    gap_rules = rules["setup"]["gaps"]
    struct_rules = rules["setup"]["structure"]

    vwap_label = _map_control_label(setup_ctx.vwap_control, "buyers_in_control", "sellers_in_control")
    avwap_label = _map_control_label(setup_ctx.avwap_control, "demand_underfoot", "supply_overhead")
    vwap_reclaim = _map_reclaim_label(setup_ctx.vwap_reclaim, "reclaiming_vwap", "below_vwap")
    avwap_reclaim = _map_reclaim_label(setup_ctx.avwap_reclaim, "reclaiming_avwap", "supply_overhead")
    vwap_acceptance = _map_reclaim_label(setup_ctx.vwap_acceptance, "accepted_above_vwap", "below_vwap")
    avwap_acceptance = _map_reclaim_label(setup_ctx.avwap_acceptance, "demand_underfoot", "supply_overhead")
    extension_label = _map_extension_label(setup_ctx.extension_state)
    structure_label = _map_structure_label(setup_ctx.structure_state)

    rules_version, rules_hash = _setup_rules_metadata(_default_rules_path())
    code_version = git_sha() or "unknown"

    labels = {
        "vwap": {
            "control": vwap_label,
            "reclaim": vwap_reclaim,
            "acceptance": vwap_acceptance,
        },
        "avwap": {
            "control": avwap_label,
            "reclaim": avwap_reclaim,
            "acceptance": avwap_acceptance,
        },
        "extension": {"state": extension_label},
        "gap": {"reset": setup_ctx.gap_reset},
        "structure": {"state": structure_label},
    }

    features = {
        "vwap": {
            "value": _safe_number(setup_ctx.vwap),
            "distance_pct": _safe_number(setup_ctx.vwap_dist_pct),
            "lookback": _safe_number(vwap_rules.get("lookback")),
            "control_buffer_pct": _safe_number(vwap_rules.get("control_buffer_pct")),
            "acceptance_bars": _safe_number(vwap_rules.get("acceptance_bars")),
        },
        "avwap": {
            "value": _safe_number(setup_ctx.avwap),
            "distance_pct": _safe_number(setup_ctx.avwap_dist_pct),
            "anchor_name": _safe_text(anchor_name),
            "control_buffer_pct": _safe_number(avwap_rules.get("control_buffer_pct")),
            "acceptance_bars": _safe_number(avwap_rules.get("acceptance_bars")),
        },
        "extension": {
            "distance_pct": _safe_number(setup_ctx.avwap_dist_pct),
            "balanced_pct": _safe_number(ext_rules.get("balanced_pct")),
            "extended_pct": _safe_number(ext_rules.get("extended_pct")),
        },
        "gap": {
            "reset_lookback": _safe_number(gap_rules.get("reset_lookback")),
            "gap_pct": _safe_number(gap_rules.get("gap_pct")),
            "reset_window": _safe_number(gap_rules.get("reset_window")),
        },
        "structure": {
            "sma_fast": _safe_number(struct_rules.get("sma_fast")),
            "sma_slow": _safe_number(struct_rules.get("sma_slow")),
            "slope_lookback": _safe_number(struct_rules.get("slope_lookback")),
        },
    }

    trace = [
        {
            "rule_id": "vwap_context",
            "module": "vwap",
            "fired": _module_enabled(setup_rules, "vwap_context", True),
            "inputs": {
                "close": _safe_number(df["Close"].iloc[-1]) if not df.empty else None,
                "buffer_pct": _safe_number(vwap_rules.get("control_buffer_pct")),
                "acceptance_bars": _safe_number(vwap_rules.get("acceptance_bars")),
            },
            "outputs": [
                "labels.vwap.control",
                "labels.vwap.reclaim",
                "labels.vwap.acceptance",
                "features.vwap.value",
                "features.vwap.distance_pct",
            ],
        },
        {
            "rule_id": "avwap_context",
            "module": "avwap",
            "fired": _module_enabled(setup_rules, "avwap_context", True),
            "inputs": {
                "close": _safe_number(df["Close"].iloc[-1]) if not df.empty else None,
                "anchor_name": _safe_text(anchor_name),
                "buffer_pct": _safe_number(avwap_rules.get("control_buffer_pct")),
                "acceptance_bars": _safe_number(avwap_rules.get("acceptance_bars")),
            },
            "outputs": [
                "labels.avwap.control",
                "labels.avwap.reclaim",
                "labels.avwap.acceptance",
                "features.avwap.value",
                "features.avwap.distance_pct",
            ],
        },
        {
            "rule_id": "extension_awareness",
            "module": "extension",
            "fired": _module_enabled(setup_rules, "extension_awareness", True),
            "inputs": {
                "distance_pct": _safe_number(setup_ctx.avwap_dist_pct),
                "balanced_pct": _safe_number(ext_rules.get("balanced_pct")),
                "extended_pct": _safe_number(ext_rules.get("extended_pct")),
            },
            "outputs": [
                "labels.extension.state",
                "features.extension.distance_pct",
                "features.extension.balanced_pct",
                "features.extension.extended_pct",
            ],
        },
        {
            "rule_id": "gap_context",
            "module": "gap",
            "fired": _module_enabled(setup_rules, "gap_context", True),
            "inputs": {
                "reset_lookback": _safe_number(gap_rules.get("reset_lookback")),
                "gap_pct": _safe_number(gap_rules.get("gap_pct")),
                "reset_window": _safe_number(gap_rules.get("reset_window")),
            },
            "outputs": [
                "labels.gap.reset",
                "features.gap.reset_lookback",
                "features.gap.gap_pct",
                "features.gap.reset_window",
            ],
        },
        {
            "rule_id": "structure_confirmation",
            "module": "structure",
            "fired": _module_enabled(setup_rules, "structure_confirmation", True),
            "inputs": {
                "sma_fast": _safe_number(struct_rules.get("sma_fast")),
                "sma_slow": _safe_number(struct_rules.get("sma_slow")),
                "slope_lookback": _safe_number(struct_rules.get("slope_lookback")),
            },
            "outputs": [
                "labels.structure.state",
                "features.structure.sma_fast",
                "features.structure.sma_slow",
                "features.structure.slope_lookback",
            ],
        },
    ]

    return {
        "schema": {
            "name": "setup_context",
            "version": 1,
        },
        "identity": {
            "symbol": symbol,
            "anchor_name": _safe_text(anchor_name),
            "as_of": _isoformat(as_of_dt),
        },
        "provenance": {
            "setup_rules_version": _safe_number(rules_version),
            "setup_rules_hash": rules_hash,
            "code_version": code_version,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        },
        "labels": labels,
        "features": features,
        "trace": trace,
    }
