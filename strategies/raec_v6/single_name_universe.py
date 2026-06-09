"""Curated mega-cap universe for the SingleNameMomentum strategy.

Selection criteria:
- Continuously in Russell 3000 since 2021-01-01 (covers our backtest
  window with no survivorship cheat).
- Mega- or upper-large-cap (≥$50B market cap in normal markets).
- Liquid enough to execute manually in Schwab 401(k) PCRA.
- Cross-sector diversification (no more than 10 names in any one sector
  so the strategy can't degenerate into a pure-tech bet).

This is intentionally a small *curated* list (~30 names) rather than a
scanner-driven dynamic universe. Reasons:
1. The scanner picks small/mid caps too, which lack the multi-year
   history needed to validate the backtest cleanly.
2. With ~30 names + top-K=5 picks, the strategy is forced to choose
   genuinely. With 200+ names, the picks would be noisy.
3. Sector caps below force diversification — the user can extend the
   list, but every addition should be motivated by sector/style coverage,
   not "this was hot last week."

Tagging is informational; sector breakdown is enforced at the strategy
level via _SECTOR_MAX_NAMES (no more than 3 picks from any sector).
"""

from __future__ import annotations


# (symbol, sector) — sectors are stable GICS labels.
_UNIVERSE: tuple[tuple[str, str], ...] = (
    # Tech / semis (10)
    ("AAPL", "Technology"),
    ("MSFT", "Technology"),
    ("GOOGL", "Communication"),
    ("AMZN", "Consumer Discretionary"),
    ("META", "Communication"),
    ("NVDA", "Technology"),
    ("AVGO", "Technology"),
    ("AMD", "Technology"),
    ("ORCL", "Technology"),
    ("ADBE", "Technology"),
    # Financials (5)
    ("JPM", "Financials"),
    ("BAC", "Financials"),
    ("MA", "Financials"),
    ("V", "Financials"),
    ("GS", "Financials"),
    # Healthcare (5)
    ("UNH", "Healthcare"),
    ("JNJ", "Healthcare"),
    ("LLY", "Healthcare"),
    ("ABBV", "Healthcare"),
    ("MRK", "Healthcare"),
    # Consumer Discretionary (3 — AMZN counted in tech-adjacent above)
    ("TSLA", "Consumer Discretionary"),
    ("HD", "Consumer Discretionary"),
    ("MCD", "Consumer Discretionary"),
    # Consumer Staples (3)
    ("PG", "Consumer Staples"),
    ("KO", "Consumer Staples"),
    ("PEP", "Consumer Staples"),
    # Industrials (3)
    ("CAT", "Industrials"),
    ("BA", "Industrials"),
    ("GE", "Industrials"),
    # Communication (2 — GOOGL/META already counted above)
    ("NFLX", "Communication"),
    ("DIS", "Communication"),
    # Energy (2)
    ("XOM", "Energy"),
    ("CVX", "Energy"),
)


UNIVERSE: tuple[str, ...] = tuple(s for s, _ in _UNIVERSE)
SECTOR_MAP: dict[str, str] = dict(_UNIVERSE)


# Max picks from a single sector — prevents the strategy from going 100%
# tech even when 10 of the top-K names are tech. Catches the V3+V5 overlap
# failure mode at the universe level.
_SECTOR_MAX_NAMES: int = 3


def apply_sector_cap(symbols_ranked: list[str], top_k: int) -> list[str]:
    """Take a ranked list and pick top-K subject to no more than
    _SECTOR_MAX_NAMES from any one sector.

    Items not in the universe are skipped (defensive — shouldn't happen
    if callers stick to UNIVERSE).
    """
    picked: list[str] = []
    sector_counts: dict[str, int] = {}
    for sym in symbols_ranked:
        if len(picked) >= top_k:
            break
        if sym not in SECTOR_MAP:
            continue
        sec = SECTOR_MAP[sym]
        if sector_counts.get(sec, 0) >= _SECTOR_MAX_NAMES:
            continue
        picked.append(sym)
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    return picked


def is_single_name(symbol: str) -> bool:
    """True if symbol is in the curated single-name universe (NOT an ETF).

    Used by the allocator to apply a tighter per-symbol cap.
    """
    return symbol.upper() in SECTOR_MAP
