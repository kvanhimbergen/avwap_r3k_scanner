"""Rolling pairwise correlation and sector exposure computation (Phase 5)."""

from __future__ import annotations

import pandas as pd


def compute_rolling_correlation(
    ohlcv_df: pd.DataFrame,
    symbols: list[str],
    lookback_days: int = 60,
) -> pd.DataFrame:
    """Compute pairwise correlation matrix of daily returns.

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        OHLCV data with a MultiIndex of (Date, Symbol) or columns
        ``Date``, ``Symbol``, ``Close``.
    symbols : list[str]
        Symbols to include in the matrix.
    lookback_days : int
        Number of trailing calendar days of data to use.

    Returns
    -------
    pd.DataFrame
        Symmetric correlation matrix with symbols as index and columns.
        Symbols with fewer than ``lookback_days // 2`` data points are excluded.
    """
    if not symbols:
        return pd.DataFrame()

    # Normalise input: accept both MultiIndex and flat column layouts.
    if isinstance(ohlcv_df.index, pd.MultiIndex):
        df = ohlcv_df.reset_index()
    else:
        df = ohlcv_df.copy()

    # Ensure standard column names exist
    col_map = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl == "date":
            col_map[c] = "date"
        elif cl == "symbol":
            col_map[c] = "symbol"
        elif cl == "close":
            col_map[c] = "close"
    df = df.rename(columns=col_map)

    if "date" not in df.columns or "symbol" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    symbols_upper = [s.upper() for s in symbols]
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[df["symbol"].isin(symbols_upper)]

    if df.empty:
        return pd.DataFrame()

    # Tail to lookback window
    max_date = df["date"].max()
    min_date = max_date - pd.Timedelta(days=lookback_days)
    df = df[df["date"] >= min_date]

    # Pivot to get close prices per symbol per date
    prices = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")

    # Drop symbols with insufficient data
    min_points = lookback_days // 2
    valid_cols = [c for c in prices.columns if prices[c].dropna().shape[0] >= min_points]
    if not valid_cols:
        return pd.DataFrame()
    prices = prices[valid_cols]

    # Daily returns
    returns = prices.pct_change().dropna(how="all")

    # Pairwise correlation
    corr = returns.corr()
    return corr


def get_sector_exposure(
    open_positions: list[dict],
    candidate_sector: str | None,
    sector_map: dict[str, str],
) -> dict:
    """Compute current and projected sector exposure.

    Parameters
    ----------
    open_positions : list[dict]
        Each dict must have at least ``symbol`` and ``notional`` keys.
    candidate_sector : str | None
        The sector of the candidate being evaluated.
    sector_map : dict[str, str]
        Mapping of symbol -> sector.

    Returns
    -------
    dict with keys ``sector``, ``current_exposure_pct``, ``would_be_exposure_pct``.
    """
    if not candidate_sector:
        return {
            "sector": candidate_sector or "",
            "current_exposure_pct": 0.0,
            "would_be_exposure_pct": 0.0,
        }

    total_notional = sum(abs(float(p.get("notional", 0.0))) for p in open_positions)

    sector_notional = 0.0
    for p in open_positions:
        sym = str(p.get("symbol", "")).upper()
        pos_sector = sector_map.get(sym, "")
        if pos_sector == candidate_sector:
            sector_notional += abs(float(p.get("notional", 0.0)))

    if total_notional <= 0:
        return {
            "sector": candidate_sector,
            "current_exposure_pct": 0.0,
            "would_be_exposure_pct": 1.0,
        }

    current_pct = sector_notional / total_notional

    # Estimate: assume candidate adds roughly the average position size
    avg_position = total_notional / max(len(open_positions), 1)
    new_total = total_notional + avg_position
    would_be_pct = (sector_notional + avg_position) / new_total

    return {
        "sector": candidate_sector,
        "current_exposure_pct": current_pct,
        "would_be_exposure_pct": would_be_pct,
    }
