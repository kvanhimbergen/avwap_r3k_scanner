from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from analytics.schwab_readonly_schemas import (
    QTY_PLACES,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
    build_snapshot_id,
    format_qty,
    parse_decimal,
    serialize_orders_snapshot,
    serialize_positions_snapshot,
    stable_json_dumps,
)
from analytics.schwab_readonly_storage import (
    RECORD_TYPE_ACCOUNT,
    RECORD_TYPE_ORDERS,
    RECORD_TYPE_POSITIONS,
    RECORD_TYPE_RECONCILIATION,
)

MANUAL_INTENT_EVENT = "MANUAL_TICKET_SENT"
CONFIRMATION_RECORD_TYPE = "SCHWAB_MANUAL_CONFIRMATION"

REASON_CONFIRMED_NO_POSITION = "CONFIRMED_EXECUTED_BUT_NO_POSITION_CHANGE"
REASON_BROKER_NO_CONFIRMATION = "BROKER_POSITION_CHANGED_BUT_NO_CONFIRMATION"
REASON_PARTIAL_FILL_MISMATCH = "PARTIAL_FILL_MISMATCH"
REASON_QTY_MISMATCH = "QTY_MISMATCH"
REASON_UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ManualIntent:
    intent_id: str
    symbol: str
    side: str
    qty: Decimal


@dataclass(frozen=True)
class ManualConfirmation:
    intent_id: str
    status: str
    qty: Optional[Decimal]


@dataclass(frozen=True)
class IntentReconciliation:
    intent_id: str
    symbol: str
    side: str
    intent_qty: Decimal
    confirmation_status: Optional[str]
    confirmation_qty: Optional[Decimal]
    broker_qty: Optional[Decimal]
    drift_reason_codes: list[str]


@dataclass(frozen=True)
class SymbolRollup:
    symbol: str
    intent_qty_total: Optional[Decimal]
    confirmed_qty_total: Optional[Decimal]
    broker_qty: Optional[Decimal]
    intent_ids: list[str]
    drift_reason_codes: list[str]


@dataclass(frozen=True)
class PortfolioRollup:
    intent_count: int
    confirmation_count: int
    broker_position_count: int
    drift_intent_count: int
    drift_symbol_count: int
    unknown_confirmation_count: int


@dataclass(frozen=True)
class SchwabReadonlyReconciliationReport:
    schema_version: int
    book_id: str
    ny_date: str
    as_of_utc: str
    snapshot_ids: dict[str, str]
    counts: PortfolioRollup
    intents: list[IntentReconciliation]
    symbols: list[SymbolRollup]
    drift_reason_codes: list[str]


@dataclass(frozen=True)
class ReconciliationWriteResult:
    ledger_path: str
    reconciliation_id: Optional[str]
    written: bool


def _quantize_qty(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-QTY_PLACES)
    return value.quantize(quant)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    with path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                entries.append(data)
    return entries


def load_manual_intents(path: Path) -> list[ManualIntent]:
    intents: list[ManualIntent] = []
    for entry in _load_jsonl(path):
        if entry.get("event") != MANUAL_INTENT_EVENT:
            continue
        intent_id = str(entry.get("intent_id") or "").strip()
        symbol = str(entry.get("symbol") or "").strip().upper()
        side = str(entry.get("side") or "").strip().upper()
        qty_raw = parse_decimal(entry.get("qty"))
        if not intent_id or not symbol or qty_raw is None:
            continue
        intents.append(
            ManualIntent(
                intent_id=intent_id,
                symbol=symbol,
                side=side or "UNKNOWN",
                qty=_quantize_qty(qty_raw) or Decimal("0"),
            )
        )
    intents.sort(key=lambda item: (item.symbol, item.intent_id))
    return intents


