"""
Phase S0 Strategy Identity contract tests (docs/ROADMAP.md).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from analytics.io.ledgers import parse_dry_run_ledger
from analytics.portfolio import build_portfolio_snapshot
from analytics.schemas import Lot, Trade
from execution_v2.config_types import EntryIntent, PositionState, StopMode
from execution_v2.orders import SlippageConfig, build_marketable_limit
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def test_strategy_id_required_on_entry_intent() -> None:
    now = datetime.now(tz=timezone.utc).timestamp()
    with pytest.raises(TypeError):
        EntryIntent(
            symbol="AAA",
            pivot_level=1.0,
            boh_confirmed_at=now,
            scheduled_entry_at=now,
            size_shares=10,
            stop_loss=9.0,
            take_profit=11.0,
            ref_price=10.0,
            dist_pct=1.0,
        )


def test_strategy_id_present_on_intent_order_and_position() -> None:
    now = datetime.now(tz=timezone.utc).timestamp()
    intent = EntryIntent(
        strategy_id=DEFAULT_STRATEGY_ID,
        symbol="AAA",
        pivot_level=1.0,
        boh_confirmed_at=now,
        scheduled_entry_at=now,
        size_shares=10,
        stop_loss=9.0,
        take_profit=11.0,
        ref_price=10.0,
        dist_pct=1.0,
    )
    assert intent.strategy_id == DEFAULT_STRATEGY_ID

    order = build_marketable_limit(
        strategy_id=DEFAULT_STRATEGY_ID,
        date_ny="2024-01-02",
        symbol="AAA",
        side="buy",
        qty=10,
        ref_price=10.0,
        cfg=SlippageConfig(max_slippage_pct=0.0, randomization_pct=0.0),
    )
    assert order.strategy_id == DEFAULT_STRATEGY_ID

    position = PositionState(
        strategy_id=DEFAULT_STRATEGY_ID,
        symbol="AAA",
        size_shares=10,
        avg_price=10.0,
        pivot_level=9.5,
        r1_level=11.0,
        r2_level=12.0,
        stop_mode=StopMode.OPEN,
        last_update_ts=now,
        stop_price=9.0,
        high_water=10.0,
    )
    assert position.strategy_id == DEFAULT_STRATEGY_ID


def test_strategy_id_present_on_fills_and_snapshot() -> None:
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))
    assert result.fills
    assert {fill.strategy_id for fill in result.fills} == {DEFAULT_STRATEGY_ID}

    trade = Trade(
        trade_id="trade-1",
        symbol="AAA",
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
    open_lot = Lot(
        lot_id="lot-1",
        symbol="AAA",
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

    snapshot = build_portfolio_snapshot(
        date_ny="2026-01-19",
        run_id="run-1",
        trades=[trade],
        open_lots=[open_lot],
        price_map={"AAA": 105.0},
    )
    assert snapshot.strategy_ids == [DEFAULT_STRATEGY_ID]
    assert {position.strategy_id for position in snapshot.positions} == {DEFAULT_STRATEGY_ID}
