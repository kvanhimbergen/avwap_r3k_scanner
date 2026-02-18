"""Tests for AlpacaRebalanceAdapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from execution_v2.alpaca_rebalance_adapter import AlpacaRebalanceAdapter, RebalanceOrderResult


@dataclass
class FakeAccount:
    equity: str = "100000.00"


@dataclass
class FakePosition:
    symbol: str = "VTI"
    market_value: str = "50000.00"


@dataclass
class FakeOrder:
    id: str = "order-001"
    status: str = "accepted"
    side: str = "buy"
    filled_qty: str = "0"
    filled_avg_price: str | None = None
    filled_at: str | None = None
    created_at: str = "2026-02-18T14:00:00Z"
    updated_at: str = "2026-02-18T14:00:00Z"


class FakeTradingClient:
    def __init__(
        self,
        account: FakeAccount | None = None,
        positions: list[FakePosition] | None = None,
        fail_symbols: set[str] | None = None,
    ) -> None:
        self._account = account or FakeAccount()
        self._positions = positions if positions is not None else []
        self._fail_symbols = fail_symbols or set()
        self.submitted_orders: list[dict] = []
        self._order_counter = 0

    def get_account(self) -> FakeAccount:
        return self._account

    def get_all_positions(self) -> list[FakePosition]:
        return list(self._positions)

    def submit_order(self, request: Any) -> FakeOrder:
        symbol = str(request.symbol).upper()
        if symbol in self._fail_symbols:
            raise RuntimeError(f"order rejected for {symbol}")
        self._order_counter += 1
        self.submitted_orders.append({
            "symbol": symbol,
            "qty": int(request.qty),
            "side": str(request.side),
        })
        return FakeOrder(id=f"order-{self._order_counter:03d}", side=str(request.side))


def test_get_account_equity() -> None:
    client = FakeTradingClient(account=FakeAccount(equity="50000.00"))
    adapter = AlpacaRebalanceAdapter(client)
    assert adapter.get_account_equity() == 50000.0


def test_get_current_allocations_with_positions() -> None:
    client = FakeTradingClient(
        account=FakeAccount(equity="100000.00"),
        positions=[
            FakePosition(symbol="VTI", market_value="40000.00"),
            FakePosition(symbol="QQQ", market_value="30000.00"),
        ],
    )
    adapter = AlpacaRebalanceAdapter(client)
    allocs = adapter.get_current_allocations("BIL")
    assert allocs["VTI"] == 40.0
    assert allocs["QQQ"] == 30.0
    assert allocs["BIL"] == 30.0  # cash residual


def test_get_current_allocations_all_cash() -> None:
    client = FakeTradingClient(
        account=FakeAccount(equity="100000.00"),
        positions=[],
    )
    adapter = AlpacaRebalanceAdapter(client)
    allocs = adapter.get_current_allocations("BIL")
    assert allocs == {"BIL": 100.0}


def test_get_current_allocations_zero_equity() -> None:
    client = FakeTradingClient(account=FakeAccount(equity="0.00"))
    adapter = AlpacaRebalanceAdapter(client)
    allocs = adapter.get_current_allocations("BIL")
    assert allocs == {"BIL": 100.0}


def test_execute_rebalance_sells_before_buys(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "QQQ", "side": "BUY", "delta_pct": 10.0, "ref_price": 400.0,
         "intent_id": "id-buy", "strategy_id": "V1"},
        {"symbol": "VTI", "side": "SELL", "delta_pct": -10.0, "ref_price": 250.0,
         "intent_id": "id-sell", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path, strategy_id="V1",
    )

    assert result.sent == 2
    assert len(client.submitted_orders) == 2
    # Sell should be first
    assert client.submitted_orders[0]["symbol"] == "VTI"
    assert "sell" in client.submitted_orders[0]["side"].lower()
    assert client.submitted_orders[1]["symbol"] == "QQQ"
    assert "buy" in client.submitted_orders[1]["side"].lower()


def test_execute_rebalance_skips_cash_symbol(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
        {"symbol": "BIL", "side": "SELL", "delta_pct": -10.0, "ref_price": 91.0,
         "intent_id": "id-2", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path, cash_symbol="BIL",
    )

    assert result.sent == 1
    assert result.skipped == 1
    assert client.submitted_orders[0]["symbol"] == "VTI"


def test_execute_rebalance_skips_notice_intents(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "NOTICE", "side": "INFO", "delta_pct": 0.0, "ref_price": 0.0,
         "intent_id": "id-notice", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    assert result.sent == 0
    assert result.skipped == 1
    assert len(client.submitted_orders) == 0


def test_execute_rebalance_computes_shares_correctly(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    # 10% of $100k = $10k, at $250/share = floor(40) = 40 shares
    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    assert result.sent == 1
    assert client.submitted_orders[0]["qty"] == 40


def test_execute_rebalance_skips_zero_share_intents(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="1000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    # 0.5% of $1000 = $5, at $250/share = floor(0.02) = 0 shares → skip
    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 0.5, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    assert result.sent == 0
    assert result.skipped == 1


def test_execute_rebalance_records_ledger_events(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    ledger_path = tmp_path / "ledger" / "ALPACA_PAPER" / "2026-02-18.jsonl"
    assert ledger_path.exists()
    lines = [line for line in ledger_path.read_text().strip().split("\n") if line]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["symbol"] == "VTI"
    assert event["strategy_id"] == "V1"
    assert event["event_type"] == "ORDER_STATUS"


def test_execute_rebalance_handles_order_errors(tmp_path: Path) -> None:
    client = FakeTradingClient(
        account=FakeAccount(equity="100000.00"),
        fail_symbols={"QQQ"},
    )
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
        {"symbol": "QQQ", "side": "BUY", "delta_pct": 10.0, "ref_price": 400.0,
         "intent_id": "id-2", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    assert result.sent == 1
    assert len(result.errors) == 1
    assert "QQQ" in result.errors[0]


def test_send_summary_ticket_compatibility(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "target_pct": 40.0, "current_pct": 30.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    result = adapter.send_summary_ticket(
        intents,
        message="test ticket message",
        ny_date="2026-02-18",
        repo_root=tmp_path,
        post_enabled=True,
    )

    assert isinstance(result, RebalanceOrderResult)
    assert result.sent == 1
    assert result.ny_date == "2026-02-18"


def test_send_summary_ticket_disabled(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0, "ref_price": 250.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    result = adapter.send_summary_ticket(
        intents,
        message="test",
        ny_date="2026-02-18",
        repo_root=tmp_path,
        post_enabled=False,
    )

    assert result.sent == 0
    assert len(client.submitted_orders) == 0


def test_execute_rebalance_skips_no_ref_price(tmp_path: Path) -> None:
    client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
    adapter = AlpacaRebalanceAdapter(client)

    intents = [
        {"symbol": "VTI", "side": "BUY", "delta_pct": 10.0,
         "intent_id": "id-1", "strategy_id": "V1"},
    ]

    result = adapter.execute_rebalance(
        intents, ny_date="2026-02-18", repo_root=tmp_path,
    )

    assert result.sent == 0
    assert result.skipped == 1
