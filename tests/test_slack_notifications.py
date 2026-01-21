import json
import sys
import types


requests_stub = types.SimpleNamespace(
    post=lambda *args, **kwargs: types.SimpleNamespace(status_code=200, text="ok")
)
sys.modules.setdefault("requests", requests_stub)

import alerts.slack as slack


def _set_env(monkeypatch, **values) -> None:
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))


def test_build_dry_run_daily_summary(tmp_path):
    ledger_path = tmp_path / "dry_run_ledger.json"
    ledger = {
        "2026-01-20:AAPL": {"symbol": "AAPL", "qty": 10, "ts": "2026-01-20T15:00:00Z"},
        "2026-01-20:MSFT": {"symbol": "MSFT", "qty": 5, "ts": "2026-01-20T15:10:00Z"},
        "2026-01-19:TSLA": {"symbol": "TSLA", "qty": 50, "ts": "2026-01-19T15:10:00Z"},
    }
    ledger_path.write_text(json.dumps(ledger))

    summary = slack.build_dry_run_daily_summary(str(ledger_path), "2026-01-20")

    assert "Date (NY): 2026-01-20" in summary
    assert "Total simulated submissions: 2" in summary
    assert "Unique symbols: 2" in summary
    assert "- AAPL: 10" in summary
    assert "- MSFT: 5" in summary


def test_heartbeat_rate_limit(monkeypatch, tmp_path):
    posted = []

    class DummyThread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            self.target()

    times = iter([10000.0, 10001.0])

    monkeypatch.setattr(slack.time, "time", lambda: next(times))
    monkeypatch.setattr(slack.threading, "Thread", DummyThread)
    monkeypatch.setattr(slack, "_post", lambda payload: posted.append(payload))
    monkeypatch.setattr(slack, "check_watchlist_freshness", lambda: (True, "fresh"))
    monkeypatch.setattr(slack, "_enabled", lambda: True)
    monkeypatch.setattr(slack, "_min_level_ok", lambda level: True)
    slack._LAST_TS.clear()

    _set_env(
        monkeypatch,
        SLACK_WEBHOOK_URL="https://example.com",
        SLACK_ENABLED="1",
        SLACK_HEARTBEAT_MINUTES="60",
        SLACK_ALERTS_MIN_LEVEL="INFO",
    )

    slack.maybe_send_heartbeat(dry_run=True, market_open=True)
    slack.maybe_send_heartbeat(dry_run=True, market_open=True)

    assert len(posted) == 1


def test_verbose_alert_default_off(monkeypatch):
    called = []
    monkeypatch.setattr(slack, "slack_alert", lambda *args, **kwargs: called.append((args, kwargs)))
    _set_env(monkeypatch, SLACK_VERBOSE=None)

    slack.send_verbose_alert("INFO", "test", "message")

    assert called == []


def test_slack_alert_no_webhook_no_throw(monkeypatch):
    _set_env(monkeypatch, SLACK_WEBHOOK_URL=None, SLACK_ENABLED=None, SLACK_ALERTS_ENABLED=None)
    slack.slack_alert("INFO", "noop", "noop")
