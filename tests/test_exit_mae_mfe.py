from datetime import datetime, timezone

from analytics.exit_metrics import compute_mae_mfe


def test_mae_mfe_calculation_long():
    entry_ts = "2024-01-02T14:00:00+00:00"
    exit_ts = "2024-01-02T15:00:00+00:00"
    bars = [
        {
            "ts": datetime(2024, 1, 2, 14, 10, tzinfo=timezone.utc),
            "high": 102.0,
            "low": 98.0,
        },
        {
            "ts": datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            "high": 105.0,
            "low": 95.0,
        },
    ]

    mae, mfe = compute_mae_mfe(
        entry_price=100.0,
        bars=bars,
        direction="long",
        entry_ts_utc=entry_ts,
        exit_ts_utc=exit_ts,
    )

    assert mae == -5.0
    assert mfe == 5.0
