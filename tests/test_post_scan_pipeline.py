from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import ops.post_scan_pipeline as pipeline


def _make_completed(returncode: int) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode)


class _SlackCapture:
    """Record every slack_alert call for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, level: str, title: str, message: str, *, component: str) -> None:
        self.calls.append(
            {"level": level, "title": title, "message": message, "component": component}
        )


@pytest.fixture
def slack(monkeypatch: pytest.MonkeyPatch) -> _SlackCapture:
    capture = _SlackCapture()
    monkeypatch.setattr(pipeline, "slack_alert", capture)
    return capture


@pytest.fixture
def fresh_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_scan_output_fresh", lambda _date: True)


def _patch_subprocess(monkeypatch: pytest.MonkeyPatch, returncodes: list[int]) -> list[list[str]]:
    """Replace subprocess.run with a stub that returns the supplied exit codes in order.

    Returns the list of captured commands so tests can assert on what ran.
    """
    captured: list[list[str]] = []
    iterator = iter(returncodes)

    def _fake_run(cmd: list[str], check: bool = False) -> SimpleNamespace:  # noqa: ARG001
        captured.append(list(cmd))
        try:
            return _make_completed(next(iterator))
        except StopIteration:
            raise AssertionError("subprocess.run called more times than expected returncodes")

    monkeypatch.setattr(pipeline.subprocess, "run", _fake_run)
    return captured


def test_pipeline_success_notifies_ok(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture, fresh_scan: None
) -> None:
    _patch_subprocess(monkeypatch, [0] * len(pipeline.STEPS))

    pipeline.run_pipeline("2026-06-05", dry_run=False)

    assert len(slack.calls) == 1
    call = slack.calls[0]
    assert call["level"] == "INFO"
    assert call["title"] == "Post-scan pipeline OK"
    assert f"ok={len(pipeline.STEPS)}/{len(pipeline.STEPS)}" in call["message"]
    assert "skipped" not in call["message"]


def test_pipeline_mandatory_failure_notifies_error_and_exits(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture, fresh_scan: None
) -> None:
    # Steps in order: [regime_e1, regime_throttle, schwab_sync(opt), schwab_seed(opt),
    #                  s2_aggro, s2_alpaca(opt), raec_coord].
    # Fail step 1 (mandatory).
    returncodes = [3]
    _patch_subprocess(monkeypatch, returncodes)

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_pipeline("2026-06-05", dry_run=False)

    assert excinfo.value.code == 3
    assert len(slack.calls) == 1
    call = slack.calls[0]
    assert call["level"] == "ERROR"
    assert call["title"] == "Post-scan pipeline FAILED"
    assert "regime_e1_runner" in call["message"]
    assert "exit_code=3" in call["message"]


def test_pipeline_optional_failure_continues_and_reports_in_summary(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture, fresh_scan: None
) -> None:
    # All steps succeed except step 3 (schwab_readonly_sync, optional).
    # Build dynamically — the pipeline grows over time as new steps are added.
    schwab_idx = next(
        i for i, s in enumerate(pipeline.STEPS) if s["name"] == "schwab_readonly_sync"
    )
    returncodes = [0] * len(pipeline.STEPS)
    returncodes[schwab_idx] = 5
    assert len(returncodes) == len(pipeline.STEPS)
    _patch_subprocess(monkeypatch, returncodes)

    pipeline.run_pipeline("2026-06-05", dry_run=False)

    # Optional failure should NOT immediately notify; only the final summary fires.
    assert len(slack.calls) == 1
    call = slack.calls[0]
    assert call["level"] == "WARNING"  # demoted from INFO because there were skips
    assert call["title"] == "Post-scan pipeline OK"
    assert "schwab_readonly_sync(exit 5)" in call["message"]


def test_pipeline_dry_run_does_not_notify(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture, fresh_scan: None
) -> None:
    _patch_subprocess(monkeypatch, [0] * len(pipeline.STEPS))

    pipeline.run_pipeline("2026-06-05", dry_run=True)

    assert slack.calls == []


def test_pipeline_stale_scan_output_notifies_warning(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture
) -> None:
    monkeypatch.setattr(pipeline, "_scan_output_fresh", lambda _date: False)
    _patch_subprocess(monkeypatch, [0] * len(pipeline.STEPS))

    pipeline.run_pipeline("2026-06-05", dry_run=False)

    # First call is the stale-scan warning; final call is the OK summary.
    assert len(slack.calls) == 2
    assert slack.calls[0]["level"] == "WARNING"
    assert "stale scan output" in slack.calls[0]["title"]
    assert slack.calls[1]["title"] == "Post-scan pipeline OK"


def test_pipeline_passes_dry_run_flag_to_relevant_steps(
    monkeypatch: pytest.MonkeyPatch, slack: _SlackCapture, fresh_scan: None
) -> None:
    captured = _patch_subprocess(monkeypatch, [0] * len(pipeline.STEPS))

    pipeline.run_pipeline("2026-06-05", dry_run=True)

    # s2_letf_orb_alpaca should have --dry-run appended.
    alpaca_cmds = [c for c in captured if "strategies.s2_letf_orb_alpaca" in c]
    assert alpaca_cmds and "--dry-run" in alpaca_cmds[0]
    # raec_v6_coordinator uses --mode dry-run instead.
    v6_cmds = [c for c in captured if "strategies.raec_v6.coordinator" in c]
    assert v6_cmds
    v6_cmd = v6_cmds[0]
    mode_idx = v6_cmd.index("--mode")
    assert v6_cmd[mode_idx + 1] == "dry-run"
    # Other steps must not have --dry-run.
    other_cmds = [c for c in captured if c not in alpaca_cmds + v6_cmds]
    for cmd in other_cmds:
        assert "--dry-run" not in cmd
