from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FEATURE_FLAG_ENV = "E3_RISK_ATTRIBUTION_SUMMARY_WRITE"

RECORD_TYPE_SUMMARY = "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
SCHEMA_VERSION = 1

ROUND_DECIMALS = 10
TOP_SYMBOLS_LIMIT = 20


def summary_write_enabled() -> bool:
    return os.getenv(FEATURE_FLAG_ENV, "0").strip() == "1"


def resolve_input_path(
    *, ny_date: str, base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION"
) -> Path:
    return Path(base_dir) / f"{ny_date}.jsonl"


def resolve_summary_path(
    *, ny_date: str, base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
) -> Path:
    return Path(base_dir) / f"{ny_date}.json"


def load_attribution_events(
    *, ny_date: str, base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION"
) -> list[dict[str, Any]]:
    path = resolve_input_path(ny_date=ny_date, base_dir=base_dir)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(json.loads(stripped))
    return events


def _round_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), ROUND_DECIMALS)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def build_daily_summary(*, ny_date: str, events: list[dict], source: str) -> dict:
    events_total = len(events)
    events_with_modulation = 0
    events_no_modulation = 0

    baseline_total = 0.0
    modulated_total = 0.0
    delta_pct_values: list[float] = []

    reason_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    hard_caps_counts: dict[str, int] = {}
    symbol_totals: dict[str, dict[str, float | int]] = {}

    for event in events:
        baseline_notional = float(event.get("baseline", {}).get("notional", 0.0))
        modulated_notional = float(event.get("modulated", {}).get("notional", 0.0))
        delta_notional = float(event.get("delta", {}).get("notional", 0.0))
        delta_qty = float(event.get("delta", {}).get("qty", 0.0))

        baseline_total += baseline_notional
        modulated_total += modulated_notional

        if delta_qty != 0 or delta_notional != 0:
            events_with_modulation += 1
        else:
            events_no_modulation += 1

        if baseline_notional > 0:
            delta_pct = event.get("delta", {}).get("pct_notional")
            if delta_pct is None:
                delta_pct = delta_notional / baseline_notional
            delta_pct_values.append(float(delta_pct))

        for reason in event.get("reason_codes", []) or []:
            reason_key = str(reason)
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1

        regime_code = event.get("regime", {}).get("code")
        regime_key = str(regime_code) if regime_code else "UNKNOWN"
        regime_counts[regime_key] = regime_counts.get(regime_key, 0) + 1

        for cap in event.get("hard_caps_applied", []) or []:
            cap_key = str(cap)
            hard_caps_counts[cap_key] = hard_caps_counts.get(cap_key, 0) + 1

        symbol = str(event.get("symbol") or "")
        if symbol:
            if symbol not in symbol_totals:
                symbol_totals[symbol] = {
                    "baseline_notional": 0.0,
                    "modulated_notional": 0.0,
                    "delta_notional": 0.0,
                    "events": 0,
                }
            agg = symbol_totals[symbol]
            agg["baseline_notional"] = float(agg["baseline_notional"]) + baseline_notional
            agg["modulated_notional"] = float(agg["modulated_notional"]) + modulated_notional
            agg["delta_notional"] = float(agg["delta_notional"]) + delta_notional
            agg["events"] = int(agg["events"]) + 1

    delta_total = modulated_total - baseline_total
    delta_pct_min = _median([])
    delta_pct_median = _median([])
    delta_pct_max = _median([])
    if delta_pct_values:
        delta_pct_min = min(delta_pct_values)
        delta_pct_median = _median(delta_pct_values)
        delta_pct_max = max(delta_pct_values)

    by_reason_code = {key: reason_counts[key] for key in sorted(reason_counts)}
    by_regime_code = {key: regime_counts[key] for key in sorted(regime_counts)}
    hard_caps_applied_counts = {
        key: hard_caps_counts[key] for key in sorted(hard_caps_counts)
    }

    top_symbols: list[dict[str, Any]] = []
    for symbol, agg in symbol_totals.items():
        delta_notional = float(agg["delta_notional"])
        top_symbols.append(
            {
                "symbol": symbol,
                "abs_delta_notional": abs(delta_notional),
                "delta_notional": delta_notional,
                "baseline_notional": float(agg["baseline_notional"]),
                "modulated_notional": float(agg["modulated_notional"]),
                "events": int(agg["events"]),
            }
        )
    top_symbols.sort(key=lambda item: (-item["abs_delta_notional"], item["symbol"]))
    top_symbols = top_symbols[:TOP_SYMBOLS_LIMIT]
    for item in top_symbols:
        item["abs_delta_notional"] = _round_value(item["abs_delta_notional"])
        item["delta_notional"] = _round_value(item["delta_notional"])
        item["baseline_notional"] = _round_value(item["baseline_notional"])
        item["modulated_notional"] = _round_value(item["modulated_notional"])

    summary = {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE_SUMMARY,
        "date_ny": ny_date,
        "source": source,
        "counts": {
            "events_total": events_total,
            "events_with_modulation": events_with_modulation,
            "events_no_modulation": events_no_modulation,
        },
        "notional_totals": {
            "baseline_total": _round_value(baseline_total),
            "modulated_total": _round_value(modulated_total),
            "delta_total": _round_value(delta_total),
            "delta_total_abs": _round_value(abs(delta_total)),
        },
        "delta_pct_distribution": {
            "min": _round_value(delta_pct_min),
            "median": _round_value(delta_pct_median),
            "max": _round_value(delta_pct_max),
        },
        "by_reason_code": by_reason_code,
        "by_regime_code": by_regime_code,
        "hard_caps_applied_counts": hard_caps_applied_counts,
        "top_symbols_by_abs_delta_notional": top_symbols,
    }
    return summary


def write_daily_summary(
    summary: dict, *, base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
) -> Path:
    ny_date = summary.get("date_ny")
    if not isinstance(ny_date, str) or not ny_date:
        raise ValueError("summary missing date_ny")
    path = resolve_summary_path(ny_date=ny_date, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
    return path


def generate_and_write_daily_summary(
    *, ny_date: str, source: str = "risk_attribution_summary"
) -> Path | None:
    if not summary_write_enabled():
        return None
    try:
        events = load_attribution_events(ny_date=ny_date)
        summary = build_daily_summary(ny_date=ny_date, events=events, source=source)
        return write_daily_summary(summary)
    except Exception as exc:  # noqa: BLE001 - fail-open
        print(f"WARN: risk attribution summary write failed: {exc}")
        return None
