"""Tests for multi-target exit behavior in sell_loop.py."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from execution_v2.config_types import PositionState, StopMode
from execution_v2.sell_loop import SellLoopConfig, evaluate_positions


@dataclass
class FakePosition:
    symbol: str
    current_price: float
    qty: float
    avg_entry_price: float
    market_value: float = 0.0


def _make_state(
    *,
    symbol: str = "AAPL",
    avg_price: float = 100.0,
    pivot_level: float = 100.0,
    r1_level: float = 105.0,
    r2_level: float = 110.0,
    stop_price: float = 95.0,
    size_shares: int = 100,
) -> PositionState:
    return PositionState(
        strategy_id="S1",
        symbol=symbol,
        size_shares=size_shares,
        avg_price=avg_price,
        pivot_level=pivot_level,
        r1_level=r1_level,
        r2_level=r2_level,
        stop_mode=StopMode.OPEN,
        last_update_ts=1000.0,
        stop_price=stop_price,
        high_water=avg_price,
        trimmed_r1=False,
        trimmed_r2=False,
    )


def _make_candidate():
    from execution_v2.buy_loop import Candidate
    return Candidate(
        symbol="AAPL",
        strategy_id="S1",
        direction="Long",
        entry_level=100.0,
        stop_loss=95.0,
        target_r2=110.0,
        target_r1=105.0,
        dist_pct=1.0,
        price=100.0,
    )


class TestBreakevenOnR1:
    """After R1 trim, stop should move to avg_price (breakeven) not pivot_level."""

    def test_r1_trim_sets_breakeven_stop(self):
        """When breakeven_on_r1=True (default), R1 trim moves stop to avg_price."""
        store = MagicMock()
        existing = _make_state(avg_price=100.0, pivot_level=98.0, stop_price=95.0)
        store.get_position.return_value = existing

        cfg = SellLoopConfig(breakeven_on_r1=True)

        position = FakePosition(
            symbol="AAPL",
            current_price=106.0,  # above R1
            qty=100,
            avg_entry_price=100.0,
        )

        trading_client = MagicMock()
        trading_client.get_all_positions.return_value = [position]

        cand = _make_candidate()
        with patch("execution_v2.sell_loop._candidate_map", return_value={"AAPL": cand}):
            evaluate_positions(store, trading_client, cfg)

        # Check that stop was set to avg_price (breakeven), not pivot_level
        upsert_call = store.upsert_position.call_args[0][0]
        assert upsert_call.trimmed_r1 is True
        assert upsert_call.stop_price >= 100.0  # breakeven (avg_price)

    def test_r1_trim_legacy_pivot_stop(self):
        """When breakeven_on_r1=False, R1 trim uses pivot_level for stop."""
        store = MagicMock()
        existing = _make_state(avg_price=100.0, pivot_level=98.0, stop_price=95.0)
        store.get_position.return_value = existing

        cfg = SellLoopConfig(breakeven_on_r1=False)

        position = FakePosition(
            symbol="AAPL",
            current_price=106.0,
            qty=100,
            avg_entry_price=100.0,
        )

        trading_client = MagicMock()
        trading_client.get_all_positions.return_value = [position]

        cand = _make_candidate()
        with patch("execution_v2.sell_loop._candidate_map", return_value={"AAPL": cand}):
            evaluate_positions(store, trading_client, cfg)

        upsert_call = store.upsert_position.call_args[0][0]
        assert upsert_call.trimmed_r1 is True
        assert upsert_call.stop_price >= 98.0  # pivot_level

    def test_stop_never_decreases(self):
        """Stop should never move down after R1 trim."""
        store = MagicMock()
        # Start with stop already above avg_price (shouldn't decrease)
        existing = _make_state(avg_price=100.0, stop_price=101.0)
        store.get_position.return_value = existing

        cfg = SellLoopConfig(breakeven_on_r1=True)

        position = FakePosition(
            symbol="AAPL",
            current_price=106.0,
            qty=100,
            avg_entry_price=100.0,
        )

        trading_client = MagicMock()
        trading_client.get_all_positions.return_value = [position]

        cand = _make_candidate()
        with patch("execution_v2.sell_loop._candidate_map", return_value={"AAPL": cand}):
            evaluate_positions(store, trading_client, cfg)

        upsert_call = store.upsert_position.call_args[0][0]
        assert upsert_call.stop_price >= 101.0  # should not decrease


class TestEntryIntentTargetR1:
    """EntryIntent should carry target_r1 through the pipeline."""

    def test_entry_intent_has_target_r1(self):
        from execution_v2.config_types import EntryIntent

        intent = EntryIntent(
            strategy_id="S1",
            symbol="AAPL",
            pivot_level=100.0,
            boh_confirmed_at=1000.0,
            scheduled_entry_at=1060.0,
            size_shares=50,
            stop_loss=95.0,
            take_profit=110.0,
            ref_price=100.0,
            dist_pct=1.0,
            target_r1=105.0,
        )
        assert intent.target_r1 == 105.0

    def test_entry_intent_target_r1_default_none(self):
        from execution_v2.config_types import EntryIntent

        intent = EntryIntent(
            strategy_id="S1",
            symbol="AAPL",
            pivot_level=100.0,
            boh_confirmed_at=1000.0,
            scheduled_entry_at=1060.0,
            size_shares=50,
            stop_loss=95.0,
            take_profit=110.0,
            ref_price=100.0,
            dist_pct=1.0,
        )
        assert intent.target_r1 is None


class TestSellLoopConfigBackwardCompat:
    """SellLoopConfig should default breakeven_on_r1=True."""

    def test_default_breakeven_on_r1(self):
        cfg = SellLoopConfig()
        assert cfg.breakeven_on_r1 is True

    def test_legacy_mode(self):
        cfg = SellLoopConfig(breakeven_on_r1=False)
        assert cfg.breakeven_on_r1 is False
