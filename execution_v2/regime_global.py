"""
Execution V2 – Global Market Regime (SPY)

PRD baseline:
- Use SPY
- Five-day moving average proxy slope
- Count of adverse expansion days over rolling window
- Output: OFF / DEFENSIVE / NORMAL

This module is PURE:
- No I/O
- No broker/data calls
- No global state
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from execution_v2.config_types import GlobalRegime
from execution_v2.pivots import DailyBar


@dataclass(frozen=True)
class GlobalRegimeConfig:
    # 5-day MA slope thresholds (in price units of SPY)
    # If slope <= off_slope_max -> OFF
    # Else if slope <= defensive_slope_max -> DEFENSIVE
    off_slope_max: float = -0.20
    defensive_slope_max: float = 0.00

    # Adverse expansion detection
    range_lookback: int = 10           # baseline range average lookback
    expansion_mult: float = 1.50       # range >= mult * avg_range => "expansion"
    adverse_window: int = 8            # rolling window to count adverse expansions

    # Count thresholds
    off_adverse_min: int = 3           # >= this => OFF
    defensive_adverse_min: int = 1     # >= this => DEFENSIVE (if not OFF)


@dataclass(frozen=True)
class GlobalRegimeMetrics:
    sma5_slope: float
    adverse_expansion_count: int


def _sma(values: list[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / float(n)


def compute_metrics(spy_daily: list[DailyBar], cfg: GlobalRegimeConfig) -> Optional[GlobalRegimeMetrics]:
    """
    spy_daily must be ordered oldest -> newest and contain completed daily bars.
    """
    if len(spy_daily) < max(6, cfg.range_lookback + 1):
        return None

    closes = [b.close for b in spy_daily]
    sma5_today = _sma(closes, 5)
    sma5_prev = _sma(closes[:-1], 5)
    if sma5_today is None or sma5_prev is None:
        return None

    sma5_slope = sma5_today - sma5_prev

    # Adverse expansion: wide-range down day relative to avg range baseline
    ranges = [(b.high - b.low) for b in spy_daily]
    avg_range = sum(ranges[-cfg.range_lookback:]) / float(cfg.range_lookback)

    def is_adverse_expansion(b: DailyBar) -> bool:
        r = b.high - b.low
        down_day = b.close < b.open
        expanded = r >= (cfg.expansion_mult * avg_range)
        return bool(down_day and expanded)

    window = spy_daily[-cfg.adverse_window:]
    adverse_count = sum(1 for b in window if is_adverse_expansion(b))

    return GlobalRegimeMetrics(
        sma5_slope=float(sma5_slope),
        adverse_expansion_count=int(adverse_count),
    )


def classify_global_regime(spy_daily: list[DailyBar], cfg: GlobalRegimeConfig) -> GlobalRegime:
    """
    Classify global regime from SPY daily bars using PRD baseline features.

    If insufficient data, fail-closed to DEFENSIVE (disables fresh entries).
    """
    m = compute_metrics(spy_daily, cfg)
    if m is None:
        return GlobalRegime.DEFENSIVE

    # OFF if volatility shock / hostile conditions
    if (m.sma5_slope <= cfg.off_slope_max) or (m.adverse_expansion_count >= cfg.off_adverse_min):
        return GlobalRegime.OFF

    # DEFENSIVE if weakening conditions (entries disabled; adds may be constrained later)
    if (m.sma5_slope <= cfg.defensive_slope_max) or (m.adverse_expansion_count >= cfg.defensive_adverse_min):
        return GlobalRegime.DEFENSIVE

    return GlobalRegime.NORMAL
# Execution V2 placeholder: regime_global.py
