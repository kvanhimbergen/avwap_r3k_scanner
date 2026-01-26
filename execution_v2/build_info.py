from __future__ import annotations

import platform
import subprocess
from pathlib import Path

APP_VERSION: str | None = None


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def get_git_sha_short(repo_root: Path) -> str | None:
    return _run_git(repo_root, ["rev-parse", "--short", "HEAD"])


def is_git_dirty(repo_root: Path) -> bool | None:
    output = _run_git(repo_root, ["status", "--porcelain"])
    if output is None:
        return None
    return bool(output.strip())


def get_python_version() -> str:
    return platform.python_version()
