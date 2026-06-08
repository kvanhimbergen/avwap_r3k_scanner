"""Credit-spread direction signal.

HYG (high-yield credit) vs IEF (intermediate treasuries) is the standard
proxy for credit spreads:
- HYG outperforming IEF → spreads tightening → credit market is healthy
- HYG underperforming IEF → spreads widening → credit stress

Output: signed float. Positive = credit favorable; negative = credit
stress. Magnitude roughly [-3, +3].

Used by:
- BondCarry strategy (when positive, tilt to HYG; when negative, tilt
  away from credit toward duration or short-end)
- (Future) the allocator regime gate for risk-on strategies
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


def compute_credit_spread_signal(
    provider: PriceProvider, asof: date
) -> float | None:
    """Return signed credit-spread direction signal (positive = spreads
    tightening / credit favorable), or None if insufficient data."""
    hyg = _closes_up_to(provider, "HYG", asof)
    ief = _closes_up_to(provider, "IEF", asof)
    if len(hyg) < 130 or len(ief) < 130:
        return None
    hyg_3mo = _return_over(hyg, 63)
    hyg_6mo = _return_over(hyg, 126)
    ief_3mo = _return_over(ief, 63)
    ief_6mo = _return_over(ief, 126)
    if None in (hyg_3mo, hyg_6mo, ief_3mo, ief_6mo):
        return None
    return (hyg_3mo - ief_3mo) * 15 + (hyg_6mo - ief_6mo) * 10
