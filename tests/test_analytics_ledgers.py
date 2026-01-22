from __future__ import annotations

from pathlib import Path

import pytest

from analytics.io.ledgers import LedgerParseError, parse_dry_run_ledger, parse_live_ledger


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def test_parse_dry_run_fixture() -> None:
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))
    assert len(result.fills) == 3

    fills_by_order = {fill.order_id: fill for fill in result.fills}
    assert fills_by_order["dry-1"].symbol == "AAPL"
    assert fills_by_order["dry-1"].side == "buy"
    assert fills_by_order["dry-1"].qty == 10.0
    assert fills_by_order["dry-1"].price == 100.5

    synthetic_order = fills_by_order["dry_run-1"]
    assert synthetic_order.symbol == "MSFT"
    assert synthetic_order.side == "sell"
    assert synthetic_order.qty == 5.0

    tz_test = fills_by_order["dry_run-2"]
    assert tz_test.ts_ny.endswith("-05:00")
    assert tz_test.date_ny == "2026-01-19"


def test_parse_live_fixture() -> None:
    result = parse_live_ledger(str(FIXTURES_DIR / "live_orders_today_min.json"))
    assert len(result.fills) == 2
    assert {fill.date_ny for fill in result.fills} == {"2026-01-20"}
    assert {fill.symbol for fill in result.fills} == {"AMZN", "AAPL"}


def test_deterministic_ordering() -> None:
    first = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))
    second = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))
    assert [fill.fill_id for fill in first.fills] == [fill.fill_id for fill in second.fills]


def test_missing_file_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    with pytest.raises(LedgerParseError) as exc:
        parse_dry_run_ledger(str(missing_path))
    assert "ledger missing" in str(exc.value)
