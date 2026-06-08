"""VIX-implied volatility signal.

Pulls the CBOE VIX index close (^VIX via yfinance) as of `asof_date`
and converts to a decimal annualized vol (VIX 20 → 0.20).

Output: float decimal vol. Returns None if VIX data unavailable.

Used by:
- The overlay's forecast_vol = max(realized, ewma, vix_implied) — VIX
  is the leading-indicator component that catches regime shifts before
  trailing realized vol does.
- CrisisAlpha strategy's activation gate (vix > 30 = stressed enough).
"""

from __future__ import annotations

from datetime import date

from data.prices import PriceProvider


def _last_close_at_or_before(
    provider: PriceProvider, symbol: str, asof: date
) -> float | None:
    series = provider.get_daily_close_series(symbol)
    if not series:
        return None
    for d, c in reversed(series):
        if d <= asof:
            return c
    return None


def compute_vix_implied(provider: PriceProvider, asof: date) -> float | None:
    """Return VIX as a decimal annualized vol (e.g. VIX 20 → 0.20), or
    None if no data.
    """
    vix = _last_close_at_or_before(provider, "^VIX", asof)
    if vix is None or vix <= 0:
        return None
    return vix / 100.0
