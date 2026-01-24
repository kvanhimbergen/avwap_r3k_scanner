from __future__ import annotations

import json
from typing import Any

from analytics.schemas import Lot, ReconstructionResult, Trade


def serialize_reconstruction(result: ReconstructionResult) -> dict[str, Any]:
    return {
        "trades": [
            {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "open_fill_id": trade.open_fill_id,
                "close_fill_id": trade.close_fill_id,
                "open_ts_utc": trade.open_ts_utc,
                "close_ts_utc": trade.close_ts_utc,
                "open_date_ny": trade.open_date_ny,
                "close_date_ny": trade.close_date_ny,
                "qty": trade.qty,
                "open_price": trade.open_price,
                "close_price": trade.close_price,
                "fees": trade.fees,
                "venue": trade.venue,
                "notes": trade.notes,
                "strategy_id": trade.strategy_id,
                "sleeve_id": trade.sleeve_id,
            }
            for trade in result.trades
        ],
        "open_lots": [
            {
                "lot_id": lot.lot_id,
                "symbol": lot.symbol,
                "side": lot.side,
                "open_fill_id": lot.open_fill_id,
                "open_ts_utc": lot.open_ts_utc,
                "open_date_ny": lot.open_date_ny,
                "open_qty": lot.open_qty,
                "open_price": lot.open_price,
                "remaining_qty": lot.remaining_qty,
                "venue": lot.venue,
                "source_paths": list(lot.source_paths),
                "strategy_id": lot.strategy_id,
                "sleeve_id": lot.sleeve_id,
            }
            for lot in result.open_lots
        ],
        "warnings": list(result.warnings),
        "source_metadata": dict(result.source_metadata),
    }


def write_reconstruction_json(path: str, result: ReconstructionResult) -> None:
    payload = serialize_reconstruction(result)
    with open(path, "w") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def parse_reconstruction_json(path: str) -> ReconstructionResult:
    with open(path, "r") as handle:
        payload = json.load(handle)
    trades = [
        Trade(
            trade_id=entry["trade_id"],
            symbol=entry["symbol"],
            direction=entry["direction"],
            open_fill_id=entry["open_fill_id"],
            close_fill_id=entry["close_fill_id"],
            open_ts_utc=entry["open_ts_utc"],
            close_ts_utc=entry["close_ts_utc"],
            open_date_ny=entry["open_date_ny"],
            close_date_ny=entry["close_date_ny"],
            qty=float(entry["qty"]),
            open_price=entry.get("open_price"),
            close_price=entry.get("close_price"),
            fees=float(entry["fees"]),
            venue=entry["venue"],
            notes=entry.get("notes"),
            strategy_id=entry.get("strategy_id", "default"),
            sleeve_id=entry.get("sleeve_id", "default"),
        )
        for entry in payload.get("trades", [])
    ]
    open_lots = [
        Lot(
            lot_id=entry["lot_id"],
            symbol=entry["symbol"],
            side=entry["side"],
            open_fill_id=entry["open_fill_id"],
            open_ts_utc=entry["open_ts_utc"],
            open_date_ny=entry["open_date_ny"],
            open_qty=float(entry["open_qty"]),
            open_price=entry.get("open_price"),
            remaining_qty=float(entry["remaining_qty"]),
            venue=entry["venue"],
            source_paths=list(entry.get("source_paths", [])),
            strategy_id=entry.get("strategy_id", "default"),
            sleeve_id=entry.get("sleeve_id", "default"),
        )
        for entry in payload.get("open_lots", [])
    ]
    warnings = list(payload.get("warnings", []))
    source_metadata = dict(payload.get("source_metadata", {}))
    return ReconstructionResult(
        trades=trades,
        open_lots=open_lots,
        warnings=warnings,
        source_metadata=source_metadata,
    )
