from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from config import cfg
from universe import _clean_ishares_data, _download_iwv_holdings_csv

DEFAULT_SNAPSHOT_PATH = "universe/snapshots/iwv_holdings_latest.csv"


def main() -> None:
    raw_text = _download_iwv_holdings_csv()
    snapshot_path = Path(
        getattr(cfg, "UNIVERSE_SNAPSHOT_PATH", None) or DEFAULT_SNAPSHOT_PATH
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(raw_text)

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
