import os

import pytest

import utils.atomic_write as atomic_write


def _find_temp_files(tmp_path, target_name: str) -> list[str]:
    return [str(path) for path in tmp_path.glob(f".{target_name}.*.tmp")]


def test_atomic_write_text_writes_content(tmp_path) -> None:
    target = tmp_path / "dry_run_ledger.json"
    payload = '{"ok":true}\n'
    atomic_write.atomic_write_text(target, payload)
    assert target.read_text(encoding="utf-8") == payload
    assert _find_temp_files(tmp_path, target.name) == []


def test_atomic_write_text_interrupted_write_leaves_target_unchanged(tmp_path, monkeypatch) -> None:
    target = tmp_path / "caps_ledger.jsonl"
    target.write_text("original\n", encoding="utf-8", newline="\n")
    original_fsync = os.fsync

    def _boom_fsync(fd):
        raise OSError("fsync interrupted")

    monkeypatch.setattr(atomic_write.os, "fsync", _boom_fsync)
    with pytest.raises(OSError, match="fsync interrupted"):
        atomic_write.atomic_write_text(target, "new\n")
    monkeypatch.setattr(atomic_write.os, "fsync", original_fsync)

    assert target.read_text(encoding="utf-8") == "original\n"