def load_manual_confirmations(path: Path) -> dict[str, ManualConfirmation]:
    confirmations: dict[str, ManualConfirmation] = {}
    for entry in _load_jsonl(path):
        if entry.get("record_type") != CONFIRMATION_RECORD_TYPE:
            continue
        intent_id = str(entry.get("intent_id") or "").strip()
        status = str(entry.get("status") or "").strip().upper()
        qty_raw = parse_decimal(entry.get("qty"))
        if not intent_id or not status:
            continue
        confirmations[intent_id] = ManualConfirmation(
            intent_id=intent_id,
            status=status,
            qty=_quantize_qty(qty_raw),
        )
    return confirmations


def _latest_snapshot_record(entries: list[dict], record_type: str) -> Optional[dict]:
    latest: Optional[dict] = None
    latest_as_of = ""
    for entry in entries:
        if entry.get("record_type") != record_type:
            continue
        as_of = str(entry.get("as_of_utc") or "")
        if not as_of:
            continue
        if as_of > latest_as_of:
            latest = entry
            latest_as_of = as_of
    return latest


def load_positions_snapshot(path: Path) -> tuple[SchwabPositionsSnapshot, str]:
    entries = _load_jsonl(path)
    record = _latest_snapshot_record(entries, RECORD_TYPE_POSITIONS)
    if record is None:
        raise RuntimeError("positions snapshot missing")
    payload = {
        "schema_version": record.get("schema_version"),
        "book_id": record.get("book_id"),
        "as_of_utc": record.get("as_of_utc"),
        "positions": record.get("positions"),
    }
    positions: list[dict] = payload.get("positions") or []
    if not isinstance(positions, list):
        raise RuntimeError("positions snapshot invalid")
    parsed_positions = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty = parse_decimal(item.get("qty"))
        parsed_positions.append(
            {
                "book_id": payload.get("book_id"),
                "as_of_utc": payload.get("as_of_utc"),
                "symbol": symbol,
                "qty": _quantize_qty(qty) or Decimal("0"),
                "cost_basis": parse_decimal(item.get("cost_basis")),
                "market_value": parse_decimal(item.get("market_value")),
            }
        )
    snapshot = SchwabPositionsSnapshot(
        schema_version=int(payload.get("schema_version") or 0),
        book_id=str(payload.get("book_id") or ""),
        as_of_utc=str(payload.get("as_of_utc") or ""),
        positions=[
            SchwabPosition(
                book_id=str(item.get("book_id") or ""),
                as_of_utc=str(item.get("as_of_utc") or ""),
                symbol=str(item.get("symbol") or ""),
                qty=item.get("qty") or Decimal("0"),
                cost_basis=item.get("cost_basis"),
                market_value=item.get("market_value"),
            )
            for item in parsed_positions
        ],
    )
    snapshot_id = build_snapshot_id(serialize_positions_snapshot(snapshot))
    return snapshot, snapshot_id


def load_orders_snapshot(path: Path) -> tuple[SchwabOrdersSnapshot, str]:
    entries = _load_jsonl(path)
    record = _latest_snapshot_record(entries, RECORD_TYPE_ORDERS)
    if record is None:
        raise RuntimeError("orders snapshot missing")
    payload = {
        "schema_version": record.get("schema_version"),
        "book_id": record.get("book_id"),
        "as_of_utc": record.get("as_of_utc"),
        "orders": record.get("orders"),
    }
    orders: list[dict] = payload.get("orders") or []
    if not isinstance(orders, list):
        raise RuntimeError("orders snapshot invalid")
    parsed_orders = []
    for item in orders:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        order_id = str(item.get("order_id") or "").strip()
        if not symbol or not order_id:
            continue
        qty = parse_decimal(item.get("qty"))
        parsed_orders.append(
            {
                "book_id": payload.get("book_id"),
                "as_of_utc": payload.get("as_of_utc"),
                "order_id": order_id,
                "symbol": symbol,
                "side": str(item.get("side") or "").strip().lower() or "unknown",
                "qty": _quantize_qty(qty) or Decimal("0"),
                "filled_qty": _quantize_qty(parse_decimal(item.get("filled_qty"))),
                "status": item.get("status"),
                "submitted_at": item.get("submitted_at"),
                "filled_at": item.get("filled_at"),
            }
        )
    snapshot = SchwabOrdersSnapshot(
        schema_version=int(payload.get("schema_version") or 0),
        book_id=str(payload.get("book_id") or ""),
        as_of_utc=str(payload.get("as_of_utc") or ""),
        orders=[
            SchwabOrder(
                book_id=str(item.get("book_id") or ""),
                as_of_utc=str(item.get("as_of_utc") or ""),
                order_id=str(item.get("order_id") or ""),
                symbol=str(item.get("symbol") or ""),
                side=str(item.get("side") or ""),
                qty=item.get("qty") or Decimal("0"),
                filled_qty=item.get("filled_qty"),
                status=item.get("status"),
                submitted_at=item.get("submitted_at"),
                filled_at=item.get("filled_at"),
            )
            for item in parsed_orders
        ],
    )
    snapshot_id = build_snapshot_id(serialize_orders_snapshot(snapshot))
    return snapshot, snapshot_id


