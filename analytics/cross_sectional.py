"""Cross-sectional scoring: z-scores, percentile ranks, and composite ranking.

Replaces absolute thresholds with universe-relative rankings.
"Top-decile today" replaces "above 5.0".  Absolute thresholds remain as
hard safety floors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_z_scores(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Compute z-scores for *columns* in *df*.

    Returns a new DataFrame with columns named ``{col}_Zscore``.

    Edge cases:
    - ``std == 0`` or ``len(df) <= 1`` → all z-scores = 0.0
    - NaN values excluded from mean/std; NaN z-scores filled with 0.0
    """
    out = pd.DataFrame(index=df.index)
    for col in columns:
        if col not in df.columns:
            out[f"{col}_Zscore"] = 0.0
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if len(series) <= 1:
            out[f"{col}_Zscore"] = 0.0
            continue
        mean = series.mean(skipna=True)
        std = series.std(skipna=True, ddof=1)
        if std is None or np.isnan(std) or std == 0:
            out[f"{col}_Zscore"] = 0.0
        else:
            out[f"{col}_Zscore"] = ((series - mean) / std).fillna(0.0)
    return out


def compute_percentile_ranks(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Compute percentile rank (0.0–1.0) for *columns* using ``rank(pct=True)``.

    Returns a new DataFrame with columns named ``{col}_Pctile``.
    """
    out = pd.DataFrame(index=df.index)
    for col in columns:
        if col not in df.columns:
            out[f"{col}_Pctile"] = np.nan
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        out[f"{col}_Pctile"] = series.rank(pct=True, na_option="keep")
    return out


def composite_rank(
    trend_z: float,
    dist_z: float,
    slope_z: float,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute a single composite rank score.

    ``dist_pct`` is *inverted*: closer to AVWAP (lower dist) = better,
    hence the subtraction.

    Default weights: trend 0.4, dist 0.3, slope 0.3.
    """
    w = weights or {"trend": 0.4, "dist": 0.3, "slope": 0.3}
    return w["trend"] * trend_z - w["dist"] * dist_z + w["slope"] * slope_z


_DEFAULT_FEATURES = ["TrendScore", "Entry_DistPct", "AVWAP_Slope"]


def apply_cross_sectional_scoring(
    candidates_df: pd.DataFrame,
    features: list[str] | None = None,
    top_decile: float = 0.1,
    hard_floor_trend: float = 5.0,
) -> pd.DataFrame:
    """Score, rank, and filter a day's candidates cross-sectionally.

    Steps:
    1. Compute z-scores and percentile ranks for *features*.
    2. Compute ``Composite_Rank`` per row.
    3. Enforce *hard_floor_trend* (drop any candidate below it).
    4. Keep top *top_decile* fraction by ``Composite_Rank``.

    Returns an enriched DataFrame with new columns:
    ``TrendScore_Zscore``, ``TrendScore_Pctile``, ``DistPct_Zscore``,
    ``Composite_Rank``.

    If the input has <= 1 row, z-scores are 0 and no filtering is applied
    (fall back to absolute thresholds upstream).
    """
    if features is None:
        features = list(_DEFAULT_FEATURES)

    if candidates_df.empty:
        for col in ("TrendScore_Zscore", "TrendScore_Pctile", "DistPct_Zscore", "Composite_Rank"):
            candidates_df[col] = pd.Series(dtype="float64")
        return candidates_df

    df = candidates_df.copy()

    # --- z-scores ---
    zscores = compute_z_scores(df, features)
    for zcol in zscores.columns:
        df[zcol] = zscores[zcol].values

    # --- percentile ranks ---
    pctiles = compute_percentile_ranks(df, features)
    for pcol in pctiles.columns:
        df[pcol] = pctiles[pcol].values

    # --- composite rank ---
    trend_z = df.get("TrendScore_Zscore", pd.Series(0.0, index=df.index))
    dist_z = df.get("Entry_DistPct_Zscore", pd.Series(0.0, index=df.index))
    slope_z = df.get("AVWAP_Slope_Zscore", pd.Series(0.0, index=df.index))

    df["Composite_Rank"] = [
        composite_rank(float(t), float(d), float(s))
        for t, d, s in zip(trend_z, dist_z, slope_z)
    ]

    # --- rename z/pctile columns to spec names ---
    rename_map = {}
    if "Entry_DistPct_Zscore" in df.columns:
        rename_map["Entry_DistPct_Zscore"] = "DistPct_Zscore"
    if "Entry_DistPct_Pctile" in df.columns:
        rename_map["Entry_DistPct_Pctile"] = "DistPct_Pctile"
    if rename_map:
        df = df.rename(columns=rename_map)

    # --- hard floor: remove candidates below trend score floor ---
    if "TrendScore" in df.columns:
        df = df[pd.to_numeric(df["TrendScore"], errors="coerce").fillna(0.0) >= hard_floor_trend]

    # --- top decile filter ---
    if len(df) > 1:
        cutoff = df["Composite_Rank"].quantile(1.0 - top_decile)
        df = df[df["Composite_Rank"] >= cutoff]

    return df.reset_index(drop=True)
