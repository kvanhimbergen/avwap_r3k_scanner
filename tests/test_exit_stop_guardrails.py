from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from execution_v2.exits import (
    ExitConfig,
    SessionPhase,
    classify_session_phase,
    select_stop_candidate,
)

NY_TZ = ZoneInfo("America/New_York")


def _bar_ts_list(start: datetime, count: int, step_minutes: int = 5):
    bars = []
    for i in range(count):
        bars.append({"ts": start + timedelta(minutes=step_minutes * (i + 1))})
    return bars


def test_classify_session_phase_boundaries():
    assert classify_session_phase(datetime(2024, 1, 2, 9, 30, tzinfo=NY_TZ)) == SessionPhase.OPEN_NOISE
    assert classify_session_phase(datetime(2024, 1, 2, 9, 45, tzinfo=NY_TZ)) == SessionPhase.EARLY_TREND
    assert (
        classify_session_phase(datetime(2024, 1, 2, 10, 30, tzinfo=NY_TZ))
        == SessionPhase.NORMAL_SESSION
    )
    assert (
        classify_session_phase(datetime(2024, 1, 2, 15, 30, tzinfo=NY_TZ))
        == SessionPhase.CLOSE_PROTECT
    )
    assert classify_session_phase(datetime(2024, 1, 2, 16, 0, tzinfo=NY_TZ)) == SessionPhase.OPEN_NOISE


def test_open_noise_forbids_intraday_stop():
    now_utc = datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc)
    events = []
    candidate, basis, allow_trailing = select_stop_candidate(
        intraday_stop=98.0,
        daily_stop=92.0,
        existing_stop=None,
        entry_price=100.0,
        entry_ts=now_utc - timedelta(minutes=30),
        intraday_bars=_bar_ts_list(now_utc - timedelta(minutes=30), 6),
        now_utc=now_utc,
        cfg=ExitConfig(),
        phase=SessionPhase.OPEN_NOISE,
        symbol="AAA",
        qty=10,
        source="test",
        emit_event=events.append,
    )

    assert candidate == 92.0
    assert basis == "daily_swing_low"
    assert allow_trailing is False


def test_min_stop_pct_rejects_too_close():
    now_utc = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    events = []
    candidate, basis, _ = select_stop_candidate(
        intraday_stop=None,
        daily_stop=99.0,
        existing_stop=None,
        entry_price=100.0,
        entry_ts=now_utc - timedelta(minutes=30),
        intraday_bars=[],
        now_utc=now_utc,
        cfg=ExitConfig(),
        phase=SessionPhase.NORMAL_SESSION,
        symbol="BBB",
        qty=10,
        source="test",
        emit_event=events.append,
    )

    assert candidate is None
    assert basis is None
    assert events
    assert events[0]["event_type"] == "STOP_TOO_CLOSE_SKIPPED"


def test_intraday_guardrails_delay_and_bars():
    now_utc = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    cfg = ExitConfig()
    events = []
    candidate, basis, _ = select_stop_candidate(
        intraday_stop=95.0,
        daily_stop=None,
        existing_stop=None,
        entry_price=100.0,
        entry_ts=now_utc - timedelta(minutes=5),
        intraday_bars=_bar_ts_list(now_utc - timedelta(minutes=5), 2),
        now_utc=now_utc,
        cfg=cfg,
        phase=SessionPhase.NORMAL_SESSION,
        symbol="CCC",
        qty=10,
        source="test",
        emit_event=events.append,
    )

    assert candidate is None
    assert basis is None
    assert events
    assert events[0]["event_type"] == "STOP_TOO_EARLY_SKIPPED"

    events.clear()
    candidate, basis, _ = select_stop_candidate(
        intraday_stop=95.0,
        daily_stop=None,
        existing_stop=None,
        entry_price=100.0,
        entry_ts=now_utc - timedelta(minutes=30),
        intraday_bars=_bar_ts_list(now_utc - timedelta(minutes=30), 4),
        now_utc=now_utc,
        cfg=cfg,
        phase=SessionPhase.NORMAL_SESSION,
        symbol="DDD",
        qty=10,
        source="test",
        emit_event=events.append,
    )

    assert candidate == 95.0
    assert basis == "intraday_hl"
    assert not events


def test_matching_stop_order_handles_enumish_strings():
    # Alpaca SDK objects often stringify enums like "OrderSide.SELL", "OrderType.STOP", "OrderStatus.NEW".
    # Our helpers should normalize these so existing stops are recognized and not re-submitted.
    from execution_v2.exits import _matching_stop_order

    order = {
        "symbol": "IMNM",
        "side": "OrderSide.SELL",
        "type": "OrderType.STOP",
        "status": "OrderStatus.NEW",
        "qty": "32",
        "stop_price": "23.57",
    }
    assert _matching_stop_order(order, "IMNM", 32, 23.57) is True
