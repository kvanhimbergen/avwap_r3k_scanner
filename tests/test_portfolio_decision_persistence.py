import json
import uuid

from execution_v2 import portfolio_decisions


def test_portfolio_decision_append_preserves_existing_line(tmp_path) -> None:
    path = tmp_path / "ledger" / "PORTFOLIO_DECISIONS" / "2024-01-02.jsonl"
    record = {
        "decision_id": "decision-1",
        "ts_utc": "2024-01-02T00:00:00+00:00",
        "ny_date": "2024-01-02",
        "intents": {"intents": []},
        "actions": {"submitted_orders": [], "skipped": [], "errors": []},
        "gates": {"blocks": []},
        "inputs": {"constraints_snapshot": {"allowlist_symbols": ["B", "A"]}},
        "artifacts": {"ledgers_written": []},
    }
    second = dict(record)
    second["decision_id"] = "decision-2"

    path.parent.mkdir(parents=True, exist_ok=True)
    first_line = portfolio_decisions.dumps_portfolio_decision(record)
    path.write_text(first_line + "\n", encoding="utf-8", newline="\n")

    portfolio_decisions.write_portfolio_decision(second, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        first_line,
        portfolio_decisions.dumps_portfolio_decision(second),
    ]


def test_portfolio_decision_latest_canonical_json(tmp_path) -> None:
    path = tmp_path / "state" / "portfolio_decision_latest.json"
    record = {
        "decision_id": "decision-1",
        "ts_utc": "2024-01-02T00:00:00+00:00",
        "ny_date": "2024-01-02",
        "intents": {"intents": []},
        "actions": {"submitted_orders": [], "skipped": [], "errors": []},
        "gates": {"blocks": []},
        "inputs": {"constraints_snapshot": {"allowlist_symbols": ["B", "A"]}},
        "artifacts": {"ledgers_written": []},
    }

    portfolio_decisions.write_portfolio_decision_latest(record, path)

    payload = path.read_text(encoding="utf-8")
    assert payload.endswith("\n")
    assert payload == portfolio_decisions.dumps_portfolio_decision(record) + "\n"

    parsed = json.loads(payload)
    assert parsed["inputs"]["constraints_snapshot"]["allowlist_symbols"] == ["A", "B"]


def test_portfolio_decision_serializes_uuid_order_id() -> None:
    order_id = uuid.uuid4()
    record = {
        "decision_id": "decision-1",
        "ts_utc": "2024-01-02T00:00:00+00:00",
        "ny_date": "2024-01-02",
        "intents": {"intents": []},
        "actions": {
            "submitted_orders": [{"broker_order_id": order_id}],
            "skipped": [],
            "errors": [],
        },
        "gates": {"blocks": []},
        "inputs": {"constraints_snapshot": {"allowlist_symbols": []}},
        "artifacts": {"ledgers_written": []},
    }

    payload = portfolio_decisions.dumps_portfolio_decision(record)

    parsed = json.loads(payload)
    assert parsed["actions"]["submitted_orders"][0]["broker_order_id"] == str(order_id)
