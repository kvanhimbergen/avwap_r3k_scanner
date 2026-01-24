from __future__ import annotations

import json
from pathlib import Path

from analytics.broker_adapter import AlpacaFixtureAdapter
from analytics.reconciliation import build_reconciliation_report, serialize_reconciliation_report
from analytics.schemas import BrokerPosition, PortfolioPosition

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "analytics"


def test_reconciliation_deterministic_serialization() -> None:
    internal = [
        PortfolioPosition(
            symbol="AAA",
            qty=10.0,
            avg_price=100.0,
            mark_price=101.0,
            notional=1010.0,
        )
    ]
    broker = [
        BrokerPosition(
            symbol="AAA",
            qty=10.0,
            avg_entry_price=100.0,
            market_value=1010.0,
            last_price=101.0,
        )
    ]

    report = build_reconciliation_report(
        as_of_date_ny="2026-01-19",
        run_id="run-1",
        internal_positions=internal,
        broker_positions=broker,
        source_paths=["ledger.json", "broker.json"],
    )
    payload_first = serialize_reconciliation_report(report)
    payload_second = serialize_reconciliation_report(report)
    serialized_first = json.dumps(payload_first, sort_keys=True, separators=(",", ":"))
    serialized_second = json.dumps(payload_second, sort_keys=True, separators=(",", ":"))
    assert serialized_first == serialized_second


def test_reconciliation_delta_detection() -> None:
    internal = [
        PortfolioPosition(
            symbol="AAA",
            qty=10.0,
            avg_price=100.0,
            mark_price=101.0,
            notional=1010.0,
        ),
        PortfolioPosition(
            symbol="CCC",
            qty=5.0,
            avg_price=50.0,
            mark_price=50.5,
            notional=252.5,
        ),
    ]
    broker = [
        BrokerPosition(
            symbol="AAA",
            qty=12.0,
            avg_entry_price=101.0,
            market_value=1212.0,
            last_price=101.0,
        ),
        BrokerPosition(
            symbol="BBB",
            qty=1.0,
            avg_entry_price=10.0,
            market_value=10.0,
            last_price=10.0,
        ),
    ]

    report = build_reconciliation_report(
        as_of_date_ny="2026-01-19",
        run_id="run-2",
        internal_positions=internal,
        broker_positions=broker,
        source_paths=["ledger.json"],
    )
    delta_types = [delta.delta_type for delta in report.deltas]
    assert "qty_mismatch" in delta_types
    assert "avg_price_mismatch" in delta_types
    assert "missing_internal" in delta_types
    assert "missing_broker" in delta_types


def test_broker_adapter_fixture_positions() -> None:
    adapter = AlpacaFixtureAdapter(positions_path=str(FIXTURES_DIR / "broker_positions_min.json"))
    positions = adapter.fetch_positions()
    assert positions[0].symbol == "AAPL"
    assert positions[0].qty == 10.0
