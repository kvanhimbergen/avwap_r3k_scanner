#!/usr/bin/env python
"""
Repro: order submission edge case (existing sell order holds qty).
"""

from __future__ import annotations

from execution_v2.exits import ExitPositionState, reconcile_stop_order


class FakeTradingClient:
    def __init__(self):
        self._orders = [
            {
                "id": "sell-1",
                "side": "sell",
                "status": "open",
                "type": "market",
                "qty": 10,
            }
        ]

    def get_orders(self):
        return list(self._orders)

    def cancel_order_by_id(self, order_id):
        print(f"cancel_order_by_id called: {order_id}")

    def submit_order(self, request):
        raise AssertionError("submit_order should not be called in this repro")


def main() -> None:
    client = FakeTradingClient()
    state = ExitPositionState(symbol="TEST", qty=5)

    events = []

    def _append(event):
        events.append(event)

    reconcile_stop_order(
        trading_client=client,
        state=state,
        desired_qty=5,
        desired_stop=9.5,
        log=print,
        append_event=_append,
    )

    print("events:", events)


if __name__ == "__main__":
    main()
