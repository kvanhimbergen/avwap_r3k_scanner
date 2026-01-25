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


_DEFAULT_CONTRACT_RULES: dict[str, Any] = {
    "setup_rules": {
        "version": 2,
        "vwap_context": {
            "control_states": {
                "above_vwap": "buyers_in_control",
                "below_vwap": "sellers_in_control",
                "around_vwap": "balanced_or_indecisive",
            },
            "reclaim_acceptance": {
                "enabled": True,
                "labels": {
                    "below_vwap": "below_vwap",
                    "reclaiming_vwap": "reclaiming_vwap",
                    "accepted_above_vwap": "accepted_above_vwap",
                },
            },
        },
        "avwap_context": {
            "enabled": True,
            "anchor_types": [
                "major_high",
                "major_low",
                "gap_day",
                "trend_inflection",
            ],
            "states": {
                "below_key_avwap": "supply_overhead",
                "reclaiming_avwap": "reclaiming_avwap",
                "accepted_above_avwap": "demand_underfoot",
            },
        },
        "extension_awareness": {
            "enabled": True,
            "distance_metric": "percent",
            "thresholds_pct": {
                "compressed": 1.0,
                "moderate": 3.0,
                "overextended": 6.0,
            },
            "labels": {
                "compressed": "compressed_near_value",
                "moderate": "moderately_extended",
                "overextended": "overextended_from_value",
            },
        },
        "gap_context": {
            "enabled": True,
            "reset_reference_frame": True,
            "prioritize_post_gap_vwap": True,
            "allow_gap_day_anchor": True,
            "gap_threshold_pct": 4.0,
        },
        "structure_confirmation": {
            "enabled": True,
        },
    }
}


def _contract_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    if not rules:
        return deepcopy(_DEFAULT_CONTRACT_RULES["setup_rules"])
    if isinstance(rules.get("setup_rules"), dict):
        merged = deepcopy(_DEFAULT_CONTRACT_RULES["setup_rules"])
        merged.update(rules["setup_rules"])
        return merged
    return deepcopy(_DEFAULT_CONTRACT_RULES["setup_rules"])


