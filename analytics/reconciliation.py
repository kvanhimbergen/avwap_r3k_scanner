from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from analytics.schemas import BrokerPosition, PortfolioPosition, ReconciliationDelta, ReconciliationReport

SCHEMA_VERSION = 1
QTY_TOLERANCE = 1e-6
PRICE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ReconciliationResult:
    report: ReconciliationReport
    output_path: Optional[str]


def _differs(left: Optional[float], right: Optional[float], *, tolerance: float) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) > tolerance


def _build_delta(
    *,
    delta_type: str,
    symbol: str,
    field: str,
    expected: Optional[object],
    observed: Optional[object],
    severity: str,
    reason_code: str,
) -> ReconciliationDelta:
    return ReconciliationDelta(
        delta_type=delta_type,
        symbol=symbol,
        field=field,
        expected=expected,
        observed=observed,
        severity=severity,
        reason_code=reason_code,
    )


def reconcile_positions(
    internal_positions: Iterable[PortfolioPosition],
    broker_positions: Optional[Iterable[BrokerPosition]],
) -> tuple[list[ReconciliationDelta], list[str]]:
    internal_by_symbol = {position.symbol: position for position in internal_positions}
    broker_by_symbol = {position.symbol: position for position in broker_positions or []}
    reason_codes: list[str] = []
    deltas: list[ReconciliationDelta] = []

    if broker_positions is None:
        return [], ["broker_positions_missing"]

    for symbol in sorted(set(internal_by_symbol) | set(broker_by_symbol)):
        internal = internal_by_symbol.get(symbol)
        broker = broker_by_symbol.get(symbol)
        if internal is None:
            deltas.append(
                _build_delta(
                    delta_type="missing_internal",
                    symbol=symbol,
                    field="symbol",
                    expected=None,
                    observed=broker.symbol if broker else None,
                    severity="critical",
                    reason_code="symbol_missing_internal",
                )
            )
            continue
        if broker is None:
            deltas.append(
                _build_delta(
                    delta_type="missing_broker",
                    symbol=symbol,
                    field="symbol",
                    expected=internal.symbol,
                    observed=None,
                    severity="critical",
                    reason_code="symbol_missing_broker",
                )
            )
            continue

        if _differs(internal.qty, broker.qty, tolerance=QTY_TOLERANCE):
            deltas.append(
                _build_delta(
                    delta_type="qty_mismatch",
                    symbol=symbol,
                    field="qty",
                    expected=internal.qty,
                    observed=broker.qty,
                    severity="critical",
                    reason_code="qty_mismatch",
                )
            )
        if internal.avg_price is None or broker.avg_entry_price is None:
            reason_codes.append("avg_price_unavailable")
        if _differs(internal.avg_price, broker.avg_entry_price, tolerance=PRICE_TOLERANCE):
            deltas.append(
                _build_delta(
                    delta_type="avg_price_mismatch",
                    symbol=symbol,
                    field="avg_price",
                    expected=internal.avg_price,
                    observed=broker.avg_entry_price,
                    severity="warning",
                    reason_code="avg_price_mismatch",
                )
            )
        if internal.mark_price is None or broker.last_price is None:
            reason_codes.append("mark_price_unavailable")
        if _differs(internal.mark_price, broker.last_price, tolerance=PRICE_TOLERANCE):
            deltas.append(
                _build_delta(
                    delta_type="mark_price_mismatch",
                    symbol=symbol,
                    field="mark_price",
                    expected=internal.mark_price,
                    observed=broker.last_price,
                    severity="warning",
                    reason_code="mark_price_mismatch",
                )
            )

    deltas_sorted = sorted(
        deltas, key=lambda item: (item.symbol, item.delta_type, item.field, item.reason_code)
    )
    return deltas_sorted, sorted(set(reason_codes))


def build_reconciliation_report(
    *,
    as_of_date_ny: str,
    run_id: str,
    internal_positions: Iterable[PortfolioPosition],
    broker_positions: Optional[Iterable[BrokerPosition]],
    source_paths: Optional[Iterable[str]] = None,
    reason_codes: Optional[Iterable[str]] = None,
) -> ReconciliationReport:
    internal_list = list(internal_positions)
    broker_list = list(broker_positions) if broker_positions is not None else None
    deltas, delta_reason_codes = reconcile_positions(internal_list, broker_list)
    combined_reason_codes = sorted(set((reason_codes or [])) | set(delta_reason_codes))
    internal_count = len(internal_list)
    broker_count = len(broker_list) if broker_list is not None else 0
    return ReconciliationReport(
        schema_version=SCHEMA_VERSION,
        as_of_date_ny=as_of_date_ny,
        run_id=run_id,
        source_paths=sorted(set(source_paths or [])),
        counts={
            "internal_positions": internal_count,
            "broker_positions": broker_count,
            "deltas": len(deltas),
        },
        deltas=deltas,
        reason_codes=combined_reason_codes,
    )


def serialize_reconciliation_report(report: ReconciliationReport) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "as_of_date_ny": report.as_of_date_ny,
        "run_id": report.run_id,
        "source_paths": list(report.source_paths),
        "counts": dict(report.counts),
        "deltas": [
            {
                "delta_type": delta.delta_type,
                "symbol": delta.symbol,
                "field": delta.field,
                "expected": delta.expected,
                "observed": delta.observed,
                "severity": delta.severity,
                "reason_code": delta.reason_code,
            }
            for delta in report.deltas
        ],
        "reason_codes": list(report.reason_codes),
    }


def write_reconciliation_report_json(path: str, report: ReconciliationReport) -> None:
    payload = serialize_reconciliation_report(report)
    with open(path, "w") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def write_reconciliation_report_artifact(
    report: ReconciliationReport, *, base_dir: str = "analytics/artifacts/reconciliation"
) -> str:
    os.makedirs(base_dir, exist_ok=True)
    output_path = os.path.join(base_dir, f"{report.as_of_date_ny}.json")
    write_reconciliation_report_json(output_path, report)
    return output_path