def _build_intent_reconciliations(
    intents: list[ManualIntent],
    confirmations: dict[str, ManualConfirmation],
    broker_positions: dict[str, Decimal],
) -> tuple[list[IntentReconciliation], list[str]]:
    reconciled: list[IntentReconciliation] = []
    drift_reason_codes: list[str] = []

    for intent in intents:
        confirmation = confirmations.get(intent.intent_id)
        broker_qty = broker_positions.get(intent.symbol)
        reasons: list[str] = []
        if confirmation and confirmation.qty is not None:
            if confirmation.qty != intent.qty:
                reasons.append(REASON_QTY_MISMATCH)
        if confirmation and confirmation.status in {"EXECUTED", "PARTIAL"}:
            if broker_qty is None or broker_qty == 0:
                reasons.append(REASON_CONFIRMED_NO_POSITION)
            if (
                confirmation.status == "PARTIAL"
                and confirmation.qty is not None
                and broker_qty is not None
                and confirmation.qty != broker_qty
            ):
                reasons.append(REASON_PARTIAL_FILL_MISMATCH)
        if confirmation is None and broker_qty is not None and broker_qty != 0:
            reasons.append(REASON_BROKER_NO_CONFIRMATION)

        reasons_sorted = sorted(set(reasons))
        drift_reason_codes.extend(reasons_sorted)
        reconciled.append(
            IntentReconciliation(
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                side=intent.side,
                intent_qty=intent.qty,
                confirmation_status=confirmation.status if confirmation else None,
                confirmation_qty=confirmation.qty if confirmation else None,
                broker_qty=broker_qty,
                drift_reason_codes=reasons_sorted,
            )
        )

    reconciled.sort(key=lambda item: (item.symbol, item.intent_id))
    return reconciled, drift_reason_codes


def _append_unknown_confirmations(
    reconciled: list[IntentReconciliation], confirmations: dict[str, ManualConfirmation], intents: list[ManualIntent]
) -> list[str]:
    intent_ids = {intent.intent_id for intent in intents}
    unknown_ids = [intent_id for intent_id in confirmations.keys() if intent_id not in intent_ids]
    drift_reason_codes: list[str] = []
    for intent_id in sorted(unknown_ids):
        confirmation = confirmations[intent_id]
        reconciled.append(
            IntentReconciliation(
                intent_id=intent_id,
                symbol="UNKNOWN",
                side="UNKNOWN",
                intent_qty=Decimal("0"),
                confirmation_status=confirmation.status,
                confirmation_qty=confirmation.qty,
                broker_qty=None,
                drift_reason_codes=[REASON_UNKNOWN_SYMBOL],
            )
        )
        drift_reason_codes.append(REASON_UNKNOWN_SYMBOL)
    return drift_reason_codes


