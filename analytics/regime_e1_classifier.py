from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analytics.regime_e1_features import RegimeFeatureSet

VOL_HIGH = 0.30
VOL_MODERATE = 0.20
DRAWDOWN_STRESSED = -0.20
DRAWDOWN_RISK_OFF = -0.10
TREND_DOWN = -0.02
TREND_UP = 0.02
BREADTH_STRONG = 0.55
BREADTH_WEAK = 0.45


@dataclass(frozen=True)
class RegimeClassification:
    regime_label: str
    confidence: float
    reason_codes: list[str]
    signals: dict[str, Any]
    inputs_snapshot: dict[str, Any]


def _confidence(base: float, count: int, cap: float) -> float:
    value = base + 0.1 * count
    return min(cap, round(value, 3))


def classify_regime(feature_set: RegimeFeatureSet) -> RegimeClassification:
    vol = feature_set.volatility
    drawdown = feature_set.drawdown
    trend = feature_set.trend
    breadth = feature_set.breadth

    stressed_reasons: list[str] = []
    if vol >= VOL_HIGH:
        stressed_reasons.append("vol_high")
    if drawdown <= DRAWDOWN_STRESSED:
        stressed_reasons.append("drawdown_deep")
    if trend <= TREND_DOWN:
        stressed_reasons.append("trend_down")

    if (vol >= VOL_HIGH and (drawdown <= DRAWDOWN_STRESSED or trend <= TREND_DOWN)) or drawdown <= DRAWDOWN_STRESSED:
        confidence = _confidence(0.7, len(stressed_reasons), 1.0)
        return RegimeClassification(
            regime_label="STRESSED",
            confidence=confidence,
            reason_codes=stressed_reasons,
            signals=feature_set.signals,
            inputs_snapshot=feature_set.inputs_snapshot,
        )

    risk_off_reasons: list[str] = []
    if vol >= VOL_MODERATE:
        risk_off_reasons.append("vol_elevated")
    if drawdown <= DRAWDOWN_RISK_OFF:
        risk_off_reasons.append("drawdown_moderate")
    if trend < 0:
        risk_off_reasons.append("trend_negative")
    if breadth <= BREADTH_WEAK:
        risk_off_reasons.append("breadth_weak")

    if risk_off_reasons:
        confidence = _confidence(0.5, len(risk_off_reasons), 0.9)
        return RegimeClassification(
            regime_label="RISK_OFF",
            confidence=confidence,
            reason_codes=risk_off_reasons,
            signals=feature_set.signals,
            inputs_snapshot=feature_set.inputs_snapshot,
        )

    risk_on_reasons: list[str] = []
    if vol <= VOL_MODERATE:
        risk_on_reasons.append("vol_calm")
    if drawdown > DRAWDOWN_RISK_OFF:
        risk_on_reasons.append("drawdown_shallow")
    if trend >= TREND_UP:
        risk_on_reasons.append("trend_positive")
    if breadth >= BREADTH_STRONG:
        risk_on_reasons.append("breadth_strong")

    if (
        vol <= VOL_MODERATE
        and drawdown > DRAWDOWN_RISK_OFF
        and trend >= TREND_UP
        and breadth >= BREADTH_STRONG
    ):
        confidence = _confidence(0.6, len(risk_on_reasons), 0.9)
        return RegimeClassification(
            regime_label="RISK_ON",
            confidence=confidence,
            reason_codes=risk_on_reasons,
            signals=feature_set.signals,
            inputs_snapshot=feature_set.inputs_snapshot,
        )

    return RegimeClassification(
        regime_label="NEUTRAL",
        confidence=0.4,
        reason_codes=["mixed_signals"],
        signals=feature_set.signals,
        inputs_snapshot=feature_set.inputs_snapshot,
    )
