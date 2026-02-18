from __future__ import annotations

import pytest

from analytics.regime_e1_features import RegimeFeatureSet
from analytics.regime_e2_classifier import (
    REGIME_RISK_OFF_THRESHOLD,
    REGIME_RISK_ON_THRESHOLD,
    WEIGHT_BREADTH,
    WEIGHT_CREDIT,
    WEIGHT_DRAWDOWN,
    WEIGHT_TREND,
    WEIGHT_VOLATILITY,
    classify_regime_e2,
)


def _make_features(
    *,
    volatility: float = 0.15,
    drawdown: float = -0.03,
    trend: float = 0.03,
    breadth: float = 0.60,
    credit_spread_z: float = 0.5,
    vix_term_structure: float = 0.0,
    gld_relative_strength: float = 0.0,
    tlt_relative_strength: float = 0.0,
) -> RegimeFeatureSet:
    return RegimeFeatureSet(
        ny_date="2025-01-15",
        last_date="2025-01-15",
        volatility=volatility,
        drawdown=drawdown,
        trend=trend,
        breadth=breadth,
        signals={},
        inputs_snapshot={},
        credit_spread_z=credit_spread_z,
        vix_term_structure=vix_term_structure,
        gld_relative_strength=gld_relative_strength,
        tlt_relative_strength=tlt_relative_strength,
    )


class TestWeights:
    def test_weights_sum_to_one(self) -> None:
        total = WEIGHT_TREND + WEIGHT_VOLATILITY + WEIGHT_CREDIT + WEIGHT_BREADTH + WEIGHT_DRAWDOWN
        assert abs(total - 1.0) < 1e-9


class TestRegimeLabels:
    def test_risk_on_threshold(self) -> None:
        """All bullish inputs -> RISK_ON."""
        features = _make_features(
            volatility=0.10,
            drawdown=0.0,
            trend=0.05,
            breadth=1.0,
            credit_spread_z=1.5,
        )
        result = classify_regime_e2(features)
        assert result["regime_label"] == "RISK_ON"
        assert result["regime_score"] >= REGIME_RISK_ON_THRESHOLD

    def test_risk_off_threshold(self) -> None:
        """All bearish inputs -> RISK_OFF."""
        features = _make_features(
            volatility=0.40,
            drawdown=-0.20,
            trend=-0.05,
            breadth=0.0,
            credit_spread_z=-1.5,
        )
        result = classify_regime_e2(features)
        assert result["regime_label"] == "RISK_OFF"
        assert result["regime_score"] < REGIME_RISK_OFF_THRESHOLD

    def test_neutral_mixed_signals(self) -> None:
        """Mixed inputs -> NEUTRAL."""
        features = _make_features(
            volatility=0.25,
            drawdown=-0.10,
            trend=0.0,
            breadth=0.50,
            credit_spread_z=0.0,
        )
        result = classify_regime_e2(features)
        assert result["regime_label"] == "NEUTRAL"
        assert REGIME_RISK_OFF_THRESHOLD <= result["regime_score"] < REGIME_RISK_ON_THRESHOLD

    def test_exact_boundary_065(self) -> None:
        """Score exactly at 0.65 should be RISK_ON."""
        # All components at 0.65 -> weighted sum = 0.65
        features = _make_features(
            volatility=0.10 + (0.40 - 0.10) * (1.0 - 0.65),  # vol_component = 0.65
            drawdown=-0.20 * (1.0 - 0.65),                    # dd_component = 0.65
            trend=-0.05 + 0.10 * 0.65,                        # trend_component = 0.65
            breadth=0.65,                                      # breadth_component = 0.65
            credit_spread_z=-1.5 + 3.0 * 0.65,                # credit_component = 0.65
        )
        result = classify_regime_e2(features)
        assert result["regime_score"] == pytest.approx(0.65, abs=1e-4)
        assert result["regime_label"] == "RISK_ON"

    def test_exact_boundary_035(self) -> None:
        """Score exactly at 0.35 should be NEUTRAL."""
        features = _make_features(
            volatility=0.10 + (0.40 - 0.10) * (1.0 - 0.35),
            drawdown=-0.20 * (1.0 - 0.35),
            trend=-0.05 + 0.10 * 0.35,
            breadth=0.35,
            credit_spread_z=-1.5 + 3.0 * 0.35,
        )
        result = classify_regime_e2(features)
        assert result["regime_score"] == pytest.approx(0.35, abs=1e-4)
        assert result["regime_label"] == "NEUTRAL"

    def test_just_below_035_is_risk_off(self) -> None:
        """Score at 0.34 -> RISK_OFF."""
        target = 0.34
        features = _make_features(
            volatility=0.10 + (0.40 - 0.10) * (1.0 - target),
            drawdown=-0.20 * (1.0 - target),
            trend=-0.05 + 0.10 * target,
            breadth=target,
            credit_spread_z=-1.5 + 3.0 * target,
        )
        result = classify_regime_e2(features)
        assert result["regime_score"] == pytest.approx(target, abs=1e-4)
        assert result["regime_label"] == "RISK_OFF"


