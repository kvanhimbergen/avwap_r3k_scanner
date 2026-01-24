from __future__ import annotations

from pathlib import Path

from analytics.schwab_readonly_adapter import SchwabReadonlyFixtureAdapter
from analytics.schwab_readonly_schemas import SCHEMA_VERSION

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schwab_readonly"


def test_schwab_readonly_fixture_adapter_loads_snapshots() -> None:
    adapter = SchwabReadonlyFixtureAdapter.from_fixture_dir(
        FIXTURE_DIR,
        book_id="SCHWAB_401K_MANUAL",
        as_of_utc="2026-01-20T16:00:00+00:00",
    )
    balance, positions, orders = adapter.load_all_snapshots()

    assert balance.schema_version == SCHEMA_VERSION
    assert balance.cash is not None
    assert positions.positions[0].symbol == "AAPL"
    assert orders.orders[0].order_id == "ord-1"
