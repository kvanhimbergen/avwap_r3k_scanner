"""Tests for analytics.schwab_seed_allocations."""
from __future__ import annotations

import json

import pytest

from analytics.schwab_seed_allocations import (
    load_allocations_from_ledger,
    positions_to_allocations,
    seed_strategy_states,
)


# ── positions_to_allocations ──────────────────────────────────────────────


def test_positions_to_allocations_normal():
    account = {"total_value": "100000.0000", "cash": "10000.0000"}
    positions = {
        "positions": [
            {"symbol": "SPY", "market_value": "60000.0000"},
            {"symbol": "SMH", "market_value": "30000.0000"},
        ],
    }
    allocs = positions_to_allocations(account, positions)
    assert allocs == {"SPY": 60.0, "SMH": 30.0, "BIL": 10.0}


def test_positions_to_allocations_cash_only():
    account = {"total_value": "50000.0000", "cash": "50000.0000"}
    positions = {"positions": []}
    allocs = positions_to_allocations(account, positions)
    assert allocs == {"BIL": 100.0}


def test_positions_to_allocations_zero_total():
    account = {"total_value": "0", "cash": "0"}
    positions = {"positions": []}
    allocs = positions_to_allocations(account, positions)
    assert allocs == {}


def test_positions_to_allocations_no_cash():
    account = {"total_value": "100000.0000", "cash": "0"}
    positions = {
        "positions": [
            {"symbol": "SPY", "market_value": "100000.0000"},
        ],
    }
    allocs = positions_to_allocations(account, positions)
    assert allocs == {"SPY": 100.0}
    assert "BIL" not in allocs


def test_positions_to_allocations_custom_cash_symbol():
    account = {"total_value": "100000.0000", "cash": "5000.0000"}
    positions = {
        "positions": [
            {"symbol": "SPY", "market_value": "95000.0000"},
        ],
    }
    allocs = positions_to_allocations(account, positions, cash_symbol="CASH")
    assert allocs == {"SPY": 95.0, "CASH": 5.0}


def test_positions_to_allocations_rounding():
    account = {"total_value": "300000.0000", "cash": "0"}
    positions = {
        "positions": [
            {"symbol": "A", "market_value": "100000.0000"},
            {"symbol": "B", "market_value": "100000.0000"},
            {"symbol": "C", "market_value": "100000.0000"},
        ],
    }
    allocs = positions_to_allocations(account, positions)
    assert allocs == {"A": 33.3, "B": 33.3, "C": 33.3}


# ── seed_strategy_states ─────────────────────────────────────────────────


def test_seed_strategy_states_existing_file(tmp_path):
    book_id = "TEST_BOOK"
    state_dir = tmp_path / "state" / "strategies" / book_id
    state_dir.mkdir(parents=True)
    existing = {
        "book_id": book_id,
        "strategy_id": "V3",
        "last_eval_date": "2026-02-17",
        "last_regime": "RISK_ON",
        "last_targets": {"SPY": 50.0, "BIL": 50.0},
        "last_known_allocations": {"BIL": 100.0},
    }
    (state_dir / "V3.json").write_text(json.dumps(existing))

    allocs = {"SPY": 60.0, "SMH": 30.0, "BIL": 10.0}
    updated = seed_strategy_states(tmp_path, allocs, ["V3"], book_id)

    assert updated == ["V3"]
    state = json.loads((state_dir / "V3.json").read_text())
    # New allocs written
    assert state["last_known_allocations"] == allocs
    # Other fields preserved
    assert state["last_eval_date"] == "2026-02-17"
    assert state["last_regime"] == "RISK_ON"
    assert state["last_targets"] == {"SPY": 50.0, "BIL": 50.0}


