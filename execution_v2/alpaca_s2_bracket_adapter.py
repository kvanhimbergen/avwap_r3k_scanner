"""Alpaca bracket-order adapter for S2 LETF ORB candidates."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_v2 import alpaca_paper, book_ids
from execution_v2.clocks import ET

logger = logging.getLogger(__name__)

STRATEGY_ID = "S2_LETF_ORB_AGGRO"
LEDGER_SUBDIR = "S2_ALPACA"


@dataclass(frozen=True)
class BracketOrderResult:
    ny_date: str
    sent: int
    skipped: int
    errors: list[str]
    orders: list[dict] = field(default_factory=list)


class AlpacaS2BracketAdapter:
    """Places bracket orders for S2 LETF ORB candidates via Alpaca paper trading."""

    def __init__(self, trading_client: Any) -> None:
        self._client = trading_client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _s2_symbols(self, positions: list[Any]) -> set[str]:
        """Return symbols from current positions.

        We don't have a perfect way to distinguish S2 positions from V2
        positions in a shared account, so the caller should filter
        candidates against this set to avoid duplicating entries.
        """
        return {str(pos.symbol).upper() for pos in positions}

    def _pending_order_symbols(self, orders: list[Any]) -> set[str]:
        return {str(o.symbol).upper() for o in orders}

    # ------------------------------------------------------------------
    # cancel stale orders
    # ------------------------------------------------------------------

    def cancel_stale_orders(self, current_candidate_symbols: set[str]) -> list[str]:
        """Cancel open buy-side orders for symbols not in today's candidate list.

        Returns list of cancelled order IDs.
        """
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        open_orders = self._client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN),
        )
        cancelled: list[str] = []
        upper_candidates = {s.upper() for s in current_candidate_symbols}
        for order in open_orders:
            symbol = str(order.symbol).upper()
            side = str(getattr(order, "side", "")).split(".")[-1].lower()
            if side != "buy":
                continue
            if symbol in upper_candidates:
                continue
            order_id = str(order.id)
            try:
                self._client.cancel_order_by_id(order_id)
                cancelled.append(order_id)
                logger.info("Cancelled stale S2 order %s (%s)", order_id, symbol)
            except Exception as exc:
                logger.warning("Failed to cancel order %s (%s): %s", order_id, symbol, exc)
        return cancelled

    # ------------------------------------------------------------------
    # execute candidates
    # ------------------------------------------------------------------

    def execute_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        ny_date: str,
        repo_root: Path,
        risk_pct: float = 1.0,
        max_positions: int = 5,
    ) -> BracketOrderResult:
        """Place bracket orders for filtered S2 candidates.

        Parameters
        ----------
        candidates:
            List of dicts with keys: Symbol, Entry_Level, Stop_Loss, Target_R2.
        ny_date:
            Trading date in NY (YYYY-MM-DD).
        repo_root:
            Project root for ledger path resolution.
        risk_pct:
            Percentage of account equity risked per trade (default 1%).
        max_positions:
            Maximum concurrent S2 positions (default 5).
        """
        from alpaca.trading.requests import LimitOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        account = self._client.get_account()
        equity = float(account.equity)
        positions = self._client.get_all_positions()
        position_symbols = self._s2_symbols(positions)

        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        open_orders = self._client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN),
        )
        pending_symbols = self._pending_order_symbols(open_orders)

        available_slots = max_positions - len(position_symbols)

        now_utc = datetime.now(timezone.utc)
        orders: list[dict] = []
        errors: list[str] = []
        skipped = 0

        for candidate in candidates:
            symbol = str(candidate.get("Symbol", "")).upper().strip()
            if not symbol:
                skipped += 1
                continue

            entry_level = float(candidate.get("Entry_Level", 0))
            stop_loss = float(candidate.get("Stop_Loss", 0))
            target_r2 = float(candidate.get("Target_R2", 0))

            # Skip: already in a position
            if symbol in position_symbols:
                logger.info("SKIP %s: already in position", symbol)
                skipped += 1
                continue

            # Skip: already have a pending order
            if symbol in pending_symbols:
                logger.info("SKIP %s: pending order exists", symbol)
                skipped += 1
                continue

            # Skip: inverted bracket (entry <= stop)
            if entry_level <= stop_loss:
                logger.info("SKIP %s: inverted bracket (entry=%.2f <= stop=%.2f)", symbol, entry_level, stop_loss)
                skipped += 1
                continue

            # Skip: no available slots
            if available_slots <= 0:
                logger.info("SKIP %s: max positions reached", symbol)
                skipped += 1
                continue

            risk_per_share = entry_level - stop_loss
            shares = max(1, math.floor(equity * risk_pct / 100.0 / risk_per_share))

            # Cap notional at 20% of equity
            max_notional = equity * 0.20
            if shares * entry_level > max_notional:
                shares = max(1, math.floor(max_notional / entry_level))

            try:
                order = self._client.submit_order(
                    LimitOrderRequest(
                        symbol=symbol,
                        qty=shares,
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY,
                        limit_price=round(entry_level, 2),
                        order_class=OrderClass.BRACKET,
                        take_profit=TakeProfitRequest(limit_price=round(target_r2, 2)),
                        stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
                    )
                )
                event = alpaca_paper.build_order_event(
                    intent_id=f"s2_{symbol}_{ny_date}",
                    symbol=symbol,
                    qty=shares,
                    ref_price=entry_level,
                    order=order,
                    now_utc=now_utc,
                )
                event["strategy_id"] = STRATEGY_ID
                event["order_type"] = "BRACKET"
                event["stop_loss"] = round(stop_loss, 2)
                event["take_profit"] = round(target_r2, 2)
                orders.append(event)
                available_slots -= 1
                logger.info(
                    "SENT bracket %s: qty=%d entry=%.2f stop=%.2f target=%.2f",
                    symbol, shares, entry_level, stop_loss, target_r2,
                )
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
                logger.error("ERROR placing bracket for %s: %s", symbol, exc)

        # Write events to ledger
        if orders:
            ledger_path = repo_root / "ledger" / LEDGER_SUBDIR / f"{ny_date}.jsonl"
            alpaca_paper.append_events(ledger_path, orders)

        return BracketOrderResult(
            ny_date=ny_date,
            sent=len(orders),
            skipped=skipped,
            errors=errors,
            orders=orders,
        )
