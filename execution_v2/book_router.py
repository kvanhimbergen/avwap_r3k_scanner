"""Book-scoped adapter selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from execution_v2 import book_ids

if TYPE_CHECKING:
    from alpaca.trading.client import TradingClient


def select_trading_client(book_id: str) -> "TradingClient":
    if book_id == book_ids.ALPACA_PAPER:
        from execution_v2.execution_main import _get_alpaca_paper_trading_client

        return _get_alpaca_paper_trading_client()
    if book_id == book_ids.ALPACA_LIVE:
        from execution_v2.execution_main import _get_trading_client

        return _get_trading_client()
    if book_id == book_ids.SCHWAB_401K_MANUAL:
        raise NotImplementedError("SCHWAB_401K_MANUAL adapter not implemented")
    raise ValueError(f"Unknown book_id: {book_id}")
