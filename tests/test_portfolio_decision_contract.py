from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from execution_v2 import portfolio_decisions


def _sample_record() -> dict:
    return {
        "schema_version": "1.0",
        "decision_id": "abc",
        "ts_utc": "2024-01-02T03:04:05+00:00",
        "ny_date": "2024-01-01",
        "cycle": {"loop_interval_sec": 300, "service_name": None, "pid": 123, "hostname": "host"},
        "mode": {"execution_mode": "DRY_RUN", "dry_run_forced": False},
        "inputs": {
            "candidates_csv": {"path": "/tmp/candidates.csv", "mtime_utc": None, "row_count": 0},
            "account": {"equity": None, "buying_power": None, "source": "none"},
            "constraints_snapshot": {
                "allowlist_symbols": ["MSFT", "AAPL"],
                "max_new_positions": 5,
                "max_gross_exposure": 5000.0,
                "max_notional_per_symbol": 1000.0,
            },
        },
        "intents": {
            "intent_count": 2,
            "intents": [
                {"symbol": "MSFT", "side": "buy", "client_order_id": "b", "qty": 1},
                {"symbol": "AAPL", "side": "buy", "client_order_id": "a", "qty": 2},
            ],
        },
        "gates": {
            "market": {"is_open": True, "clock_source": "clock_snapshot"},
            "freshness": {"candidates_fresh": None, "reason": None},
            "live_gate_applied": False,
            "blocks": [{"code": "z", "message": "last"}, {"code": "a", "message": "first"}],
        },
        "actions": {
            "submitted_orders": [
                {"symbol": "MSFT", "side": "buy", "client_order_id": "b", "qty": 1, "status": "submitted"},
                {"symbol": "AAPL", "side": "buy", "client_order_id": "a", "qty": 2, "status": "submitted"},
            ],
            "skipped": [{"symbol": "ZZZ", "reason": "nope"}],
            "errors": [{"where": "x", "message": "err", "exception_type": None}],
        },
        "artifacts": {"ledgers_written": ["b", "a"], "portfolio_decisions_path": "/tmp/decisions.jsonl"},
    }


def test_portfolio_decision_path_uses_ny_date() -> None:
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime(2024, 2, 3, 9, 30, tzinfo=ny_tz)
    path = portfolio_decisions.resolve_portfolio_decisions_path(Path("/x"), now_ny)
    assert str(path).endswith("ledger/PORTFOLIO_DECISIONS/2024-02-03.jsonl")


def test_write_appends_jsonl_and_newline(tmp_path) -> None:
    record = _sample_record()
    output_path = tmp_path / "decision.jsonl"
    portfolio_decisions.write_portfolio_decision(record, output_path)
    contents = output_path.read_text(encoding="utf-8")
    assert contents.endswith("\n")
    assert len(contents.splitlines()) == 1


def test_deterministic_serialization_and_ordering() -> None:
    record = _sample_record()
    payload = portfolio_decisions.dumps_portfolio_decision(record)
    parsed = json.loads(payload)

    intents = parsed["intents"]["intents"]
    assert [intent["symbol"] for intent in intents] == ["AAPL", "MSFT"]

    submitted = parsed["actions"]["submitted_orders"]
    assert [item["symbol"] for item in submitted] == ["AAPL", "MSFT"]

    blocks = parsed["gates"]["blocks"]
    assert [block["code"] for block in blocks] == ["a", "z"]

    artifacts = parsed["artifacts"]["ledgers_written"]
    assert artifacts == ["a", "b"]

    allowlist = parsed["inputs"]["constraints_snapshot"]["allowlist_symbols"]
    assert allowlist == ["AAPL", "MSFT"]

    assert payload.startswith("{\"actions\"")


def test_single_invocation_writes_one_line(tmp_path) -> None:
    record = _sample_record()
    output_path = tmp_path / "single.jsonl"
    portfolio_decisions.write_portfolio_decision(record, output_path)
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
