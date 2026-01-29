"""
Execution V2 – Entry suppression helpers (one-shot per session).
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from execution_v2.state_store import StateStore


@dataclass(frozen=True)
class OneShotConfig:
    enabled: bool = False
    reset_mode: str = "cooldown"
    cooldown_minutes: int = 120

    @classmethod
    def from_env(cls) -> "OneShotConfig":
        return cls(
            enabled=os.getenv("ONE_SHOT_PER_SYMBOL_ENABLED", "0").strip()
            in {"1", "true", "TRUE", "yes", "YES"},
            reset_mode=os.getenv("ONE_SHOT_RESET_MODE", "cooldown").strip().lower(),
            cooldown_minutes=int(os.getenv("ONE_SHOT_COOLDOWN_MINUTES", "120")),
        )


@dataclass(frozen=True)
class OneShotDecision:
    blocked: bool
    reason: str | None = None


def evaluate_one_shot(
    *,
    store: StateStore,
    date_ny: str,
    strategy_id: str,
    symbol: str,
    now_ts: float,
    config: OneShotConfig,
) -> OneShotDecision:
    if not config.enabled:
        return OneShotDecision(blocked=False, reason=None)

    record = store.get_entry_fill(date_ny, strategy_id, symbol)
    if record is None:
        return OneShotDecision(blocked=False, reason=None)

    reset_mode = config.reset_mode
    if reset_mode == "cooldown":
        cooldown_sec = max(config.cooldown_minutes, 0) * 60
        try:
            filled_ts = float(record["filled_ts"])
        except Exception:
            filled_ts = now_ts
        if now_ts - filled_ts >= cooldown_sec:
            return OneShotDecision(blocked=False, reason=None)
        return OneShotDecision(blocked=True, reason="one_shot_cooldown_active")
    if reset_mode == "session":
        return OneShotDecision(blocked=True, reason="one_shot_session_blocked")

    return OneShotDecision(blocked=True, reason=f"one_shot_reset_mode_unknown:{reset_mode}")
