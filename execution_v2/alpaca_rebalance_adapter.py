"""Alpaca rebalance adapter for RAEC V1/V2 paper trading."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from execution_v2 import alpaca_paper, book_ids
from execution_v2.clocks import ET


@dataclass(frozen=True)
class RebalanceOrderResult:
    ny_date: str
    sent: int
    skipped: int
    orders: list[dict]
    errors: list[str]


def _get_field(intent: Any, name: str, fallback: Any = None) -> Any:
    if isinstance(intent, Mapping):
        return intent.get(name, fallback)
    return getattr(intent, name, fallback)


class AlpacaRebalanceAdapter:
    """Wraps an Alpaca TradingClient for percentage-based portfolio rebalancing.

    Designed as a drop-in replacement for SchwabManualAdapter's
    ``send_summary_ticket()`` call signature so V1/V2 strategies need
    minimal changes.
    """

    def __init__(self, trading_client: Any) -> None:
        self._client = trading_client

    def get_account_equity(self) -> float:
        account = self._client.get_account()
        return float(account.equity)

    def get_current_allocations(self, cash_symbol: str) -> dict[str, float]:
        """Return current portfolio as percentage allocations.

        Maps Alpaca's USD cash balance to ``cash_symbol`` in the output dict.
        """
        account = self._client.get_account()
        equity = float(account.equity)
        if equity <= 0:
            return {cash_symbol: 100.0}

        positions = self._client.get_all_positions()
        allocations: dict[str, float] = {}
        position_total = 0.0
        for pos in positions:
            symbol = str(pos.symbol).upper()
            market_value = abs(float(pos.market_value))
            pct = round(market_value / equity * 100.0, 1)
            if pct > 0:
                allocations[symbol] = pct
                position_total += pct

        cash_pct = round(max(0.0, 100.0 - position_total), 1)
        if cash_pct > 0:
            allocations[cash_symbol] = allocations.get(cash_symbol, 0.0) + cash_pct

        return allocations

    def execute_rebalance(
        self,
        intents: Iterable[Any],
        *,
        ny_date: str,
        repo_root: Path,
        strategy_id: str = "",
        cash_symbol: str = "BIL",
    ) -> RebalanceOrderResult:
        """Convert percentage-delta intents to Alpaca orders.

        - Skips cash_symbol intents (cash is the residual).
        - Executes SELLs before BUYs.
        - Records order events via alpaca_paper.append_events().
        """
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        equity = self.get_account_equity()
        intent_list = list(intents)

        # Separate sells and buys; skip cash symbol and INFO/NOTICE intents
        sells: list[dict] = []
        buys: list[dict] = []
        skipped = 0
        for intent in intent_list:
            symbol = str(_get_field(intent, "symbol", "")).upper()
            side = str(_get_field(intent, "side", "")).upper()
            delta_pct = float(_get_field(intent, "delta_pct", 0.0))

            if symbol == cash_symbol.upper() or side == "INFO" or symbol == "NOTICE":
                skipped += 1
                continue

            ref_price = _get_field(intent, "ref_price")
            if ref_price is None:
                skipped += 1
                continue
            ref_price = float(ref_price)
            if ref_price <= 0:
                skipped += 1
                continue

            shares = math.floor(abs(equity * delta_pct / 100.0) / ref_price)
            if shares <= 0:
                skipped += 1
                continue

            entry = {
                "symbol": symbol,
                "side": side,
                "delta_pct": delta_pct,
                "ref_price": ref_price,
                "shares": shares,
                "intent_id": str(_get_field(intent, "intent_id", "")),
                "strategy_id": str(_get_field(intent, "strategy_id", strategy_id)),
            }
            if side == "SELL":
                sells.append(entry)
            else:
                buys.append(entry)

        now_utc = datetime.now(timezone.utc)
        orders: list[dict] = []
        errors: list[str] = []
        events: list[dict] = []

        for entry in sells + buys:
            alpaca_side = OrderSide.SELL if entry["side"] == "SELL" else OrderSide.BUY
            try:
                order = self._client.submit_order(
                    MarketOrderRequest(
                        symbol=entry["symbol"],
                        qty=entry["shares"],
                        side=alpaca_side,
                        time_in_force=TimeInForce.DAY,
                    )
                )
                order_event = alpaca_paper.build_order_event(
                    intent_id=entry["intent_id"],
                    symbol=entry["symbol"],
                    qty=entry["shares"],
                    ref_price=entry["ref_price"],
                    order=order,
                    now_utc=now_utc,
                )
                if entry["strategy_id"]:
                    order_event["strategy_id"] = entry["strategy_id"]
                events.append(order_event)
                orders.append(order_event)
            except Exception as exc:
                errors.append(f"{entry['symbol']}: {exc}")

        if events:
            ledger_path = alpaca_paper.ledger_path(repo_root, ny_date)
            alpaca_paper.append_events(ledger_path, events)

        return RebalanceOrderResult(
            ny_date=ny_date,
            sent=len(orders),
            skipped=skipped,
            orders=orders,
            errors=errors,
        )

    def send_summary_ticket(
        self,
        intents: Iterable[Any],
        *,
        message: str = "",
        ny_date: str,
        repo_root: Path,
        post_enabled: bool | None = None,
        **kwargs: Any,
    ) -> RebalanceOrderResult:
        """Compatibility shim matching SchwabManualAdapter.send_summary_ticket().

        Checks ALPACA_REBALANCE_ENABLED env var (or post_enabled kwarg) before
        submitting orders.
        """
        import os

        if post_enabled is None:
            enabled = os.getenv("ALPACA_REBALANCE_ENABLED", "1").strip().lower() in {
                "1", "true", "yes",
            }
        else:
            enabled = post_enabled

        if not enabled:
            return RebalanceOrderResult(
                ny_date=ny_date,
                sent=0,
                skipped=0,
                orders=[],
                errors=[],
            )

        intent_list = list(intents)
        strategy_id = ""
        cash_symbol = "BIL"
        for intent in intent_list:
            sid = _get_field(intent, "strategy_id")
            if sid:
                strategy_id = str(sid)
                break

        return self.execute_rebalance(
            intent_list,
            ny_date=ny_date,
            repo_root=repo_root,
            strategy_id=strategy_id,
            cash_symbol=cash_symbol,
        )
