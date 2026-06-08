"""Cross-asset trend signal.

For each asset class, compute a signed trend score using the class's
representative ETF. Score combines:
- Price-vs-200d-MA distance (long-horizon trend)
- 6-month return (medium-horizon momentum)
- 50d-vs-200d MA gap (trend direction)

Output: dict[asset_class, float] where positive = uptrend, negative = downtrend.
Scale roughly [-3, +3] but not bounded.

Used by:
- CrossAssetTrend strategy (to pick which asset classes to hold)
- Allocator's regime_alignment check (a strategy holding inverse_equity
  during a strong equity uptrend is mis-aligned)
"""

from __future__ import annotations

import math
from datetime import date
from typing import Mapping

from data.prices import PriceProvider


# Representative ETF for each asset class. Strict — every class that we
# want a trend score for must have a representative here. Classes not
# listed do not produce a score.
REPRESENTATIVES: Mapping[str, str] = {
    "equity_us_broad": "SPY",
    "equity_intl": "EEM",
    "sector": "XLK",  # tech is the most liquid sector for trend signal
    "bond_short": "SHY",
    "bond_mid": "IEF",
    "bond_long": "TLT",
    "credit": "HYG",
    "commodity_broad": "PDBC",
    "metal": "GLD",
    "energy": "USO",
    "crypto": "IBIT",
    "vol_long": "VIXY",
    "currency_dollar": "UUP",
}


def _closes_up_to(
    provider: PriceProvider, symbol: str, asof: date, max_lookback: int = 280
) -> list[float]:
    series = provider.get_daily_close_series(symbol)
    if not series:
        return []
    # Keep only entries <= asof, then take the last `max_lookback` of them.
    filtered = [c for d, c in series if d <= asof]
    return filtered[-max_lookback:]


def _trend_score(closes: list[float]) -> float | None:
    """Combine three signals into a single signed score.

    Returns None if not enough history (<210 closes).
    """
    if len(closes) < 210:
        return None
    last = closes[-1]
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / 200
    six_mo_idx = len(closes) - 126  # ~6 trading months
    if six_mo_idx < 0:
        return None
    six_mo_ago = closes[six_mo_idx]
    if last <= 0 or six_mo_ago <= 0 or sma200 <= 0:
        return None

    # Three normalized components, each roughly in [-1, +1] in normal markets:
    price_vs_200 = (last / sma200) - 1.0  # +0.1 = 10% above 200d MA
    sma_gap = (sma50 / sma200) - 1.0      # +0.02 = 50d 2% above 200d (golden cross)
    six_mo_ret = (last / six_mo_ago) - 1.0  # +0.2 = up 20% over 6 months

    # Sum with equal weighting; rough scale 3x (so [-3, +3] in extreme moves).
    return price_vs_200 * 10 + sma_gap * 50 + six_mo_ret * 5


def compute_cross_asset_trend(
    provider: PriceProvider,
    asof: date,
) -> dict[str, float]:
    """Return signed trend score per asset class.

    Classes lacking enough price history at `asof` are omitted from the
    output (rather than scored 0.0, so callers can distinguish "no data"
    from "neutral trend").
    """
    out: dict[str, float] = {}
    for asset_class, sym in REPRESENTATIVES.items():
        closes = _closes_up_to(provider, sym, asof)
        score = _trend_score(closes)
        if score is not None and math.isfinite(score):
            out[asset_class] = score
    return out
