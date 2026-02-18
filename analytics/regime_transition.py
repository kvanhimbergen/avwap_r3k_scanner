from __future__ import annotations

from typing import Any

DEFAULT_SMOOTHING_DAYS = 5


class RegimeTransitionDetector:
    """Require N consecutive days of a new regime before transitioning.

    Prevents single-day whipsaw by returning the sticky (previous) regime
    during transition periods.
    """

    def __init__(self, smoothing_days: int = DEFAULT_SMOOTHING_DAYS) -> None:
        self.smoothing_days = smoothing_days
        self._history: list[dict[str, Any]] = []
        self._confirmed_regime: str | None = None

    def update(self, raw_regime: str, confidence: float, date: str) -> str:
        """Record a new observation and return the smoothed regime label.

        The first observation is accepted immediately. Subsequent transitions
        require *smoothing_days* consecutive days of the new regime.
        """
        self._history.append({
            "regime": raw_regime,
            "confidence": confidence,
            "date": date,
        })

        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if raw_regime == self._confirmed_regime:
            return self._confirmed_regime

        recent = self._history[-self.smoothing_days :]
        if (
            len(recent) >= self.smoothing_days
            and all(r["regime"] == raw_regime for r in recent)
        ):
            self._confirmed_regime = raw_regime

        return self._confirmed_regime

    def reset(self) -> None:
        """Clear all history and confirmed regime."""
        self._history.clear()
        self._confirmed_regime = None

    def get_transition_state(self) -> dict[str, Any]:
        """Return introspection dict describing current transition state."""
        if not self._history:
            return {
                "current_regime": None,
                "pending_regime": None,
                "consecutive_days": 0,
                "is_transitioning": False,
            }

        current = self._confirmed_regime
        latest_raw = self._history[-1]["regime"]

        if latest_raw == current:
            return {
                "current_regime": current,
                "pending_regime": None,
                "consecutive_days": 0,
                "is_transitioning": False,
            }

        # Count consecutive days of the pending regime from the end
        consecutive = 0
        for entry in reversed(self._history):
            if entry["regime"] == latest_raw:
                consecutive += 1
            else:
                break

        return {
            "current_regime": current,
            "pending_regime": latest_raw,
            "consecutive_days": consecutive,
            "is_transitioning": True,
        }
