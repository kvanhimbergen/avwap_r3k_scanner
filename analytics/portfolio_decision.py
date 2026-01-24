from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from analytics.schemas import PortfolioDecision, PortfolioDecisionBatch

REASON_CODE_ORDER = [
    "CANDIDATES_MISSING",
    "CANDIDATES_PARSE_ERROR",
    "PORTFOLIO_SNAPSHOT_MISSING",
    "PORTFOLIO_SNAPSHOT_INVALID",
    "OPEN_POSITIONS_MISSING",
    "LIMIT_MAX_OPEN_POSITIONS",
    "LIMIT_MAX_NEW_ENTRIES_PER_DAY",
    "LIMIT_SYMBOL_CONCENTRATION",
    "LIMIT_GROSS_EXPOSURE",
    "LIMIT_DRAWDOWN_THROTTLE",
    "ALLOW_WITHIN_LIMITS",
]


@dataclass(frozen=True)
class PortfolioDecisionConfig:
    max_open_positions: int
    max_new_entries_per_day: int
    max_symbol_concentration_pct: float
    max_gross_exposure_pct: float
    max_drawdown_pct_block: float


@dataclass(frozen=True)
class PortfolioSnapshotInputs:
    date_ny: str
    capital: float
    open_positions: int
    gross_exposure: float
    per_symbol_exposure: dict[str, float]
    drawdown: float


DEFAULT_CONFIG = PortfolioDecisionConfig(
    max_open_positions=10,
    max_new_entries_per_day=5,
    max_symbol_concentration_pct=0.2,
    max_gross_exposure_pct=1.0,
    max_drawdown_pct_block=0.2,
)


def _ordered_reason_codes(reason_codes: Iterable[str]) -> list[str]:
    index = {code: idx for idx, code in enumerate(REASON_CODE_ORDER)}
    unique = list(dict.fromkeys(reason_codes))
    return sorted(unique, key=lambda code: index.get(code, len(REASON_CODE_ORDER)))


