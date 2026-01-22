from __future__ import annotations

import json
from typing import Any

from analytics.schemas import CumulativeAggregate, DailyAggregate


def serialize_daily_aggregates(dailies: list[DailyAggregate]) -> dict[str, Any]:
    return {
        "daily": [
            {
                "date_ny": daily.date_ny,
                "trade_count": daily.trade_count,
                "closed_qty": daily.closed_qty,
                "gross_notional_closed": daily.gross_notional_closed,
                "realized_pnl": daily.realized_pnl,
                "missing_price_trade_count": daily.missing_price_trade_count,
                "fees_total": daily.fees_total,
                "symbols_traded": list(daily.symbols_traded),
                "warnings": list(daily.warnings),
            }
            for daily in dailies
        ]
    }


def serialize_cumulative_aggregates(cumulative: list[CumulativeAggregate]) -> dict[str, Any]:
    return {
        "cumulative": [
            {
                "through_date_ny": entry.through_date_ny,
                "trade_count": entry.trade_count,
                "closed_qty": entry.closed_qty,
                "gross_notional_closed": entry.gross_notional_closed,
                "realized_pnl": entry.realized_pnl,
                "missing_price_trade_count": entry.missing_price_trade_count,
                "fees_total": entry.fees_total,
                "symbols_traded": list(entry.symbols_traded),
            }
            for entry in cumulative
        ]
    }


def write_metrics_json(
    path: str, *, dailies: list[DailyAggregate], cumulative: list[CumulativeAggregate]
) -> None:
    payload = {}
    payload.update(serialize_daily_aggregates(dailies))
    payload.update(serialize_cumulative_aggregates(cumulative))
    with open(path, "w") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
