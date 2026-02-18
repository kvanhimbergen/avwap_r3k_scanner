"""Point-in-time historical R3K constituency loading.

Looks up dated CSV files in a directory (default: universe/historical/)
and returns the most recent snapshot where file_date <= requested date.
"""

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent / "historical"


def _parse_date_from_filename(filename: str) -> str | None:
    """Extract YYYY-MM-DD from a filename like '2024-06-15.csv'."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})\.csv$", filename)
    return m.group(1) if m else None


def list_available_dates(constituency_path: str | Path | None = None) -> list[str]:
    """Return sorted list of available historical snapshot dates."""
    path = Path(constituency_path) if constituency_path else _DEFAULT_PATH
    if not path.is_dir():
        return []
    dates = []
    for f in path.iterdir():
        d = _parse_date_from_filename(f.name)
        if d is not None:
            dates.append(d)
    return sorted(dates)


def load_universe_as_of(
    date_str: str,
    constituency_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load R3K universe membership as of a specific date (point-in-time).

    Finds the most recent CSV file where file_date <= date_str.
    Falls back to current universe with a warning if no historical data exists.
    """
    path = Path(constituency_path) if constituency_path else _DEFAULT_PATH
    available = list_available_dates(path)

    # Find most recent file where file_date <= requested date
    best = None
    for d in available:
        if d <= date_str:
            best = d

    if best is None:
        logger.warning(
            "No historical constituency data available for %s (path=%s). "
            "Falling back to current universe.",
            date_str,
            path,
        )
        from universe import load_r3k_universe_from_iwv

        return load_r3k_universe_from_iwv(allow_network=False)

    csv_path = path / f"{best}.csv"
    df = pd.read_csv(csv_path)

    # Standardize columns
    df.columns = [c.strip() for c in df.columns]
    expected = {"Ticker", "Sector", "Weight"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(
            f"Historical constituency CSV {csv_path} missing columns: {missing}"
        )

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    return df.reset_index(drop=True)
