from __future__ import annotations

import json
from pathlib import Path

import pytest

from analytics.portfolio import (
    DailyRealized,
    build_portfolio_snapshot,
    build_positions,
    compute_drawdown,
    compute_rolling_volatility,
    compute_symbol_contributions,
    compute_unrealized_pnl,
    size_position,
    evaluate_allocation_guardrails,
)
from analytics.portfolio_storage import (
    serialize_portfolio_snapshot,
    write_portfolio_snapshot_json,
)
from analytics.schemas import Lot, Trade


def _make_trade(
    *,
    trade_id: str,
    symbol: str,
    qty: float,
    open_price: float | None,
    close_price: float | None,
    close_date_ny: str,
    fees: float,
) -> Trade:
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        direction="long",
        open_fill_id="open",
        close_fill_id="close",
        open_ts_utc="2026-01-19T14:31:00+00:00",
        close_ts_utc="2026-01-19T15:31:00+00:00",
        open_date_ny="2026-01-19",
        close_date_ny=close_date_ny,
        qty=qty,
        open_price=open_price,
        close_price=close_price,
        fees=fees,
        venue="TEST",
        notes=None,
        strategy_id="default",
        sleeve_id="default",
    )


def _make_open_lot(symbol: str, qty: float, open_price: float | None) -> Lot:
    return Lot(
        lot_id="lot",
        symbol=symbol,
        side="long",
        open_fill_id="fill",
        open_ts_utc="2026-01-19T14:31:00+00:00",
        open_date_ny="2026-01-19",
        open_qty=qty,
        open_price=open_price,
        remaining_qty=qty,
        venue="TEST",
        source_paths=["ledger.json"],
        strategy_id="default",
        sleeve_id="default",
    )


def test_symbol_contributions_realized_pnl_net_fees() -> None:
    trades = [
        _make_trade(
            trade_id="t1",
            symbol="AAA",
            qty=1,
            open_price=100.0,
            close_price=110.0,
            close_date_ny="2026-01-19",
            fees=1.0,
        ),
        _make_trade(
            trade_id="t2",
            symbol="BBB",
            qty=2,
            open_price=50.0,
            close_price=40.0,
            close_date_ny="2026-01-19",
            fees=0.5,
        ),
    ]

    contributions = compute_symbol_contributions(trades)
    by_symbol = {row["symbol"]: row for row in contributions}

    assert by_symbol["AAA"]["realized_pnl"] == pytest.approx(9.0)
    assert by_symbol["BBB"]["realized_pnl"] == pytest.approx(-20.5)
    assert by_symbol["AAA"]["trade_count"] == 1
    assert by_symbol["BBB"]["fees_total"] == pytest.approx(0.5)


def test_drawdown_and_volatility_deterministic() -> None:
    daily_realized = [
        DailyRealized(date_ny="2026-01-19", realized_pnl=100.0, fees_total=0.0, trade_count=1, missing_price_trade_count=0),
        DailyRealized(date_ny="2026-01-20", realized_pnl=-50.0, fees_total=0.0, trade_count=1, missing_price_trade_count=0),
        DailyRealized(date_ny="2026-01-21", realized_pnl=25.0, fees_total=0.0, trade_count=1, missing_price_trade_count=0),
    ]

    drawdown = compute_drawdown(daily_realized, starting_capital=1000.0)
    assert drawdown["max_drawdown"] == pytest.approx(-0.0454545454)
    assert drawdown["series"][1]["drawdown"] == pytest.approx(-0.0454545454)

    volatility = compute_rolling_volatility(daily_realized, starting_capital=1000.0, window=2)
    series = volatility["series"]
    assert series[0]["volatility"] is None
    expected_returns = [0.1, -50.0 / 1100.0]
    mean = sum(expected_returns) / len(expected_returns)
    variance = sum((value - mean) ** 2 for value in expected_returns) / len(expected_returns)
    expected_vol = variance**0.5
    assert series[1]["volatility"] == pytest.approx(expected_vol)


def test_unrealized_pnl_missing_mark_price() -> None:
    open_lots = [_make_open_lot("AAA", qty=2, open_price=100.0)]
    positions, reason_codes = build_positions(open_lots)
    assert "position_mark_price_missing" in reason_codes

    unrealized_pnl, unrealized_reason = compute_unrealized_pnl(positions)
    assert unrealized_pnl is None
    assert "mark_price_unavailable" in unrealized_reason


def test_snapshot_serialization_deterministic(tmp_path: Path) -> None:
    trades = [
        _make_trade(
            trade_id="t1",
            symbol="AAA",
            qty=1,
            open_price=100.0,
            close_price=110.0,
            close_date_ny="2026-01-19",
            fees=1.0,
        )
    ]
    open_lots = [_make_open_lot("AAA", qty=1, open_price=100.0)]

    snapshot = build_portfolio_snapshot(
        date_ny="2026-01-19",
        run_id="run-123",
        trades=trades,
        open_lots=open_lots,
        starting_capital=1000.0,
        ending_capital=1100.0,
        price_map={"AAA": 105.0},
        ledger_paths=["ledger.json"],
        input_hashes={"ledger.json": "abc"},
    )

    payload_first = serialize_portfolio_snapshot(snapshot)
    payload_second = serialize_portfolio_snapshot(snapshot)
    serialized_first = json.dumps(payload_first, sort_keys=True, separators=(",", ":"))
    serialized_second = json.dumps(payload_second, sort_keys=True, separators=(",", ":"))
    assert serialized_first == serialized_second

    output_path = tmp_path / "snapshot.json"
    write_portfolio_snapshot_json(str(output_path), snapshot)
    assert output_path.read_text() == serialized_first


def test_sizing_and_guardrails_deterministic() -> None:
    sizing_first = size_position(capital=1000.0, risk_budget=0.1, price=50.0)
    sizing_second = size_position(capital=1000.0, risk_budget=0.1, price=50.0)
    assert sizing_first == sizing_second
    assert sizing_first["qty"] == pytest.approx(2.0)

    open_lots = [_make_open_lot("AAA", qty=10, open_price=100.0)]
    positions, _ = build_positions(open_lots, price_map={"AAA": 100.0})
    guardrails = evaluate_allocation_guardrails(
        positions=positions, capital=1000.0, concentration_limit=0.5
    )
    assert guardrails["passed"] is False
    assert guardrails["violations"][0]["code"] == "concentration_exceeded"
    assert guardrails["correlation"]["status"] == "placeholder"