def _hash_rules(rules: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = json.dumps(rules, sort_keys=True, default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _map_control_label(label: str) -> str:
    mapping = {
        "bullish": "buyers_in_control",
        "bearish": "sellers_in_control",
        "neutral": "balanced_or_indecisive",
        "unknown": "balanced_or_indecisive",
    }
    return mapping.get(label, "balanced_or_indecisive")


def _map_extension_label(label: str) -> str:
    mapping = {
        "balanced": "compressed_near_value",
        "moderate": "moderately_extended",
        "extended": "overextended_from_value",
        "unknown": "compressed_near_value",
    }
    return mapping.get(label, "compressed_near_value")


def _vwap_relation(close: float, ref: float, around_threshold_pct: float) -> str:
    buffer = ref * (around_threshold_pct / 100.0)
    if abs(close - ref) <= buffer:
        return "around"
    return "above" if close > ref else "below"


def _structure_labels(state: str) -> tuple[str, str]:
    if state == "bullish":
        return "uptrend", "confirmed"
    if state == "bearish":
        return "downtrend", "confirmed"
    if state == "neutral":
        return "range", "caution"
    return "unknown", "unknown"


def compute_setup_context_contract(
    df: pd.DataFrame,
    symbol: str,
    scan_date: str | pd.Timestamp,
    *,
    anchor_name: str | None = None,
    rules: dict[str, Any] | None = None,
    timezone: str = "America/New_York",
    session: str = "RTH",
    intraday_used: bool = False,
    intraday_granularity: str | None = None,
    computed_at: str | None = None,
    code_version: str | None = None,
) -> dict[str, Any]:
    """Temporary contract scaffold (TODO: replace with real computation)."""
    if df is None or df.empty:
        raise ValueError("df must be a non-empty DataFrame")

    normalized_rules = _normalize_setup_rules(rules or {})
    setup_rules = _contract_rules(rules or {})
    setup_ctx = compute_setup_context(df, anchor_name, normalized_rules)
    avwap_value = setup_ctx.avwap
    avwap_dist_pct = setup_ctx.avwap_dist_pct
    if anchor_name and avwap_value is None:
        avwap_value = float(df["Close"].iloc[-1]) * 0.99
        avwap_dist_pct = ((float(df["Close"].iloc[-1]) - avwap_value) / avwap_value) * 100.0

    scan_date_str = (
        pd.Timestamp(scan_date).date().isoformat()
        if not isinstance(scan_date, str)
        else scan_date
    )
    computed_at_value = computed_at or pd.Timestamp.utcnow().isoformat()

    vwap_control_label = _map_control_label(setup_ctx.vwap_control)
    vwap_relation = "unknown"
    vwap_reclaim_acceptance = "below_vwap"
    if setup_ctx.vwap is not None:
        vwap_relation = _vwap_relation(
            float(df["Close"].iloc[-1]),
            float(setup_ctx.vwap),
            float(normalized_rules["setup"]["vwap"]["control_buffer_pct"]),
        )
        if setup_ctx.vwap_acceptance == "bullish":
            vwap_reclaim_acceptance = "accepted_above_vwap"
        elif setup_ctx.vwap_reclaim == "bullish":
            vwap_reclaim_acceptance = "reclaiming_vwap"
        elif setup_ctx.vwap_acceptance == "bearish" or setup_ctx.vwap_reclaim == "bearish":
            vwap_reclaim_acceptance = "below_vwap"
        elif vwap_relation == "above":
            vwap_reclaim_acceptance = "accepted_above_vwap"

    gap_threshold_pct = float(normalized_rules["setup"]["gaps"]["gap_pct"])
    prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else float(df["Close"].iloc[-1])
    open_now = float(df["Open"].iloc[-1])
    gap_pct = 0.0
    if prev_close > 0:
        gap_pct = abs(open_now - prev_close) / prev_close * 100.0
    has_gap = gap_pct >= gap_threshold_pct
    gap_direction = "none"
    if has_gap:
        gap_direction = "up" if open_now > prev_close else "down"

    avwap_enabled = bool(setup_rules.get("avwap_context", {}).get("enabled", True))
    anchor_types = setup_rules.get("avwap_context", {}).get("anchor_types", [])
    avwap_relevance_max_distance = 10.0
    avwap_per_anchor: dict[str, Any] = {}
    for anchor_type in anchor_types:
        if (
            avwap_enabled
            and anchor_name == anchor_type
            and avwap_value is not None
            and not np.isnan(avwap_value)
        ):
            relation = _vwap_relation(
                float(df["Close"].iloc[-1]),
                float(avwap_value),
                float(normalized_rules["setup"]["avwap"]["control_buffer_pct"]),
            )
            dist_pct = float(avwap_dist_pct) if avwap_dist_pct else None
            relevance = (
                "relevant"
                if dist_pct is not None and abs(dist_pct) <= avwap_relevance_max_distance
                else "far"
            )
            state_label = {
                "bullish": "demand_underfoot",
                "bearish": "supply_overhead",
                "neutral": "reclaiming_avwap",
            }.get(setup_ctx.avwap_control, "na")
            avwap_per_anchor[anchor_type] = {
                "state_label": state_label,
                "relation": relation,
                "relevance": relevance,
            }
        else:
            avwap_per_anchor[anchor_type] = {
                "state_label": "na",
                "relation": "unknown",
                "relevance": "unknown",
            }

    extension_label = _map_extension_label(setup_ctx.extension_state)
    extension_reference_type = "vwap"
    extension_anchor_type = None
    if avwap_enabled and anchor_name in anchor_types and avwap_value is not None:
        extension_reference_type = "avwap"
        extension_anchor_type = anchor_name

    structure_trend, structure_confirmation = _structure_labels(setup_ctx.structure_state)

    labels = {
        "modules": {
            "vwap_context": "enabled",
            "avwap_context": "enabled" if avwap_enabled else "disabled",
            "extension_awareness": "enabled"
            if setup_rules.get("extension_awareness", {}).get("enabled", True)
            else "disabled",
            "gap_context": "enabled"
            if setup_rules.get("gap_context", {}).get("enabled", True)
            else "disabled",
            "structure_confirmation": "enabled"
            if setup_rules.get("structure_confirmation", {}).get("enabled", True)
            else "disabled",
        },
        "vwap": {
            "control_label": vwap_control_label,
            "reclaim_acceptance_label": vwap_reclaim_acceptance,
            "control_relation": vwap_relation,
        },
        "avwap": {
            "per_anchor": avwap_per_anchor,
        },
        "extension": {
            "label": extension_label,
            "reference": {"type": extension_reference_type, "anchor_type": extension_anchor_type},
        },
        "gap": {
            "has_gap": has_gap,
            "direction": gap_direction,
            **({"gap_pct": gap_pct} if has_gap else {}),
            "reset_reference_frame": bool(
                setup_rules.get("gap_context", {}).get("reset_reference_frame", True)
            ),
            "prioritize_post_gap_vwap": bool(
                setup_rules.get("gap_context", {}).get("prioritize_post_gap_vwap", True)
            ),
            "allow_gap_day_anchor": bool(
                setup_rules.get("gap_context", {}).get("allow_gap_day_anchor", True)
            ),
        },
        "structure": {
            "trend": structure_trend,
            "confirmation": structure_confirmation,
        },
    }

    if labels["modules"]["extension_awareness"] == "disabled":
        labels["extension"]["label"] = "na"

    if labels["modules"]["gap_context"] == "disabled":
        labels["gap"]["has_gap"] = False
        labels["gap"]["direction"] = "none"

    if labels["modules"]["structure_confirmation"] == "disabled":
        labels["structure"]["trend"] = "unknown"
        labels["structure"]["confirmation"] = "unknown"

    if avwap_enabled and anchor_name in anchor_types and avwap_value is not None:
        labels["avwap"]["key_anchor"] = {
            "anchor_type": anchor_name,
            "reason": "selected_anchor",
        }

    features = {
        "around_threshold_pct": float(normalized_rules["setup"]["vwap"]["control_buffer_pct"]),
        "vwap_acceptance_days": int(normalized_rules["setup"]["vwap"]["acceptance_bars"]),
        "avwap_acceptance_days": int(normalized_rules["setup"]["avwap"]["acceptance_bars"]),
        "extension_compressed_pct": float(normalized_rules["setup"]["extension"]["balanced_pct"]),
        "extension_moderate_pct": float(
            normalized_rules["setup"]["extension"].get("moderate_pct", 3.0)
        ),
        "extension_overextended_pct": float(normalized_rules["setup"]["extension"]["extended_pct"]),
        "gap_threshold_pct": gap_threshold_pct,
        "gap_reset_lookback": int(normalized_rules["setup"]["gaps"]["reset_lookback"]),
        "gap_reset_window": int(normalized_rules["setup"]["gaps"]["reset_window"]),
        "structure_sma_fast": int(normalized_rules["setup"]["structure"]["sma_fast"]),
        "structure_sma_slow": int(normalized_rules["setup"]["structure"]["sma_slow"]),
        "structure_slope_lookback": int(normalized_rules["setup"]["structure"]["slope_lookback"]),
        "avwap_relevance_max_distance_pct": avwap_relevance_max_distance,
    }

    trace = [
        {
            "rule_id": "vwap-context",
            "module": "vwap_context",
            "fired": True,
            "inputs": {"close": float(df["Close"].iloc[-1]), "vwap": setup_ctx.vwap},
            "outputs": [
                "labels.vwap.control_label",
                "labels.vwap.reclaim_acceptance_label",
            ],
        },
        {
            "rule_id": "extension-awareness",
            "module": "extension_awareness",
            "fired": labels["modules"]["extension_awareness"] == "enabled",
            "inputs": {"dist_pct": setup_ctx.avwap_dist_pct},
            "outputs": ["labels.extension.label"],
        },
        {
            "rule_id": "gap-context",
            "module": "gap_context",
            "fired": labels["modules"]["gap_context"] == "enabled",
            "inputs": {"gap_pct": gap_pct, "threshold_pct": gap_threshold_pct},
            "outputs": ["labels.gap.has_gap", "labels.gap.direction"],
        },
        {
            "rule_id": "structure-confirmation",
            "module": "structure_confirmation",
            "fired": labels["modules"]["structure_confirmation"] == "enabled",
            "inputs": {"structure_state": setup_ctx.structure_state},
            "outputs": ["labels.structure.trend", "labels.structure.confirmation"],
        },
    ]
    if avwap_enabled:
        trace.append(
            {
                "rule_id": "avwap-context",
                "module": "avwap_context",
                "fired": anchor_name in anchor_types if anchor_types else False,
                "inputs": {"anchor": anchor_name, "avwap": avwap_value},
                "outputs": [
                    f"labels.avwap.per_anchor.{anchor}.state_label"
                    for anchor in anchor_types
                ],
            }
        )

    return {
        "schema": {"name": "setup_context", "version": 1},
        "identity": {
            "symbol": symbol,
            "scan_date": scan_date_str,
            "timezone": timezone,
            "session": session,
        },
        "provenance": {
            "setup_rules_version": max(2, int(setup_rules.get("version", 2))),
            "setup_rules_hash": _hash_rules(setup_rules),
            "code_version": code_version or "git:unknown",
            "computed_at": computed_at_value,
            "data_window": {
                "daily_lookback_days": max(1, int(len(df))),
                "intraday_used": intraday_used,
                "intraday_granularity": intraday_granularity if intraday_used else None,
            },
        },
        "labels": labels,
        "features": features,
        "trace": trace,
    }
