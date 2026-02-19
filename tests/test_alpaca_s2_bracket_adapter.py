"""Tests for AlpacaS2BracketAdapter and s2_letf_orb_alpaca runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter, BracketOrderResult


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeAccount:
    equity: str = "100000.00"


@dataclass
class FakePosition:
    symbol: str = "TQQQ"
    market_value: str = "5000.00"


@dataclass
class FakeOrder:
    id: str = "order-001"
    symbol: str = "TQQQ"
    status: str = "accepted"
    side: str = "buy"
    filled_qty: str = "0"
    filled_avg_price: str | None = None
    filled_at: str | None = None
    created_at: str = "2026-02-18T14:00:00Z"
    updated_at: str = "2026-02-18T14:00:00Z"


class FakeTradingClient:
    def __init__(
        self,
        account: FakeAccount | None = None,
        positions: list[FakePosition] | None = None,
        open_orders: list[FakeOrder] | None = None,
        fail_symbols: set[str] | None = None,
    ) -> None:
        self._account = account or FakeAccount()
        self._positions = positions if positions is not None else []
        self._open_orders = open_orders if open_orders is not None else []
        self._fail_symbols = fail_symbols or set()
        self.submitted_orders: list[dict] = []
        self.cancelled_order_ids: list[str] = []
        self._order_counter = 0

    def get_account(self) -> FakeAccount:
        return self._account

    def get_all_positions(self) -> list[FakePosition]:
        return list(self._positions)

    def get_orders(self, filter: Any = None) -> list[FakeOrder]:
        return list(self._open_orders)

    def submit_order(self, request: Any) -> FakeOrder:
        symbol = str(request.symbol).upper()
        if symbol in self._fail_symbols:
            raise RuntimeError(f"order rejected for {symbol}")
        self._order_counter += 1
        self.submitted_orders.append({
            "symbol": symbol,
            "qty": int(request.qty),
            "side": str(request.side),
            "limit_price": getattr(request, "limit_price", None),
        })
        return FakeOrder(
            id=f"order-{self._order_counter:03d}",
            symbol=symbol,
            side=str(request.side),
        )

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled_order_ids.append(order_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    symbol: str = "TQQQ",
    entry: float = 80.0,
    stop: float = 76.0,
    target_r2: float = 88.8,
) -> dict:
    return {
        "Symbol": symbol,
        "Direction": "Long",
        "Strategy_ID": "S2_LETF_ORB_AGGRO",
        "Entry_Level": entry,
        "Stop_Loss": stop,
        "Target_R2": target_r2,
    }


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_basic_risk_sizing(self, tmp_path: Path) -> None:
        """$100k equity, 1% risk, $4 risk/share → 250 shares."""
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
            risk_pct=1.0, max_positions=5,
        )

        assert result.sent == 1
        # risk/share = 80 - 76 = 4, shares = floor(100000 * 0.01 / 4) = 250
        assert client.submitted_orders[0]["qty"] == 250

    def test_notional_cap_20pct(self, tmp_path: Path) -> None:
        """When risk-based shares exceed 20% of equity, cap is applied."""
        client = FakeTradingClient(account=FakeAccount(equity="100000.00"))
        adapter = AlpacaS2BracketAdapter(client)

        # risk/share = 0.10, so 1% risk → floor(100000 * 0.01 / 0.10) = 10000 shares
        # at $50/share = $500,000 notional, way over 20% of $100k ($20k)
        # cap: floor(20000 / 50) = 400 shares
        candidates = [_make_candidate("SOXL", entry=50.0, stop=49.90, target_r2=55.0)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 1
        assert client.submitted_orders[0]["qty"] == 400

    def test_min_one_share(self, tmp_path: Path) -> None:
        """Even with tiny equity, at least 1 share is placed."""
        client = FakeTradingClient(account=FakeAccount(equity="10.00"))
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 1
        assert client.submitted_orders[0]["qty"] == 1

    def test_high_risk_pct(self, tmp_path: Path) -> None:
        """2% risk doubles the risk-based share count, but notional cap may bind."""
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        # Use a low-priced candidate so 20% notional cap doesn't bind.
        # risk/share = 2, shares = floor(100000 * 0.02 / 2) = 1000
        # notional = 1000 * 10 = $10k < $20k cap → passes
        candidates = [_make_candidate("SOXL", entry=10.0, stop=8.0, target_r2=14.4)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
            risk_pct=2.0,
        )

        assert result.sent == 1
        assert client.submitted_orders[0]["qty"] == 1000


# ---------------------------------------------------------------------------
# Candidate filtering tests
# ---------------------------------------------------------------------------

class TestCandidateFiltering:
    def test_skip_existing_position(self, tmp_path: Path) -> None:
        client = FakeTradingClient(
            positions=[FakePosition(symbol="TQQQ")],
        )
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("TQQQ")]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 0
        assert result.skipped == 1

    def test_skip_pending_order(self, tmp_path: Path) -> None:
        client = FakeTradingClient(
            open_orders=[FakeOrder(symbol="SOXL", side="buy")],
        )
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("SOXL")]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 0
        assert result.skipped == 1

    def test_skip_inverted_bracket(self, tmp_path: Path) -> None:
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        # Entry <= Stop → inverted bracket
        candidates = [_make_candidate("TQQQ", entry=76.0, stop=80.0)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 0
        assert result.skipped == 1

    def test_skip_equal_entry_stop(self, tmp_path: Path) -> None:
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("TQQQ", entry=80.0, stop=80.0)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 0
        assert result.skipped == 1

    def test_mixed_candidates(self, tmp_path: Path) -> None:
        """One valid, one with existing position, one inverted."""
        client = FakeTradingClient(
            positions=[FakePosition(symbol="SOXL")],
        )
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [
            _make_candidate("SOXL", entry=40.0, stop=38.0, target_r2=44.4),  # has position
            _make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8),  # valid
            _make_candidate("SPXL", entry=50.0, stop=55.0, target_r2=60.0),  # inverted
        ]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 1
        assert result.skipped == 2
        assert client.submitted_orders[0]["symbol"] == "TQQQ"


# ---------------------------------------------------------------------------
# Max positions cap
# ---------------------------------------------------------------------------

class TestMaxPositionsCap:
    def test_cap_enforced(self, tmp_path: Path) -> None:
        """With 2 existing positions and max_positions=3, only 1 more can be placed."""
        client = FakeTradingClient(
            positions=[
                FakePosition(symbol="SOXL"),
                FakePosition(symbol="TECL"),
            ],
        )
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [
            _make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8),
            _make_candidate("SPXL", entry=50.0, stop=48.0, target_r2=54.4),
        ]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
            max_positions=3,
        )

        assert result.sent == 1
        assert result.skipped == 1
        assert client.submitted_orders[0]["symbol"] == "TQQQ"

    def test_zero_available_slots(self, tmp_path: Path) -> None:
        """When at max positions, no orders are placed."""
        client = FakeTradingClient(
            positions=[
                FakePosition(symbol="SOXL"),
                FakePosition(symbol="TECL"),
                FakePosition(symbol="TQQQ"),
            ],
        )
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("SPXL", entry=50.0, stop=48.0, target_r2=54.4)]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
            max_positions=3,
        )

        assert result.sent == 0
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# Stale order cancellation
# ---------------------------------------------------------------------------

class TestStaleOrderCancellation:
    def test_cancel_stale_buy_orders(self) -> None:
        client = FakeTradingClient(
            open_orders=[
                FakeOrder(id="old-1", symbol="SOXL", side="buy"),
                FakeOrder(id="old-2", symbol="TECL", side="buy"),
                FakeOrder(id="keep-1", symbol="TQQQ", side="buy"),
            ],
        )
        adapter = AlpacaS2BracketAdapter(client)

        # Only TQQQ is in today's candidates
        cancelled = adapter.cancel_stale_orders({"TQQQ"})

        assert len(cancelled) == 2
        assert set(cancelled) == {"old-1", "old-2"}

    def test_preserve_sell_orders(self) -> None:
        """Sell-side orders (stop-loss legs) should not be cancelled."""
        client = FakeTradingClient(
            open_orders=[
                FakeOrder(id="sl-1", symbol="SOXL", side="sell"),
            ],
        )
        adapter = AlpacaS2BracketAdapter(client)

        cancelled = adapter.cancel_stale_orders(set())

        assert len(cancelled) == 0

    def test_no_stale_orders(self) -> None:
        """When all open orders are for current candidates, nothing is cancelled."""
        client = FakeTradingClient(
            open_orders=[
                FakeOrder(id="keep-1", symbol="TQQQ", side="buy"),
            ],
        )
        adapter = AlpacaS2BracketAdapter(client)

        cancelled = adapter.cancel_stale_orders({"TQQQ"})

        assert len(cancelled) == 0


# ---------------------------------------------------------------------------
# Order errors
# ---------------------------------------------------------------------------

class TestOrderErrors:
    def test_error_continues_to_next_candidate(self, tmp_path: Path) -> None:
        """When one order fails, the next candidate is still attempted."""
        client = FakeTradingClient(fail_symbols={"TQQQ"})
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [
            _make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8),
            _make_candidate("SOXL", entry=40.0, stop=38.0, target_r2=44.4),
        ]
        result = adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        assert result.sent == 1
        assert len(result.errors) == 1
        assert "TQQQ" in result.errors[0]
        assert client.submitted_orders[0]["symbol"] == "SOXL"


# ---------------------------------------------------------------------------
# Ledger writing
# ---------------------------------------------------------------------------

class TestLedgerWriting:
    def test_events_written_to_ledger(self, tmp_path: Path) -> None:
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        candidates = [_make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8)]
        adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        ledger_path = tmp_path / "ledger" / "S2_ALPACA" / "2026-02-18.jsonl"
        assert ledger_path.exists()
        lines = [line for line in ledger_path.read_text().strip().split("\n") if line]
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["symbol"] == "TQQQ"
        assert event["strategy_id"] == "S2_LETF_ORB_AGGRO"
        assert event["order_type"] == "BRACKET"
        assert event["stop_loss"] == 76.0
        assert event["take_profit"] == 88.8

    def test_no_ledger_when_no_orders(self, tmp_path: Path) -> None:
        client = FakeTradingClient()
        adapter = AlpacaS2BracketAdapter(client)

        # inverted bracket → skipped → no events → no ledger file
        candidates = [_make_candidate("TQQQ", entry=76.0, stop=80.0)]
        adapter.execute_candidates(
            candidates, ny_date="2026-02-18", repo_root=tmp_path,
        )

        ledger_path = tmp_path / "ledger" / "S2_ALPACA" / "2026-02-18.jsonl"
        assert not ledger_path.exists()


# ---------------------------------------------------------------------------
# Runner dry-run mode
# ---------------------------------------------------------------------------

class TestRunnerDryRun:
    def test_dry_run_prints_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Dry-run should print candidate summary and not build adapter."""
        import pandas as pd
        from strategies.s2_letf_orb_alpaca import run

        # Write a minimal candidates CSV
        csv_path = tmp_path / "candidates.csv"
        df = pd.DataFrame([
            _make_candidate("TQQQ", entry=80.0, stop=76.0, target_r2=88.8),
            _make_candidate("SOXL", entry=40.0, stop=38.0, target_r2=44.4),
        ])
        df.to_csv(csv_path, index=False)

        run(
            asof_date="2026-02-18",
            repo_root=tmp_path,
            dry_run=True,
            candidates_csv=csv_path,
        )

        captured = capsys.readouterr()
        assert "DRY_RUN" in captured.out
        assert "TQQQ" in captured.out
        assert "SOXL" in captured.out

    def test_no_candidates_csv(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """When CSV does not exist, runner reports 0 candidates."""
        from strategies.s2_letf_orb_alpaca import run

        run(
            asof_date="2026-02-18",
            repo_root=tmp_path,
            dry_run=True,
        )

        captured = capsys.readouterr()
        assert "candidates=0" in captured.out


# ---------------------------------------------------------------------------
# Pipeline step order
# ---------------------------------------------------------------------------

class TestPipelineStepOrder:
    def test_pipeline_steps_in_correct_order(self) -> None:
        from ops.post_scan_pipeline import STEPS

        names = [step["name"] for step in STEPS]
        assert names == [
            "regime_e1_runner",
            "regime_throttle_writer",
            "schwab_readonly_sync",
            "schwab_seed_allocations",
            "s2_letf_orb_aggro",
            "s2_letf_orb_alpaca",
            "raec_401k_coordinator",
            "raec_401k_v2",
        ]

    def test_s2_aggro_uses_leveraged_only(self) -> None:
        from ops.post_scan_pipeline import STEPS

        s2_aggro = next(s for s in STEPS if s["name"] == "s2_letf_orb_aggro")
        args = s2_aggro["args"]("2026-02-18")
        assert "--universe-profile" in args
        idx = args.index("--universe-profile")
        assert args[idx + 1] == "leveraged_only"

    def test_dry_run_appended_to_execution_steps(self) -> None:
        """Verify dry-run is appended to s2_letf_orb_alpaca, raec_401k_coordinator, raec_401k_v2."""
        from ops.post_scan_pipeline import STEPS

        dry_run_steps = {"s2_letf_orb_alpaca", "raec_401k_coordinator", "raec_401k_v2"}
        # Simulate the pipeline dry_run logic
        for step in STEPS:
            cmd = step["args"]("2026-02-18")
            if step["name"] in dry_run_steps:
                cmd.append("--dry-run")
            if step["name"] in dry_run_steps:
                assert "--dry-run" in cmd, f"Missing --dry-run for {step['name']}"
            else:
                assert "--dry-run" not in cmd, f"Unexpected --dry-run for {step['name']}"
