"""
Phase S1 portfolio arbitration tests (docs/ROADMAP.md).
"""

from __future__ import annotations

import pytest

from execution_v2.portfolio_arbiter import PortfolioConstraints, arbitrate_intents
from execution_v2.portfolio_intents import TradeIntent
from execution_v2.config_types import EntryIntent


def _intent(
    *,
    strategy_id: str,
    symbol: str,
    side: str = "buy",
    qty: int = 10,
    intent_ts: float = 1000.0,
    valid_until: float = 2000.0,
) -> TradeIntent:
    return TradeIntent(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        qty=qty,
        intent_ts_utc=intent_ts,
        valid_until_ts_utc=valid_until,
        reason_codes=["test"],
        risk_tags=[],
        sleeve_id="default",
    )


def test_arbitration_is_deterministic_hash() -> None:
    intents = [
        _intent(strategy_id="S-A", symbol="AAA", qty=5),
        _intent(strategy_id="S-B", symbol="AAA", qty=10),
        _intent(strategy_id="S-C", symbol="BBB", qty=7),
    ]
    constraints = PortfolioConstraints(max_positions=5, open_positions_count=0)
    first = arbitrate_intents(
        intents,
        now_ts_utc=1500.0,
        constraints=constraints,
        run_id="run-1",
        date_ny="2026-01-02",
    )
    second = arbitrate_intents(
        intents,
        now_ts_utc=1500.0,
        constraints=constraints,
        run_id="run-1",
        date_ny="2026-01-02",
    )

    assert first.decision_hash == second.decision_hash
    assert [order.symbol for order in first.approved_orders] == ["AAA", "BBB"]
    assert [order.qty for order in first.approved_orders] == [10, 7]
    assert [rej.intent.symbol for rej in first.rejected_intents] == ["AAA"]


def test_stale_intent_rejected_fail_closed() -> None:
    intents = [_intent(strategy_id="S-A", symbol="STALE", intent_ts=500.0, valid_until=900.0)]
    decision = arbitrate_intents(
        intents,
        now_ts_utc=1000.0,
        constraints=PortfolioConstraints(),
        run_id="run-2",
        date_ny="2026-01-02",
    )

    assert decision.approved_orders == []
    assert decision.rejected_intents
    assert decision.rejected_intents[0].rejection_reason == "stale_intent"
    assert "stale_intent" in decision.rejected_intents[0].reason_codes


def test_constraint_max_positions_enforced() -> None:
    intents = [
        _intent(strategy_id="S-A", symbol="AAA"),
        _intent(strategy_id="S-B", symbol="BBB"),
    ]
    constraints = PortfolioConstraints(max_positions=1, open_positions_count=1)
    decision = arbitrate_intents(
        intents,
        now_ts_utc=1500.0,
        constraints=constraints,
        run_id="run-3",
        date_ny="2026-01-02",
    )

    assert decision.approved_orders == []
    assert {rej.rejection_reason for rej in decision.rejected_intents} == {"max_positions"}


def test_strategy_id_propagates_to_orders() -> None:
    intents = [_intent(strategy_id="S-STRAT", symbol="AAA")]
    decision = arbitrate_intents(
        intents,
        now_ts_utc=1500.0,
        constraints=PortfolioConstraints(),
        run_id="run-4",
        date_ny="2026-01-02",
    )

    assert decision.approved_orders[0].strategy_id == "S-STRAT"


def test_no_decision_no_orders_fail_closed(tmp_path, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    sys.modules.setdefault(
        "requests",
        SimpleNamespace(
            post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
            Session=object,
            Response=object,
        ),
    )
    sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object))

    from execution_v2 import execution_main

    monkeypatch.setenv("EXECUTION_MODE", "SCHWAB_401K_MANUAL")
    monkeypatch.setenv("DRY_RUN", "1")

    monkeypatch.setattr(execution_main.book_router, "select_trading_client", lambda *_: SimpleNamespace())
    monkeypatch.setattr(execution_main, "_market_open", lambda *_: True)
    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", lambda *_: 0)
    monkeypatch.setattr(execution_main.exits, "manage_positions", lambda **_: None)
    import execution_v2.schwab_manual_adapter as schwab_manual_adapter

    monkeypatch.setattr(
        schwab_manual_adapter,
        "send_manual_tickets",
        lambda *_args, **_kwargs: pytest.fail("order submitted"),
    )
    monkeypatch.setattr(execution_main.portfolio_arbiter, "arbitrate_intents", lambda *_, **__: (_ for _ in ()).throw(ValueError("bad")))

    now = 1000.0
    entry_intent = EntryIntent(
        strategy_id="S-TEST",
        symbol="AAA",
        pivot_level=1.0,
        boh_confirmed_at=now,
        scheduled_entry_at=now,
        size_shares=1,
        stop_loss=0.9,
        take_profit=1.1,
        ref_price=1.0,
        dist_pct=1.0,
    )

    class DummyStore:
        def __init__(self, *_):
            self._intents = [entry_intent]

        def pop_due_entry_intents(self, *_):
            return self._intents

        def list_positions(self):
            return []

        def pop_trim_intents(self):
            return []

    monkeypatch.setattr(execution_main, "StateStore", DummyStore)

    cfg = SimpleNamespace(
        candidates_csv="daily_candidates.csv",
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(tmp_path / "state.sqlite"),
        execution_mode="SCHWAB_401K_MANUAL",
        dry_run=True,
        poll_seconds=300,
        ignore_market_hours=True,
    )

    execution_main.run_once(cfg)