def _decision_id(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _generated_at_for_date(date_ny: str) -> str:
    dt = datetime.fromisoformat(date_ny).replace(tzinfo=timezone.utc)
    return dt.isoformat()


def load_portfolio_decision_config() -> tuple[PortfolioDecisionConfig, list[str]]:
    errors: list[str] = []

    def parse_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            errors.append("PORTFOLIO_SNAPSHOT_INVALID")
            return default

    def parse_float(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            errors.append("PORTFOLIO_SNAPSHOT_INVALID")
            return default

    config = PortfolioDecisionConfig(
        max_open_positions=parse_int("PORTFOLIO_MAX_OPEN_POSITIONS", DEFAULT_CONFIG.max_open_positions),
        max_new_entries_per_day=parse_int(
            "PORTFOLIO_MAX_NEW_ENTRIES_PER_DAY", DEFAULT_CONFIG.max_new_entries_per_day
        ),
        max_symbol_concentration_pct=parse_float(
            "PORTFOLIO_MAX_SYMBOL_CONCENTRATION_PCT",
            DEFAULT_CONFIG.max_symbol_concentration_pct,
        ),
        max_gross_exposure_pct=parse_float(
            "PORTFOLIO_MAX_GROSS_EXPOSURE_PCT", DEFAULT_CONFIG.max_gross_exposure_pct
        ),
        max_drawdown_pct_block=parse_float(
            "PORTFOLIO_MAX_DRAWDOWN_PCT_BLOCK", DEFAULT_CONFIG.max_drawdown_pct_block
        ),
    )
    return config, _ordered_reason_codes(errors)


def load_daily_candidates(path: str) -> tuple[list[str], list[str]]:
    if not os.path.exists(path):
        return [], ["CANDIDATES_MISSING"]

    try:
        with open(path, newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return [], ["CANDIDATES_PARSE_ERROR"]
            fieldnames = {name.strip() for name in reader.fieldnames if name}
            symbol_key = None
            for candidate_key in ("symbol", "Symbol"):
                if candidate_key in fieldnames:
                    symbol_key = candidate_key
                    break
            if symbol_key is None:
                return [], ["CANDIDATES_PARSE_ERROR"]
            symbols: list[str] = []
            for row in reader:
                symbol = (row.get(symbol_key) or "").strip()
                if not symbol:
                    return [], ["CANDIDATES_PARSE_ERROR"]
                symbols.append(symbol)
            return symbols, []
    except (csv.Error, OSError):
        return [], ["CANDIDATES_PARSE_ERROR"]


def resolve_latest_portfolio_snapshot(
    *, base_dir: str = "analytics/artifacts/portfolio_snapshots"
) -> Optional[str]:
    path = Path(base_dir)
    if not path.exists():
        return None
    candidates = sorted(path.glob("*.json"))
    if not candidates:
        return None
    return str(candidates[-1])


def load_portfolio_snapshot(path: str) -> tuple[Optional[PortfolioSnapshotInputs], list[str]]:
    if not os.path.exists(path):
        return None, ["PORTFOLIO_SNAPSHOT_MISSING"]

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ["PORTFOLIO_SNAPSHOT_INVALID"]

    try:
        date_ny = payload["date_ny"]
        capital_payload = payload["capital"]
        metrics = payload["metrics"]
        positions = payload["positions"]
    except KeyError:
        return None, ["PORTFOLIO_SNAPSHOT_INVALID"]

    if not isinstance(positions, list) or not isinstance(capital_payload, dict):
        return None, ["PORTFOLIO_SNAPSHOT_INVALID"]

    capital_value = capital_payload.get("ending")
    if capital_value is None:
        capital_value = capital_payload.get("starting")
    if capital_value is None:
        return None, ["PORTFOLIO_SNAPSHOT_INVALID"]

    drawdown = metrics.get("drawdown") if isinstance(metrics, dict) else None
    if drawdown is None:
        return None, ["PORTFOLIO_SNAPSHOT_INVALID"]

    per_symbol_exposure: dict[str, float] = {}
    open_positions = 0
    gross_exposure = 0.0
    for position in positions:
        symbol = position.get("symbol") if isinstance(position, dict) else None
        qty = position.get("qty") if isinstance(position, dict) else None
        avg_price = position.get("avg_price") if isinstance(position, dict) else None
        if symbol is None or qty is None or avg_price is None:
            return None, ["PORTFOLIO_SNAPSHOT_INVALID"]
        exposure = abs(float(qty) * float(avg_price))
        per_symbol_exposure[symbol] = per_symbol_exposure.get(symbol, 0.0) + exposure
        gross_exposure += exposure
        if float(qty) != 0.0:
            open_positions += 1

    snapshot_inputs = PortfolioSnapshotInputs(
        date_ny=str(date_ny),
        capital=float(capital_value),
        open_positions=open_positions,
        gross_exposure=gross_exposure,
        per_symbol_exposure=per_symbol_exposure,
        drawdown=float(drawdown),
    )
    return snapshot_inputs, []


def load_new_entries_count(path: str) -> tuple[Optional[int], list[str]]:
    if not os.path.exists(path):
        return None, ["OPEN_POSITIONS_MISSING"]
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ["OPEN_POSITIONS_MISSING"]
    if isinstance(payload, dict) and "new_entries" in payload:
        try:
            return int(payload["new_entries"]), []
        except (TypeError, ValueError):
            return None, ["OPEN_POSITIONS_MISSING"]
    if isinstance(payload, int):
        return payload, []
    return None, ["OPEN_POSITIONS_MISSING"]


def _resolve_inputs_used(*paths: Optional[str]) -> list[str]:
    return [path for path in paths if path]


def build_portfolio_decisions(
    *,
    date_ny: str,
    candidates_path: str = "daily_candidates.csv",
    snapshot_path: Optional[str] = None,
    new_entries_path: Optional[str] = None,
    config: Optional[PortfolioDecisionConfig] = None,
) -> PortfolioDecisionBatch:
    if config is None:
        config, config_errors = load_portfolio_decision_config()
    else:
        config_errors = []

    candidates, candidate_errors = load_daily_candidates(candidates_path)
    snapshot_path = snapshot_path or resolve_latest_portfolio_snapshot()
    snapshot_inputs = None
    snapshot_errors: list[str] = []
    if snapshot_path is None:
        snapshot_errors = ["PORTFOLIO_SNAPSHOT_MISSING"]
    else:
        snapshot_inputs, snapshot_errors = load_portfolio_snapshot(snapshot_path)

    new_entries_count = None
    new_entries_errors: list[str] = []
    if config.max_new_entries_per_day is not None:
        if new_entries_path is None:
            new_entries_errors = ["OPEN_POSITIONS_MISSING"]
        else:
            new_entries_count, new_entries_errors = load_new_entries_count(new_entries_path)

    inputs_used = _resolve_inputs_used(candidates_path, snapshot_path, new_entries_path)

    decisions: list[PortfolioDecision] = []
    for symbol in sorted(candidates):
        reason_codes: list[str] = []
        reason_codes.extend(candidate_errors)
        reason_codes.extend(snapshot_errors)
        reason_codes.extend(config_errors)
        reason_codes.extend(new_entries_errors)

        decision = "ALLOW"
        if reason_codes:
            decision = "BLOCK"
        if snapshot_inputs and not reason_codes:
            if snapshot_inputs.open_positions > config.max_open_positions:
                reason_codes.append("LIMIT_MAX_OPEN_POSITIONS")
            if new_entries_count is not None:
                if new_entries_count >= config.max_new_entries_per_day:
                    reason_codes.append("LIMIT_MAX_NEW_ENTRIES_PER_DAY")
            symbol_exposure = snapshot_inputs.per_symbol_exposure.get(symbol, 0.0)
            if snapshot_inputs.capital <= 0:
                reason_codes.append("PORTFOLIO_SNAPSHOT_INVALID")
            else:
                if (
                    symbol_exposure / snapshot_inputs.capital
                    > config.max_symbol_concentration_pct
                ):
                    reason_codes.append("LIMIT_SYMBOL_CONCENTRATION")
                if (
                    snapshot_inputs.gross_exposure / snapshot_inputs.capital
                    > config.max_gross_exposure_pct
                ):
                    reason_codes.append("LIMIT_GROSS_EXPOSURE")
                if snapshot_inputs.drawdown >= config.max_drawdown_pct_block:
                    reason_codes.append("LIMIT_DRAWDOWN_THROTTLE")

        if reason_codes:
            decision = "BLOCK"
        else:
            reason_codes.append("ALLOW_WITHIN_LIMITS")

        ordered_codes = _ordered_reason_codes(reason_codes)
        decision_id = _decision_id(
            date_ny,
            symbol,
            decision,
            ",".join(ordered_codes),
            ",".join(inputs_used),
        )
        decisions.append(
            PortfolioDecision(
                decision_id=decision_id,
                date=date_ny,
                symbol=symbol,
                decision=decision,
                reason_codes=ordered_codes,
                inputs_used=inputs_used,
            )
        )

    batch = PortfolioDecisionBatch(
        date=date_ny,
        generated_at=_generated_at_for_date(date_ny),
        decisions=decisions,
    )
    return batch


def serialize_portfolio_decision(decision: PortfolioDecision) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "date": decision.date,
        "symbol": decision.symbol,
        "decision": decision.decision,
        "reason_codes": list(decision.reason_codes),
        "inputs_used": list(decision.inputs_used),
    }


def serialize_portfolio_decision_batch(batch: PortfolioDecisionBatch) -> dict[str, Any]:
    return {
        "date": batch.date,
        "generated_at": batch.generated_at,
        "decisions": [serialize_portfolio_decision(decision) for decision in batch.decisions],
    }


def dumps_portfolio_decision_batch(batch: PortfolioDecisionBatch) -> str:
    payload = serialize_portfolio_decision_batch(batch)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def write_portfolio_decision_batch(
    batch: PortfolioDecisionBatch, *, base_dir: str = "analytics/artifacts/portfolio_decisions"
) -> str:
    os.makedirs(base_dir, exist_ok=True)
    output_path = os.path.join(base_dir, f"{batch.date}.json")
    payload = dumps_portfolio_decision_batch(batch)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return output_path
