from __future__ import annotations

from pathlib import Path

import pytest

from analytics.io.ledgers import parse_dry_run_ledger
from analytics.metrics import compute_cumulative_aggregates, compute_daily_aggregates
from analytics.reconstruction import reconstruct_trades


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def _load_trades():
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_reconstruction.json"))
    reconstruction = reconstruct_trades(result.fills)
    return reconstruction.trades


def test_metrics_deterministic_and_ordered() -> None:
    trades = _load_trades()
    dailies_first = compute_daily_aggregates(trades)
    dailies_second = compute_daily_aggregates(trades)

    assert dailies_first == dailies_second
    assert [daily.date_ny for daily in dailies_first] == sorted(
        daily.date_ny for daily in dailies_first
    )
    for daily in dailies_first:
        assert daily.symbols_traded == sorted(daily.symbols_traded)

    cumulative_first = compute_cumulative_aggregates(dailies_first)
    cumulative_second = compute_cumulative_aggregates(dailies_first)
    assert cumulative_first == cumulative_second


def test_metrics_realized_pnl_and_fees() -> None:
    trades = _load_trades()
    dailies = compute_daily_aggregates(trades)
    daily_by_date = {daily.date_ny: daily for daily in dailies}

    day_one = daily_by_date["2026-01-19"]
    assert day_one.realized_pnl == pytest.approx(40.0)
    assert day_one.missing_price_trade_count == 0
    assert day_one.fees_total == pytest.approx(0.8)

    day_two = daily_by_date["2026-01-20"]
    assert day_two.realized_pnl is None
    assert day_two.missing_price_trade_count == 2
    assert "missing_price_in_day" in day_two.warnings
    assert day_two.fees_total == pytest.approx(2.2)

    cumulative = compute_cumulative_aggregates(dailies)
    assert cumulative[0].realized_pnl == pytest.approx(40.0)
    assert cumulative[-1].realized_pnl is None
