from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

from portfolio.risk_controls import RiskControls

FEATURE_FLAG_ENV = "E3_RISK_ATTRIBUTION_WRITE"

RECORD_TYPE = "PORTFOLIO_RISK_ATTRIBUTION"
SCHEMA_VERSION = 1


def attribution_write_enabled() -> bool:
    return os.getenv(FEATURE_FLAG_ENV, "0").strip() == "1"


def _normalize_payload_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_payload_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_payload_value(val) for val in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _normalize_payload_value(item())
        except Exception:
            return value
    return value


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _normalize_payload_value(payload)


def stable_json_dumps(payload: dict[str, Any]) -> str:
    normalized = normalize_payload(payload)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def ordered_reason_codes(reasons: Iterable[str] | None) -> list[str]:
    if not reasons:
        return []
    return sorted(dict.fromkeys([str(reason) for reason in reasons if reason]))


def build_decision_id(payload: dict[str, Any]) -> str:
    packed = json.dumps(normalize_payload(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def resolve_attribution_path(*, ny_date: str, base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION") -> Path:
    return Path(base_dir) / f"{ny_date}.jsonl"


def resolve_throttle_policy_reference(
    *,
    repo_root: Path,
    ny_date: str,
    source: str | None,
) -> str | None:
    if not source:
        return None
    if source == "PORTFOLIO_THROTTLE":
        return str(repo_root / "ledger" / "PORTFOLIO_THROTTLE" / f"{ny_date}.jsonl")
    if source == "REGIME_E1":
        return str(repo_root / "ledger" / "REGIME_E1" / f"{ny_date}.jsonl")
    return None


def _pct_delta(delta: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return delta / baseline


def _infer_hard_caps(
    *,
    base_qty: int,
    price: float,
    account_equity: float | None,
    risk_controls: RiskControls | None,
    gross_exposure: float | None,
    min_qty: int | None,
) -> list[str]:
    if base_qty <= 0 or risk_controls is None or account_equity is None:
        return []

    caps: list[str] = []
    adjusted_qty = int(math.floor(base_qty * risk_controls.risk_multiplier))
    if adjusted_qty < base_qty:
        caps.append("risk_multiplier")

    if risk_controls.per_position_cap is not None:
        cap_qty = int(math.floor((account_equity * risk_controls.per_position_cap) / price))
        if cap_qty < adjusted_qty:
            caps.append("per_position_cap")
        adjusted_qty = min(adjusted_qty, cap_qty)

    if risk_controls.max_gross_exposure is not None and gross_exposure is not None:
        if risk_controls.max_gross_exposure <= 1.0:
            limit = account_equity * risk_controls.max_gross_exposure
        else:
            limit = risk_controls.max_gross_exposure
        remaining = limit - gross_exposure
        remaining = max(0.0, remaining)
        cap_qty = int(math.floor(remaining / price))
        if cap_qty < adjusted_qty:
            caps.append("max_gross_exposure")
        adjusted_qty = min(adjusted_qty, cap_qty)

    if min_qty is not None and min_qty > 1 and adjusted_qty < min_qty:
        caps.append("min_qty_floor")

    return sorted(dict.fromkeys(caps))


def build_attribution_event(
    *,
    date_ny: str,
    symbol: str,
    baseline_qty: int,
    modulated_qty: int,
    price: float,
    account_equity: float | None,
    gross_exposure: float | None,
    risk_controls: RiskControls | None,
    risk_control_reasons: Iterable[str] | None,
    throttle_source: str | None,
    throttle_regime_label: str | None,
    throttle_policy_ref: str | None,
    drawdown: float | None,
    drawdown_threshold: float | None,
    min_qty: int | None,
    source: str,
    correlation_penalty: float = 0.0,
) -> dict[str, Any]:
    baseline_notional = price * baseline_qty
    modulated_notional = price * modulated_qty
    delta_qty = modulated_qty - baseline_qty
    delta_notional = modulated_notional - baseline_notional

    hard_caps = _infer_hard_caps(
        base_qty=baseline_qty,
        price=price,
        account_equity=account_equity,
        risk_controls=risk_controls,
        gross_exposure=gross_exposure,
        min_qty=min_qty,
    )

    reason_codes = ordered_reason_codes(risk_control_reasons)
    drawdown_applied = (
        drawdown is not None
        and drawdown_threshold is not None
        and drawdown >= drawdown_threshold
    )

    decision_payload = {
        "date_ny": date_ny,
        "symbol": symbol,
        "baseline_qty": baseline_qty,
        "modulated_qty": modulated_qty,
        "price": price,
        "source": source,
        "throttle_source": throttle_source,
        "throttle_regime_label": throttle_regime_label,
        "drawdown": drawdown,
        "drawdown_threshold": drawdown_threshold,
    }
    decision_id = build_decision_id(decision_payload)

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "decision_id": decision_id,
        "date_ny": date_ny,
        "symbol": symbol,
        "source": source,
        "baseline": {
            "qty": baseline_qty,
            "notional": baseline_notional,
        },
        "modulated": {
            "qty": modulated_qty,
            "notional": modulated_notional,
        },
        "delta": {
            "qty": delta_qty,
            "notional": delta_notional,
            "pct_qty": _pct_delta(delta_qty, baseline_qty),
            "pct_notional": _pct_delta(delta_notional, baseline_notional),
        },
        "regime": {
            "code": throttle_regime_label,
            "source": throttle_source,
            "throttle_policy_ref": throttle_policy_ref,
        },
        "drawdown_guard": {
            "applied": drawdown_applied,
            "drawdown": drawdown,
            "threshold": drawdown_threshold,
        },
        "hard_caps_applied": hard_caps,
        "reason_codes": reason_codes,
        "risk_controls": {
            "risk_multiplier": risk_controls.risk_multiplier if risk_controls else None,
            "max_gross_exposure": risk_controls.max_gross_exposure if risk_controls else None,
            "max_positions": risk_controls.max_positions if risk_controls else None,
            "per_position_cap": risk_controls.per_position_cap if risk_controls else None,
            "throttle_reason": risk_controls.throttle_reason if risk_controls else None,
        },
        "correlation_penalty": float(correlation_penalty),
    }


def write_attribution_event(
    event: dict[str, Any],
    *,
    base_dir: str = "ledger/PORTFOLIO_RISK_ATTRIBUTION",
) -> Path:
    ny_date = event.get("date_ny")
    if not isinstance(ny_date, str) or not ny_date:
        raise ValueError("event missing date_ny")
    path = resolve_attribution_path(ny_date=ny_date, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json_dumps(event) + "\n")
    return path
