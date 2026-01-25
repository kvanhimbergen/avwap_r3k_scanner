from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FEATURE_FLAG_ENV = "E2_REGIME_RISK_MODULATION"

RECORD_TYPE_THROTTLE = "PORTFOLIO_THROTTLE"
RECORD_TYPE_RISK_CONTROLS = "PORTFOLIO_RISK_CONTROLS"
RECORD_TYPE_REGIME_SIGNAL = "REGIME_E1_SIGNAL"
RECORD_TYPE_REGIME_SKIPPED = "REGIME_E1_SKIPPED"

SCHEMA_VERSION = 1

DEFAULT_DRAWNDOWN_BLOCK_PCT = 0.2


@dataclass(frozen=True)
class RiskControls:
    risk_multiplier: float
    max_gross_exposure: float | None
    max_positions: int | None
    per_position_cap: float | None
    throttle_reason: str


@dataclass(frozen=True)
class RiskControlResult:
    controls: RiskControls
    record: dict[str, Any] | None
    reasons: list[str]


def risk_modulation_enabled() -> bool:
    return os.getenv(FEATURE_FLAG_ENV, "0").strip() == "1"


def build_risk_controls(
    *,
    ny_date: str,
    repo_root: Path | str = ".",
    base_max_positions: int | None = None,
    base_max_gross_exposure: float | None = None,
    base_per_position_cap: float | None = None,
    drawdown: float | None = None,
    max_drawdown_pct_block: float | None = None,
    as_of_utc: str | None = None,
    enabled: bool | None = None,
    write_ledger: bool = True,
) -> RiskControlResult:
    if enabled is None:
        enabled = risk_modulation_enabled()

    if not enabled:
        controls = RiskControls(
            risk_multiplier=1.0,
            max_gross_exposure=base_max_gross_exposure,
            max_positions=base_max_positions,
            per_position_cap=base_per_position_cap,
            throttle_reason="disabled",
        )
        return RiskControlResult(controls=controls, record=None, reasons=["disabled"])

    repo_root = Path(repo_root)
    throttle, throttle_reasons, source, resolved_ny_date = _resolve_regime_throttle(
        repo_root=repo_root,
        ny_date=ny_date,
    )

    drawdown_multiplier, drawdown_reasons = _drawdown_guardrail_multiplier(
        drawdown=drawdown,
        max_drawdown_pct_block=max_drawdown_pct_block,
    )

    risk_multiplier = _clamp(float(throttle.get("risk_multiplier", 0.0)))
    risk_multiplier = min(risk_multiplier, drawdown_multiplier)

    max_positions_multiplier = throttle.get("max_new_positions_multiplier")
    max_positions = None
    if base_max_positions is not None and max_positions_multiplier is not None:
        max_positions = max(0, int(math.floor(base_max_positions * float(max_positions_multiplier))))

    max_gross_exposure = None
    if base_max_gross_exposure is not None:
        max_gross_exposure = float(base_max_gross_exposure) * risk_multiplier

    per_position_cap = None
    if base_per_position_cap is not None:
        per_position_cap = float(base_per_position_cap) * risk_multiplier

    reasons = _ordered_reasons(throttle_reasons + drawdown_reasons)
    throttle_reason = reasons[0] if reasons else "ok"

    controls = RiskControls(
        risk_multiplier=risk_multiplier,
        max_gross_exposure=max_gross_exposure,
        max_positions=max_positions,
        per_position_cap=per_position_cap,
        throttle_reason=throttle_reason,
    )

    record = None
    if write_ledger:
        record = _build_record(
            ny_date=ny_date,
            resolved_ny_date=resolved_ny_date,
            as_of_utc=as_of_utc,
            source=source,
            controls=controls,
            reasons=reasons,
        )
        _append_record(_risk_controls_path(repo_root, ny_date), record)

    return RiskControlResult(controls=controls, record=record, reasons=reasons)


