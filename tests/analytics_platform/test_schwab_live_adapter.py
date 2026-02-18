from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from analytics.schwab_readonly_live_adapter import (
    SchwabLiveAdapterError,
    SchwabReadonlyLiveAdapter,
)
from analytics.schwab_readonly_schemas import SCHEMA_VERSION


BOOK_ID = "TEST_BOOK"
ACCOUNT_HASH = "abc123hash"
AS_OF_UTC = "2026-02-18T15:00:00+00:00"


_DEFAULT_BALANCES = {
    "cashBalance": 1234.56,
    "longMarketValue": 50000.00,
    "liquidationValue": 51234.56,
}


def _account_response(*, positions=None, balances=_DEFAULT_BALANCES):
    """Build a mock Schwab API account response."""
    acct = {
        "securitiesAccount": {
            "currentBalances": balances,
            "positions": positions if positions is not None else [],
        }
    }
    return acct


def _make_adapter(client: MagicMock) -> SchwabReadonlyLiveAdapter:
    return SchwabReadonlyLiveAdapter(
        client=client,
        book_id=BOOK_ID,
        account_hash=ACCOUNT_HASH,
        as_of_utc=AS_OF_UTC,
    )


def _mock_client(*, account_data=None, orders_data=None, account_status=200, orders_status=200):
    client = MagicMock()
    account_resp = MagicMock()
    account_resp.status_code = account_status
    account_resp.json.return_value = account_data or _account_response()
    client.get_account.return_value = account_resp

    orders_resp = MagicMock()
    orders_resp.status_code = orders_status
    orders_resp.json.return_value = orders_data if orders_data is not None else []
    client.get_orders_for_account.return_value = orders_resp

    return client


class TestLoadBalanceSnapshot:
    def test_basic_balance(self):
        client = _mock_client()
        adapter = _make_adapter(client)
        snap = adapter.load_balance_snapshot()
        assert snap.schema_version == SCHEMA_VERSION
        assert snap.book_id == BOOK_ID
        assert snap.as_of_utc == AS_OF_UTC
        assert snap.cash == Decimal("1234.56")
        assert snap.market_value == Decimal("50000")
        assert snap.total_value == Decimal("51234.56")

    def test_balance_with_none_fields(self):
        client = _mock_client(account_data=_account_response(balances={}))
        adapter = _make_adapter(client)
        snap = adapter.load_balance_snapshot()
        assert snap.cash is None
        assert snap.market_value is None
        assert snap.total_value is None

    def test_balance_api_failure(self):
        client = _mock_client(account_status=401)
        adapter = _make_adapter(client)
        with pytest.raises(SchwabLiveAdapterError, match="HTTP 401"):
            adapter.load_balance_snapshot()


class TestLoadPositionsSnapshot:
    def test_basic_positions(self):
        positions = [
            {
                "instrument": {"symbol": "SPY"},
                "longQuantity": 100,
                "currentDayCost": 45000.00,
                "marketValue": 47500.00,
            },
            {
                "instrument": {"symbol": "BIL"},
                "longQuantity": 50,
                "currentDayCost": 4500.00,
                "marketValue": 4550.00,
            },
        ]
        client = _mock_client(account_data=_account_response(positions=positions))
        adapter = _make_adapter(client)
        snap = adapter.load_positions_snapshot()
        assert snap.schema_version == SCHEMA_VERSION
        assert len(snap.positions) == 2
        # Sorted by symbol
        assert snap.positions[0].symbol == "BIL"
        assert snap.positions[1].symbol == "SPY"
        assert snap.positions[1].qty == Decimal("100")
        assert snap.positions[1].cost_basis == Decimal("45000")
        assert snap.positions[1].market_value == Decimal("47500")

    def test_empty_positions(self):
        client = _mock_client(account_data=_account_response(positions=[]))
        adapter = _make_adapter(client)
        snap = adapter.load_positions_snapshot()
        assert snap.positions == []

    def test_positions_skip_missing_symbol(self):
        positions = [
            {"instrument": {}, "longQuantity": 10, "marketValue": 1000},
            {"instrument": {"symbol": "AAPL"}, "longQuantity": 5, "marketValue": 900},
        ]
        client = _mock_client(account_data=_account_response(positions=positions))
        adapter = _make_adapter(client)
        snap = adapter.load_positions_snapshot()
        assert len(snap.positions) == 1
        assert snap.positions[0].symbol == "AAPL"

    def test_positions_zero_qty(self):
        positions = [
            {"instrument": {"symbol": "VTI"}, "longQuantity": 0, "marketValue": 0},
        ]
        client = _mock_client(account_data=_account_response(positions=positions))
        adapter = _make_adapter(client)
        snap = adapter.load_positions_snapshot()
        assert snap.positions[0].qty == Decimal("0")


