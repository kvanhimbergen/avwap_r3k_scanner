"""Point-in-time feature readers — never return future data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from feature_store.versioning import get_store_path, list_available_dates


def _latest_date_on_or_before(dates: list[str], as_of_date: str) -> str | None:
    """Return the latest date string <= as_of_date, or None."""
    candidates = [d for d in dates if d <= as_of_date]
    return candidates[-1] if candidates else None


def read_features(
    base_dir: Path,
    feature_type: str,
    as_of_date: str,
    version: int | None = None,
) -> pd.DataFrame:
    """Read features for *feature_type* as of *as_of_date* (point-in-time).

    Returns the latest partition where date <= as_of_date.
    Returns an empty DataFrame if no qualifying partition exists.
    """
    dates = list_available_dates(base_dir, feature_type, version)
    match = _latest_date_on_or_before(dates, as_of_date)
    if match is None:
        return pd.DataFrame()

    store = get_store_path(base_dir, version)
    parquet_path = store / match / f"{feature_type}.parquet"
    if not parquet_path.exists():
        return pd.DataFrame()

    return pd.read_parquet(parquet_path, engine="pyarrow")


def read_feature_meta(
    base_dir: Path,
    feature_type: str,
    as_of_date: str,
    version: int | None = None,
) -> dict:
    """Return the _meta.json for the partition matched by point-in-time lookup."""
    dates = list_available_dates(base_dir, feature_type, version)
    match = _latest_date_on_or_before(dates, as_of_date)
    if match is None:
        return {}

    store = get_store_path(base_dir, version)
    meta_path = store / match / "_meta.json"
    if not meta_path.exists():
        return {}

    with open(meta_path, "r") as f:
        return json.load(f)
