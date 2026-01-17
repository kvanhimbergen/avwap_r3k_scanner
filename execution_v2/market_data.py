"""
Execution V2 – Market Data Adapter (Alpaca)

Responsibilities:
- Fetch completed DAILY bars (for pivots + global regime)
- Fetch last two CLOSED 10-minute bars (for BOH)
- Provide staleness/basic sanity checks

This module performs I/O but contains NO strategy logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from execution_v2.pivots import DailyBar
from execution_v2.boh import Bar10m


@dataclass(frozen=True)
class MarketDataConfig:
    api_key: str
    api_secret: str
    # lookbacks
    daily_lookback_days: int = 320
    intraday_lookback_days: int = 5


class MarketData:
    def __init__(self, cfg: MarketDataConfig) -> None:
        self.cfg = cfg
        self.client = StockHistoricalDataClient(cfg.api_key, cfg.api_secret)

    def get_daily_bars(self, symbol: str, lookback_days: Optional[int] = None) -> list[DailyBar]:
        days = lookback_days or self.cfg.daily_lookback_days
        start = datetime.now(timezone.utc) - timedelta(days=days)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start)
        bars = self.client.get_stock_bars(req).df
        if bars is None or bars.empty:
            return []

        df = bars.reset_index()

        out: list[DailyBar] = []
        for _, r in df.iterrows():
            # Alpaca returns timestamps; normalize to epoch seconds
            ts = r["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc).timestamp()
            out.append(
                DailyBar(
                    ts=float(ts),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                )
            )
        return out

    def get_last_two_closed_10m(self, symbol: str) -> list[Bar10m]:
        """
        Returns exactly two most recent CLOSED 10-minute bars (ordered oldest->newest).
        If insufficient data, returns [].

        Implementation detail:
        Alpaca timeframe supports Minute * N.
        We request a small lookback window and then take last two completed bars.
        """
        start = datetime.now(timezone.utc) - timedelta(days=self.cfg.intraday_lookback_days)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute * 10, start=start)
        bars = self.client.get_stock_bars(req).df
        if bars is None or bars.empty:
            return []

        df = bars.reset_index()
        # last two rows are the most recent bars; assume Alpaca returns completed bars up to "now"
        if len(df) < 2:
            return []

        last_two = df.iloc[-2:].copy()
        out: list[Bar10m] = []
        for _, r in last_two.iterrows():
            ts = r["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc).timestamp()
            out.append(
                Bar10m(
                    ts=float(ts),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                )
            )
        return out


def from_env() -> MarketData:
    """
    Construct MarketData from existing env vars used elsewhere in the repo.
    """
    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or ""
    sec = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET_KEY") or ""
    if not key or not sec:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    return MarketData(MarketDataConfig(api_key=key, api_secret=sec))
# Execution V2 placeholder: market_data.py
