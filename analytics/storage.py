from __future__ import annotations

import json
from typing import Any

from analytics.schemas import ReconstructionResult


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
