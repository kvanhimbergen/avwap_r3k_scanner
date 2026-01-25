import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from execution_v2 import exit_events, live_gate, paper_sim, portfolio_decisions
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


def test_exit_events_append_atomic_appends(tmp_path) -> None:
    repo_root = tmp_path
    ts = datetime(2024, 1, 2, tzinfo=timezone.utc)
    first = exit_events.build_exit_event(event_type="EXIT", symbol="ABC", ts=ts)
    second = exit_events.build_exit_event(event_type="EXIT", symbol="XYZ", ts=ts)

    exit_events.append_exit_event(repo_root, first)
    exit_events.append_exit_event(repo_root, second)

    ledger_path = repo_root / "ledger" / "EXIT_EVENTS" / f"{first['date_ny']}.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        exit_events.serialize_exit_event(first),
        exit_events.serialize_exit_event(second),
    ]


def test_exit_events_append_atomic_failure_leaves_existing(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    ts = datetime(2024, 1, 2, tzinfo=timezone.utc)
    existing = exit_events.build_exit_event(event_type="EXIT", symbol="ABC", ts=ts)
    ledger_path = repo_root / "ledger" / "EXIT_EVENTS" / f"{existing['date_ny']}.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(exit_events.serialize_exit_event(existing) + "\n", encoding="utf-8")

    new_event = exit_events.build_exit_event(event_type="EXIT", symbol="XYZ", ts=ts)

    def _boom_replace(src, dst):
        raise OSError("replace interrupted")

    monkeypatch.setattr(atomic_write.os, "replace", _boom_replace)
    with pytest.raises(OSError, match="replace interrupted"):
        exit_events.append_exit_event(repo_root, new_event)

    assert ledger_path.read_text(encoding="utf-8") == exit_events.serialize_exit_event(existing) + "\n"


def test_portfolio_decision_append_atomic_appends(tmp_path) -> None:
    path = tmp_path / "ledger" / "PORTFOLIO_DECISIONS" / "2024-01-02.jsonl"
    record = {
        "decision_id": "decision-1",
        "ts_utc": "2024-01-02T00:00:00+00:00",
        "ny_date": "2024-01-02",
        "execution_mode": "DRY_RUN",
        "candidates_path": "daily_candidates.csv",
        "candidates_mtime_utc": None,
        "pid": 123,
        "intents": {"intents": []},
        "actions": {"submitted_orders": [], "skipped": [], "errors": []},
        "gates": {"blocks": []},
        "inputs": {"constraints_snapshot": {"allowlist_symbols": ["B", "A"]}},
        "artifacts": {"ledgers_written": []},
    }
    second = dict(record)
    second["decision_id"] = "decision-2"

    portfolio_decisions.write_portfolio_decision(record, path)
    portfolio_decisions.write_portfolio_decision(second, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        portfolio_decisions.dumps_portfolio_decision(record),
        portfolio_decisions.dumps_portfolio_decision(second),
    ]


def test_portfolio_decision_append_atomic_failure_leaves_existing(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ledger" / "PORTFOLIO_DECISIONS" / "2024-01-02.jsonl"
    record = {"decision_id": "decision-1", "intents": {"intents": []}}
    payload = portfolio_decisions.dumps_portfolio_decision(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")

    def _boom_replace(src, dst):
        raise OSError("replace interrupted")

    monkeypatch.setattr(atomic_write.os, "replace", _boom_replace)
    with pytest.raises(OSError, match="replace interrupted"):
        portfolio_decisions.write_portfolio_decision({"decision_id": "decision-2"}, path)

    assert path.read_text(encoding="utf-8") == payload + "\n"


def test_paper_sim_append_atomic_appends(tmp_path) -> None:
    repo_root = tmp_path
    intent = SimpleNamespace(
        symbol="ABC",
        side="buy",
        qty=10,
        entry_price=12.5,
        intent_id="intent-1",
    )
    now_utc = datetime(2024, 1, 2, tzinfo=timezone.utc)

    fills = paper_sim.simulate_fills(
        [intent],
        date_ny="2024-01-02",
        now_utc=now_utc,
        repo_root=repo_root,
    )

    ledger_path = repo_root / "ledger" / "PAPER_SIM" / "2024-01-02.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(fills) == 1
    assert len(lines) == 1
    assert json.loads(lines[0])["intent_id"] == "intent-1"


def test_paper_sim_append_atomic_failure_leaves_existing(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    ledger_path = repo_root / "ledger" / "PAPER_SIM" / "2024-01-02.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing_payload = json.dumps({"intent_id": "intent-0"}, sort_keys=True)
    ledger_path.write_text(existing_payload + "\n", encoding="utf-8")

    intent = SimpleNamespace(
        symbol="ABC",
        side="buy",
        qty=10,
        entry_price=12.5,
        intent_id="intent-1",
    )
    now_utc = datetime(2024, 1, 2, tzinfo=timezone.utc)

    def _boom_replace(src, dst):
        raise OSError("replace interrupted")

    monkeypatch.setattr(atomic_write.os, "replace", _boom_replace)
    with pytest.raises(OSError, match="replace interrupted"):
        paper_sim.simulate_fills(
            [intent],
            date_ny="2024-01-02",
            now_utc=now_utc,
            repo_root=repo_root,
        )

    assert ledger_path.read_text(encoding="utf-8") == existing_payload + "\n"


def test_live_gate_ledger_atomic_appends(tmp_path) -> None:
    date_ny = "2024-01-02"
    ledger_path = tmp_path / "ledger" / "ALPACA_LIVE" / f"{date_ny}.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {
        "order_id": "order-1",
        "symbol": "ABC",
        "notional": 100.0,
        "timestamp": "2024-01-02T00:00:00+00:00",
        "date_ny": date_ny,
        "book_id": "ALPACA_LIVE",
    }
    new_entry = {
        "order_id": "order-2",
        "symbol": "XYZ",
        "notional": 200.0,
        "timestamp": "2024-01-02T00:00:01+00:00",
        "date_ny": date_ny,
        "book_id": "ALPACA_LIVE",
    }

    ledger = live_gate.LiveLedger(str(ledger_path), date_ny, [existing, new_entry])
    ledger.save()

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    assert [entry["order_id"] for entry in parsed] == ["order-1", "order-2"]


def test_live_gate_ledger_atomic_failure_leaves_existing(tmp_path, monkeypatch) -> None:
    date_ny = "2024-01-02"
    ledger_path = tmp_path / "ledger" / "ALPACA_LIVE" / f"{date_ny}.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing_payload = json.dumps(
        {
            "order_id": "order-1",
            "symbol": "ABC",
            "notional": 100.0,
            "timestamp": "2024-01-02T00:00:00+00:00",
            "date_ny": date_ny,
            "book_id": "ALPACA_LIVE",
        },
        sort_keys=True,
    )
    ledger_path.write_text(existing_payload + "\n", encoding="utf-8")

    ledger = live_gate.LiveLedger(
        str(ledger_path),
        date_ny,
        [
            {
                "order_id": "order-1",
                "symbol": "ABC",
                "notional": 100.0,
                "timestamp": "2024-01-02T00:00:00+00:00",
                "date_ny": date_ny,
                "book_id": "ALPACA_LIVE",
            },
            {
                "order_id": "order-2",
                "symbol": "XYZ",
                "notional": 200.0,
                "timestamp": "2024-01-02T00:00:01+00:00",
                "date_ny": date_ny,
                "book_id": "ALPACA_LIVE",
            },
        ],
    )

    def _boom_replace(src, dst):
        raise OSError("replace interrupted")

    monkeypatch.setattr(atomic_write.os, "replace", _boom_replace)
    with pytest.raises(OSError, match="replace interrupted"):
        ledger.save()

    assert ledger_path.read_text(encoding="utf-8") == existing_payload + "\n"
