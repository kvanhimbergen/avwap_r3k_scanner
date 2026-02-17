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
