"""Yield-curve / duration signal.

Long-duration treasuries (TLT) and short-end (SHY) carry opposite
exposures to rates. When TLT outperforms SHY over a rolling window,
yields are falling (curve trade favors duration). When SHY outperforms
TLT, yields are rising (curve trade favors short-end or inverse-tsy).

Output: signed float, positive = duration favorable, negative = inverse
favorable. Magnitude roughly [-3, +3] in normal markets.

Used by:
- BondCarry strategy (long TLT/EDV when positive; long TBT when very
  negative; long SHY/IEF middle ground)
"""

from __future__ import annotations

from datetime import date

from data.prices import PriceProvider


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 280) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _return_over(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    start = closes[-(window + 1)]
    if start <= 0:
        return None
    return (closes[-1] / start) - 1.0


def compute_yield_curve_signal(
    provider: PriceProvider, asof: date
) -> float | None:
    """Return signed yield-curve signal or None if insufficient data."""
    tlt = _closes_up_to(provider, "TLT", asof)
    shy = _closes_up_to(provider, "SHY", asof)
    if len(tlt) < 130 or len(shy) < 130:
        return None
    tlt_3mo = _return_over(tlt, 63)
    tlt_6mo = _return_over(tlt, 126)
    shy_3mo = _return_over(shy, 63)
    shy_6mo = _return_over(shy, 126)
    if None in (tlt_3mo, tlt_6mo, shy_3mo, shy_6mo):
        return None
    # Outperformance of duration vs short-end, weighted.
    diff_3mo = tlt_3mo - shy_3mo
    diff_6mo = tlt_6mo - shy_6mo
    return diff_3mo * 15 + diff_6mo * 10
