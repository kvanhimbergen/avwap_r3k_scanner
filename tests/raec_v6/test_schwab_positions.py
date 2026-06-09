"""Tests for the Schwab position reader used by v6 live mode."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from strategies.raec_v6.schwab_positions import (
    SchwabPositionsStaleError,
    read_latest_snapshot,
)


def _write_snapshot(
    repo_root: Path, snap_date: date, equity: float, cash: float,
    positions: dict[str, float],
) -> None:
    p = repo_root / "ledger" / "SCHWAB_401K_MANUAL" / f"{snap_date.isoformat()}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    account_rec = {
        "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
        "as_of_utc": f"{snap_date.isoformat()}T16:00:00+00:00",
        "ny_date": snap_date.isoformat(),
        "total_value": str(equity),
        "cash": str(cash),
        "market_value": str(equity - cash),
    }
    positions_rec = {
        "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
        "as_of_utc": f"{snap_date.isoformat()}T16:00:00+00:00",
        "ny_date": snap_date.isoformat(),
        "positions": [
            {"symbol": sym, "market_value": str(mv), "qty": "1"}
            for sym, mv in positions.items()
        ],
    }
    with p.open("w") as f:
        f.write(json.dumps(account_rec) + "\n")
        f.write(json.dumps(positions_rec) + "\n")


def test_reads_today_snapshot(tmp_path: Path) -> None:
    asof = date(2026, 6, 8)
    _write_snapshot(tmp_path, asof, equity=253862.38, cash=1968.24,
                    positions={"SGOV": 92925.50, "EEM": 29647.47})
    snap = read_latest_snapshot(repo_root=tmp_path, asof=asof)
    assert snap.asof == asof
    assert snap.total_equity == 253862.38
    assert snap.cash == 1968.24
    assert snap.positions_dollars["SGOV"] == 92925.50
    assert abs(snap.cash_pct - 1968.24 / 253862.38) < 1e-9
    assert abs(snap.positions_pct["SGOV"] - 92925.50 / 253862.38) < 1e-9


def test_walks_back_to_recent_snapshot(tmp_path: Path) -> None:
    """If today's file isn't there yet, walks back to find one."""
    _write_snapshot(tmp_path, date(2026, 6, 5), equity=250000, cash=1000,
                    positions={"SPY": 249000})
    snap = read_latest_snapshot(repo_root=tmp_path, asof=date(2026, 6, 6))
    assert snap.asof == date(2026, 6, 5)


def test_refuses_stale_snapshot(tmp_path: Path) -> None:
    """Snapshot from a week ago should error rather than mislead."""
    _write_snapshot(tmp_path, date(2026, 6, 1), equity=250000, cash=1000,
                    positions={"SPY": 249000})
    with pytest.raises(SchwabPositionsStaleError):
        read_latest_snapshot(
            repo_root=tmp_path,
            asof=date(2026, 6, 8),
            max_stale_bdays=1,
        )


def test_no_snapshot_raises(tmp_path: Path) -> None:
    with pytest.raises(SchwabPositionsStaleError):
        read_latest_snapshot(repo_root=tmp_path, asof=date(2026, 6, 8))
