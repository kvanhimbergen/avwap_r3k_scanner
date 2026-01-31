from dataclasses import dataclass

from execution_v2.exits import ExitPositionState, reconcile_stop_order


@dataclass
class FakeOrder:
    id: str
    symbol: str
    side: str
    status: str
    order_type: str
    qty: int
    stop_price: float | None = None


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
