from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k
from strategies.raec_401k_allocs import (
    DEFAULT_CSV_DROP_SUBDIR,
    _resolve_csv_source,
    _resolve_strategy_module,
    parse_schwab_positions_csv,
)


def _make_series(start: date, values: list[float]) -> list[tuple[date, float]]:
    return [(start + timedelta(days=idx), value) for idx, value in enumerate(values)]


def _risk_on_series() -> list[tuple[date, float]]:
    values = [100 + (idx * 0.1) for idx in range(300)]
    return _make_series(date(2024, 1, 1), values)


def _risk_off_series() -> list[tuple[date, float]]:
    values = [200 - (idx * 0.1) for idx in range(300)]
    return _make_series(date(2024, 1, 1), values)


def _transition_series() -> list[tuple[date, float]]:
    values = [100 + (idx * 0.05) for idx in range(280)]
    for idx in range(20):
        bump = 3 if idx % 2 == 0 else -3
        values.append(values[-1] + bump)
    return _make_series(date(2024, 1, 1), values)


def _provider_for(series: list[tuple[date, float]]) -> FixturePriceProvider:
    return FixturePriceProvider({"VTI": series, "BIL": series})


def test_regime_classification_risk_on() -> None:
    provider = _provider_for(_risk_on_series())
    signal = raec_401k._compute_signals(provider.get_daily_close_series("VTI"))
    assert signal.regime == "RISK_ON"


def test_regime_classification_risk_off() -> None:
    provider = _provider_for(_risk_off_series())
    signal = raec_401k._compute_signals(provider.get_daily_close_series("VTI"))
    assert signal.regime == "RISK_OFF"


def test_regime_classification_transition() -> None:
    provider = _provider_for(_transition_series())
    signal = raec_401k._compute_signals(provider.get_daily_close_series("VTI"))
    assert signal.regime == "TRANSITION"


@pytest.mark.parametrize("regime", ["RISK_ON", "TRANSITION", "RISK_OFF"])
def test_targets_sum_to_100(regime: str) -> None:
    targets = raec_401k._targets_for_regime(regime, "BIL")
    assert round(sum(targets.values()), 1) == 100.0


def test_rebalance_gating_triggers() -> None:
    asof = date(2025, 2, 7)
    targets = {"VTI": 50.0, "BIL": 50.0}
    state = {"last_eval_date": "2025-01-10", "last_regime": "RISK_ON"}
    assert raec_401k._should_rebalance(
        asof=asof,
        state=state,
        regime="RISK_ON",
        targets=targets,
        current_allocs={"VTI": 50.0, "BIL": 50.0},
    )

    state = {"last_eval_date": "2025-02-01", "last_regime": "RISK_OFF"}
    assert raec_401k._should_rebalance(
        asof=asof,
        state=state,
        regime="RISK_ON",
        targets=targets,
        current_allocs={"VTI": 50.0, "BIL": 50.0},
    )

    state = {"last_eval_date": "2025-02-01", "last_regime": "RISK_ON"}
    assert raec_401k._should_rebalance(
        asof=asof,
        state=state,
        regime="RISK_ON",
        targets=targets,
        current_allocs={"VTI": 45.0, "BIL": 55.0},
    )


def test_rebalance_gating_no_trigger() -> None:
    asof = date(2025, 2, 7)
    targets = {"VTI": 50.0, "BIL": 50.0}
    state = {"last_eval_date": "2025-02-01", "last_regime": "RISK_ON"}
    assert not raec_401k._should_rebalance(
        asof=asof,
        state=state,
        regime="RISK_ON",
        targets=targets,
        current_allocs={"VTI": 52.0, "BIL": 48.0},
    )


def test_turnover_scaling_and_min_trade_filter() -> None:
    targets = {"VTI": 8.0, "QUAL": 8.0, "BIL": 0.4}
    current = {"VTI": 0.0, "QUAL": 0.0, "BIL": 0.0}
    intents = raec_401k._build_intents(
        asof_date="2025-02-07",
        targets=targets,
        current=current,
        min_trade_pct=0.5,
        max_weekly_turnover=10.0,
    )
    assert [intent["symbol"] for intent in intents] == ["QUAL", "VTI"]
    assert intents[0]["delta_pct"] == pytest.approx(5.0, abs=0.01)
    assert intents[1]["delta_pct"] == pytest.approx(5.0, abs=0.01)


