from __future__ import annotations

import json
from pathlib import Path

from analytics.portfolio_daily import build_daily_portfolio_snapshot, write_daily_portfolio_snapshot
from analytics.portfolio_storage import serialize_portfolio_snapshot
from analytics.schemas import Lot, ReconstructionResult, Trade
from analytics.storage import write_reconstruction_json
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


def _make_trade(*, trade_id: str, symbol: str) -> Trade:
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        direction="long",
        open_fill_id="open",
        close_fill_id="close",
        open_ts_utc="2026-01-19T14:31:00+00:00",
        close_ts_utc="2026-01-19T15:31:00+00:00",
        open_date_ny="2026-01-19",
        close_date_ny="2026-01-19",
        qty=1.0,
        open_price=100.0,
        close_price=110.0,
        fees=1.0,
        venue="TEST",
        notes=None,
        strategy_id=DEFAULT_STRATEGY_ID,
        sleeve_id="default",
    )


def _make_open_lot(symbol: str) -> Lot:
    return Lot(
        lot_id=f"lot-{symbol}",
        symbol=symbol,
        side="long",
        open_fill_id="fill",
        open_ts_utc="2026-01-19T14:31:00+00:00",
        open_date_ny="2026-01-19",
        open_qty=1.0,
        open_price=100.0,
        remaining_qty=1.0,
        venue="TEST",
        source_paths=["ledger.json"],
        strategy_id=DEFAULT_STRATEGY_ID,
        sleeve_id="default",
    )


def test_daily_snapshot_writer_deterministic(tmp_path: Path) -> None:
    reconstruction_path = tmp_path / "reconstruction.json"
    write_reconstruction_json(
        str(reconstruction_path),
        result=ReconstructionResult(
            trades=[_make_trade(trade_id="t1", symbol="AAA")],
            open_lots=[_make_open_lot("AAA")],
            warnings=[],
            source_metadata={},
        ),
    )

    snapshot = build_daily_portfolio_snapshot(
        date_ny="2026-01-19",
        run_id="run-1",
        reconstruction_path=str(reconstruction_path),
        price_map={"AAA": 105.0},
        ledger_paths=[str(reconstruction_path)],
    )
    serialized_first = json.dumps(
        serialize_portfolio_snapshot(snapshot), sort_keys=True, separators=(",", ":")
    )

    output = write_daily_portfolio_snapshot(snapshot, base_dir=str(tmp_path / "snapshots"))
    assert output.output_path.endswith("2026-01-19.json")
    assert Path(output.output_path).read_text() == serialized_first

    snapshot_second = build_daily_portfolio_snapshot(
        date_ny="2026-01-19",
        run_id="run-1",
        reconstruction_path=str(reconstruction_path),
        price_map={"AAA": 105.0},
        ledger_paths=[str(reconstruction_path)],
    )
    serialized_second = json.dumps(
        serialize_portfolio_snapshot(snapshot_second), sort_keys=True, separators=(",", ":")
    )
    assert serialized_first == serialized_second
    assert "broker_positions_missing" in snapshot.provenance["reason_codes"]
