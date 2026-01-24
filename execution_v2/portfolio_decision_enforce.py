"""
Execution V2 – Portfolio Decision Enforcement (Phase 2B)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import json
import os


ENFORCEMENT_ENV = "PORTFOLIO_DECISION_ENFORCE"

ENFORCEMENT_REASON_ORDER = [
    "DECISION_FILE_MISSING",
    "DECISION_JSON_INVALID",
    "DECISION_SCHEMA_INVALID",
    "DECISION_DATE_MISMATCH",
    "DECISION_SYMBOL_NOT_FOUND",
]


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    date_ny: str
    symbol: str
    decision: str
    reason_codes: list[str]
    inputs_used: list[str]


@dataclass(frozen=True)
class DecisionBatch:
    date_ny: str
    generated_at: str
    decisions: dict[str, DecisionRecord]
    artifact_path: str


@dataclass(frozen=True)
class DecisionContext:
    date_ny: str
    artifact_path: str
    batch: Optional[DecisionBatch]
    errors: list[str]


@dataclass(frozen=True)
class EnforcementResult:
    symbol: str
    decision: str
    reason_codes: list[str]
    decision_id: Optional[str]
    enforced: bool


def enforcement_enabled() -> bool:
    return os.getenv(ENFORCEMENT_ENV, "").strip() == "1"


def resolve_decision_artifact_path(
    date_ny: str, *, base_dir: str = "analytics/artifacts/portfolio_decisions"
) -> Path:
    return Path(base_dir) / f"{date_ny}.json"


def resolve_enforcement_artifact_path(
    date_ny: str, *, base_dir: str = "analytics/artifacts/portfolio_decisions/enforcement"
) -> Path:
    return Path(base_dir) / f"{date_ny}.jsonl"


def load_decision_context(
    date_ny: str, *, base_dir: str = "analytics/artifacts/portfolio_decisions"
) -> DecisionContext:
    artifact_path = resolve_decision_artifact_path(date_ny, base_dir=base_dir)
    batch, errors = load_portfolio_decision_batch(date_ny, path=artifact_path)
    return DecisionContext(
        date_ny=date_ny,
        artifact_path=str(artifact_path),
        batch=batch,
        errors=errors,
    )


def load_portfolio_decision_batch(
    date_ny: str, *, path: Path
) -> tuple[Optional[DecisionBatch], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return None, _order_reason_codes(["DECISION_FILE_MISSING"])

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, _order_reason_codes(["DECISION_JSON_INVALID"])

    if not isinstance(payload, dict):
        return None, _order_reason_codes(["DECISION_SCHEMA_INVALID"])

    batch_date = payload.get("date")
    generated_at = payload.get("generated_at")
    decisions = payload.get("decisions")

    if not isinstance(batch_date, str) or not isinstance(generated_at, str) or not isinstance(decisions, list):
        return None, _order_reason_codes(["DECISION_SCHEMA_INVALID"])

    if batch_date != date_ny:
        errors.append("DECISION_DATE_MISMATCH")

    decision_map: dict[str, DecisionRecord] = {}
    schema_invalid = False

    for item in decisions:
        if not isinstance(item, dict):
            schema_invalid = True
            break
        decision_id = item.get("decision_id")
        symbol = item.get("symbol")
        decision = item.get("decision")
        reason_codes = item.get("reason_codes")
        inputs_used = item.get("inputs_used")
        item_date = item.get("date")

        if not isinstance(decision_id, str) or not isinstance(symbol, str) or not isinstance(decision, str):
            schema_invalid = True
            break
        if not isinstance(reason_codes, list) or not isinstance(inputs_used, list):
            schema_invalid = True
            break
        if not all(isinstance(code, str) for code in reason_codes):
            schema_invalid = True
            break
        if not all(isinstance(val, str) for val in inputs_used):
            schema_invalid = True
            break
        if decision not in {"ALLOW", "BLOCK"}:
            schema_invalid = True
            break
        if item_date != batch_date:
            schema_invalid = True
            break
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            schema_invalid = True
            break
        if normalized_symbol in decision_map:
            schema_invalid = True
            break

        decision_map[normalized_symbol] = DecisionRecord(
            decision_id=decision_id,
            date_ny=batch_date,
            symbol=normalized_symbol,
            decision=decision,
            reason_codes=list(reason_codes),
            inputs_used=list(inputs_used),
        )

    if schema_invalid:
        errors.append("DECISION_SCHEMA_INVALID")

    if errors:
        return None, _order_reason_codes(errors)

    batch = DecisionBatch(
        date_ny=batch_date,
        generated_at=generated_at,
        decisions=decision_map,
        artifact_path=str(path),
    )
    return batch, []


def evaluate_entry(symbol: str, context: DecisionContext) -> EnforcementResult:
    normalized_symbol = (symbol or "").strip().upper()
    if context.errors:
        return EnforcementResult(
            symbol=normalized_symbol,
            decision="BLOCK",
            reason_codes=_order_reason_codes(context.errors),
            decision_id=None,
            enforced=True,
        )
    batch = context.batch
    if batch is None:
        return EnforcementResult(
            symbol=normalized_symbol,
            decision="BLOCK",
            reason_codes=_order_reason_codes(["DECISION_SCHEMA_INVALID"]),
            decision_id=None,
            enforced=True,
        )
    decision = batch.decisions.get(normalized_symbol)
    if decision is None:
        return EnforcementResult(
            symbol=normalized_symbol,
            decision="BLOCK",
            reason_codes=_order_reason_codes(["DECISION_SYMBOL_NOT_FOUND"]),
            decision_id=None,
            enforced=True,
        )
    return EnforcementResult(
        symbol=normalized_symbol,
        decision=decision.decision,
        reason_codes=list(decision.reason_codes),
        decision_id=decision.decision_id,
        enforced=True,
    )


def evaluate_action(action: str, symbol: str, context: DecisionContext) -> EnforcementResult:
    normalized_action = (action or "").strip().lower()
    if normalized_action != "entry":
        return EnforcementResult(
            symbol=(symbol or "").strip().upper(),
            decision="ALLOW",
            reason_codes=[],
            decision_id=None,
            enforced=False,
        )
    return evaluate_entry(symbol, context)


def build_enforcement_record(
    *,
    date_ny: str,
    symbol: str,
    decision: str,
    enforced: bool,
    reason_codes: list[str],
    decision_id: Optional[str],
    decision_artifact_path: str,
    decision_batch_generated_at: Optional[str],
) -> dict:
    run_id = decision_batch_generated_at or date_ny
    return {
        "date_ny": date_ny,
        "decision": decision,
        "enforced": bool(enforced),
        "provenance": {
            "decision_artifact_path": decision_artifact_path,
            "decision_batch_generated_at": decision_batch_generated_at,
            "decision_id": decision_id,
            "run_id": run_id,
        },
        "reason_codes": list(reason_codes),
        "symbol": symbol,
    }


def write_enforcement_records(records: list[dict], path: Path) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda rec: (rec.get("symbol") or ""))
    with path.open("a", encoding="utf-8") as handle:
        for record in ordered:
            payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
            handle.write(payload)
            handle.write("\n")


def summarize_blocked_records(records: Iterable[dict]) -> tuple[list[str], list[str]]:
    blocked_symbols: list[str] = []
    reason_codes: list[str] = []
    for record in records:
        if record.get("decision") != "BLOCK":
            continue
        symbol = str(record.get("symbol") or "").strip().upper()
        if symbol:
            blocked_symbols.append(symbol)
        for code in record.get("reason_codes") or []:
            if isinstance(code, str):
                reason_codes.append(code)
    blocked_symbols = sorted(set(blocked_symbols))
    ordered_reasons = _order_reason_codes(reason_codes)
    return blocked_symbols, ordered_reasons


def send_blocked_alert(
    *,
    date_ny: str,
    blocked_symbols: list[str],
    reason_codes: list[str],
    slack_sender,
) -> None:
    if not blocked_symbols:
        return
    symbols_str = ", ".join(blocked_symbols)
    reasons_str = ", ".join(reason_codes) if reason_codes else "none"
    slack_sender(
        "WARNING",
        "Portfolio decision enforcement blocked entries",
        f"enforcement=1 date_ny={date_ny} blocked=[{symbols_str}] reasons=[{reasons_str}]",
        component="EXECUTION_V2",
        throttle_key="portfolio_decision_enforce_blocked",
        throttle_seconds=300,
    )


def _order_reason_codes(reason_codes: Iterable[str]) -> list[str]:
    seen = []
    for code in reason_codes:
        if code and code not in seen:
            seen.append(code)
    index = {code: idx for idx, code in enumerate(ENFORCEMENT_REASON_ORDER)}
    return sorted(seen, key=lambda code: (index.get(code, len(index)), code))
