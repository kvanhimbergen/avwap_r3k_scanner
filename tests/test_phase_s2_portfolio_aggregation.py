from __future__ import annotations

from analytics.portfolio import build_portfolio_snapshot
from analytics.schemas import Lot, Trade


def _trade(
    trade_id: str,
    symbol: str,
    qty: float,
    open_price: float,
    close_price: float,
    strategy_id: str,
) -> Trade:
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        direction="long",
        open_fill_id=f"open-{trade_id}",
        close_fill_id=f"close-{trade_id}",
        open_ts_utc="2024-01-02T14:30:00Z",
        close_ts_utc="2024-01-02T19:30:00Z",
        open_date_ny="2024-01-02",
        close_date_ny="2024-01-02",
        qty=qty,
        open_price=open_price,
        close_price=close_price,
        fees=0.0,
        venue="test",
        notes=None,
        strategy_id=strategy_id,
        sleeve_id="default",
    )


def _lot(
    lot_id: str,
    symbol: str,
    qty: float,
    open_price: float,
    strategy_id: str,
) -> Lot:
    return Lot(
        lot_id=lot_id,
        symbol=symbol,
        side="buy",
        open_fill_id=f"fill-{lot_id}",
        open_ts_utc="2024-01-02T14:30:00Z",
        open_date_ny="2024-01-02",
        open_qty=qty,
        open_price=open_price,
        remaining_qty=qty,
        venue="test",
        source_paths=["ledger/test.jsonl"],
        strategy_id=strategy_id,
        sleeve_id="default",
    )


def test_strategy_attribution_reconciles() -> None:
    trades = [
        _trade("t1", "AAA", 10, 100.0, 110.0, "alpha"),
        _trade("t2", "BBB", 5, 200.0, 190.0, "beta"),
    ]
    open_lots = [
        _lot("l1", "AAA", 5, 100.0, "alpha"),
        _lot("l2", "BBB", 2, 200.0, "beta"),
    ]
    price_map = {"AAA": 105.0, "BBB": 195.0}

    snapshot = build_portfolio_snapshot(
        date_ny="2024-01-02",
        run_id="run-1",
        trades=trades,
        open_lots=open_lots,
        starting_capital=100000.0,
        ending_capital=100000.0,
        price_map=price_map,
        ledger_paths=["ledger/test.jsonl"],
        input_hashes={"test": "hash"},
    )

    attribution = snapshot.metrics["strategy_attribution"]
    reconciliation = attribution["reconciliation"]

    assert reconciliation["exposure"]["gross_delta"] == 0.0
    assert reconciliation["exposure"]["net_delta"] == 0.0
    assert reconciliation["pnl"]["realized_delta"] == 0.0
    assert reconciliation["pnl"]["unrealized_delta"] == 0.0
