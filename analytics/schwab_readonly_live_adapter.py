from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from analytics.schwab_readonly_schemas import (
    SCHEMA_VERSION,
    SchwabBalanceSnapshot,
    SchwabOrder,
    SchwabOrdersSnapshot,
    SchwabPosition,
    SchwabPositionsSnapshot,
    parse_decimal,
)
from analytics.util import normalize_side, normalize_symbol


class SchwabLiveAdapterError(RuntimeError):
    pass


class SchwabReadonlyLiveAdapter:
    """Fetches account data from the Schwab Trader API via schwab-py."""

    def __init__(
        self,
        *,
        client: Any,
        book_id: str,
        account_hash: str,
        as_of_utc: str,
    ) -> None:
        self.client = client
        self.book_id = book_id
        self.account_hash = account_hash
        self.as_of_utc = as_of_utc

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        book_id: str,
        as_of_utc: str,
    ) -> SchwabReadonlyLiveAdapter:
        """Build from OAuth config — creates schwab-py client with token auto-refresh."""
        import schwab

        client = schwab.auth.client_from_token_file(
            token_path=config.token_path,
            api_key=config.client_id,
            app_secret=config.client_secret,
        )
        return cls(
            client=client,
            book_id=book_id,
            account_hash=config.account_hash,
            as_of_utc=as_of_utc,
        )

    def _get_account_data(self) -> dict:
        """Fetch account data with positions from the Schwab API."""
        resp = self.client.get_account(
            self.account_hash,
            fields=["positions"],
        )
        if resp.status_code != 200:
            raise SchwabLiveAdapterError(
                f"get_account failed: HTTP {resp.status_code}"
            )
        return resp.json()

    def load_balance_snapshot(self) -> SchwabBalanceSnapshot:
        data = self._get_account_data()
        acct = data.get("securitiesAccount", {})
        balances = acct.get("currentBalances", {})
        return SchwabBalanceSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            cash=parse_decimal(balances.get("cashBalance")),
            market_value=parse_decimal(balances.get("longMarketValue")),
            total_value=parse_decimal(balances.get("liquidationValue")),
        )

    def load_positions_snapshot(self) -> SchwabPositionsSnapshot:
        data = self._get_account_data()
        acct = data.get("securitiesAccount", {})
        raw_positions = acct.get("positions", [])
        positions: list[SchwabPosition] = []
        for entry in raw_positions:
            instrument = entry.get("instrument", {})
            symbol = normalize_symbol(instrument.get("symbol"))
            if not symbol:
                continue
            positions.append(
                SchwabPosition(
                    book_id=self.book_id,
                    as_of_utc=self.as_of_utc,
                    symbol=symbol,
                    qty=parse_decimal(entry.get("longQuantity")) or Decimal("0"),
                    cost_basis=parse_decimal(entry.get("currentDayCost")),
                    market_value=parse_decimal(entry.get("marketValue")),
                )
            )
        positions.sort(key=lambda p: p.symbol)
        return SchwabPositionsSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            positions=positions,
        )

    def load_orders_snapshot(self) -> SchwabOrdersSnapshot:
        now = datetime.now(tz=timezone.utc)
        from_dt = now - timedelta(days=1)
        resp = self.client.get_orders_for_account(
            self.account_hash,
            from_entered_datetime=from_dt,
            to_entered_datetime=now,
        )
        if resp.status_code != 200:
            raise SchwabLiveAdapterError(
                f"get_orders_for_account failed: HTTP {resp.status_code}"
            )
        raw_orders = resp.json()
        if not isinstance(raw_orders, list):
            raw_orders = []
        orders: list[SchwabOrder] = []
        for entry in raw_orders:
            order_id = str(entry.get("orderId", ""))
            if not order_id:
                continue
            legs = entry.get("orderLegCollection", [])
            if not legs:
                continue
            leg = legs[0]
            instrument = leg.get("instrument", {})
            symbol = normalize_symbol(instrument.get("symbol"))
            if not symbol:
                continue
            side = normalize_side(leg.get("instruction"))
            orders.append(
                SchwabOrder(
                    book_id=self.book_id,
                    as_of_utc=self.as_of_utc,
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    qty=parse_decimal(entry.get("quantity")) or Decimal("0"),
                    filled_qty=parse_decimal(entry.get("filledQuantity")),
                    status=entry.get("status"),
                    submitted_at=entry.get("enteredTime"),
                    filled_at=entry.get("closeTime"),
                )
            )
        orders.sort(key=lambda o: (o.symbol, o.order_id))
        return SchwabOrdersSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            orders=orders,
        )

    def load_all_snapshots(
        self,
    ) -> tuple[SchwabBalanceSnapshot, SchwabPositionsSnapshot, SchwabOrdersSnapshot]:
        data = self._get_account_data()
        acct = data.get("securitiesAccount", {})

        # Balance
        balances = acct.get("currentBalances", {})
        balance_snapshot = SchwabBalanceSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            cash=parse_decimal(balances.get("cashBalance")),
            market_value=parse_decimal(balances.get("longMarketValue")),
            total_value=parse_decimal(balances.get("liquidationValue")),
        )

        # Positions
        raw_positions = acct.get("positions", [])
        positions: list[SchwabPosition] = []
        for entry in raw_positions:
            instrument = entry.get("instrument", {})
            symbol = normalize_symbol(instrument.get("symbol"))
            if not symbol:
                continue
            positions.append(
                SchwabPosition(
                    book_id=self.book_id,
                    as_of_utc=self.as_of_utc,
                    symbol=symbol,
                    qty=parse_decimal(entry.get("longQuantity")) or Decimal("0"),
                    cost_basis=parse_decimal(entry.get("currentDayCost")),
                    market_value=parse_decimal(entry.get("marketValue")),
                )
            )
        positions.sort(key=lambda p: p.symbol)
        positions_snapshot = SchwabPositionsSnapshot(
            schema_version=SCHEMA_VERSION,
            book_id=self.book_id,
            as_of_utc=self.as_of_utc,
            positions=positions,
        )

        # Orders (separate API call)
        orders_snapshot = self.load_orders_snapshot()

        return balance_snapshot, positions_snapshot, orders_snapshot
