from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k


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


def test_intent_id_deterministic() -> None:
    intent_id = raec_401k._intent_id(
        asof_date="2025-02-07",
        symbol="VTI",
        side="BUY",
        target_pct=40.0,
    )
    assert (
        intent_id
        == "1ba8bcba6aa8c881f0a40d72fe9a59ea20dafcce26ac7a110749cbbc2c22abd7"
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
