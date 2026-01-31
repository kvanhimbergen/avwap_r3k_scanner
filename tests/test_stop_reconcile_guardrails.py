from dataclasses import dataclass
from datetime import datetime, timezone

from execution_v2.exits import ExitPositionState, _read_existing_stop, reconcile_stop_order


@dataclass
class FakeOrder:
    id: str
    symbol: str
    side: str
    status: str
    order_type: str
    qty: int
    stop_price: float | None = None
    submitted_at: datetime | None = None


class FakeTradingClient:
    def __init__(self, orders):
        self.orders = list(orders)
        self.cancel_calls = []
        self.submit_calls = 0

    def get_orders(self):
        return list(self.orders)

    def cancel_order_by_id(self, order_id):
        self.cancel_calls.append(order_id)
        self.orders = [o for o in self.orders if o.id != order_id]

    def submit_order(self, order):
        self.submit_calls += 1
        return order


def test_reconcile_stop_order_matches_existing_stop():
    orders = [
        FakeOrder(
            id="stop-1",
            symbol="AAA",
            side="sell",
            status="open",
            order_type="stop",
            qty=10,
            stop_price=95.0,
        )
    ]
    client = FakeTradingClient(orders)
    state = ExitPositionState(symbol="AAA", qty=10)
    events = []

    updated = reconcile_stop_order(
        trading_client=client,
        state=state,
        desired_qty=10,
        desired_stop=95.0,
        append_event=events.append,
    )

    assert updated.stop_order_id == "stop-1"
    assert client.submit_calls == 0
    assert client.cancel_calls == []
    assert events == []


def test_reconcile_stop_order_skips_when_sell_order_holds_qty():
    orders = [
        FakeOrder(
            id="sell-1",
            symbol="BBB",
            side="sell",
            status="open",
            order_type="market",
            qty=10,
        )
    ]
    client = FakeTradingClient(orders)
    state = ExitPositionState(symbol="BBB", qty=10)
    events = []

    updated = reconcile_stop_order(
        trading_client=client,
        state=state,
        desired_qty=10,
        desired_stop=90.0,
        append_event=events.append,
    )

    assert updated.stop_order_id is None
    assert client.submit_calls == 0
    assert client.cancel_calls == []
    assert events
    assert events[0]["event"] == "STOP_SKIP_HELD"


def test_stop_selection_prefers_most_recent_when_enabled(monkeypatch):
    monkeypatch.setenv("EXIT_STOP_SELECTION_V2", "1")
    recent = datetime(2024, 1, 3, tzinfo=timezone.utc)
    older = datetime(2024, 1, 1, tzinfo=timezone.utc)
    orders = [
        FakeOrder(
            id="stop-old",
            symbol="CCC",
            side="sell",
            status="open",
            order_type="stop",
            qty=10,
            stop_price=90.0,
            submitted_at=older,
        ),
        FakeOrder(
            id="stop-new",
            symbol="CCC",
            side="sell",
            status="open",
            order_type="stop",
            qty=10,
            stop_price=92.0,
            submitted_at=recent,
        ),
    ]
    client = FakeTradingClient(orders)

    selected = _read_existing_stop(
        client,
        "CCC",
        desired_qty=10,
        desired_stop=95.0,
    )

    assert selected == 92.0


def test_stop_selection_disabled_preserves_first_match(monkeypatch):
    monkeypatch.delenv("EXIT_STOP_SELECTION_V2", raising=False)
    orders = [
        FakeOrder(
            id="stop-first",
            symbol="DDD",
            side="sell",
            status="open",
            order_type="stop",
            qty=10,
            stop_price=88.0,
        ),
        FakeOrder(
            id="stop-second",
            symbol="DDD",
            side="sell",
            status="open",
            order_type="stop",
            qty=10,
            stop_price=91.0,
        ),
    ]
    client = FakeTradingClient(orders)

    selected = _read_existing_stop(
        client,
        "DDD",
        desired_qty=10,
        desired_stop=95.0,
    )

    assert selected == 88.0
