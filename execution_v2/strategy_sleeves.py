"""
Execution V2 – Strategy Sleeve Configuration (Phase S2).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

SLEEVES_JSON_ENV = "S2_SLEEVES_JSON"
SLEEVES_FILE_ENV = "S2_SLEEVES_FILE"
ALLOW_UNSLEEVED_ENV = "S2_ALLOW_UNSLEEVED"
ALLOW_SYMBOL_OVERLAP_ENV = "S2_ALLOW_SYMBOL_OVERLAP"
DAILY_PNL_JSON_ENV = "S2_DAILY_PNL_JSON"

MAX_SLEEVE_SNAPSHOT = 50


@dataclass(frozen=True)
class StrategySleeve:
    max_daily_loss_usd: float | None = None
    max_gross_exposure_usd: float | None = None
    max_concurrent_positions: int | None = None

    def to_snapshot(self) -> dict[str, float | int | None]:
        return {
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_gross_exposure_usd": self.max_gross_exposure_usd,
            "max_concurrent_positions": self.max_concurrent_positions,
        }


@dataclass(frozen=True)
class SleeveConfig:
    sleeves: dict[str, StrategySleeve]
    allow_unsleeved: bool
    allow_symbol_overlap: bool
    daily_pnl_by_strategy: dict[str, float]
    daily_pnl_source: str | None = None
    daily_pnl_parse_error: str | None = None

    def to_snapshot(self) -> dict[str, object]:
        items = []
        for strategy_id in sorted(self.sleeves):
            items.append((strategy_id, self.sleeves[strategy_id].to_snapshot()))
        limited = items[:MAX_SLEEVE_SNAPSHOT]
        return {
            "allow_unsleeved": self.allow_unsleeved,
            "allow_symbol_overlap": self.allow_symbol_overlap,
            "sleeves": {strategy_id: payload for strategy_id, payload in limited},
            "sleeves_truncated": len(items) > len(limited),
        }


def load_sleeve_config() -> tuple[SleeveConfig, list[str]]:
    errors: list[str] = []
    sleeves: dict[str, StrategySleeve] = {}
    payload = _load_sleeves_payload(errors)
    if payload is not None:
        sleeves, parse_errors = _parse_sleeves_payload(payload)
        errors.extend(parse_errors)
    allow_unsleeved = os.getenv(ALLOW_UNSLEEVED_ENV, "0").strip() == "1"
    allow_symbol_overlap = os.getenv(ALLOW_SYMBOL_OVERLAP_ENV, "0").strip() == "1"
    daily_pnl_by_strategy, pnl_errors, pnl_source, pnl_parse_error = _load_daily_pnl()
    errors.extend(pnl_errors)
    return (
        SleeveConfig(
            sleeves=sleeves,
            allow_unsleeved=allow_unsleeved,
            allow_symbol_overlap=allow_symbol_overlap,
            daily_pnl_by_strategy=daily_pnl_by_strategy,
            daily_pnl_source=pnl_source,
            daily_pnl_parse_error=pnl_parse_error,
        ),
        errors,
    )


def _load_sleeves_payload(errors: list[str]) -> dict | None:
    raw = os.getenv(SLEEVES_JSON_ENV)
    file_path = os.getenv(SLEEVES_FILE_ENV)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"sleeves_json_invalid:{exc.msg}")
            return None
    if file_path:
        path = Path(file_path)
        if not path.exists():
            errors.append("sleeves_file_missing")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"sleeves_file_invalid:{exc.msg}")
            return None
    return None


def _parse_sleeves_payload(payload: dict) -> tuple[dict[str, StrategySleeve], list[str]]:
    errors: list[str] = []
    sleeves: dict[str, StrategySleeve] = {}
    if not isinstance(payload, dict):
        return {}, ["sleeves_payload_invalid"]
    for strategy_id, config in payload.items():
        if not strategy_id:
            errors.append("sleeves_strategy_id_missing")
            continue
        if not isinstance(config, dict):
            errors.append(f"sleeves_invalid_config:{strategy_id}")
            continue
        max_daily_loss_usd = _parse_optional_float(
            config.get("max_daily_loss_usd"), errors, "max_daily_loss_usd", strategy_id
        )
        max_gross_exposure_usd = _parse_optional_float(
            config.get("max_gross_exposure_usd"),
            errors,
            "max_gross_exposure_usd",
            strategy_id,
        )
        max_concurrent_positions = _parse_optional_int(
            config.get("max_concurrent_positions"),
            errors,
            "max_concurrent_positions",
            strategy_id,
        )
        sleeves[str(strategy_id)] = StrategySleeve(
            max_daily_loss_usd=max_daily_loss_usd,
            max_gross_exposure_usd=max_gross_exposure_usd,
            max_concurrent_positions=max_concurrent_positions,
        )
    return sleeves, errors


def _parse_optional_float(
    value: object, errors: list[str], field: str, strategy_id: str
) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"sleeves_invalid_{field}:{strategy_id}")
        return None


def _parse_optional_int(
    value: object, errors: list[str], field: str, strategy_id: str
) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"sleeves_invalid_{field}:{strategy_id}")
        return None


def _load_daily_pnl() -> tuple[dict[str, float], list[str], str | None, str | None]:
    errors: list[str] = []
    raw = os.getenv(DAILY_PNL_JSON_ENV)
    if not raw:
        return {}, errors, "none", None
    source = f"env:{DAILY_PNL_JSON_ENV}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        parse_error = f"daily_pnl_json_invalid:{exc.msg}"
        errors.append(parse_error)
        return {}, errors, source, parse_error
    if not isinstance(payload, dict):
        parse_error = "daily_pnl_payload_invalid"
        return {}, [parse_error], source, parse_error
    pnl: dict[str, float] = {}
    for strategy_id, value in payload.items():
        if not strategy_id:
            errors.append("daily_pnl_strategy_id_missing")
            continue
        try:
            pnl[str(strategy_id)] = float(value)
        except (TypeError, ValueError):
            errors.append(f"daily_pnl_invalid_value:{strategy_id}")
    return pnl, errors, source, None