def test_seed_strategy_states_new_file(tmp_path):
    book_id = "TEST_BOOK"
    allocs = {"SPY": 80.0, "BIL": 20.0}
    updated = seed_strategy_states(tmp_path, allocs, ["V5"], book_id)

    assert updated == ["V5"]
    state_path = tmp_path / "state" / "strategies" / book_id / "V5.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_known_allocations"] == allocs
    assert state["book_id"] == book_id
    assert state["strategy_id"] == "V5"


def test_seed_strategy_states_multiple(tmp_path):
    book_id = "TEST_BOOK"
    allocs = {"SPY": 100.0}
    updated = seed_strategy_states(tmp_path, allocs, ["V3", "V4", "V5"], book_id)
    assert updated == ["V3", "V4", "V5"]
    for sid in ["V3", "V4", "V5"]:
        state = json.loads(
            (tmp_path / "state" / "strategies" / book_id / f"{sid}.json").read_text(),
        )
        assert state["last_known_allocations"] == {"SPY": 100.0}


# ── load_allocations_from_ledger ─────────────────────────────────────────


def test_load_allocations_from_ledger(tmp_path):
    book_id = "TEST_BOOK"
    ny_date = "2026-02-18"
    ledger_dir = tmp_path / "ledger" / book_id
    ledger_dir.mkdir(parents=True)

    account_rec = {
        "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
        "snapshot_id": "abc",
        "total_value": "200000.0000",
        "cash": "20000.0000",
    }
    positions_rec = {
        "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
        "snapshot_id": "def",
        "positions": [
            {"symbol": "SPY", "market_value": "120000.0000"},
            {"symbol": "SMH", "market_value": "60000.0000"},
        ],
    }
    orders_rec = {
        "record_type": "SCHWAB_READONLY_ORDERS_SNAPSHOT",
        "snapshot_id": "ghi",
        "orders": [],
    }

    lines = [json.dumps(r) for r in [account_rec, positions_rec, orders_rec]]
    (ledger_dir / f"{ny_date}.jsonl").write_text("\n".join(lines) + "\n")

    allocs = load_allocations_from_ledger(tmp_path, book_id, ny_date)
    assert allocs is not None
    assert allocs == {"SPY": 60.0, "SMH": 30.0, "BIL": 10.0}


def test_load_allocations_from_ledger_missing_file(tmp_path):
    allocs = load_allocations_from_ledger(tmp_path, "NOPE", "2026-01-01")
    assert allocs is None


def test_load_allocations_from_ledger_uses_last_snapshot(tmp_path):
    """When multiple snapshots exist, the last one in the file wins."""
    book_id = "TEST_BOOK"
    ny_date = "2026-02-18"
    ledger_dir = tmp_path / "ledger" / book_id
    ledger_dir.mkdir(parents=True)

    # First snapshot
    recs_1 = [
        {
            "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
            "snapshot_id": "a1",
            "total_value": "100000.0000",
            "cash": "50000.0000",
        },
        {
            "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
            "snapshot_id": "p1",
            "positions": [{"symbol": "SPY", "market_value": "50000.0000"}],
        },
        {
            "record_type": "SCHWAB_READONLY_ORDERS_SNAPSHOT",
            "snapshot_id": "o1",
            "orders": [],
        },
    ]
    # Second (later) snapshot
    recs_2 = [
        {
            "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
            "snapshot_id": "a2",
            "total_value": "100000.0000",
            "cash": "10000.0000",
        },
        {
            "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
            "snapshot_id": "p2",
            "positions": [{"symbol": "SPY", "market_value": "90000.0000"}],
        },
        {
            "record_type": "SCHWAB_READONLY_ORDERS_SNAPSHOT",
            "snapshot_id": "o2",
            "orders": [],
        },
    ]

    lines = [json.dumps(r) for r in recs_1 + recs_2]
    (ledger_dir / f"{ny_date}.jsonl").write_text("\n".join(lines) + "\n")

    allocs = load_allocations_from_ledger(tmp_path, book_id, ny_date)
    # Should reflect second snapshot: 90% SPY, 10% cash
    assert allocs == {"SPY": 90.0, "BIL": 10.0}
