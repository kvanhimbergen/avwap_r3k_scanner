from __future__ import annotations

from analytics.regime_transition import RegimeTransitionDetector


class TestStickyBehavior:
    def test_alternating_does_not_flip(self) -> None:
        """Alternating RISK_ON/RISK_OFF every day should NOT transition."""
        detector = RegimeTransitionDetector(smoothing_days=5)
        # First observation sets the confirmed regime
        result = detector.update("RISK_ON", 0.8, "2025-01-01")
        assert result == "RISK_ON"

        regimes = ["RISK_OFF", "RISK_ON"] * 5
        for i, regime in enumerate(regimes):
            result = detector.update(regime, 0.7, f"2025-01-{i+2:02d}")
            assert result == "RISK_ON", f"Day {i+2}: expected sticky RISK_ON, got {result}"

    def test_single_day_different_regime_stays_sticky(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        result = detector.update("RISK_OFF", 0.9, "2025-01-02")
        assert result == "RISK_ON"


class TestTransitionAfterNDays:
    def test_flips_after_smoothing_days(self) -> None:
        """5 consecutive RISK_OFF days after RISK_ON should flip on day 5."""
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")

        # Days 2-5: RISK_OFF but not enough consecutive days
        for i in range(1, 5):
            result = detector.update("RISK_OFF", 0.7, f"2025-01-{i+1:02d}")
            assert result == "RISK_ON", f"Day {i+1}: should still be sticky RISK_ON"

        # Day 6: 5th consecutive RISK_OFF -> should flip
        result = detector.update("RISK_OFF", 0.7, "2025-01-06")
        assert result == "RISK_OFF"

    def test_interrupted_transition_resets_count(self) -> None:
        """4 RISK_OFF days then 1 RISK_ON day resets the streak."""
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")

        for i in range(4):
            detector.update("RISK_OFF", 0.7, f"2025-01-{i+2:02d}")

        # Interrupt with RISK_ON
        result = detector.update("RISK_ON", 0.8, "2025-01-06")
        assert result == "RISK_ON"

        # 4 more RISK_OFF — still not enough
        for i in range(4):
            result = detector.update("RISK_OFF", 0.7, f"2025-01-{i+7:02d}")
            assert result == "RISK_ON"

        # 5th consecutive RISK_OFF -> flip
        result = detector.update("RISK_OFF", 0.7, "2025-01-11")
        assert result == "RISK_OFF"

    def test_smoothing_days_1_flips_immediately(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=1)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        result = detector.update("RISK_OFF", 0.7, "2025-01-02")
        assert result == "RISK_OFF"

    def test_first_observation_accepted_immediately(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        result = detector.update("NEUTRAL", 0.5, "2025-01-01")
        assert result == "NEUTRAL"


class TestReset:
    def test_reset_clears_history(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        detector.update("RISK_ON", 0.8, "2025-01-02")

        detector.reset()

        state = detector.get_transition_state()
        assert state["current_regime"] is None
        assert state["consecutive_days"] == 0

    def test_reset_then_new_observation(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        detector.reset()

        result = detector.update("RISK_OFF", 0.9, "2025-02-01")
        assert result == "RISK_OFF"


class TestGetTransitionState:
    def test_empty_state(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        state = detector.get_transition_state()
        assert state == {
            "current_regime": None,
            "pending_regime": None,
            "consecutive_days": 0,
            "is_transitioning": False,
        }

    def test_stable_state(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        detector.update("RISK_ON", 0.8, "2025-01-02")
        state = detector.get_transition_state()
        assert state["current_regime"] == "RISK_ON"
        assert state["pending_regime"] is None
        assert state["is_transitioning"] is False

    def test_during_transition(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=5)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        detector.update("RISK_OFF", 0.7, "2025-01-02")
        detector.update("RISK_OFF", 0.7, "2025-01-03")

        state = detector.get_transition_state()
        assert state["current_regime"] == "RISK_ON"
        assert state["pending_regime"] == "RISK_OFF"
        assert state["consecutive_days"] == 2
        assert state["is_transitioning"] is True

    def test_after_transition_completes(self) -> None:
        detector = RegimeTransitionDetector(smoothing_days=3)
        detector.update("RISK_ON", 0.8, "2025-01-01")
        for i in range(3):
            detector.update("RISK_OFF", 0.7, f"2025-01-{i+2:02d}")

        state = detector.get_transition_state()
        assert state["current_regime"] == "RISK_OFF"
        assert state["pending_regime"] is None
        assert state["is_transitioning"] is False
