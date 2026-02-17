"""High-level FeatureStore facade wrapping readers/writers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from feature_store.readers import read_feature_meta, read_features
from feature_store.versioning import get_current_schema_version, list_available_dates
from feature_store.writers import write_feature_partition

_DEFAULT_BASE_DIR = Path("feature_store_data")


class FeatureStore:
    """Versioned, point-in-time-correct feature store.

    Parameters
    ----------
    base_dir : Path
        Root directory for all partitions.
    schema_version : int | None
        Override schema version (defaults to current).
    """

    def __init__(
        self,
        base_dir: Path | str = _DEFAULT_BASE_DIR,
        schema_version: int | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.schema_version = schema_version or get_current_schema_version()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(
        self,
        date: str,
        feature_type: str,
        df: pd.DataFrame,
        meta: dict | None = None,
    ) -> Path:
        """Write a feature partition atomically."""
        return write_feature_partition(
            base_dir=self.base_dir,
            date_str=date,
            feature_type=feature_type,
            df=df,
            meta=meta,
            version=self.schema_version,
        )

    # ------------------------------------------------------------------
    # Read (point-in-time)
    # ------------------------------------------------------------------

    def read(self, feature_type: str, as_of_date: str) -> pd.DataFrame:
        """Read features with point-in-time enforcement (never future data)."""
        return read_features(
            base_dir=self.base_dir,
            feature_type=feature_type,
            as_of_date=as_of_date,
            version=self.schema_version,
        )

    def read_meta(self, feature_type: str, as_of_date: str) -> dict:
        """Read the provenance sidecar for the matched partition."""
        return read_feature_meta(
            base_dir=self.base_dir,
            feature_type=feature_type,
            as_of_date=as_of_date,
            version=self.schema_version,
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def available_dates(self, feature_type: str) -> list[str]:
        """List all date partitions for a given feature type."""
        return list_available_dates(
            base_dir=self.base_dir,
            feature_type=feature_type,
            version=self.schema_version,
        )
