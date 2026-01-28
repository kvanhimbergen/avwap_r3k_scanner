import sys
from datetime import datetime
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import clocks
from execution_v2 import execution_main


def test_resolve_poll_seconds_tight_window(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_SECONDS", "12")
    monkeypatch.setenv("EXECUTION_POLL_MARKET_SECONDS", "45")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_START_ET", "09:30")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_END_ET", "10:05")
    cfg = SimpleNamespace(poll_seconds=300)
    now_et = datetime(2024, 1, 2, 9, 45, tzinfo=clocks.ET)

    assert execution_main.resolve_poll_seconds(cfg, now_et=now_et) == 12


def test_resolve_poll_seconds_market_window(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_SECONDS", "12")
    monkeypatch.setenv("EXECUTION_POLL_MARKET_SECONDS", "45")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_START_ET", "09:30")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_END_ET", "10:05")
    cfg = SimpleNamespace(poll_seconds=300)
    now_et = datetime(2024, 1, 2, 11, 0, tzinfo=clocks.ET)

    assert execution_main.resolve_poll_seconds(cfg, now_et=now_et) == 45


def test_resolve_poll_seconds_outside_market(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_SECONDS", "12")
    monkeypatch.setenv("EXECUTION_POLL_MARKET_SECONDS", "45")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_START_ET", "09:30")
    monkeypatch.setenv("EXECUTION_POLL_TIGHT_END_ET", "10:05")
    cfg = SimpleNamespace(poll_seconds=300)
    now_et = datetime(2024, 1, 2, 8, 0, tzinfo=clocks.ET)

    assert execution_main.resolve_poll_seconds(cfg, now_et=now_et) == 300
