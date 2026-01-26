from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _fsync_dir(path: Path) -> None:
    try:
        dir_fd = os.open(path, os.O_DIRECTORY)  # type: ignore[attr-defined]
    except (AttributeError, FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        return
    finally:
        os.close(dir_fd)


def atomic_write_text(path: str | Path, data: str) -> None:
    if not isinstance(data, str):
        raise TypeError("data must be a string")
    target = Path(path)
    directory = target.parent
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(directory),
    )
    tmp_target = Path(tmp_path)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        _fsync_dir(directory)
    except Exception:
        try:
            if tmp_target.exists():
                tmp_target.unlink()
        except Exception:
            pass
        raise
    else:
        try:
            if tmp_target.exists():
                tmp_target.unlink()
        except Exception:
            pass


def atomic_append_line(path: str | Path, line: str) -> None:
    if not isinstance(line, str):
        raise TypeError("line must be a string")
    normalized = line.replace("\r\n", "\n")
    if "\r" in normalized:
        raise ValueError("line must be single-line JSON")
    if "\n" in normalized:
        if normalized.endswith("\n") and normalized.count("\n") == 1:
            normalized = normalized[:-1]
        else:
            raise ValueError("line must be single-line JSON")
    payload = f"{normalized}\n".encode("utf-8")
    target = Path(path)
    fd = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(target.parent)