def adjust_order_quantity(
    *,
    base_qty: int,
    price: float,
    account_equity: float,
    risk_controls: RiskControls,
    gross_exposure: float | None = None,
    min_qty: int | None = None,
) -> int:
    if base_qty <= 0:
        return 0

    adjusted_qty = int(math.floor(base_qty * risk_controls.risk_multiplier))

    if risk_controls.per_position_cap is not None:
        cap_qty = int(math.floor((account_equity * risk_controls.per_position_cap) / price))
        adjusted_qty = min(adjusted_qty, cap_qty)

    if risk_controls.max_gross_exposure is not None and gross_exposure is not None:
        remaining = (account_equity * risk_controls.max_gross_exposure) - gross_exposure
        remaining = max(0.0, remaining)
        cap_qty = int(math.floor(remaining / price))
        adjusted_qty = min(adjusted_qty, cap_qty)

    return _finalize_qty(base_qty=base_qty, adjusted_qty=adjusted_qty, min_qty=min_qty)


def resolve_drawdown_from_snapshot(
    *, base_dir: str = "analytics/artifacts/portfolio_snapshots"
) -> tuple[float | None, list[str]]:
    path = Path(base_dir)
    if not path.exists():
        return None, ["portfolio_snapshot_missing"]
    candidates = sorted(path.glob("*.json"))
    if not candidates:
        return None, ["portfolio_snapshot_missing"]
    latest_path = candidates[-1]
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ["portfolio_snapshot_invalid"]
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    drawdown = metrics.get("drawdown") if isinstance(metrics, dict) else None
    if drawdown is None:
        return None, ["portfolio_snapshot_invalid"]
    try:
        return float(drawdown), []
    except (TypeError, ValueError):
        return None, ["portfolio_snapshot_invalid"]


def resolve_drawdown_guardrail(
    *,
    drawdown: float | None = None,
    max_drawdown_pct_block: float | None = None,
    snapshot_dir: str = "analytics/artifacts/portfolio_snapshots",
) -> tuple[float | None, float | None, list[str]]:
    reasons: list[str] = []

    if drawdown is None:
        drawdown, snapshot_reasons = resolve_drawdown_from_snapshot(base_dir=snapshot_dir)
        reasons.extend(snapshot_reasons)

    if max_drawdown_pct_block is None:
        raw = os.getenv("PORTFOLIO_MAX_DRAWDOWN_PCT_BLOCK")
        if raw is None:
            max_drawdown_pct_block = DEFAULT_DRAWNDOWN_BLOCK_PCT
        else:
            try:
                max_drawdown_pct_block = float(raw)
            except ValueError:
                max_drawdown_pct_block = DEFAULT_DRAWNDOWN_BLOCK_PCT
                reasons.append("drawdown_threshold_invalid")

    return drawdown, max_drawdown_pct_block, _ordered_reasons(reasons)


def _resolve_regime_throttle(
    *,
    repo_root: Path,
    ny_date: str,
) -> tuple[dict[str, Any], list[str], str, str]:
    throttle_record, throttle_errors = _read_latest_record(
        _throttle_path(repo_root, ny_date), RECORD_TYPE_THROTTLE, "throttle_ledger"
    )
    if throttle_record is not None:
        throttle = throttle_record.get("throttle") or {}
        reasons = list(throttle.get("reasons") or []) + throttle_errors
        resolved_ny_date = throttle_record.get("resolved_ny_date") or ny_date
        return throttle, _ordered_reasons(reasons), "PORTFOLIO_THROTTLE", resolved_ny_date

    regime_record, regime_errors = _read_latest_regime_record(
        _regime_path(repo_root, ny_date)
    )
    if regime_record is not None:
        throttle = _regime_to_throttle(
            regime_record.get("regime_label"),
            regime_record.get("confidence"),
        )
        reasons = list(throttle.get("reasons") or []) + throttle_errors + regime_errors
        resolved_ny_date = regime_record.get("resolved_ny_date") or ny_date
        return throttle, _ordered_reasons(reasons), "REGIME_E1", resolved_ny_date

    throttle = {
        "risk_multiplier": 0.0,
        "max_new_positions_multiplier": 0.0,
        "reasons": ["missing_regime"],
    }
    reasons = throttle_errors + regime_errors + list(throttle.get("reasons") or [])
    return throttle, _ordered_reasons(reasons), "MISSING", ny_date


