import json
import sqlite3
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

from execution_v2 import clocks, execution_main


def _base_cfg(tmp_path, db_path):
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
    return SimpleNamespace(
        base_dir=str(tmp_path),
        candidates_csv=str(candidates_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(db_path),
        execution_mode="DRY_RUN",
        dry_run=True,
        poll_seconds=300,
        ignore_market_hours=False,
    )


def test_decision_latest_includes_db_metadata_and_state_store_path(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    db_path = tmp_path / "execution.sqlite"
    sqlite3.connect(db_path).close()

    captured = {}

    class _Store:
        def __init__(self, path, *_args, **_kwargs) -> None:
            captured["path"] = path

    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_main, "StateStore", _Store)
    monkeypatch.setattr(
        execution_main.clocks,
        "now_snapshot",
        lambda: SimpleNamespace(
            market_open=False,
            now_et=datetime(2024, 1, 2, 8, 0, tzinfo=clocks.ET),
        ),
    )
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

    cfg = _base_cfg(tmp_path, db_path)
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    inputs = payload["inputs"]
    assert captured["path"] == str(db_path)
    assert inputs["db_path"] == str(db_path)
    assert inputs["db_path_abs"] == str(db_path.resolve())
    assert inputs["db_exists"] is True
    assert isinstance(inputs["db_size_bytes"], int)
    assert inputs["db_size_bytes"] >= 0
    assert isinstance(inputs["db_mtime_utc"], str)


def test_state_store_init_failure_is_fail_closed_and_recorded(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"

    class _FailingStore:
        def __init__(self, *_args, **_kwargs) -> None:
            raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_main, "StateStore", _FailingStore)
    monkeypatch.setattr(
        execution_main.clocks,
        "now_snapshot",
        lambda: SimpleNamespace(
            market_open=True,
            now_et=datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET),
        ),
    )
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

    cfg = _base_cfg(tmp_path, tmp_path / "execution.sqlite")
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    blocks = payload.get("gates", {}).get("blocks", [])
    errors = payload.get("actions", {}).get("errors", [])
    assert any(block.get("code") == "state_store_init_failed" for block in blocks)
    assert any(error.get("where") == "state_store_init" for error in errors)
    assert payload.get("actions", {}).get("submitted_orders", []) == []
