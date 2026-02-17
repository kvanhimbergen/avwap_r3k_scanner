"""Schema versioning and store path utilities."""

from __future__ import annotations

from pathlib import Path

from feature_store.schemas import FEATURE_SCHEMAS

CURRENT_SCHEMA_VERSION: int = 1


def get_current_schema_version() -> int:
    return CURRENT_SCHEMA_VERSION


def get_store_path(base_dir: Path, version: int | None = None) -> Path:
    """Return the versioned store root: base_dir/v{version}/."""
    v = version if version is not None else CURRENT_SCHEMA_VERSION
    return base_dir / f"v{v}"


def list_available_dates(base_dir: Path, feature_type: str, version: int | None = None) -> list[str]:
    """Return sorted date strings for which *feature_type*.parquet exists."""
    store = get_store_path(base_dir, version)
    if not store.is_dir():
        return []
    dates: list[str] = []
    for child in sorted(store.iterdir()):
        if child.is_dir() and (child / f"{feature_type}.parquet").exists():
            dates.append(child.name)
    return dates