def test_non_target_sell_is_gated_by_drift_threshold() -> None:
    targets = {"VTI": 50.0, "BIL": 50.0}
    # SPY is a non-target holding at 2% (below DRIFT_THRESHOLD_PCT=3.0)
    current = {"VTI": 48.0, "BIL": 50.0, "SPY": 2.0}
    intents = raec_401k._build_intents(
        asof_date="2025-02-07",
        targets=targets,
        current=current,
        min_trade_pct=0.5,
        max_weekly_turnover=10.0,
    )
    # Expect no SPY SELL intent due to drift gate; only VTI BUY should appear.
    assert [intent["symbol"] for intent in intents] == ["VTI"]
    assert intents[0]["side"] == "BUY"
    assert intents[0]["delta_pct"] == pytest.approx(2.0, abs=0.01)


def test_intent_id_deterministic() -> None:
    intent_id = raec_401k._intent_id(
        asof_date="2025-02-07",
        symbol="VTI",
        side="BUY",
        target_pct=40.0,
    )
    assert (
        intent_id
        == "1c95d73ca6e9ce0418a49d2e2531f019426019fa26912f02ffe41865592acd1c"
    )


def test_runner_dry_run_no_slack(tmp_path: Path) -> None:
    series = _risk_on_series()
    provider = FixturePriceProvider({"VTI": series, "BIL": series})
    state_path = tmp_path / "state" / "strategies" / raec_401k.BOOK_ID / f"{raec_401k.STRATEGY_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_eval_date": "2025-01-31",
                "last_regime": "RISK_OFF",
                "last_known_allocations": {"VTI": 50.0, "BIL": 50.0},
            }
        )
    )

    class _Adapter:
        def send_summary_ticket(self, *args, **kwargs):
            raise AssertionError("adapter should not be called in dry run")

    result = raec_401k.run_strategy(
        asof_date="2025-02-07",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        adapter_override=_Adapter(),
    )
    assert result.should_rebalance
    assert result.posted is False
    assert json.loads(state_path.read_text())["last_eval_date"] == "2025-01-31"


def test_runner_uses_alpaca_allocations_in_non_dry_run(tmp_path: Path) -> None:
    from dataclasses import dataclass as _dataclass
    from execution_v2.alpaca_rebalance_adapter import AlpacaRebalanceAdapter, RebalanceOrderResult

    @_dataclass
    class _FakeAccount:
        equity: str = "100000.00"

    @_dataclass
    class _FakePosition:
        symbol: str = "VTI"
        market_value: str = "50000.00"

    @_dataclass
    class _FakeOrder:
        id: str = "order-001"
        status: str = "accepted"
        side: str = "buy"
        filled_qty: str = "0"
        filled_avg_price: str | None = None
        filled_at: str | None = None
        created_at: str = "2026-02-18T14:00:00Z"
        updated_at: str = "2026-02-18T14:00:00Z"

    class _FakeClient:
        def __init__(self):
            self.submitted = []

        def get_account(self):
            return _FakeAccount()

        def get_all_positions(self):
            return [
                _FakePosition(symbol="SPY", market_value="25000.00"),
                _FakePosition(symbol="VTI", market_value="25000.00"),
            ]

        def submit_order(self, req):
            self.submitted.append(req)
            return _FakeOrder()

    series = _risk_on_series()
    provider = FixturePriceProvider({"VTI": series, "SPY": series, "BIL": series})
    state_path = tmp_path / "state" / "strategies" / raec_401k.BOOK_ID / f"{raec_401k.STRATEGY_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_eval_date": "2025-01-31",
                "last_regime": "RISK_OFF",
                "last_known_allocations": {"BIL": 100.0},
            }
        )
    )

    fake_client = _FakeClient()
    adapter = AlpacaRebalanceAdapter(fake_client)

    result = raec_401k.run_strategy(
        asof_date="2025-02-07",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        adapter_override=adapter,
        post_enabled=True,
    )

    assert result.notice is None
    assert result.should_rebalance


