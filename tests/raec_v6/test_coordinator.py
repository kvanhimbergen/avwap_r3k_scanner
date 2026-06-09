"""End-to-end smoke tests for the v6 coordinator.

Uses a FixturePriceProvider so the test is deterministic and fast (no
yfinance calls). Verifies:
- State is created on first run
- State is updated and persisted on subsequent runs
- Ledger record is written
- DryRunAdapter rejection still works through the coordinator
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from helpers import linear_series
from strategies.raec_v6 import coordinator as cd
from strategies.raec_v6.dry_run_adapter import (
    DryRunAdapter,
    V6DryRunSafetyError,
)


def _fixture_provider() -> FixturePriceProvider:
    """Build a provider with enough history for every signal/strategy in v6
    to produce non-None outputs."""
    start = date(2024, 1, 1)
    n = 400
    series: dict[str, list[tuple[date, float]]] = {}
    # SPY benchmark + cash equivalents
    series["SPY"] = linear_series(start=start, base=400, slope=0.20, wiggle=0.20, n=n)
    series["BIL"] = linear_series(start=start, base=91, slope=0.001, wiggle=0.005, n=n)
    # Cross-asset trend reps
    for s in ("EEM", "XLK", "SHY", "IEF", "TLT", "HYG", "PDBC", "GLD", "USO",
              "IBIT", "VIXY", "UUP"):
        series[s] = linear_series(start=start, base=80, slope=0.05, wiggle=0.10, n=n)
    # Equity leveraged momentum
    for s in ("QQQ", "IWM", "VTI", "MDY", "VOO", "TQQQ", "UPRO", "SSO",
              "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
              "XLC", "SMH", "XBI", "XME",
              "SOXL", "TECL", "FNGU", "ERX", "NVDL", "FAS", "LABU"):
        series[s] = linear_series(start=start, base=100, slope=0.10, wiggle=0.10, n=n)
    # Theme
    for s in ("AIQ", "BOTZ", "ROBO", "ARKK", "ARKQ", "ARKX", "ARKG", "ARKW",
              "CHAT", "UFO", "HACK", "WCLD", "IGV", "SKYY"):
        series[s] = linear_series(start=start, base=100, slope=0.05, wiggle=0.20, n=n)
    # Bonds + credit + commodity + crypto + crisis
    for s in ("SGOV", "GOVT", "EDV", "ZROZ", "TBT", "TBF", "JNK", "LQD", "TIP",
              "DBC", "DBA", "SLV", "IAU", "UNG", "USL",
              "FBTC", "ETHA", "BITX", "ETHU", "BITO", "BITI",
              "SVXY", "UVXY", "PSQ", "SQQQ", "SH", "SDS", "DOG", "RWM",
              "UDN"):
        series[s] = linear_series(start=start, base=50, slope=0.02, wiggle=0.10, n=n)
    # VIX as constant 18
    series["^VIX"] = [(start + timedelta(days=i), 18.0) for i in range(n)]
    return FixturePriceProvider(series)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A scratch repo root with state/ and ledger/ dirs."""
    (tmp_path / "state").mkdir()
    (tmp_path / "ledger").mkdir()
    return tmp_path


def test_first_run_creates_state_and_ledger(repo_root: Path) -> None:
    provider = _fixture_provider()
    asof = date(2024, 11, 15)
    result = cd.run_coordinator(
        asof_date=asof,
        repo_root=repo_root,
        price_provider=provider,
        post_enabled=False,
    )
    assert result.asof_date == asof
    # State file exists
    state_path = repo_root / "state" / "strategies" / cd.BOOK_ID / "coordinator.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["started_at"] == asof.isoformat()
    assert state["last_eval_date"] == asof.isoformat()
    assert state["shadow_book"] is not None
    # Ledger written
    ledger_path = repo_root / "ledger" / "RAEC_V6" / f"{asof.isoformat()}.jsonl"
    assert ledger_path.exists()
    record = json.loads(ledger_path.read_text().splitlines()[0])
    assert record["record_type"] == "RAEC_V6_RUN"
    assert record["book_id"] == cd.BOOK_ID
    assert "strategy_outputs" in record
    assert "allocator" in record
    assert "overlay" in record


def test_second_run_persists_history(repo_root: Path) -> None:
    provider = _fixture_provider()
    cd.run_coordinator(
        asof_date=date(2024, 11, 15),
        repo_root=repo_root,
        price_provider=provider,
        post_enabled=False,
    )
    cd.run_coordinator(
        asof_date=date(2024, 11, 16),
        repo_root=repo_root,
        price_provider=provider,
        post_enabled=False,
    )
    state_path = repo_root / "state" / "strategies" / cd.BOOK_ID / "coordinator.json"
    state = json.loads(state_path.read_text())
    # Equity curve has 2 entries; asof_history has 2 dates
    sb = state["shadow_book"]
    assert len(sb["equity_curve"]) == 2
    assert len(sb["asof_history"]) == 2
    # strategy_returns also grew
    for sid, ret_list in state["strategy_returns"].items():
        assert len(ret_list) == 2


def test_coordinator_refuses_wrong_book_adapter(repo_root: Path) -> None:
    provider = _fixture_provider()
    with pytest.raises(V6DryRunSafetyError):
        # Constructing the adapter with the live book is itself a refusal,
        # so we have to bypass that to test the coordinator's own guard.
        # The way to provoke this: manually-construct an adapter, then
        # mutate its book_id (hacky but tests the coordinator's check).
        adapter = DryRunAdapter()
        object.__setattr__(adapter, "_book_id", "SCHWAB_401K_MANUAL")
        cd.run_coordinator(
            asof_date=date(2024, 11, 15),
            repo_root=repo_root,
            price_provider=provider,
            adapter=adapter,
            post_enabled=False,
        )


def test_no_post_keeps_posted_false(repo_root: Path) -> None:
    provider = _fixture_provider()
    result = cd.run_coordinator(
        asof_date=date(2024, 11, 15),
        repo_root=repo_root,
        price_provider=provider,
        post_enabled=False,
    )
    assert result.posted is False
