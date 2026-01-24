from __future__ import annotations

from typing import Any


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def regime_to_throttle(regime_label: str | None, confidence: float | None) -> dict[str, Any]:
    reasons: list[str] = []
    normalized_label = regime_label.upper() if isinstance(regime_label, str) else None
    mapping = {
        "RISK_ON": (1.0, 1.0),
        "NEUTRAL": (0.6, 0.7),
        "RISK_OFF": (0.2, 0.3),
    }

    if normalized_label in mapping:
        risk_multiplier, max_new_positions_multiplier = mapping[normalized_label]
    else:
        risk_multiplier, max_new_positions_multiplier = (0.0, 0.0)
        reasons.append("missing_regime")

    if confidence is not None and confidence < 0.6:
        risk_multiplier *= 0.5
        max_new_positions_multiplier *= 0.5
        reasons.append("low_confidence_haircut")

    return {
        "schema_version": 1,
        "regime_label": regime_label,
        "confidence": confidence,
        "risk_multiplier": _clamp(risk_multiplier),
        "max_new_positions_multiplier": _clamp(max_new_positions_multiplier),
        "reasons": reasons,
    }
