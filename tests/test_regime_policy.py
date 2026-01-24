from __future__ import annotations

from analytics.regime_policy import regime_to_throttle


def test_regime_policy_mapping() -> None:
    risk_on = regime_to_throttle("RISK_ON", 0.9)
    assert risk_on["risk_multiplier"] == 1.0
    assert risk_on["max_new_positions_multiplier"] == 1.0
    assert risk_on["reasons"] == []

    neutral = regime_to_throttle("NEUTRAL", 0.9)
    assert neutral["risk_multiplier"] == 0.6
    assert neutral["max_new_positions_multiplier"] == 0.7
    assert neutral["reasons"] == []

    risk_off = regime_to_throttle("RISK_OFF", 0.9)
    assert risk_off["risk_multiplier"] == 0.2
    assert risk_off["max_new_positions_multiplier"] == 0.3
    assert risk_off["reasons"] == []

    missing = regime_to_throttle(None, None)
    assert missing["risk_multiplier"] == 0.0
    assert missing["max_new_positions_multiplier"] == 0.0
    assert missing["reasons"] == ["missing_regime"]


def test_regime_policy_low_confidence_haircut() -> None:
    throttled = regime_to_throttle("RISK_OFF", 0.59)
    assert throttled["risk_multiplier"] == 0.1
    assert throttled["max_new_positions_multiplier"] == 0.15
    assert throttled["reasons"] == ["low_confidence_haircut"]
