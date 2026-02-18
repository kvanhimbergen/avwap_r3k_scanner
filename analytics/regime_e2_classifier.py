from __future__ import annotations

from typing import Any

from analytics.regime_e1_features import RegimeFeatureSet

WEIGHT_TREND = 0.30
WEIGHT_VOLATILITY = 0.25
WEIGHT_CREDIT = 0.20
WEIGHT_BREADTH = 0.15
WEIGHT_DRAWDOWN = 0.10

REGIME_RISK_ON_THRESHOLD = 0.65
REGIME_RISK_OFF_THRESHOLD = 0.35

# Normalization parameters
VOL_LOW = 0.10   # annualized vol at which score = 1.0 (calm)
VOL_HIGH = 0.40  # annualized vol at which score = 0.0 (extreme)

TREND_STRONG = 0.05   # SMA50/SMA200 - 1.0 at which score = 1.0
TREND_WEAK = -0.05    # SMA50/SMA200 - 1.0 at which score = 0.0

DRAWDOWN_NONE = 0.0     # no drawdown -> score 1.0
DRAWDOWN_DEEP = -0.20   # 20% drawdown -> score 0.0

CREDIT_Z_BULLISH = 1.5   # tight spreads -> score 1.0
CREDIT_Z_BEARISH = -1.5  # wide spreads -> score 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize_linear(value: float, low: float, high: float) -> float:
    """Map *value* from [low, high] to [0, 1], clamped."""
    if high == low:
        return 0.5
    return _clamp((value - low) / (high - low))


def _trend_component(features: RegimeFeatureSet) -> float:
    """Trend score: SPY SMA50/SMA200 ratio mapped to 0-1."""
    return _normalize_linear(features.trend, TREND_WEAK, TREND_STRONG)


def _volatility_component(features: RegimeFeatureSet) -> float:
    """Volatility score: inverse — low vol = high score."""
    return 1.0 - _normalize_linear(features.volatility, VOL_LOW, VOL_HIGH)


def _credit_component(features: RegimeFeatureSet) -> float:
    """Credit score: positive z (tight spreads) = risk-on."""
    return _normalize_linear(
        features.credit_spread_z, CREDIT_Z_BEARISH, CREDIT_Z_BULLISH
    )


def _breadth_component(features: RegimeFeatureSet) -> float:
    """Breadth score: fraction above 50-SMA, already 0-1."""
    return _clamp(features.breadth)


def _drawdown_component(features: RegimeFeatureSet) -> float:
    """Drawdown score: inverse — shallow drawdown = high score."""
    return _normalize_linear(features.drawdown, DRAWDOWN_DEEP, DRAWDOWN_NONE)


def _regime_label(score: float) -> str:
    if score >= REGIME_RISK_ON_THRESHOLD:
        return "RISK_ON"
    if score >= REGIME_RISK_OFF_THRESHOLD:
        return "NEUTRAL"
    return "RISK_OFF"


def _confidence(score: float) -> float:
    """Higher confidence away from thresholds, lower near boundaries."""
    dist_to_risk_on = abs(score - REGIME_RISK_ON_THRESHOLD)
    dist_to_risk_off = abs(score - REGIME_RISK_OFF_THRESHOLD)
    nearest_dist = min(dist_to_risk_on, dist_to_risk_off)
    return _clamp(1.0 - 2.0 * nearest_dist)


def classify_regime_e2(features: RegimeFeatureSet) -> dict[str, Any]:
    """Multi-factor weighted regime classifier returning continuous score."""
    trend_raw = _trend_component(features)
    vol_raw = _volatility_component(features)
    credit_raw = _credit_component(features)
    breadth_raw = _breadth_component(features)
    drawdown_raw = _drawdown_component(features)

    regime_score = (
        WEIGHT_TREND * trend_raw
        + WEIGHT_VOLATILITY * vol_raw
        + WEIGHT_CREDIT * credit_raw
        + WEIGHT_BREADTH * breadth_raw
        + WEIGHT_DRAWDOWN * drawdown_raw
    )
    regime_score = round(_clamp(regime_score), 6)

    label = _regime_label(regime_score)
    conf = round(_confidence(regime_score), 6)

    factors: dict[str, Any] = {
        "trend": {"raw": round(trend_raw, 6), "weight": WEIGHT_TREND, "weighted": round(WEIGHT_TREND * trend_raw, 6)},
        "volatility": {"raw": round(vol_raw, 6), "weight": WEIGHT_VOLATILITY, "weighted": round(WEIGHT_VOLATILITY * vol_raw, 6)},
        "credit": {"raw": round(credit_raw, 6), "weight": WEIGHT_CREDIT, "weighted": round(WEIGHT_CREDIT * credit_raw, 6)},
        "breadth": {"raw": round(breadth_raw, 6), "weight": WEIGHT_BREADTH, "weighted": round(WEIGHT_BREADTH * breadth_raw, 6)},
        "drawdown": {"raw": round(drawdown_raw, 6), "weight": WEIGHT_DRAWDOWN, "weighted": round(WEIGHT_DRAWDOWN * drawdown_raw, 6)},
    }

    return {
        "regime_label": label,
        "regime_score": regime_score,
        "confidence": conf,
        "factors": factors,
    }
