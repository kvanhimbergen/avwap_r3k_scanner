"""Tests for the DryRunAdapter safety contract + formatting."""

from __future__ import annotations

from datetime import date

import pytest

from strategies.raec_v6.dry_run_adapter import (
    DRY_RUN_BOOK_ID,
    LIVE_BOOK_ID,
    DryRunAdapter,
    V6DryRunSafetyError,
    V6Intent,
)


def _intents() -> list[V6Intent]:
    return [
        V6Intent(symbol="SPY", side="BUY", delta_pct=0.05, target_pct=0.30,
                 current_pct=0.25, dollar_delta=11500),
        V6Intent(symbol="BIL", side="SELL", delta_pct=-0.05, target_pct=0.40,
                 current_pct=0.45, dollar_delta=-11500),
    ]


def test_default_construction_uses_dry_run_book() -> None:
    a = DryRunAdapter()
    assert a.book_id == DRY_RUN_BOOK_ID


def test_construction_refuses_live_book() -> None:
    with pytest.raises(V6DryRunSafetyError, match="DRY_RUN"):
        DryRunAdapter(book_id=LIVE_BOOK_ID)


def test_construction_refuses_any_non_dry_run_book() -> None:
    with pytest.raises(V6DryRunSafetyError):
        DryRunAdapter(book_id="SOME_OTHER_BOOK")


def test_post_live_always_raises() -> None:
    a = DryRunAdapter()
    with pytest.raises(V6DryRunSafetyError, match="cannot post live"):
        a.post_live()


def test_post_live_ignores_arguments_still_raises() -> None:
    """No combination of kwargs lets post_live succeed."""
    a = DryRunAdapter()
    with pytest.raises(V6DryRunSafetyError):
        a.post_live(asof=date(2026, 6, 9), intents=_intents())


def test_post_advisory_returns_formatted_text() -> None:
    """The advisory text contains the date, book, regime, and per-intent lines."""
    a = DryRunAdapter()
    text = a.post_advisory(
        asof=date(2026, 6, 9),
        equity=230_000,
        cash=92_000,
        rebalance=True,
        intents=_intents(),
        regime_label="RISK_ON",
        target_vol=0.24,
        forecast_vol=0.13,
        exposure_scale=1.2,
        strategy_shares={"V6_CROSS_ASSET_TREND": 0.35},
    )
    assert "2026-06-09" in text
    assert DRY_RUN_BOOK_ID in text
    assert "RISK_ON" in text
    assert "BUY  SPY" in text
    assert "SELL BIL" in text
    assert "V6_CROSS_ASSET_TREND" in text


def test_post_advisory_no_rebalance_notice() -> None:
    a = DryRunAdapter()
    text = a.post_advisory(
        asof=date(2026, 6, 9),
        equity=230_000,
        cash=230_000,
        rebalance=False,
        intents=[],
        regime_label="NEUTRAL",
        target_vol=0.24,
        forecast_vol=0.12,
        exposure_scale=1.0,
        strategy_shares={},
        notice="within tolerance",
    )
    assert "NO REBALANCE TODAY" in text
    assert "within tolerance" in text


def test_post_error_does_not_raise() -> None:
    """Error posts go through cleanly even if Slack is disabled."""
    a = DryRunAdapter()
    # Should not raise (Slack is a no-op when SLACK_WEBHOOK_URL unset).
    a.post_error(asof=date(2026, 6, 9), error="something broke")
