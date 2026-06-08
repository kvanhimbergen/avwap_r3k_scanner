"""ThematicConviction strategy.

Picks top-K thematic ETFs (AI / robotics / cyber / cloud / space) using
each theme's momentum *z-score vs its own trailing history* as the gate.
Without the z-score, momentum scores can't be compared across themes
with different vol regimes; with it, a moderately-up cyber theme can
still trigger conviction if it's unusually strong relative to its own
recent record.

Why: This replaces V5's raw-score gate. V5's bug: in a calm market,
even the "best" theme had low absolute momentum, but the strategy still
bought it — buying lukewarm names is the canonical "thematic" trap.
The z-score gate forces "only buy when something is actually breaking
out for the theme."

Conviction = average z-score of picked themes, squashed to [0, 1].
A picked set with z=2.5 each → conviction near 1.0. z barely above
threshold → conviction near 0.3.

Regime gate:
- 1.0 always at the strategy level (themes don't depend on macro regime
  as strongly as broad equity does — they trend on their own news cycle).
  The allocator's correlation derate will catch correlated co-movement
  with EquityLeveragedMomentum during shocks.

History quality: marked "moderate" because most theme ETFs have 3-6
years of history. Cap at 0.25 share until live track record accumulates.
"""

from __future__ import annotations

import math
from datetime import date

from data.prices import PriceProvider
from strategies.raec_v6 import asset_classes as ac
from strategies.raec_v6.base import BaseStrategyV6
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategy_output import StrategyOutput


_THEMES = ac.get_symbols_in_class("theme")


_MANIFEST = StrategyManifest(
    strategy_id="V6_THEMATIC_CONVICTION",
    asset_classes=("theme",),
    history_quality="moderate",
    max_share_cap=0.25,
    backtest_oos_sharpe=0.4,
    description="Top-K themes by momentum z-score; gate on z > threshold.",
    tags=("themes", "conviction", "z_score"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 520) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _momentum_3mo(closes: list[float]) -> float | None:
    if len(closes) < 63:
        return None
    if closes[-63] <= 0:
        return None
    return (closes[-1] / closes[-63]) - 1.0


def _momentum_zscore(closes: list[float], samples: int = 50) -> float | None:
    """Z-score of current 3mo momentum vs trailing 252d of rolling 3mo
    momenta of the same symbol.

    Returns None if too little history (need ~315 trading days = 252 +
    3mo lookback).
    """
    if len(closes) < 315:
        return None
    current = _momentum_3mo(closes)
    if current is None:
        return None
    step = max(1, 252 // samples)
    history: list[float] = []
    # Sample rolling 3mo momenta over the trailing 252 trading days.
    for offset in range(252, 63, -step):
        end = len(closes) - offset + 63
        if end < 63:
            continue
        win = closes[end - 63 : end]
        if win[0] > 0:
            history.append(win[-1] / win[0] - 1.0)
    if len(history) < 10:
        return None
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / (len(history) - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd <= 0:
        return 0.0
    return (current - mean) / sd


def _annualized_vol(closes: list[float], window: int = 60) -> float:
    if len(closes) < window:
        return 0.0
    rs: list[float] = []
    for i in range(len(closes) - window, len(closes)):
        if i > 0 and closes[i - 1] > 0:
            rs.append(closes[i] / closes[i - 1] - 1.0)
    if len(rs) < 5:
        return 0.0
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


class ThematicConviction(BaseStrategyV6):
    def __init__(
        self,
        *,
        top_k: int = 3,
        z_threshold: float = 0.5,
        max_single_weight: float = 0.30,
    ) -> None:
        self._top_k = top_k
        self._z_threshold = z_threshold
        self._max_single_weight = max_single_weight

    @property
    def manifest(self) -> StrategyManifest:
        return _MANIFEST

    def compute(
        self,
        *,
        signal_state: SignalState,
        price_provider: PriceProvider,
        asof_date: date,
    ) -> StrategyOutput:
        scored: list[tuple[str, float]] = []
        vols: dict[str, float] = {}
        for sym in _THEMES:
            closes = _closes_up_to(price_provider, sym, asof_date)
            z = _momentum_zscore(closes)
            if z is None:
                continue
            scored.append((sym, z))
            vol = _annualized_vol(closes)
            if vol > 0:
                vols[sym] = vol

        if not scored:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_themes_with_history"},
            )

        scored.sort(key=lambda kv: -kv[1])
        # Z-threshold gate: must be unusually strong vs its own history.
        eligible = [(s, z) for s, z in scored if z >= self._z_threshold]
        picked = eligible[: self._top_k]

        if not picked:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "no_themes_above_z_threshold",
                    "z_threshold": self._z_threshold,
                    "best_z": scored[0][1] if scored else None,
                    "all_z": scored,
                },
            )

        usable = [(s, vols[s]) for s, _ in picked if s in vols]
        if not usable:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_vol_data"},
            )

        inv = [(s, 1.0 / v) for s, v in usable]
        total_inv = sum(w for _, w in inv)
        raw = {s: w / total_inv for s, w in inv}
        capped = {s: min(w, self._max_single_weight) for s, w in raw.items()}

        # Conviction: mean of picked z-scores, squashed to [0, 1].
        mean_z = sum(z for _, z in picked) / len(picked)
        conviction = 1.0 / (1.0 + math.exp(-(mean_z - 1.0)))

        basket_vol = sum(vols[s] for s, _ in picked if s in vols) / max(1, len(usable))

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=1.0,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "picked": [{"symbol": s, "z": z} for s, z in picked],
                "mean_z": mean_z,
                "z_threshold": self._z_threshold,
            },
        )
