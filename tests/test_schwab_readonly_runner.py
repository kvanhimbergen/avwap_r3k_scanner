from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import analytics.schwab_readonly_runner as runner
from analytics.schwab_readonly_runner import (
    SchwabReadonlyRunResult,
    run_snapshot_and_reconciliation,
)

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schwab_readonly"


def _enabled_config(token_path: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        token_path=token_path or Path("/tmp/fake-token.json"),
        app_key="key",
        app_secret="secret",
        callback_url="https://localhost/callback",
        account_hash="hash",
    )


# ---------------------------------------------------------------------------
# CLI argument validation: --live and --fixture-dir are mutually exclusive
# ---------------------------------------------------------------------------

def test_main_requires_live_or_fixture_dir(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["schwab_readonly_runner"])
    with pytest.raises(SystemExit) as excinfo:
        runner.main()
    # argparse exits with 2 on missing required mutually-exclusive group.
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "one of the arguments" in err or "required" in err


def test_main_rejects_live_and_fixture_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["schwab_readonly_runner", "--live", "--fixture-dir", str(_FIXTURE_DIR)],
    )
    with pytest.raises(SystemExit) as excinfo:
        runner.main()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not allowed" in err.lower() or "argument" in err.lower()


# ---------------------------------------------------------------------------
# Fixture mode happy path
# ---------------------------------------------------------------------------

def test_fixture_mode_writes_snapshots_and_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "load_schwab_readonly_oauth_config", lambda: _enabled_config()
    )

    result = run_snapshot_and_reconciliation(
        repo_root=tmp_path,
        fixture_dir=_FIXTURE_DIR,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
        ny_date="2026-01-20",
        require_enabled=True,
        live=False,
    )

    assert isinstance(result, SchwabReadonlyRunResult)
    assert result.snapshots_written > 0
    assert Path(result.ledger_path).exists()
    assert result.reconciliation_written is True


def test_fixture_mode_requires_fixture_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "load_schwab_readonly_oauth_config", lambda: _enabled_config()
    )
    with pytest.raises(RuntimeError, match="fixture_dir required"):
        run_snapshot_and_reconciliation(
            repo_root=tmp_path,
            fixture_dir=None,
            book_id="SCHWAB_401K_MANUAL",
            as_of_utc="2026-01-20T16:00:00+00:00",
            require_enabled=True,
            live=False,
        )


# ---------------------------------------------------------------------------
# Enablement gate
# ---------------------------------------------------------------------------

def test_disabled_config_raises_when_require_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disabled = SimpleNamespace(
        enabled=False,
        token_path=Path("/tmp/x"),
        app_key="",
        app_secret="",
        callback_url="",
        account_hash="",
    )
    monkeypatch.setattr(runner, "load_schwab_readonly_oauth_config", lambda: disabled)

    with pytest.raises(RuntimeError, match="SCHWAB_READONLY_ENABLED"):
        run_snapshot_and_reconciliation(
            repo_root=tmp_path,
            fixture_dir=_FIXTURE_DIR,
            book_id="SCHWAB_401K_MANUAL",
            as_of_utc="2026-01-20T16:00:00+00:00",
            require_enabled=True,
            live=False,
        )


def test_ny_date_mismatch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "load_schwab_readonly_oauth_config", lambda: _enabled_config()
    )
    with pytest.raises(RuntimeError, match="ny_date does not match"):
        run_snapshot_and_reconciliation(
            repo_root=tmp_path,
            fixture_dir=_FIXTURE_DIR,
            book_id="SCHWAB_401K_MANUAL",
            as_of_utc="2026-01-20T16:00:00+00:00",
            ny_date="2026-01-22",  # mismatch
            require_enabled=True,
            live=False,
        )


# ---------------------------------------------------------------------------
# Live mode token health gate
# ---------------------------------------------------------------------------

def test_live_mode_aborts_when_token_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "load_schwab_readonly_oauth_config", lambda: _enabled_config()
    )

    class _StubHealth:
        healthy = False
        reason = "missing token file"
        days_until_expiry = 0.0

    def _fake_health(_path: Any) -> _StubHealth:
        return _StubHealth()

    # The live-mode import is in-function; monkeypatch the module before it
    # gets imported by run_snapshot_and_reconciliation.
    import analytics.schwab_token_health as token_health

    monkeypatch.setattr(token_health, "check_token_health", _fake_health)

    with pytest.raises(RuntimeError, match="Schwab token unhealthy"):
        run_snapshot_and_reconciliation(
            repo_root=tmp_path,
            book_id="SCHWAB_401K_MANUAL",
            as_of_utc="2026-01-20T16:00:00+00:00",
            require_enabled=True,
            live=True,
        )


def _stub_live_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the live adapter with a stub that aborts after the token check."""
    import analytics.schwab_readonly_live_adapter as live_adapter

    class _StubAdapter:
        @classmethod
        def from_config(cls, *args: Any, **kwargs: Any) -> "_StubAdapter":
            return cls()

        def load_all_snapshots(self) -> tuple:
            raise RuntimeError("stop_after_token_check")

    monkeypatch.setattr(live_adapter, "SchwabReadonlyLiveAdapter", _StubAdapter)


def _run_live_with_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    days_until_expiry: float,
) -> list[dict[str, Any]]:
    """Drive run_snapshot_and_reconciliation with a stubbed token-health value.

    Returns the captured slack_alert calls.
    """
    monkeypatch.setattr(
        runner, "load_schwab_readonly_oauth_config", lambda: _enabled_config()
    )

    class _StubHealth:
        healthy = True
        reason = "ok"

    _StubHealth.days_until_expiry = days_until_expiry

    import analytics.schwab_token_health as token_health

    monkeypatch.setattr(token_health, "check_token_health", lambda _p: _StubHealth())
    _stub_live_adapter(monkeypatch)

    alerts: list[dict[str, Any]] = []

    def _capture(level: str, title: str, message: str, **kwargs: Any) -> None:
        alerts.append({"level": level, "title": title, "message": message, **kwargs})

    monkeypatch.setattr(runner, "slack_alert", _capture)

    with pytest.raises(RuntimeError, match="stop_after_token_check"):
        run_snapshot_and_reconciliation(
            repo_root=tmp_path,
            book_id="SCHWAB_401K_MANUAL",
            as_of_utc="2026-01-20T16:00:00+00:00",
            require_enabled=True,
            live=True,
        )

    return alerts


def test_live_mode_warns_via_slack_at_under_2_days(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alerts = _run_live_with_health(tmp_path, monkeypatch, days_until_expiry=1.5)

    assert len(alerts) == 1
    assert alerts[0]["level"] == "WARNING"
    assert "expires in 1.5 days" in alerts[0]["message"]
    assert "schwab_auth" in alerts[0]["message"]
    # The stderr printout is preserved for log scrapers.
    assert "WARNING:" in capsys.readouterr().out


def test_live_mode_escalates_to_error_at_under_1_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts = _run_live_with_health(tmp_path, monkeypatch, days_until_expiry=0.5)

    assert len(alerts) == 1
    assert alerts[0]["level"] == "ERROR"
    assert "expires in 0.5 days" in alerts[0]["message"]


def test_live_mode_does_not_alert_when_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts = _run_live_with_health(tmp_path, monkeypatch, days_until_expiry=5.0)
    assert alerts == []
