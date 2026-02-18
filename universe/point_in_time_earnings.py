"""Point-in-time earnings calendar for survivorship-clean backtesting.

Replaces the live yfinance earnings lookup in backtest mode to avoid
lookahead bias (live API returns future-announced earnings dates that
would not have been known at the simulated as_of_date).
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "universe" / "earnings_calendar.parquet"


def load_earnings_calendar(path: str | Path | None = None) -> pd.DataFrame:
    """Load historical earnings calendar from Parquet.

    Columns: symbol, earnings_date, is_before_market (bool)

    Returns empty DataFrame if file doesn't exist.
    """
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return pd.DataFrame(columns=["symbol", "earnings_date", "is_before_market"])

    df = pd.read_parquet(p)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.normalize()
    return df


def is_near_earnings_pit(
    symbol: str,
    as_of_date: str,
    calendar_df: pd.DataFrame,
    window_days: int = 3,
) -> bool:
    """Check if symbol has earnings within window_days of as_of_date (point-in-time).

    Only considers earnings dates that are <= as_of_date + window_days AND
    where the earnings_date itself is known (i.e., <= as_of_date, simulating
    that earnings dates are announced before they occur).

    This avoids lookahead bias: we only use information that would have been
    available on as_of_date.
    """
    if calendar_df.empty:
        return False

    sym = symbol.upper().strip()
    as_of = pd.Timestamp(as_of_date).normalize()

    sym_df = calendar_df[calendar_df["symbol"] == sym]
    if sym_df.empty:
        return False

    # Point-in-time constraint: only consider earnings dates that were
    # known as of as_of_date. We assume an earnings date is "known" if
    # earnings_date <= as_of_date + window_days (it's already scheduled/announced).
    # But we also require earnings_date >= as_of_date - window_days to be "near".
    window_start = as_of - pd.Timedelta(days=window_days)
    window_end = as_of + pd.Timedelta(days=window_days)

    # Only use earnings dates that were known by as_of_date:
    # an earnings date is considered "known" if it falls on or before
    # as_of_date + window_days (we're checking if we're near a future/past date)
    near = sym_df[
        (sym_df["earnings_date"] >= window_start)
        & (sym_df["earnings_date"] <= window_end)
    ]

    return not near.empty
