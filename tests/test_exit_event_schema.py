from datetime import datetime, timezone

from analytics.io.exit_events import parse_exit_ledger
from execution_v2.exit_events import append_exit_event, build_exit_event


def test_exit_event_schema_round_trip(tmp_path):
    event = build_exit_event(
        event_type="STOP_RESOLVED",
        symbol="ABC",
        ts=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
        source="unit_test",
        qty=100,
        stop_price=9.5,
        stop_basis="intraday_hl",
        stop_action="initial",
        entry_price=10.0,
        entry_ts_utc="2024-01-02T14:00:00+00:00",
    )

    append_exit_event(tmp_path, event)

    result = parse_exit_ledger(str(tmp_path / "ledger" / "EXIT_EVENTS" / "2024-01-02.jsonl"))
    assert result.events
    parsed = result.events[0]
    assert parsed.schema_version == 1
    assert parsed.event_type == "STOP_RESOLVED"
    assert parsed.symbol == "ABC"
    assert parsed.position_id is not None