def _build_symbol_rollups(
    intents: list[ManualIntent],
    reconciled: list[IntentReconciliation],
    broker_positions: dict[str, Decimal],
) -> tuple[list[SymbolRollup], list[str]]:
    intents_by_symbol: dict[str, list[ManualIntent]] = {}
    for intent in intents:
        intents_by_symbol.setdefault(intent.symbol, []).append(intent)

    reconciled_by_symbol: dict[str, list[IntentReconciliation]] = {}
    for item in reconciled:
        reconciled_by_symbol.setdefault(item.symbol, []).append(item)

    symbols = sorted(set(intents_by_symbol.keys()) | set(broker_positions.keys()))
    rollups: list[SymbolRollup] = []
    drift_reason_codes: list[str] = []

    for symbol in symbols:
        intent_items = intents_by_symbol.get(symbol, [])
        intent_qty_total = sum((intent.qty for intent in intent_items), Decimal("0")) if intent_items else None
        confirmed_qty_total = None
        rec_items = reconciled_by_symbol.get(symbol, [])
        if rec_items:
            confirmed_values = [item.confirmation_qty for item in rec_items if item.confirmation_qty is not None]
            if confirmed_values:
                confirmed_qty_total = sum(confirmed_values, Decimal("0"))
        broker_qty = broker_positions.get(symbol)
        reason_codes: list[str] = []
        intent_ids = sorted({intent.intent_id for intent in intent_items})

        for item in rec_items:
            reason_codes.extend(item.drift_reason_codes)
        if symbol in broker_positions and not intent_items:
            reason_codes.append(REASON_UNKNOWN_SYMBOL)
            if broker_qty is not None and broker_qty != 0:
                reason_codes.append(REASON_BROKER_NO_CONFIRMATION)

        reason_sorted = sorted(set(reason_codes))
        drift_reason_codes.extend(reason_sorted)
        rollups.append(
            SymbolRollup(
                symbol=symbol,
                intent_qty_total=_quantize_qty(intent_qty_total),
                confirmed_qty_total=_quantize_qty(confirmed_qty_total),
                broker_qty=_quantize_qty(broker_qty),
                intent_ids=intent_ids,
                drift_reason_codes=reason_sorted,
            )
        )

    rollups.sort(key=lambda item: item.symbol)
    return rollups, drift_reason_codes


def build_reconciliation_report(
    *,
    ledger_path: Path,
) -> SchwabReadonlyReconciliationReport:
    entries = _load_jsonl(ledger_path)
    positions_snapshot, positions_snapshot_id = load_positions_snapshot(ledger_path)
    orders_snapshot, orders_snapshot_id = load_orders_snapshot(ledger_path)

    account_record = _latest_snapshot_record(entries, RECORD_TYPE_ACCOUNT)
    if account_record is None:
        raise RuntimeError("account snapshot missing")

    book_id = str(account_record.get("book_id") or "")
    ny_date = str(account_record.get("ny_date") or "")
    as_of_utc = str(account_record.get("as_of_utc") or "")

    intents = load_manual_intents(ledger_path)
    confirmations = load_manual_confirmations(ledger_path)

    broker_positions: dict[str, Decimal] = {
        position.symbol: _quantize_qty(position.qty) or Decimal("0")
        for position in positions_snapshot.positions
    }

    reconciled, drift_reasons_intents = _build_intent_reconciliations(intents, confirmations, broker_positions)
    drift_reasons_intents.extend(_append_unknown_confirmations(reconciled, confirmations, intents))
    reconciled.sort(key=lambda item: (item.symbol, item.intent_id))
    rollups, drift_reasons_symbols = _build_symbol_rollups(intents, reconciled, broker_positions)

    unknown_confirmation_ids = [
        intent_id for intent_id in confirmations.keys() if intent_id not in {intent.intent_id for intent in intents}
    ]
    drift_reasons = set(drift_reasons_intents) | set(drift_reasons_symbols)
    if unknown_confirmation_ids:
        drift_reasons.add(REASON_UNKNOWN_SYMBOL)

    report = SchwabReadonlyReconciliationReport(
        schema_version=SCHEMA_VERSION,
        book_id=book_id,
        ny_date=ny_date,
        as_of_utc=as_of_utc,
        snapshot_ids={
            "account": str(account_record.get("snapshot_id") or ""),
            "positions": positions_snapshot_id,
            "orders": orders_snapshot_id,
        },
        counts=PortfolioRollup(
            intent_count=len(intents),
            confirmation_count=len(confirmations),
            broker_position_count=len(broker_positions),
            drift_intent_count=sum(1 for item in reconciled if item.drift_reason_codes),
            drift_symbol_count=sum(1 for item in rollups if item.drift_reason_codes),
            unknown_confirmation_count=len(unknown_confirmation_ids),
        ),
        intents=reconciled,
        symbols=rollups,
        drift_reason_codes=sorted(drift_reasons),
    )
    return report


