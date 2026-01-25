from __future__ import annotations

from datetime import datetime, timezone

import pytest

from execution_v2 import live_gate
from execution_v2.config_types import EntryIntent
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


def _intent(symbol: str, qty: int = 10, price: float = 10.0) -> EntryIntent:
    now = datetime.now(tz=timezone.utc).timestamp()
    return EntryIntent(
        strategy_id=DEFAULT_STRATEGY_ID,
        symbol=symbol,
        pivot_level=1.0,
        boh_confirmed_at=now,
        scheduled_entry_at=now,
        size_shares=qty,
        stop_loss=9.0,
        take_profit=11.0,
        ref_price=price,
        dist_pct=1.0,
    )


def test_live_trading_default_off(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.delenv("LIVE_CONFIRM_TOKEN", raising=False)
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    enabled, reason = live_gate.live_trading_enabled(state_dir=str(tmp_path))
    assert enabled is False
    assert "LIVE_TRADING" in reason


def test_live_trading_requires_confirm_token(monkeypatch, tmp_path) -> None:
    token_path = tmp_path / "live_confirm_token.txt"
    token_path.write_text("token-123")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "token-123")
    enabled, reason = live_gate.live_trading_enabled(state_dir=str(tmp_path))
    assert enabled is True
    assert "confirmed" in reason


def test_live_trading_rejects_token_mismatch(monkeypatch, tmp_path) -> None:
    token_path = tmp_path / "live_confirm_token.txt"
    token_path.write_text("token-abc")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "token-def")
    enabled, reason = live_gate.live_trading_enabled(state_dir=str(tmp_path))
    assert enabled is False
    assert "mismatch" in reason


