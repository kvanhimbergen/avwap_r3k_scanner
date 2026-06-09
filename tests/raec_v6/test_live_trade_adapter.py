"""Tests for the LiveTradeAdapter: safety, ticket format, intent IDs."""

from __future__ import annotations

from datetime import date

import pytest

from strategies.raec_v6.dry_run_adapter import DRY_RUN_BOOK_ID, V6DryRunSafetyError
from strategies.raec_v6.live_trade_adapter import (
    LIVE_BOOK_ID,
    LiveIntent,
    LiveTradeAdapter,
    make_intent_id,
)


def _intents() -> list[LiveIntent]:
    return [
        LiveIntent(
            intent_id=make_intent_id(asof=date(2026, 6, 9), symbol="SPY", side="BUY",
                                     target_pct=0.30, current_pct=0.25),
            symbol="SPY", side="BUY", delta_pct=0.05, target_pct=0.30,
            current_pct=0.25, dollar_delta=11500, shares_delta=20,
        ),
        LiveIntent(
            intent_id=make_intent_id(asof=date(2026, 6, 9), symbol="BIL", side="SELL",
                                     target_pct=0.40, current_pct=0.45),
            symbol="BIL", side="SELL", delta_pct=-0.05, target_pct=0.40,
            current_pct=0.45, dollar_delta=-11500, shares_delta=-128,
        ),
    ]


def test_default_construction_uses_live_book() -> None:
    a = LiveTradeAdapter()
    assert a.book_id == LIVE_BOOK_ID


def test_construction_refuses_dry_run_book() -> None:
    """LiveTradeAdapter must NEVER operate on the dry-run book."""
    with pytest.raises(V6DryRunSafetyError, match=LIVE_BOOK_ID):
        LiveTradeAdapter(book_id=DRY_RUN_BOOK_ID)


def test_construction_refuses_arbitrary_book() -> None:
    with pytest.raises(V6DryRunSafetyError):
        LiveTradeAdapter(book_id="FOO")


def test_intent_id_is_deterministic() -> None:
    """Same inputs → same intent_id, so re-running a date matches up."""
    a = make_intent_id(asof=date(2026, 6, 9), symbol="SPY", side="BUY",
                       target_pct=0.30, current_pct=0.25)
    b = make_intent_id(asof=date(2026, 6, 9), symbol="SPY", side="BUY",
                       target_pct=0.30, current_pct=0.25)
    assert a == b


def test_intent_id_differs_when_inputs_change() -> None:
    a = make_intent_id(asof=date(2026, 6, 9), symbol="SPY", side="BUY",
                       target_pct=0.30, current_pct=0.25)
    b = make_intent_id(asof=date(2026, 6, 9), symbol="QQQ", side="BUY",  # different symbol
                       target_pct=0.30, current_pct=0.25)
    assert a != b


def test_post_ticket_returns_formatted_text() -> None:
    a = LiveTradeAdapter()
    text = a.post_ticket(
        asof=date(2026, 6, 9),
        equity=253_862,
        cash_pct=0.008,
        rebalance=True,
        regime_label="RISK_ON",
        target_vol=0.24,
        forecast_vol=0.13,
        exposure_scale=1.2,
        strategy_shares={"V6_CROSS_ASSET_TREND": 0.35, "V6_BOND_CARRY": 0.10},
        intents=_intents(),
    )
    assert "RAEC v6 Rebalance Ticket" in text
    assert "Book: SCHWAB_401K_MANUAL" in text
    assert "INTENT" in text
    assert "BUY SPY" in text
    assert "SELL BIL" in text
    # Sells first ordering
    sell_pos = text.index("SELL BIL")
    buy_pos = text.index("BUY SPY")
    assert sell_pos < buy_pos
    # Reply protocol present
    assert "EXECUTED" in text and "intent_id" in text


def test_post_ticket_no_intents_shows_at_target_message() -> None:
    a = LiveTradeAdapter()
    text = a.post_ticket(
        asof=date(2026, 6, 9),
        equity=253_862,
        cash_pct=0.5,
        rebalance=False,
        regime_label="NEUTRAL",
        target_vol=0.24,
        forecast_vol=0.12,
        exposure_scale=1.0,
        strategy_shares={"V6_CROSS_ASSET_TREND": 0.20},
        intents=[],
        notice="within tolerance (L1 drift 2.0% < 5.0%)",
    )
    assert "Order intents: none" in text
    assert "within tolerance" in text


def test_post_error_does_not_raise() -> None:
    a = LiveTradeAdapter()
    a.post_error(asof=date(2026, 6, 9), error="something broke")
