"""Tests for the manual Schwab snapshot override."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strategies.raec_v6.manual_position_override import (
    _parse_positions,
    build_records,
    write_records,
)


def test_parse_positions_normalizes_case_and_int_shares() -> None:
    out = _parse_positions(["sgov=0", "XLK=212", "spy=35.5"])
    assert out == {"SGOV": 0.0, "XLK": 212.0, "SPY": 35.5}


def test_parse_positions_rejects_bad_pair() -> None:
    with pytest.raises(ValueError):
        _parse_positions(["BAD"])


def test_parse_positions_rejects_bad_shares() -> None:
    with pytest.raises(ValueError):
        _parse_positions(["XLK=abc"])


def test_build_records_passes_consistency_check() -> None:
    account, positions = build_records(
        ny_date="2026-06-11",
        equity=20000,
        cash=2000,
        positions={"SPY": 30, "QQQ": 20},
        prices={"SPY": 600, "QQQ": 0},  # 30×600 + 20×0 = 18000; +2000 = 20000 ✓
    )
    assert account["total_value"] == "20000.0000"
    assert account["cash"] == "2000.0000"
    # zero-share positions should be dropped — but SPY/QQQ both have non-zero shares
    syms = {p["symbol"] for p in positions["positions"]}
    assert syms == {"SPY", "QQQ"}


def test_build_records_drops_zero_share_entries() -> None:
    _, positions = build_records(
        ny_date="2026-06-11",
        equity=18000,
        cash=0,
        positions={"SPY": 30, "OLD": 0},  # OLD should be dropped
        prices={"SPY": 600, "OLD": 100},
    )
    syms = {p["symbol"] for p in positions["positions"]}
    assert "OLD" not in syms
    assert "SPY" in syms


def test_build_records_rejects_inconsistent_equity() -> None:
    """Stated equity that doesn't match cash + sum(MV) is a sign of typo."""
    with pytest.raises(ValueError, match="disagrees"):
        build_records(
            ny_date="2026-06-11",
            equity=50000,  # but cash + MV will be 20000
            cash=2000,
            positions={"SPY": 30},
            prices={"SPY": 600},
            equity_tolerance=0.01,
        )


def test_build_records_accepts_within_tolerance() -> None:
    """A 0.5% drift should pass at 1% tolerance."""
    account, _ = build_records(
        ny_date="2026-06-11",
        equity=20100,  # actual 20000, drift 0.5%
        cash=2000,
        positions={"SPY": 30},
        prices={"SPY": 600},
        equity_tolerance=0.01,
    )
    assert account["total_value"] == "20100.0000"


def test_write_records_appends_to_existing_ledger(tmp_path: Path) -> None:
    """If a Schwab snapshot from the morning sync is already there, we append."""
    p = tmp_path / "ledger" / "SCHWAB_401K_MANUAL" / "2026-06-11.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"record_type": "EXISTING", "ny_date": "2026-06-11"}) + "\n")

    account, positions = build_records(
        ny_date="2026-06-11", equity=20000, cash=2000,
        positions={"SPY": 30}, prices={"SPY": 600},
    )
    write_records(tmp_path, "2026-06-11", account, positions)

    lines = p.read_text().splitlines()
    assert len(lines) == 3  # existing + account + positions
    # Last two records are our additions
    assert json.loads(lines[1])["record_type"] == "SCHWAB_READONLY_ACCOUNT_SNAPSHOT"
    assert json.loads(lines[2])["record_type"] == "SCHWAB_READONLY_POSITIONS_SNAPSHOT"


def test_write_records_creates_file_if_missing(tmp_path: Path) -> None:
    """No prior ledger file should still work."""
    account, positions = build_records(
        ny_date="2026-06-11", equity=20000, cash=2000,
        positions={"SPY": 30}, prices={"SPY": 600},
    )
    path = write_records(tmp_path, "2026-06-11", account, positions)
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
