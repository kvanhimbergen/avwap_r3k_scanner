from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from universe import (
    _clean_ishares_data,
    _download_iwv_holdings_csv,
)


def main() -> None:
    raw_text = _download_iwv_holdings_csv()
    cache_path = Path("universe/cache/iwv_holdings.csv")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(raw_text)

    df = _clean_ishares_data(raw_text)
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(
        "IWV holdings refreshed:",
        f"rows={len(df)}",
        f"unique_tickers={df['Ticker'].nunique()}",
        f"timestamp={timestamp}",
    )


if __name__ == "__main__":
    main()