class TestLoadOrdersSnapshot:
    def test_basic_orders(self):
        orders = [
            {
                "orderId": "12345",
                "orderLegCollection": [
                    {"instrument": {"symbol": "SPY"}, "instruction": "BUY"},
                ],
                "quantity": 10,
                "filledQuantity": 10,
                "status": "FILLED",
                "enteredTime": "2026-02-18T14:30:00+00:00",
                "closeTime": "2026-02-18T14:30:05+00:00",
            },
        ]
        client = _mock_client(orders_data=orders)
        adapter = _make_adapter(client)
        snap = adapter.load_orders_snapshot()
        assert snap.schema_version == SCHEMA_VERSION
        assert len(snap.orders) == 1
        order = snap.orders[0]
        assert order.order_id == "12345"
        assert order.symbol == "SPY"
        assert order.side == "buy"
        assert order.qty == Decimal("10")
        assert order.filled_qty == Decimal("10")
        assert order.status == "FILLED"
        assert order.submitted_at == "2026-02-18T14:30:00+00:00"
        assert order.filled_at == "2026-02-18T14:30:05+00:00"

    def test_empty_orders(self):
        client = _mock_client(orders_data=[])
        adapter = _make_adapter(client)
        snap = adapter.load_orders_snapshot()
        assert snap.orders == []

    def test_orders_api_failure(self):
        client = _mock_client(orders_status=500)
        adapter = _make_adapter(client)
        with pytest.raises(SchwabLiveAdapterError, match="HTTP 500"):
            adapter.load_orders_snapshot()

    def test_orders_skip_missing_order_id(self):
        orders = [
            {
                "orderLegCollection": [
                    {"instrument": {"symbol": "SPY"}, "instruction": "BUY"},
                ],
                "quantity": 5,
            },
        ]
        client = _mock_client(orders_data=orders)
        adapter = _make_adapter(client)
        snap = adapter.load_orders_snapshot()
        assert snap.orders == []

    def test_orders_skip_no_legs(self):
        orders = [
            {
                "orderId": "999",
                "orderLegCollection": [],
                "quantity": 5,
            },
        ]
        client = _mock_client(orders_data=orders)
        adapter = _make_adapter(client)
        snap = adapter.load_orders_snapshot()
        assert snap.orders == []

    def test_orders_sell_side(self):
        orders = [
            {
                "orderId": "555",
                "orderLegCollection": [
                    {"instrument": {"symbol": "AAPL"}, "instruction": "SELL"},
                ],
                "quantity": 3,
                "filledQuantity": 0,
                "status": "PENDING_ACTIVATION",
            },
        ]
        client = _mock_client(orders_data=orders)
        adapter = _make_adapter(client)
        snap = adapter.load_orders_snapshot()
        assert snap.orders[0].side == "sell"
        assert snap.orders[0].filled_qty == Decimal("0")
        assert snap.orders[0].filled_at is None


class TestLoadAllSnapshots:
    def test_load_all_combines_account_and_orders(self):
        positions = [
            {"instrument": {"symbol": "VTI"}, "longQuantity": 200, "marketValue": 40000},
        ]
        orders = [
            {
                "orderId": "888",
                "orderLegCollection": [
                    {"instrument": {"symbol": "VTI"}, "instruction": "BUY"},
                ],
                "quantity": 200,
                "filledQuantity": 200,
                "status": "FILLED",
            },
        ]
        client = _mock_client(
            account_data=_account_response(positions=positions),
            orders_data=orders,
        )
        adapter = _make_adapter(client)
        bal, pos, ords = adapter.load_all_snapshots()
        assert bal.cash == Decimal("1234.56")
        assert len(pos.positions) == 1
        assert pos.positions[0].symbol == "VTI"
        assert len(ords.orders) == 1
        assert ords.orders[0].order_id == "888"

    def test_load_all_single_account_call(self):
        """load_all_snapshots should make only one get_account call (+ one get_orders)."""
        client = _mock_client(
            account_data=_account_response(
                positions=[{"instrument": {"symbol": "SPY"}, "longQuantity": 10, "marketValue": 5000}]
            ),
            orders_data=[],
        )
        adapter = _make_adapter(client)
        adapter.load_all_snapshots()
        assert client.get_account.call_count == 1
        assert client.get_orders_for_account.call_count == 1


class TestFromConfig:
    def test_from_config_calls_schwab_auth(self, monkeypatch):
        mock_client = MagicMock()
        mock_schwab = MagicMock()
        mock_schwab.auth.client_from_token_file.return_value = mock_client
        monkeypatch.setitem(__import__("sys").modules, "schwab", mock_schwab)

        config = MagicMock()
        config.token_path = "/tmp/token.json"
        config.client_id = "test-id"
        config.client_secret = "test-secret"
        config.account_hash = "hash123"

        adapter = SchwabReadonlyLiveAdapter.from_config(
            config, book_id="TEST", as_of_utc="2026-01-01T00:00:00Z"
        )
        assert adapter.client is mock_client
        assert adapter.account_hash == "hash123"
        mock_schwab.auth.client_from_token_file.assert_called_once_with(
            token_path="/tmp/token.json",
            api_key="test-id",
            app_secret="test-secret",
        )
