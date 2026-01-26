from __future__ import annotations

from types import SimpleNamespace

import platform

from execution_v2 import build_info


def test_get_git_sha_short_returns_none_when_git_unavailable(monkeypatch, tmp_path) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(build_info.subprocess, "run", _raise)
    assert build_info.get_git_sha_short(tmp_path) is None


def test_is_git_dirty_returns_none_when_git_unavailable(monkeypatch, tmp_path) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(build_info.subprocess, "run", _raise)
    assert build_info.is_git_dirty(tmp_path) is None


def test_is_git_dirty_returns_bool(monkeypatch, tmp_path) -> None:
    def _run(*_args, **_kwargs):
        return SimpleNamespace(stdout=" M execution_v2/execution_main.py\n")

    monkeypatch.setattr(build_info.subprocess, "run", _run)
    assert build_info.is_git_dirty(tmp_path) is True


def test_get_python_version_matches_platform() -> None:
    assert build_info.get_python_version() == platform.python_version()
