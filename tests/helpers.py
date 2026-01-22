from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")


FORBIDDEN_KEYS = (
    "entry",
    "entries",
    "signal",
    "order",
    "buy",
    "sell",
    "stop",
    "stop_loss",
    "target",
    "take_profit",
    "position_size",
    "sizing",
    "risk",
    "r_multiple",
    "expectancy",
    "pnl",
    "portfolio",
    "allocation",
    "leverage",
)


@dataclass(frozen=True)
class SyntheticInput:
    df: pd.DataFrame
    symbol: str
    scan_date: str


def make_ohlcv(start: str, periods: int, *, gap: bool = False) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq="D")
    close = np.linspace(100.0, 110.0, periods)
    open_ = close - 0.5
    if gap and periods > 1:
        open_[-1] = close[-2] * 1.1
    data = {
        "Open": open_,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.full(periods, 1_000_000.0),
    }
    return pd.DataFrame(data, index=dates)


def make_setup_rules(
    *,
    avwap_enabled: bool = True,
    extension_enabled: bool = True,
    gap_enabled: bool = True,
    structure_enabled: bool = True,
    vwap_lookback: int = 5,
    gap_threshold_pct: float = 4.0,
) -> dict[str, Any]:
    return {
        "setup": {
            "vwap": {
                "lookback": vwap_lookback,
                "control_buffer_pct": 0.2,
                "acceptance_bars": 2,
            },
            "avwap": {
                "control_buffer_pct": 0.2,
                "acceptance_bars": 2,
            },
            "extension": {
                "balanced_pct": 1.0,
                "moderate_pct": 3.0,
                "extended_pct": 6.0,
            },
            "gaps": {
                "reset_lookback": 10,
                "gap_pct": gap_threshold_pct,
                "reset_window": 3,
            },
            "structure": {
                "sma_fast": 3,
                "sma_slow": 5,
                "slope_lookback": 2,
            },
        },
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
                "enabled": avwap_enabled,
                "anchor_types": ["major_high", "major_low"],
                "states": {
                    "below_key_avwap": "supply_overhead",
                    "reclaiming_avwap": "reclaiming_avwap",
                    "accepted_above_avwap": "demand_underfoot",
                },
            },
            "extension_awareness": {
                "enabled": extension_enabled,
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
                "enabled": gap_enabled,
                "reset_reference_frame": True,
                "prioritize_post_gap_vwap": True,
                "allow_gap_day_anchor": True,
                "gap_threshold_pct": gap_threshold_pct,
            },
            "structure_confirmation": {
                "enabled": structure_enabled,
            },
        },
    }


def assert_no_forbidden_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = str(key).lower()
            for forbidden in FORBIDDEN_KEYS:
                if forbidden in key_lower:
                    raise AssertionError(f"Forbidden key detected: {key}")
            assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_forbidden_keys(item)


def get_by_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    return current


def assert_trace_outputs_exist(payload: dict[str, Any]) -> None:
    for entry in payload.get("trace", []):
        outputs = entry.get("outputs", [])
        for output in outputs:
            if get_by_path(payload, output) is None:
                raise AssertionError(f"Trace output path missing: {output}")


def assert_numeric_features_finite(features: dict[str, Any]) -> None:
    for key, value in features.items():
        if isinstance(value, (int, float)):
            if not np.isfinite(value):
                raise AssertionError(f"Feature {key} is not finite: {value}")
