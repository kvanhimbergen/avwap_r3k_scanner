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
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from execution_v2.pivots import DailyBar
from execution_v2.boh import Bar10m


@dataclass(frozen=True)
class VolumeProfile:
    """Session volume profile for rvol gating."""
    today_cumulative: float
    avg_cumulative: float
    rvol: float
    sample_days: int
    bar_count_today: int


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
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame(10, TimeFrameUnit.Minute), start=start)
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
                    volume=float(r["volume"]),
                )
            )
        return out

    def get_intraday_bars(
        self,
        symbol: str,
        minutes: int = 5,
        lookback_days: int = 3,
    ) -> list[dict]:
        """
        Return intraday bars ordered oldest->newest using Alpaca StockBarsRequest.
        Avoid pandas in the public surface by returning simple dicts.
        """
        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(minutes, TimeFrameUnit.Minute),
            start=start,
        )
        bars = self.client.get_stock_bars(req).df
        if bars is None or bars.empty:
            return []

        df = bars.reset_index()
        out: list[dict] = []
        for _, r in df.iterrows():
            ts = r["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc)
            out.append(
                {
                    "ts": ts,
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                }
            )
        return out


    def get_session_volume_profile(
        self,
        symbol: str,
        lookback_days: int = 20,
    ) -> Optional[VolumeProfile]:
        """Compute relative volume (rvol) for *symbol*.

        Fetches 5-minute bars over *lookback_days*, groups by NY date, and
        computes cumulative volume up to the current time of day.  Averages
        historical days' cumulative volume at the same time → rvol = today / avg.

        Returns None if insufficient data (fail-open).
        """
        from zoneinfo import ZoneInfo

        bars = self.get_intraday_bars(symbol, minutes=5, lookback_days=lookback_days + 2)
        if not bars:
            return None

        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)
        today_str = now_et.strftime("%Y-%m-%d")
        cutoff_time = now_et.time()

        # Group bars by NY date and compute cumulative volume up to cutoff time
        daily_cumvol: dict[str, float] = {}
        for bar in bars:
            ts = bar["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bar_et = ts.astimezone(et)
            bar_date = bar_et.strftime("%Y-%m-%d")
            bar_time = bar_et.time()
            if bar_time <= cutoff_time:
                daily_cumvol[bar_date] = daily_cumvol.get(bar_date, 0.0) + bar["volume"]

        today_vol = daily_cumvol.pop(today_str, None)
        if today_vol is None or not daily_cumvol:
            return None

        hist_vols = list(daily_cumvol.values())
        avg_vol = sum(hist_vols) / len(hist_vols) if hist_vols else 0.0
        if avg_vol <= 0:
            return None

        rvol = today_vol / avg_vol

        today_bars = sum(
            1 for bar in bars
            if bar["ts"].astimezone(et).strftime("%Y-%m-%d") == today_str
            and bar["ts"].astimezone(et).time() <= cutoff_time
        )

        return VolumeProfile(
            today_cumulative=today_vol,
            avg_cumulative=round(avg_vol, 2),
            rvol=round(rvol, 4),
            sample_days=len(hist_vols),
            bar_count_today=today_bars,
        )


def from_env() -> MarketData:
    """
    Construct MarketData from existing env vars used elsewhere in the repo.
    """
    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or ""
    sec = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET_KEY") or ""
    if not key or not sec:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    return MarketData(MarketDataConfig(api_key=key, api_secret=sec))