def test_kill_switch_blocks(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("KILL_SWITCH", "1")
    active, reason = live_gate.is_kill_switch_active(state_dir=str(tmp_path))
    assert active is True
    assert reason == "env"


def test_dry_run_mode_does_not_require_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    result = live_gate.resolve_live_mode(dry_run=True, state_dir=str(tmp_path))
    assert result.live_enabled is False
    assert result.mode == "DRY_RUN"
    assert "DRY_RUN" in result.reason


def _enable_live(monkeypatch, tmp_path, *, token: str = "token-123") -> None:
    token_path = tmp_path / "live_confirm_token.txt"
    token_path.write_text(token)
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", token)


def test_phase_c_requires_live_enable_date(monkeypatch, tmp_path) -> None:
    _enable_live(monkeypatch, tmp_path)
    monkeypatch.setenv("PHASE_C", "1")
    monkeypatch.setenv("ALLOWLIST_SYMBOLS", "AAPL")
    result = live_gate.resolve_live_mode(
        dry_run=False,
        state_dir=str(tmp_path),
        today_ny="2024-07-01",
    )
    assert result.live_enabled is False
    assert result.mode == "DRY_RUN"
    assert result.reason == "phase_c_live_date_not_permitted"


def test_phase_c_rejects_mismatched_date(monkeypatch, tmp_path) -> None:
    _enable_live(monkeypatch, tmp_path)
    monkeypatch.setenv("PHASE_C", "1")
    monkeypatch.setenv("ALLOWLIST_SYMBOLS", "AAPL")
    monkeypatch.setenv("LIVE_ENABLE_DATE_NY", "2024-07-02")
    result = live_gate.resolve_live_mode(
        dry_run=False,
        state_dir=str(tmp_path),
        today_ny="2024-07-01",
    )
    assert result.live_enabled is False
    assert result.reason == "phase_c_live_date_not_permitted"


@pytest.mark.parametrize(
    "allowlist_env",
    [
        None,
        "",
        "AAPL,MSFT",
    ],
)
def test_phase_c_requires_single_symbol_allowlist(monkeypatch, tmp_path, allowlist_env) -> None:
    _enable_live(monkeypatch, tmp_path)
    monkeypatch.setenv("PHASE_C", "1")
    monkeypatch.setenv("LIVE_ENABLE_DATE_NY", "2024-07-01")
    if allowlist_env is None:
        monkeypatch.delenv("ALLOWLIST_SYMBOLS", raising=False)
    else:
        monkeypatch.setenv("ALLOWLIST_SYMBOLS", allowlist_env)
    result = live_gate.resolve_live_mode(
        dry_run=False,
        state_dir=str(tmp_path),
        today_ny="2024-07-01",
    )
    assert result.live_enabled is False
    assert result.reason == "phase_c_allowlist_must_be_single_symbol"


def test_phase_c_live_passes_with_single_symbol(monkeypatch, tmp_path) -> None:
    _enable_live(monkeypatch, tmp_path)
    monkeypatch.setenv("PHASE_C", "1")
    monkeypatch.setenv("LIVE_ENABLE_DATE_NY", "2024-07-01")
    monkeypatch.setenv("ALLOWLIST_SYMBOLS", " aapl ")
    result = live_gate.resolve_live_mode(
        dry_run=False,
        state_dir=str(tmp_path),
        today_ny="2024-07-01",
    )
    assert result.live_enabled is True
    assert result.mode == "LIVE"
    assert "phase_c=1" in result.reason


def test_phase_c_disabled_keeps_live_behavior(monkeypatch, tmp_path) -> None:
    _enable_live(monkeypatch, tmp_path)
    monkeypatch.delenv("PHASE_C", raising=False)
    monkeypatch.delenv("LIVE_ENABLE_DATE_NY", raising=False)
    monkeypatch.delenv("ALLOWLIST_SYMBOLS", raising=False)
    result = live_gate.resolve_live_mode(
        dry_run=False,
        state_dir=str(tmp_path),
        today_ny="2024-07-01",
    )
    assert result.live_enabled is True
    assert result.mode == "LIVE"


def test_allowlist_blocks_symbol_in_live(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    today = datetime.now(tz=timezone.utc).date().isoformat()
    ledger_path = live_gate.live_ledger_path(tmp_path, today)
    ledger = live_gate.LiveLedger.initialize(str(ledger_path), today)
    ledger.save()
    caps = live_gate.CapsConfig(
        max_orders_per_day=5,
        max_positions=5,
        max_gross_notional=5000.0,
        max_notional_per_symbol=1000.0,
    )
    allowlist = {"AAPL"}
    allowed, reason = live_gate.enforce_caps(
        _intent("MSFT"),
        ledger,
        allowlist,
        caps,
        open_positions=0,
    )
    assert allowed is False
    assert "allowlist" in reason


def test_caps_block_orders_and_notional(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    today = datetime.now(tz=timezone.utc).date().isoformat()
    ledger_path = live_gate.live_ledger_path(tmp_path, today)
    ledger = live_gate.LiveLedger.initialize(str(ledger_path), today)
    ledger.add_entry("order-1", "AAPL", 1000.0, datetime.now(tz=timezone.utc).isoformat())
    ledger.save()
    caps = live_gate.CapsConfig(
        max_orders_per_day=1,
        max_positions=2,
        max_gross_notional=1500.0,
        max_notional_per_symbol=1100.0,
    )
    intent = _intent("AAPL", qty=10, price=60.0)
    allowed, reason = live_gate.enforce_caps(
        intent,
        ledger,
        None,
        caps,
        open_positions=1,
    )
    assert allowed is False
    assert "max orders/day" in reason or "max gross notional" in reason or "max symbol notional" in reason


def test_caps_block_positions(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVWAP_STATE_DIR", str(tmp_path))
    today = datetime.now(tz=timezone.utc).date().isoformat()
    ledger_path = live_gate.live_ledger_path(tmp_path, today)
    ledger = live_gate.LiveLedger.initialize(str(ledger_path), today)
    ledger.save()
    caps = live_gate.CapsConfig(
        max_orders_per_day=5,
        max_positions=1,
        max_gross_notional=5000.0,
        max_notional_per_symbol=1000.0,
    )
    intent = _intent("AAPL", qty=1, price=50.0)
    allowed, reason = live_gate.enforce_caps(
        intent,
        ledger,
        None,
        caps,
        open_positions=1,
    )
    assert allowed is False
    assert "max positions" in reason
