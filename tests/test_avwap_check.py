import json
import os
from types import SimpleNamespace

from tools import avwap_check


def _make_repo(tmp_path):
    base_dir = tmp_path / "repo"
    (base_dir / "docs").mkdir(parents=True)
    (base_dir / "execution_v2").mkdir(parents=True)
    return base_dir


def _mock_proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_pass_when_required_dirs_writable(monkeypatch, tmp_path, capsys):
    base_dir = _make_repo(tmp_path)
    monkeypatch.setattr(avwap_check, "_run_execution_config_check", lambda *_: _mock_proc())
    monkeypatch.setattr(avwap_check, "_systemctl_available", lambda: False)

    exit_code = avwap_check.main(["--base-dir", str(base_dir), "--mode", "execution"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RESULT=PASS" in output


def test_fail_when_dir_unwritable(monkeypatch, tmp_path, capsys):
    base_dir = _make_repo(tmp_path)
    state_dir = base_dir / "state"
    state_dir.mkdir()
    state_dir.chmod(0o500)
    monkeypatch.setattr(avwap_check, "_systemctl_available", lambda: False)

    if os.access(state_dir, os.W_OK):
        monkeypatch.setattr(avwap_check, "_write_probe_file", lambda *_: "not writable: simulated")

    exit_code = avwap_check.main(
        ["--base-dir", str(base_dir), "--state-dir", str(state_dir), "--mode", "scan"]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output


def test_warn_for_missing_optional_backtest_artifacts(monkeypatch, tmp_path, capsys):
    base_dir = _make_repo(tmp_path)
    monkeypatch.setattr(avwap_check, "_systemctl_available", lambda: False)

    exit_code = avwap_check.main(["--base-dir", str(base_dir), "--mode", "backtest"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "WARN" in output


def test_strict_turns_warn_into_fail(monkeypatch, tmp_path, capsys):
    base_dir = _make_repo(tmp_path)
    monkeypatch.setattr(avwap_check, "_systemctl_available", lambda: False)

    exit_code = avwap_check.main(
        ["--base-dir", str(base_dir), "--mode", "backtest", "--strict"]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "RESULT=FAIL" in output


def test_json_output_is_stable(monkeypatch, tmp_path, capsys):
    base_dir = _make_repo(tmp_path)
    monkeypatch.setattr(avwap_check, "_run_execution_config_check", lambda *_: _mock_proc())
    monkeypatch.setattr(avwap_check, "_systemctl_available", lambda: False)

    exit_code = avwap_check.main(["--base-dir", str(base_dir), "--mode", "execution", "--json"])

    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    payload = json.loads(output)
    assert output == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_execution_config_preserves_dry_run_env(monkeypatch, tmp_path):
    base_dir = _make_repo(tmp_path)
    captured = {}

    def fake_run(cmd, cwd, capture_output, text, env, check):
        captured["env"] = env
        return _mock_proc()

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    monkeypatch.setattr(avwap_check.subprocess, "run", fake_run)

    avwap_check._run_execution_config_check(base_dir)

    assert captured["env"]["DRY_RUN"] == "1"
    assert captured["env"]["EXECUTION_MODE"] == "DRY_RUN"