def _read_latest_regime_record(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["missing_regime_ledger"]
    latest_record: dict[str, Any] | None = None
    invalid = False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                invalid = True
                continue
            if data.get("record_type") not in {RECORD_TYPE_REGIME_SIGNAL, RECORD_TYPE_REGIME_SKIPPED}:
                continue
            latest_record = data
    if latest_record is None:
        reason = "invalid_regime_ledger" if invalid else "missing_regime_record"
        return None, [reason]
    reasons = []
    if latest_record.get("record_type") != RECORD_TYPE_REGIME_SIGNAL:
        reasons.append("regime_record_skipped")
    return latest_record, reasons


def _read_latest_record(
    path: Path, record_type: str, missing_reason: str
) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"missing_{missing_reason}"]
    latest_record: dict[str, Any] | None = None
    invalid = False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                invalid = True
                continue
            if data.get("record_type") != record_type:
                continue
            latest_record = data
    if latest_record is None:
        reason = f"invalid_{missing_reason}" if invalid else f"missing_{missing_reason}_record"
        return None, [reason]
    return latest_record, []


def _throttle_path(repo_root: Path, ny_date: str) -> Path:
    return repo_root / "ledger" / "PORTFOLIO_THROTTLE" / f"{ny_date}.jsonl"


def _regime_path(repo_root: Path, ny_date: str) -> Path:
    return repo_root / "ledger" / "REGIME_E1" / f"{ny_date}.jsonl"


def _risk_controls_path(repo_root: Path, ny_date: str) -> Path:
    return repo_root / "ledger" / "PORTFOLIO_RISK_CONTROLS" / f"{ny_date}.jsonl"


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_stable_json_dumps(record) + "\n")


def _stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _build_record(
    *,
    ny_date: str,
    resolved_ny_date: str,
    as_of_utc: str | None,
    source: str,
    controls: RiskControls,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "as_of_utc": as_of_utc or _default_as_of_utc(ny_date),
        "requested_ny_date": ny_date,
        "resolved_ny_date": resolved_ny_date,
        "record_type": RECORD_TYPE_RISK_CONTROLS,
        "schema_version": SCHEMA_VERSION,
        "provenance": {"module": "portfolio.risk_controls"},
        "source": source,
        "risk_controls": {
            "risk_multiplier": controls.risk_multiplier,
            "max_gross_exposure": controls.max_gross_exposure,
            "max_positions": controls.max_positions,
            "per_position_cap": controls.per_position_cap,
            "throttle_reason": controls.throttle_reason,
            "reasons": reasons,
        },
    }


def _default_as_of_utc(ny_date: str) -> str:
    return f"{ny_date}T16:00:00+00:00"


def _drawdown_guardrail_multiplier(
    *,
    drawdown: float | None,
    max_drawdown_pct_block: float | None,
) -> tuple[float, list[str]]:
    if drawdown is None or max_drawdown_pct_block is None:
        return 1.0, []
    if drawdown >= max_drawdown_pct_block:
        return 0.0, ["drawdown_guardrail"]
    return 1.0, []


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _regime_to_throttle(regime_label: str | None, confidence: float | None) -> dict[str, Any]:
    reasons: list[str] = []
    normalized_label = regime_label.upper() if isinstance(regime_label, str) else None
    mapping = {
        "RISK_ON": (1.0, 1.0),
        "NEUTRAL": (0.6, 0.7),
        "RISK_OFF": (0.2, 0.3),
    }

    if normalized_label in mapping:
        risk_multiplier, max_new_positions_multiplier = mapping[normalized_label]
    else:
        risk_multiplier, max_new_positions_multiplier = (0.0, 0.0)
        reasons.append("missing_regime")

    if confidence is not None and confidence < 0.6:
        risk_multiplier *= 0.5
        max_new_positions_multiplier *= 0.5
        reasons.append("low_confidence_haircut")

    return {
        "schema_version": SCHEMA_VERSION,
        "regime_label": regime_label,
        "confidence": confidence,
        "risk_multiplier": _clamp(risk_multiplier),
        "max_new_positions_multiplier": _clamp(max_new_positions_multiplier),
        "reasons": reasons,
    }


def _finalize_qty(*, base_qty: int, adjusted_qty: int, min_qty: int | None) -> int:
    adjusted_qty = min(base_qty, max(0, adjusted_qty))
    if base_qty <= 0:
        return 0

    minimum = 1
    if min_qty is not None:
        minimum = max(min_qty, minimum)
    minimum = min(base_qty, minimum)
    return max(adjusted_qty, minimum)


def _ordered_reasons(reasons: list[str]) -> list[str]:
    return sorted(dict.fromkeys([str(reason) for reason in reasons if reason]))
