"""Corporate action handling: splits, mergers, delistings.

Adjusts OHLCV prices retroactively for splits and identifies delisted symbols.
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "universe" / "corporate_actions.csv"


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: str  # "split", "merger", "delisting"
    effective_date: str  # YYYY-MM-DD
    ratio: float | None  # 2.0 = 2-for-1 split
    acquirer: str | None = None


def load_corporate_actions(path: str | Path | None = None) -> list[CorporateAction]:
    """Load corporate actions from CSV.

    Columns: symbol, action_type, effective_date, ratio, acquirer
    """
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return []

    actions = []
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ratio_str = row.get("ratio", "").strip()
            ratio = float(ratio_str) if ratio_str else None
            acquirer = row.get("acquirer", "").strip() or None
            actions.append(
                CorporateAction(
                    symbol=row["symbol"].strip().upper(),
                    action_type=row["action_type"].strip().lower(),
                    effective_date=row["effective_date"].strip(),
                    ratio=ratio,
                    acquirer=acquirer,
                )
            )
    return actions


def adjust_prices_for_splits(
    ohlcv_df: pd.DataFrame,
    actions: list[CorporateAction],
) -> pd.DataFrame:
    """Adjust pre-split OHLCV prices by 1/ratio and volume by ratio.

    Only processes actions with action_type == "split".
    Only adjusts rows where Date < effective_date for matching symbol.
    Returns a new DataFrame (does not modify in place).
    """
    if not actions or ohlcv_df.empty:
        return ohlcv_df.copy()

    df = ohlcv_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])

    price_cols = [c for c in ("Open", "High", "Low", "Close") if c in df.columns]

    for action in actions:
        if action.action_type != "split" or action.ratio is None:
            continue

        effective = pd.Timestamp(action.effective_date)
        mask = (df["Ticker"].str.upper() == action.symbol) & (df["Date"] < effective)

        if not mask.any():
            continue

        adjustment = 1.0 / action.ratio
        for col in price_cols:
            df.loc[mask, col] = df.loc[mask, col] * adjustment

        if "Volume" in df.columns:
            df.loc[mask, "Volume"] = df.loc[mask, "Volume"] * action.ratio

    return df


def get_delistings(
    actions: list[CorporateAction],
    as_of_date: str | None = None,
) -> list[str]:
    """Return symbols delisted on or before as_of_date.

    If as_of_date is None, returns all delisted symbols.
    """
    result = []
    for a in actions:
        if a.action_type != "delisting":
            continue
        if as_of_date is None or a.effective_date <= as_of_date:
            result.append(a.symbol)
    return result
