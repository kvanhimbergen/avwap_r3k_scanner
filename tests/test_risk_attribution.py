from __future__ import annotations

from pathlib import Path

from analytics import risk_attribution
from portfolio.risk_controls import RiskControls


def _base_event() -> dict:
    controls = RiskControls(
        risk_multiplier=0.5,
        max_gross_exposure=0.5,
        max_positions=5,
        per_position_cap=0.1,
        throttle_reason="risk_multiplier",
    )
    return risk_attribution.build_attribution_event(
        date_ny="2024-01-02",
        symbol="AAPL",
        baseline_qty=10,
        modulated_qty=5,
        price=100.0,
        account_equity=100_000.0,
        gross_exposure=20_000.0,
        risk_controls=controls,
        risk_control_reasons=["z_reason", "a_reason", "a_reason"],
        throttle_source="PORTFOLIO_THROTTLE",
        throttle_regime_label="NEUTRAL",
        throttle_policy_ref="ledger/PORTFOLIO_THROTTLE/2024-01-02.jsonl",
        drawdown=0.05,
        drawdown_threshold=0.2,
        min_qty=None,
        source="unit_test",
    )


def test_attribution_event_deterministic() -> None:
    first = _base_event()
    second = _base_event()
    assert first == second


def test_decision_id_stable() -> None:
    event = _base_event()
    payload = {
        "date_ny": event["date_ny"],
        "symbol": event["symbol"],
        "baseline_qty": event["baseline"]["qty"],
        "modulated_qty": event["modulated"]["qty"],
        "price": 100.0,
        "source": "unit_test",
        "throttle_source": event["regime"]["source"],
        "throttle_regime_label": event["regime"]["code"],
        "drawdown": event["drawdown_guard"]["drawdown"],
        "drawdown_threshold": event["drawdown_guard"]["threshold"],
    }
    first = risk_attribution.build_decision_id(payload)
    second = risk_attribution.build_decision_id(payload)
    assert first == second


def test_reason_codes_ordered() -> None:
    event = _base_event()
    assert event["reason_codes"] == ["a_reason", "z_reason"]


def test_delta_math_correctness() -> None:
    event = _base_event()
    assert event["delta"]["qty"] == -5
    assert event["delta"]["notional"] == -500.0
    assert event["delta"]["pct_qty"] == -0.5
    assert event["delta"]["pct_notional"] == -0.5


def test_event_preserves_input_quantities() -> None:
    event = _base_event()
    assert event["baseline"]["qty"] == 10
    assert event["modulated"]["qty"] == 5


def test_no_network_imports() -> None:
    source = Path(risk_attribution.__file__).read_text(encoding="utf-8")
    banned = ("requests", "httpx", "urllib3", "aiohttp")
    assert not any(token in source for token in banned)