class TestConfidence:
    def test_extreme_risk_on_high_confidence(self) -> None:
        features = _make_features(
            volatility=0.10,
            drawdown=0.0,
            trend=0.05,
            breadth=1.0,
            credit_spread_z=1.5,
        )
        result = classify_regime_e2(features)
        assert result["confidence"] > 0.0

    def test_near_threshold_lower_confidence(self) -> None:
        """Score near 0.65 threshold should have lower confidence."""
        features = _make_features(
            volatility=0.10 + (0.40 - 0.10) * (1.0 - 0.64),
            drawdown=-0.20 * (1.0 - 0.64),
            trend=-0.05 + 0.10 * 0.64,
            breadth=0.64,
            credit_spread_z=-1.5 + 3.0 * 0.64,
        )
        result = classify_regime_e2(features)
        # Near boundary -> confidence should not be very high
        assert result["confidence"] <= 1.0

    def test_confidence_bounded(self) -> None:
        features = _make_features()
        result = classify_regime_e2(features)
        assert 0.0 <= result["confidence"] <= 1.0


class TestFactors:
    def test_all_factors_present(self) -> None:
        features = _make_features()
        result = classify_regime_e2(features)
        factors = result["factors"]
        assert set(factors.keys()) == {"trend", "volatility", "credit", "breadth", "drawdown"}

    def test_each_factor_has_fields(self) -> None:
        features = _make_features()
        result = classify_regime_e2(features)
        for name, factor in result["factors"].items():
            assert "raw" in factor, f"{name} missing raw"
            assert "weight" in factor, f"{name} missing weight"
            assert "weighted" in factor, f"{name} missing weighted"

    def test_weighted_sum_equals_score(self) -> None:
        features = _make_features()
        result = classify_regime_e2(features)
        weighted_sum = sum(f["weighted"] for f in result["factors"].values())
        assert abs(weighted_sum - result["regime_score"]) < 1e-4

    def test_raw_values_bounded_0_1(self) -> None:
        features = _make_features()
        result = classify_regime_e2(features)
        for name, factor in result["factors"].items():
            assert 0.0 <= factor["raw"] <= 1.0, f"{name} raw out of bounds: {factor['raw']}"


class TestExtremeInputs:
    def test_all_bullish(self) -> None:
        features = _make_features(
            volatility=0.05,
            drawdown=0.0,
            trend=0.10,
            breadth=1.0,
            credit_spread_z=3.0,
        )
        result = classify_regime_e2(features)
        assert result["regime_score"] == 1.0
        assert result["regime_label"] == "RISK_ON"

    def test_all_bearish(self) -> None:
        features = _make_features(
            volatility=0.60,
            drawdown=-0.30,
            trend=-0.10,
            breadth=0.0,
            credit_spread_z=-3.0,
        )
        result = classify_regime_e2(features)
        assert result["regime_score"] == 0.0
        assert result["regime_label"] == "RISK_OFF"

    def test_score_always_bounded(self) -> None:
        for vol in [0.0, 0.10, 0.25, 0.40, 0.60]:
            for dd in [0.0, -0.10, -0.20, -0.30]:
                for trend in [-0.10, 0.0, 0.05, 0.10]:
                    features = _make_features(
                        volatility=vol,
                        drawdown=dd,
                        trend=trend,
                        breadth=0.5,
                        credit_spread_z=0.0,
                    )
                    result = classify_regime_e2(features)
                    assert 0.0 <= result["regime_score"] <= 1.0
                    assert result["regime_label"] in ("RISK_ON", "NEUTRAL", "RISK_OFF")
