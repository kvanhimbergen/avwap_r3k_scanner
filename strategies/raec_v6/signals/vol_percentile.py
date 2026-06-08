"""Per-symbol vol percentile.

For each symbol, compute realized 20-day vol at the as-of date, then rank
it against the trailing 252 daily 20d-vols of the same symbol. Output is
the percentile in [0, 1] where 0 = vol at min, 1 = vol at max.

Used by:
- EquityLeveragedMomentum to scale its leverage cap
- The vol overlay's diagnostic check (per-symbol vol contributing to
  portfolio vol estimate)
- Optionally exposed in the dashboard
"""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from data.prices import PriceProvider


def _closes_up_to(
    provider: PriceProvider, symbol: str, asof: date, max_lookback: int = 320
) -> list[float]:
    series = provider.get_daily_close_series(symbol)
    if not series:
        return []
    filtered = [c for d, c in series if d <= asof]
    return filtered[-max_lookback:]


def _daily_returns(closes: list[float]) -> list[float]:
    if len(closes) < 2:
        return []
    return [
        (closes[i] / closes[i - 1]) - 1.0
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]


def _rolling_vol_20d(returns: list[float]) -> list[float]:
    """Rolling 20d realized vol (annualized). Output aligned to returns
    starting at index 19."""
    out: list[float] = []
    window = 20
    if len(returns) < window:
        return out
    for end in range(window, len(returns) + 1):
        win = returns[end - window : end]
        mean = sum(win) / window
        var = sum((r - mean) ** 2 for r in win) / (window - 1)
        if var <= 0:
            out.append(0.0)
        else:
            out.append(math.sqrt(var) * math.sqrt(252))
    return out


def compute_vol_percentile(
    provider: PriceProvider,
    symbols: Iterable[str],
    asof: date,
) -> dict[str, float]:
    """Return {symbol: vol_percentile_in_[0,1]}.

    A symbol is omitted from the output if it has <252 trailing rolling
    20d vols available at the as-of date (need ~272 calendar trading days
    of closes total).
    """
    out: dict[str, float] = {}
    for symbol in symbols:
        sym = symbol.upper()
        closes = _closes_up_to(provider, sym, asof)
        returns = _daily_returns(closes)
        vols = _rolling_vol_20d(returns)
        if len(vols) < 252:
            continue
        current = vols[-1]
        history = vols[-252:]
        if current <= 0:
            out[sym] = 0.0
            continue
        # Percentile of `current` within `history`. Use rank /n; ties go up.
        rank = sum(1 for v in history if v <= current)
        out[sym] = rank / len(history)
    return out
