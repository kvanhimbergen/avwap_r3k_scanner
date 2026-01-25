from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

FEATURE_FLAG_ENV = "E3_RISK_ATTRIBUTION_ROLLING_WRITE"
RECORD_TYPE = "PORTFOLIO_RISK_ATTRIBUTION_ROLLING_SUMMARY"
SCHEMA_VERSION = 1

ROUND_NOTIONAL_DECIMALS = 2
ROUND_PCT_DECIMALS = 4
TOP_SYMBOLS_LIMIT = 25
WINDOW_LABEL_DEFAULT = "20D"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def round_notional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), ROUND_NOTIONAL_DECIMALS)


def round_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), ROUND_PCT_DECIMALS)


def rolling_write_enabled() -> bool:
    return os.getenv(FEATURE_FLAG_ENV, "0").strip() == "1"


def resolve_input_dir() -> Path:
    return Path("ledger/PORTFOLIO_RISK_ATTRIBUTION_SUMMARY")


def resolve_output_path(*, as_of_date_ny: str, window_label: str = WINDOW_LABEL_DEFAULT) -> Path:
    return Path("ledger/PORTFOLIO_RISK_ATTRIBUTION_ROLLING") / window_label / f"{as_of_date_ny}.json"


def list_available_daily_dates(input_dir: Path) -> list[str]:
    if not input_dir.exists():
        return []
    dates: list[str] = []
    for entry in input_dir.iterdir():
        if not entry.is_file() or entry.suffix != ".json":
            continue
        date_part = entry.stem
        if _DATE_RE.match(date_part):
            dates.append(date_part)
    return sorted(dates)


