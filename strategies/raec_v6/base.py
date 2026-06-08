"""BaseStrategyV6 — abstract base class for all v6 strategies.

A strategy is a pure function (signal_state, price_provider, asof) -> StrategyOutput.
Strategies declare a static manifest and implement compute() without side effects.

State and side effects (ledger, Slack, etc.) live in the coordinator, NOT
in the strategy. This is the core architectural shift from BaseRAECStrategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from data.prices import PriceProvider
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategy_output import StrategyOutput


class BaseStrategyV6(ABC):
    """Abstract base for a v6 strategy.

    Subclasses declare a manifest via the `manifest` property and implement
    compute(). compute() must be deterministic and side-effect-free given
    the same inputs.
    """

    @property
    @abstractmethod
    def manifest(self) -> StrategyManifest:
        """Static metadata. Same instance every call."""

    @abstractmethod
    def compute(
        self,
        *,
        signal_state: SignalState,
        price_provider: PriceProvider,
        asof_date: date,
    ) -> StrategyOutput:
        """Compute target weights + conviction for the given as-of date.

        Pure function: no state writes, no logging side effects, no I/O
        outside reading from `price_provider`.

        Returning a StrategyOutput with conviction=0.0 or regime_gate=0.0
        is the correct way to signal "I don't want to be active today" —
        the allocator will route the share to cash.

        Raising an exception is interpreted by the coordinator as a hard
        failure; that strategy's share routes to cash AND a Slack WARNING
        is posted. Strategies should prefer returning conviction=0 over
        raising for known degenerate cases.
        """
