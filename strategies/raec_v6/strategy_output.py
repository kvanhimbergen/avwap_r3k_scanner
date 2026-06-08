"""StrategyOutput — what each strategy returns from its pure compute() call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from strategies.raec_v6.manifest import StrategyManifest


@dataclass(frozen=True)
class StrategyOutput:
    """Pure-function output of a strategy's compute() call.

    Strategies do NOT decide their share of the book — they declare what
    they would hold at 100% allocation, their self-rated conviction, and
    a regime gate. The allocator sizes them.

    Invariants (enforced by the allocator, not the strategy):
    - sum(weights.values()) <= 1.0; residual = strategy's own cash
    - 0.0 <= conviction <= 1.0
    - regime_gate in {0.0, 0.5, 1.0}
    - realized_vol_60d > 0 (or 0.0 if not enough history; allocator will fall back)
    """

    weights: Mapping[str, float]
    conviction: float
    regime_gate: float
    realized_vol_60d: float
    manifest: StrategyManifest
    # Optional: diagnostic info for the ledger / dashboard. Not used by the
    # allocator. Strategies may include any JSON-serializable values here.
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.conviction <= 1.0):
            raise ValueError(
                f"conviction must be in [0,1], got {self.conviction} for {self.manifest.strategy_id}"
            )
        if self.regime_gate not in (0.0, 0.5, 1.0):
            raise ValueError(
                f"regime_gate must be 0.0/0.5/1.0, got {self.regime_gate} for {self.manifest.strategy_id}"
            )
        if self.realized_vol_60d < 0.0:
            raise ValueError(
                f"realized_vol_60d must be >= 0, got {self.realized_vol_60d} for {self.manifest.strategy_id}"
            )
        weight_sum = sum(self.weights.values())
        if weight_sum > 1.0 + 1e-6:
            raise ValueError(
                f"weights must sum to <= 1.0, got {weight_sum:.4f} for {self.manifest.strategy_id}"
            )
        for sym, w in self.weights.items():
            if w < 0.0:
                raise ValueError(
                    f"weights must be non-negative (no shorts in v6 — use inverse ETFs), "
                    f"got {sym}={w} for {self.manifest.strategy_id}"
                )