def load_daily_summary(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_reason_code_totals(value: Any) -> tuple[int, float]:
    if isinstance(value, dict):
        decisions = int(value.get("decisions", 0))
        delta_notional = float(value.get("delta_notional", 0.0))
        return decisions, delta_notional
    if isinstance(value, (int, float)):
        return int(value), 0.0
    return 0, 0.0


def _extract_symbol_entries(summary: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = summary.get("top_symbols_by_abs_delta_notional")
    if isinstance(candidates, list):
        return candidates
    candidates = summary.get("top_symbols_by_delta_notional")
    if isinstance(candidates, list):
        return candidates
    candidates = summary.get("top_symbols")
    if isinstance(candidates, list):
        return candidates
    return []


def build_rolling_summary(
    *,
    as_of_date_ny: str,
    window_size: int = 20,
    window_label: str = WINDOW_LABEL_DEFAULT,
    input_dir: Path | None = None,
) -> dict[str, Any] | None:
    input_dir = input_dir or resolve_input_dir()
    available_dates = list_available_daily_dates(input_dir)
    if as_of_date_ny not in available_dates:
        return None
    eligible_dates = [date for date in available_dates if date <= as_of_date_ny]
    if len(eligible_dates) < window_size:
        return None
    window_dates = eligible_dates[-window_size:]
    if len(window_dates) < window_size:
        return None

    baseline_total = 0.0
    modulated_total = 0.0
    delta_total = 0.0
    decisions_total = 0
    decisions_modulated = 0
    decisions_unmodified = 0

    reason_totals: dict[str, dict[str, float | int]] = {}
    symbol_totals: dict[str, dict[str, float | int]] = {}

    source_files: list[str] = []

    for date in window_dates:
        summary_path = input_dir / f"{date}.json"
        source_files.append(str(summary_path))
        summary = load_daily_summary(summary_path)

        notional_totals = summary.get("notional_totals", {})
        baseline_total += float(notional_totals.get("baseline_total", 0.0))
        modulated_total += float(notional_totals.get("modulated_total", 0.0))
        delta_total += float(notional_totals.get("delta_total", 0.0))

        counts = summary.get("counts", {})
        decisions_total += int(counts.get("events_total", 0))
        decisions_modulated += int(counts.get("events_with_modulation", 0))
        decisions_unmodified += int(counts.get("events_no_modulation", 0))

        for reason_code, value in (summary.get("by_reason_code", {}) or {}).items():
            decisions, delta_notional = _extract_reason_code_totals(value)
            if reason_code not in reason_totals:
                reason_totals[reason_code] = {"decisions": 0, "delta_notional": 0.0}
            agg = reason_totals[reason_code]
            agg["decisions"] = int(agg["decisions"]) + decisions
            agg["delta_notional"] = float(agg["delta_notional"]) + delta_notional

        for symbol_entry in _extract_symbol_entries(summary):
            symbol = str(symbol_entry.get("symbol") or "")
            if not symbol:
                continue
            delta_notional = float(symbol_entry.get("delta_notional", 0.0))
            decisions = int(symbol_entry.get("decisions", symbol_entry.get("events", 0)))
            if symbol not in symbol_totals:
                symbol_totals[symbol] = {"delta_notional": 0.0, "decisions": 0}
            agg = symbol_totals[symbol]
            agg["delta_notional"] = float(agg["delta_notional"]) + delta_notional
            agg["decisions"] = int(agg["decisions"]) + decisions

    delta_pct = None
    if baseline_total > 0:
        delta_pct = delta_total / baseline_total

    ordered_reason_totals = {
        code: {
            "decisions": int(reason_totals[code]["decisions"]),
            "delta_notional": round_notional(float(reason_totals[code]["delta_notional"])),
        }
        for code in sorted(reason_totals)
    }

    top_symbols: list[dict[str, Any]] = []
    for symbol, agg in symbol_totals.items():
        top_symbols.append(
            {
                "symbol": symbol,
                "delta_notional": round_notional(float(agg["delta_notional"])),
                "decisions": int(agg["decisions"]),
            }
        )
    top_symbols.sort(key=lambda item: (item["delta_notional"], item["symbol"]))
    top_symbols = top_symbols[:TOP_SYMBOLS_LIMIT]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "as_of_date_ny": as_of_date_ny,
        "window": {
            "label": window_label,
            "trading_days_required": window_size,
            "trading_days_included": len(window_dates),
            "start_date_ny": window_dates[0],
            "end_date_ny": window_dates[-1],
            "dates_ny": list(window_dates),
        },
        "inputs": {
            "source_dir": str(input_dir),
            "source_files": list(source_files),
        },
        "totals": {
            "baseline_notional": round_notional(baseline_total),
            "modulated_notional": round_notional(modulated_total),
            "delta_notional": round_notional(delta_total),
            "delta_pct": round_pct(delta_pct),
            "decisions_total": decisions_total,
            "decisions_modulated": decisions_modulated,
            "decisions_unmodified": decisions_unmodified,
        },
        "breakdowns": {"by_reason_code": ordered_reason_totals},
        "top_symbols": {"by_delta_notional": top_symbols},
        "determinism": {
            "stable_json": True,
            "sort_keys": True,
            "separators": ",:",
            "rounding": {
                "notional_decimals": ROUND_NOTIONAL_DECIMALS,
                "pct_decimals": ROUND_PCT_DECIMALS,
            },
            "window_rule": "last_20_available_dates_on_disk_lte_as_of",
        },
    }
    return payload


def write_rolling_summary(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    packed = stable_json_dumps(payload)
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(packed)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def generate_and_write_rolling_summary(*, as_of_date_ny: str) -> Path | None:
    if not rolling_write_enabled():
        return None
    try:
        payload = build_rolling_summary(as_of_date_ny=as_of_date_ny)
        if payload is None:
            return None
        output_path = resolve_output_path(as_of_date_ny=as_of_date_ny)
        return write_rolling_summary(payload, output_path)
    except Exception as exc:  # noqa: BLE001 - fail-open
        print(f"WARN: risk attribution rolling write failed: {exc}")
        return None
