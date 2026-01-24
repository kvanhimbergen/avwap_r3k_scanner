from datetime import datetime, timezone

from execution_v2.exit_events import build_exit_event, serialize_exit_event


def test_exit_event_serialization_determinism():
    event = build_exit_event(
        event_type="STOP_RATCHET",
        symbol="XYZ",
        ts=datetime(2024, 2, 1, 15, 0, tzinfo=timezone.utc),
        source="unit_test",
        qty=50,
        stop_price=12.34,
        stop_basis="daily_swing_low",
        stop_action="ratchet",
        entry_price=12.5,
        entry_ts_utc="2024-02-01T14:00:00+00:00",
    )

    first = serialize_exit_event(event)
    second = serialize_exit_event(event)

    assert first == second