def _write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "positions.csv"
    path.write_text(content)
    return path


def test_parse_schwab_positions_csv_basic(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "Positions for account 123 as of 03/01/2025",
            "Symbol,Description,Security Type,Mkt Val (Market Value)",
            "VTI,Vanguard Total Stock Market ETF,ETF,$12,345.67",
            "QUAL,iShares MSCI USA Quality Factor ETF,ETF,$2,000.00",
            "Account Total,,, $14,345.67",
            "Cash & Cash Investments,Cash & Cash Investments,Cash and Money Market,$0.00",
        ]
    )
    path = _write_csv(tmp_path, content)
    allocations = parse_schwab_positions_csv(path)
    total_mv = 12345.67 + 2000.00
    assert allocations["VTI"] == pytest.approx(round(12345.67 / total_mv * 100, 1))
    assert allocations["QUAL"] == pytest.approx(round(2000.00 / total_mv * 100, 1))


def test_parse_schwab_positions_csv_description_mapping(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "Positions for account 456 as of 03/01/2025",
            "Symbol,Description,Security Type,Mkt Val (Market Value)",
            ",Vanguard Total Stock Market Index Fund,Mutual Fund,$1,000.00",
        ]
    )
    path = _write_csv(tmp_path, content)
    allocations = parse_schwab_positions_csv(path)
    assert allocations == {"VTI": 100.0}


def test_parse_schwab_positions_csv_cash_security_type(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "Positions for account 789 as of 03/01/2025",
            "Symbol,Description,Security Type,Mkt Val (Market Value)",
            ",Cash & Cash Investments,Cash and Money Market,$500.00",
        ]
    )
    path = _write_csv(tmp_path, content)
    allocations = parse_schwab_positions_csv(path)
    assert allocations == {"BIL": 100.0}


def test_parse_schwab_positions_csv_unmappable_row(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "Positions for account 999 as of 03/01/2025",
            "Symbol,Description,Security Type,Mkt Val (Market Value)",
            ",Unknown Fund,Mutual Fund,$500.00",
        ]
    )
    path = _write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="Unknown Fund"):
        parse_schwab_positions_csv(path)


def test_parse_schwab_positions_csv_rounding_stable(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "Positions for account 111 as of 03/01/2025",
            "Symbol,Description,Security Type,Mkt Val (Market Value)",
            "AAA,Alpha Fund,ETF,$2.00",
            "BBB,Bravo Fund,ETF,$1.00",
        ]
    )
    path = _write_csv(tmp_path, content)
    allocations = parse_schwab_positions_csv(path)
    assert allocations == {"AAA": 66.7, "BBB": 33.3}


def test_resolve_csv_source_default_drop_uses_latest(tmp_path: Path) -> None:
    drop_dir = tmp_path / DEFAULT_CSV_DROP_SUBDIR
    drop_dir.mkdir(parents=True, exist_ok=True)
    old_csv = drop_dir / "Schwab-Positions-older.csv"
    new_csv = drop_dir / "Schwab-Positions-newer.csv"
    old_csv.write_text("old")
    new_csv.write_text("new")
    os.utime(old_csv, (1000, 1000))
    os.utime(new_csv, (2000, 2000))

    resolved = _resolve_csv_source("__LATEST__", repo_root=tmp_path)
    assert resolved == new_csv


def test_resolve_csv_source_directory_uses_latest(tmp_path: Path) -> None:
    folder = tmp_path / "drop_here"
    folder.mkdir(parents=True, exist_ok=True)
    csv_a = folder / "a.csv"
    csv_b = folder / "b.csv"
    csv_a.write_text("a")
    csv_b.write_text("b")
    os.utime(csv_a, (500, 500))
    os.utime(csv_b, (700, 700))

    resolved = _resolve_csv_source(str(folder), repo_root=tmp_path)
    assert resolved == csv_b


def test_resolve_strategy_module_v3() -> None:
    strategy = _resolve_strategy_module("v3")
    assert strategy.STRATEGY_ID == "RAEC_401K_V3"
