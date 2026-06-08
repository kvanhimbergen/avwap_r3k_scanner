"""Strategy manifest — static metadata declared by each strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


HistoryQuality = Literal["robust", "moderate", "thin"]


@dataclass(frozen=True)
class StrategyManifest:
    """Static metadata for a strategy. Declared once at construction; never varies.

    The allocator uses these to:
    - cap a strategy's share of the book regardless of how good it looks
    - blend the live track record with the backtested prior for thin-history strategies
    - report what asset classes a strategy is allowed to touch
    """

    strategy_id: str
    asset_classes: tuple[str, ...]
    history_quality: HistoryQuality = "robust"
    # Hard upper bound on the allocator share regardless of conviction/skill.
    # 1.0 = no cap. CrisisAlpha uses 0.10; CryptoTrend uses 0.05 until it
    # accumulates 12mo live track record.
    max_share_cap: float = 1.0
    # Bayesian prior for skill tilt during the first ~20 live days (before
    # the rolling Sharpe has enough history). Set to the strategy's out-of-
    # sample backtest Sharpe shrunk by 0.3 (per plan §risks).
    backtest_oos_sharpe: float = 0.0
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
