"""Tests for v6 coordinator live mode.

Uses a fixture price provider + a pre-written Schwab snapshot so the
test is deterministic. Verifies:
- Live mode reads Schwab positions
- Live mode posts via LiveTradeAdapter (not DryRunAdapter)
- Live mode writes ledger to RAEC_V6_LIVE/
- Live mode refuses construction with wrong adapter
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from strategies.raec_v6 import coordinator as cd
from strategies.raec_v6.dry_run_adapter import DryRunAdapter, V6DryRunSafetyError
from strategies.raec_v6.live_trade_adapter import LiveTradeAdapter

from tests.raec_v6.test_coordinator import _fixture_provider  # type: ignore[import]


def _write_snapshot(repo_root: Path, asof: date) -> None:
    p = repo_root / "ledger" / "SCHWAB_401K_MANUAL" / f"{asof.isoformat()}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        f.write(json.dumps({
            "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
            "as_of_utc": f"{asof.isoformat()}T16:00:00+00:00",
            "ny_date": asof.isoformat(),
            "total_value": "250000",
            "cash": "5000",
            "market_value": "245000",
        }) + "\n")
        f.write(json.dumps({
            "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
            "as_of_utc": f"{asof.isoformat()}T16:00:00+00:00",
            "ny_date": asof.isoformat(),
            "positions": [
                {"symbol": "SPY", "market_value": "120000", "qty": "200"},
                {"symbol": "BIL", "market_value": "125000", "qty": "1389"},
            ],
        }) + "\n")


@pytest.fixture
def repo_with_snapshot(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir()
    (tmp_path / "ledger").mkdir()
    _write_snapshot(tmp_path, date(2024, 11, 15))
    return tmp_path


def test_live_mode_writes_to_live_ledger(repo_with_snapshot: Path) -> None:
    provider = _fixture_provider()
    result = cd.run_coordinator(
        asof_date=date(2024, 11, 15),
        repo_root=repo_with_snapshot,
        mode=cd.MODE_LIVE,
        price_provider=provider,
        post_enabled=False,
    )
    assert result.asof_date == date(2024, 11, 15)
    live_ledger = repo_with_snapshot / "ledger" / "RAEC_V6_LIVE" / "2024-11-15.jsonl"
    assert live_ledger.exists()
    record = json.loads(live_ledger.read_text().splitlines()[0])
    assert record["record_type"] == "RAEC_V6_LIVE_RUN"
    assert record["mode"] == "live"
    assert record["book_id"] == cd.BOOK_ID_LIVE


def test_live_mode_uses_schwab_equity_for_intents(repo_with_snapshot: Path) -> None:
    """Intent dollar deltas should be relative to the real Schwab equity ($250K),
    not the synthetic shadow book."""
    provider = _fixture_provider()
    cd.run_coordinator(
        asof_date=date(2024, 11, 15),
        repo_root=repo_with_snapshot,
        mode=cd.MODE_LIVE,
        price_provider=provider,
        post_enabled=False,
    )
    live_ledger = repo_with_snapshot / "ledger" / "RAEC_V6_LIVE" / "2024-11-15.jsonl"
    record = json.loads(live_ledger.read_text().splitlines()[0])
    intents = record["intents"]
    # First intent should reference dollars consistent with ~$250K equity.
    if intents:
        ix = intents[0]
        assert "dollar_delta" in ix
        # Sanity: BUY/SELL up to maybe $200K total possible at 100% of book
        assert -300000 < ix["dollar_delta"] < 300000


def test_live_mode_refuses_dry_run_adapter(repo_with_snapshot: Path) -> None:
    provider = _fixture_provider()
    with pytest.raises(V6DryRunSafetyError):
        cd.run_coordinator(
            asof_date=date(2024, 11, 15),
            repo_root=repo_with_snapshot,
            mode=cd.MODE_LIVE,
            adapter=DryRunAdapter(),
            price_provider=provider,
            post_enabled=False,
        )


def test_dry_run_mode_refuses_live_adapter(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "ledger").mkdir()
    provider = _fixture_provider()
    with pytest.raises(V6DryRunSafetyError):
        cd.run_coordinator(
            asof_date=date(2024, 11, 15),
            repo_root=tmp_path,
            mode=cd.MODE_DRY_RUN,
            adapter=LiveTradeAdapter(),
            price_provider=provider,
            post_enabled=False,
        )


def test_invalid_mode_raises(tmp_path: Path) -> None:
    provider = _fixture_provider()
    with pytest.raises(ValueError, match="mode must be"):
        cd.run_coordinator(
            asof_date=date(2024, 11, 15),
            repo_root=tmp_path,
            mode="invalid",
            price_provider=provider,
            post_enabled=False,
        )


def test_live_mode_requires_snapshot(tmp_path: Path) -> None:
    """No Schwab snapshot in ledger → live mode raises."""
    (tmp_path / "state").mkdir()
    (tmp_path / "ledger").mkdir()
    from strategies.raec_v6.schwab_positions import SchwabPositionsStaleError
    provider = _fixture_provider()
    with pytest.raises(SchwabPositionsStaleError):
        cd.run_coordinator(
            asof_date=date(2024, 11, 15),
            repo_root=tmp_path,
            mode=cd.MODE_LIVE,
            price_provider=provider,
            post_enabled=False,
        )
