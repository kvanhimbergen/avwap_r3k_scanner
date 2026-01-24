from __future__ import annotations

from pathlib import Path

import pandas as pd

from analytics.regime_e1_runner import run_regime_e1


def _write_history(path: Path) -> None:
    history = pd.DataFrame(
        {
            "Date": ["2024-01-04", "2024-01-05"],
            "Ticker": ["SPY", "SPY"],
            "Close": [470.0, 472.0],
        }
    )
    history.to_parquet(path, index=False)


def test_resolves_weekend_to_last_trading_day(tmp_path: Path) -> None:
    history_path = tmp_path / "history.parquet"
    _write_history(history_path)

    result = run_regime_e1(
        repo_root=tmp_path,
        ny_date="2024-01-06",
        as_of_utc="2024-01-06T16:00:00+00:00",
        history_path=history_path,
    )

    record = result["record"]
    assert record["requested_ny_date"] == "2024-01-06"
    assert record["resolved_ny_date"] == "2024-01-05"
    assert "resolved_to_last_trading_day" in record["reason_codes"]
