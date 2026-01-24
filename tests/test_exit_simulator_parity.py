from datetime import datetime, timedelta, timezone

from execution_v2.exit_simulator import simulate_exit
from execution_v2.exits import compute_intraday_higher_low_stop


def test_exit_simulator_matches_stop_logic():
    start = datetime(2024, 3, 1, 14, 0, tzinfo=timezone.utc)
    lows = [11.0, 9.0, 12.0, 10.0, 13.0, 9.0]
    highs = [12.0, 12.5, 13.0, 12.0, 14.0, 10.0]
    intraday_bars = []
    for idx, (low, high) in enumerate(zip(lows, highs)):
        intraday_bars.append(
            {
                "ts": start + timedelta(minutes=5 * idx),
                "low": low,
                "high": high,
            }
        )

    daily_bars = [
        {
            "ts": start - timedelta(days=1),
            "low": 8.5,
            "high": 13.5,
        }
    ]

    expected_stop = compute_intraday_higher_low_stop(intraday_bars, stop_buffer_dollars=0.5)

    events = simulate_exit(
        symbol="AAA",
        entry_price=12.0,
        qty=10,
        entry_ts_utc="2024-03-01T14:00:00+00:00",
        intraday_bars=intraday_bars,
        daily_bars=daily_bars,
        stop_buffer_dollars=0.5,
        min_intraday_bars=6,
        source="unit_test",
    )

    stop_events = [e for e in events if e["event_type"] == "STOP_RESOLVED"]
    exit_events = [e for e in events if e["event_type"] == "EXIT_FILLED"]

    assert stop_events
    assert stop_events[0]["stop_price"] == expected_stop
    assert exit_events
