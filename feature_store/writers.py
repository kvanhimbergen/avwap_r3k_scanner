"""Atomic Parquet + meta writers for feature store partitions."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from feature_store.schemas import schema_version_for
from feature_store.versioning import get_store_path
from provenance import git_sha


def write_feature_partition(
    base_dir: Path,
    date_str: str,
    feature_type: str,
    df: pd.DataFrame,
    meta: dict | None = None,
    version: int | None = None,
) -> Path:
    """Write a feature partition atomically.

    Layout: base_dir/v{version}/{date_str}/{feature_type}.parquet
    Sidecar: base_dir/v{version}/{date_str}/_meta.json

    Returns the path to the written parquet file.
    """
    sv = schema_version_for(feature_type)
    store = get_store_path(base_dir, version)
    partition_dir = store / date_str
    os.makedirs(partition_dir, exist_ok=True)

    parquet_path = partition_dir / f"{feature_type}.parquet"
    tmp_parquet = parquet_path.with_suffix(".parquet.tmp")

    # Atomic parquet write
    df.to_parquet(tmp_parquet, index=False, engine="pyarrow", compression="snappy")
    os.replace(tmp_parquet, parquet_path)

    # Build and write meta sidecar
    meta_payload = {
        "schema_version": sv,
        "git_sha": git_sha(),
        "feature_type": feature_type,
        "date": date_str,
        "row_count": len(df),
    }
    if meta:
        meta_payload.update(meta)

    meta_path = partition_dir / "_meta.json"
    tmp_meta = meta_path.with_suffix(".json.tmp")
    with open(tmp_meta, "w") as f:
        json.dump(meta_payload, f, indent=2, sort_keys=True)
    os.replace(tmp_meta, meta_path)

    return parquet_path


def write_cross_sectional_distributions(
    base_dir: Path,
    date_str: str,
    candidates_df: pd.DataFrame,
    features: list[str],
    version: int | None = None,
) -> Path:
    """Persist daily cross-sectional distribution stats for reproducibility.

    Writes a JSON sidecar with mean, std, and percentile breakpoints
    for each feature column.

    Returns the path to the written JSON file.
    """
    import numpy as np

    store = get_store_path(base_dir, version)
    partition_dir = store / date_str
    os.makedirs(partition_dir, exist_ok=True)

    stats: dict[str, dict] = {}
    for col in features:
        if col not in candidates_df.columns:
            continue
        series = pd.to_numeric(candidates_df[col], errors="coerce").dropna()
        if series.empty:
            continue
        stats[col] = {
            "mean": float(series.mean()),
            "std": float(series.std(ddof=1)) if len(series) > 1 else 0.0,
            "count": int(len(series)),
            "min": float(series.min()),
            "p10": float(np.nanpercentile(series, 10)),
            "p25": float(np.nanpercentile(series, 25)),
            "p50": float(np.nanpercentile(series, 50)),
            "p75": float(np.nanpercentile(series, 75)),
            "p90": float(np.nanpercentile(series, 90)),
            "max": float(series.max()),
        }

    payload = {
        "date": date_str,
        "git_sha": git_sha(),
        "feature_type": "cross_sectional_distributions",
        "features": stats,
    }

    out_path = partition_dir / "cross_sectional_distributions.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp_path, out_path)
    return out_path