def serialize_reconciliation_report(report: SchwabReadonlyReconciliationReport) -> dict[str, object]:
    return {
        "schema_version": int(report.schema_version),
        "book_id": report.book_id,
        "ny_date": report.ny_date,
        "as_of_utc": report.as_of_utc,
        "snapshot_ids": dict(report.snapshot_ids),
        "counts": {
            "intent_count": report.counts.intent_count,
            "confirmation_count": report.counts.confirmation_count,
            "broker_position_count": report.counts.broker_position_count,
            "drift_intent_count": report.counts.drift_intent_count,
            "drift_symbol_count": report.counts.drift_symbol_count,
            "unknown_confirmation_count": report.counts.unknown_confirmation_count,
        },
        "intents": [
            {
                "intent_id": item.intent_id,
                "symbol": item.symbol,
                "side": item.side,
                "intent_qty": format_qty(item.intent_qty),
                "confirmation_status": item.confirmation_status,
                "confirmation_qty": format_qty(item.confirmation_qty),
                "broker_qty": format_qty(item.broker_qty),
                "drift_reason_codes": list(item.drift_reason_codes),
            }
            for item in report.intents
        ],
        "symbols": [
            {
                "symbol": item.symbol,
                "intent_qty_total": format_qty(item.intent_qty_total),
                "confirmed_qty_total": format_qty(item.confirmed_qty_total),
                "broker_qty": format_qty(item.broker_qty),
                "intent_ids": list(item.intent_ids),
                "drift_reason_codes": list(item.drift_reason_codes),
            }
            for item in report.symbols
        ],
        "drift_reason_codes": list(report.drift_reason_codes),
    }


def write_reconciliation_record(
    *,
    ledger_path: Path,
    report: SchwabReadonlyReconciliationReport,
) -> ReconciliationWriteResult:
    payload = serialize_reconciliation_report(report)
    reconciliation_id = build_snapshot_id(payload)
    record = {
        "record_type": RECORD_TYPE_RECONCILIATION,
        "reconciliation_id": reconciliation_id,
        "ny_date": report.ny_date,
        "book_id": report.book_id,
        "as_of_utc": report.as_of_utc,
        "report": payload,
        "provenance": {
            "module": "analytics.schwab_readonly_reconciliation",
        },
    }

    existing = set()
    if ledger_path.exists():
        for entry in _load_jsonl(ledger_path):
            existing_id = entry.get("reconciliation_id")
            if entry.get("record_type") == RECORD_TYPE_RECONCILIATION and existing_id:
                existing.add(str(existing_id))

    if reconciliation_id in existing:
        return ReconciliationWriteResult(
            ledger_path=str(ledger_path),
            reconciliation_id=reconciliation_id,
            written=False,
        )

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as handle:
        handle.write(stable_json_dumps(record) + "\n")

    return ReconciliationWriteResult(
        ledger_path=str(ledger_path),
        reconciliation_id=reconciliation_id,
        written=True,
    )
