from __future__ import annotations

import json
import os
from typing import Any

from analytics.schemas import PortfolioSnapshot


def serialize_portfolio_snapshot(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "schema_version": int(snapshot.schema_version),
        "date_ny": snapshot.date_ny,
        "run_id": snapshot.run_id,
        "capital": dict(snapshot.capital),
        "gross_exposure": snapshot.gross_exposure,
        "net_exposure": snapshot.net_exposure,
        "positions": [
            {
                "symbol": position.symbol,
                "qty": position.qty,
                "avg_price": position.avg_price,
                "mark_price": position.mark_price,
                "notional": position.notional,
            }
            for position in snapshot.positions
        ],
        "pnl": dict(snapshot.pnl),
        "metrics": snapshot.metrics,
        "provenance": snapshot.provenance,
    }


def write_portfolio_snapshot_json(path: str, snapshot: PortfolioSnapshot) -> None:
    payload = serialize_portfolio_snapshot(snapshot)
    with open(path, "w") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def write_portfolio_snapshot_artifact(
    snapshot: PortfolioSnapshot, *, base_dir: str = "analytics/artifacts/portfolio_snapshots"
) -> str:
    os.makedirs(base_dir, exist_ok=True)
    output_path = os.path.join(base_dir, f"{snapshot.date_ny}.json")
    write_portfolio_snapshot_json(output_path, snapshot)
    return output_path
