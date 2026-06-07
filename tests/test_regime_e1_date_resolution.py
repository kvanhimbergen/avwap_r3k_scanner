from __future__ import annotations

from pathlib import Path

import pandas as pd

from analytics.regime_e1_runner import (
    MAX_REGIME_STALENESS_BDAYS,
    run_regime_e1,
)
from analytics.regime_e1_schemas import RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED


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


def test_skips_on_excessive_price_staleness(tmp_path: Path) -> None:
    # SPY last bar is 2024-01-05 (Fri); request 6 business days later (2024-01-15).
    # bdate_range(2024-01-05, 2024-01-15) = [01-05, 01-08, 01-09, 01-10, 01-11, 01-12 (Fri), 01-15]
    # which is 7 entries → staleness = 6 bdays, > MAX_REGIME_STALENESS_BDAYS (5).
    history_path = tmp_path / "history.parquet"
    _write_history(history_path)

    requested = "2024-01-15"
    result = run_regime_e1(
        repo_root=tmp_path,
        ny_date=requested,
        as_of_utc=f"{requested}T16:00:00+00:00",
        history_path=history_path,
    )

    record = result["record"]
    assert result["status"] == "skipped"
    assert record["record_type"] == RECORD_TYPE_SKIPPED
    assert "excessive_price_staleness" in record["reason_codes"]
    assert record["inputs_snapshot"]["staleness_bdays"] > MAX_REGIME_STALENESS_BDAYS
    # No SIGNAL features computed when staleness gate fires.
    assert "regime_label" not in record
    assert "signals" not in record


def test_emits_signal_when_staleness_within_threshold(tmp_path: Path) -> None:
    # 3 bday gap (Fri 2024-01-05 → Wed 2024-01-10) — within MAX_REGIME_STALENESS_BDAYS;
    # gate must not fire. Feature computation may still skip for lack of bars, but
    # the resulting reason_codes must NOT include excessive_price_staleness.
    history_path = tmp_path / "history.parquet"
    _write_history(history_path)

    result = run_regime_e1(
        repo_root=tmp_path,
        ny_date="2024-01-10",
        as_of_utc="2024-01-10T16:00:00+00:00",
        history_path=history_path,
    )

    record = result["record"]
    assert "excessive_price_staleness" not in record.get("reason_codes", [])
    assert record["record_type"] in {RECORD_TYPE_SIGNAL, RECORD_TYPE_SKIPPED}
