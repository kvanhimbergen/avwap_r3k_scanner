from datetime import datetime, timedelta, timezone

from execution_v2 import state_machine


def test_exit_not_armed_immediately_after_entry():
    now = datetime.now(timezone.utc)
    entry_ts = now.isoformat()
    assert state_machine.is_exit_armed(
        entry_fill_ts_utc=entry_ts,
        now_utc=now,
        min_seconds=120,
        closed_10m_bars=[],
    ) is False


def test_exit_armed_after_bar_or_delay():
    now = datetime.now(timezone.utc)
    entry_ts = (now - timedelta(seconds=600)).isoformat()
    closed_bars = [{"ts": (now - timedelta(seconds=1)).timestamp()}]
    assert state_machine.is_exit_armed(
        entry_fill_ts_utc=entry_ts,
        now_utc=now,
        min_seconds=120,
        closed_10m_bars=closed_bars,
    ) is True
