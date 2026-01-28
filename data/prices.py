"""Price provider interfaces for offline-first strategy runners."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class PriceProvider(Protocol):
    def get_daily_close_series(self, symbol: str) -> list[tuple[date, float]]:
        """Return daily close series as (date, close) tuples."""


class FixturePriceProvider:
    def __init__(self, series: dict[str, list[tuple[date, float]]]) -> None:
        self._series = {symbol.upper(): data for symbol, data in series.items()}

    def get_daily_close_series(self, symbol: str) -> list[tuple[date, float]]:
        return list(self._series.get(symbol.upper(), []))


@dataclass(frozen=True)
class _YFinancePriceProvider:
    period: str = "5y"

    def get_daily_close_series(self, symbol: str) -> list[tuple[date, float]]:
        if not symbol:
            return []
        import logging

        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        data = yf.download(
            tickers=[symbol],
            period=self.period,
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if data is None or data.empty:
            return []
        column = "Adj Close" if "Adj Close" in data.columns else "Close"
        closes = data[column].dropna()
        series: list[tuple[date, float]] = []
        for idx, value in closes.items():
            series.append((idx.date(), float(value)))
        return series


def get_default_price_provider(repo_root: str) -> PriceProvider:
    """Return the default price provider for strategy runners."""
    _ = repo_root
    return _YFinancePriceProvider()
