from __future__ import annotations

from pathlib import Path

import pytest

from analytics.io.ledgers import parse_dry_run_ledger
from analytics.reconstruction import reconstruct_trades


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def _load_reconstruction():
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_reconstruction.json"))
    return result, reconstruct_trades(result.fills)


def test_reconstruction_partial_and_multi_lot() -> None:
    ingest, reconstruction = _load_reconstruction()
    fills_by_order = {fill.order_id: fill for fill in ingest.fills}

    assert reconstruction.warnings == []
    assert len(reconstruction.trades) == 5
    assert len(reconstruction.open_lots) == 1

    open_lot = reconstruction.open_lots[0]
    assert open_lot.open_fill_id == fills_by_order["o3"].fill_id
    assert open_lot.remaining_qty == 2.0
    assert open_lot.open_date_ny == "2026-01-19"

    trade_o2 = next(
        trade
        for trade in reconstruction.trades
        if trade.close_fill_id == fills_by_order["o2"].fill_id
    )
    assert trade_o2.open_fill_id == fills_by_order["o1"].fill_id
    assert trade_o2.qty == 4.0
    assert trade_o2.fees == pytest.approx(0.8)

    trades_o4 = [
        trade
        for trade in reconstruction.trades
        if trade.close_fill_id == fills_by_order["o4"].fill_id
    ]
    assert len(trades_o4) == 2
    trades_o4_sorted = sorted(trades_o4, key=lambda trade: trade.qty)
    assert trades_o4_sorted[0].open_fill_id == fills_by_order["o3"].fill_id
    assert trades_o4_sorted[0].qty == 2.0
    assert trades_o4_sorted[0].fees == pytest.approx(0.4)
    assert trades_o4_sorted[1].open_fill_id == fills_by_order["o1"].fill_id
    assert trades_o4_sorted[1].qty == 6.0
    assert trades_o4_sorted[1].fees == pytest.approx(1.2)
    assert trades_o4_sorted[1].close_date_ny == "2026-01-20"

    trade_o5 = next(
        trade
        for trade in reconstruction.trades
        if trade.close_fill_id == fills_by_order["o5"].fill_id
    )
    assert trade_o5.close_price is None
    assert trade_o5.notes == "missing_price_close"

    trade_o7 = next(
        trade
        for trade in reconstruction.trades
        if trade.close_fill_id == fills_by_order["o7"].fill_id
    )
    assert trade_o7.open_price is None
    assert trade_o7.notes == "missing_price_open"


def test_reconstruction_deterministic_ordering() -> None:
    _, first = _load_reconstruction()
    _, second = _load_reconstruction()

    assert [trade.trade_id for trade in first.trades] == [trade.trade_id for trade in second.trades]
    assert [lot.lot_id for lot in first.open_lots] == [lot.lot_id for lot in second.open_lots]
