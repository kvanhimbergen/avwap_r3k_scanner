"""CrossAssetTrend strategy.

Picks the top-K asset classes by trend score and holds their
representative ETF, inverse-vol weighted within the selected set.

Why: "There's always a bull market somewhere." This strategy is the
diversifier — it doesn't care if the bull is in equities, gold, bonds,
or crypto; it follows whichever asset classes are trending up.

Conviction: scaled by the dispersion of trend scores. When top scores
cluster (one or two clearly leading), conviction is high. When all scores
are middling, conviction collapses.

Regime gate: 1.0 always. This strategy is regime-agnostic by design —
it sells what's going down and buys what's going up at the asset-class
level. The allocator decides if its size should shrink, not the strategy.
"""

from __future__ import annotations

import math
from datetime import date

from data.prices import PriceProvider
from strategies.raec_v6.base import BaseStrategyV6
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.signals.cross_asset_trend import REPRESENTATIVES
from strategies.raec_v6.strategy_output import StrategyOutput


_MANIFEST = StrategyManifest(
    strategy_id="V6_CROSS_ASSET_TREND",
    asset_classes=tuple(REPRESENTATIVES.keys()),
    history_quality="robust",
    max_share_cap=0.40,  # broadest diversifier; can take a big share
    backtest_oos_sharpe=0.6,  # rough prior; will be calibrated by Phase A backtest
    description="Top-K asset classes by trend score; inverse-vol weighted.",
    tags=("trend", "cross_asset", "diversifier"),
)


def _trailing_returns(closes: list[float], window: int) -> list[float]:
    """Daily simple returns over the last `window` closes."""
    if len(closes) < 2:
        return []
    rs: list[float] = []
    start = max(1, len(closes) - window)
    for i in range(start, len(closes)):
        if closes[i - 1] > 0:
            rs.append(closes[i] / closes[i - 1] - 1.0)
    return rs


def _annualized_vol(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


def _closes_up_to(provider: PriceProvider, symbol: str, asof: date) -> list[float]:
    series = provider.get_daily_close_series(symbol)
    return [c for d, c in series if d <= asof]


class CrossAssetTrend(BaseStrategyV6):
    """Top-K asset-class trend follower."""

    def __init__(
        self,
        *,
        top_k: int = 4,
        min_score_to_hold: float = 0.0,
        max_single_weight: float = 0.35,
    ) -> None:
        self._top_k = top_k
        self._min_score_to_hold = min_score_to_hold
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
        trend = signal_state.cross_asset_trend or {}

        # Filter to positive (or above-floor) scores; rank descending.
        eligible = [(cls, s) for cls, s in trend.items() if s > self._min_score_to_hold]
        eligible.sort(key=lambda kv: -kv[1])
        picked = eligible[: self._top_k]

        if not picked:
            # Nothing trending up. Strategy stands down (full cash residual,
            # zero conviction — allocator will route share to cash).
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"eligible_count": 0, "trend_snapshot": dict(trend)},
            )

        # Build representative-ETF picks and compute their 60d vols for
        # inverse-vol weighting.
        symbols: list[tuple[str, float]] = []  # (symbol, vol)
        for cls, _score in picked:
            sym = REPRESENTATIVES.get(cls)
            if not sym:
                continue
            closes = _closes_up_to(price_provider, sym, asof_date)
            vol = _annualized_vol(_trailing_returns(closes, window=60))
            if vol > 0:
                symbols.append((sym, vol))

        if not symbols:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_vol_data"},
            )

        # Inverse-vol weights, normalized to 1, then capped per-symbol with
        # excess routed to cash residual (NOT redistributed — we want the
        # strategy to be honest about how much it wants invested).
        inv = [(s, 1.0 / v) for s, v in symbols]
        total_inv = sum(w for _, w in inv)
        raw = {s: w / total_inv for s, w in inv}
        capped: dict[str, float] = {}
        for s, w in raw.items():
            capped[s] = min(w, self._max_single_weight)

        # Conviction: dispersion of the picked scores (top minus median).
        # If 1 class clearly dominates, dispersion is high → conviction high.
        # If 4 classes have similar scores, dispersion is low → conviction
        # modest but positive (we still want to be invested, just less
        # confident in any single one).
        scores = [s for _, s in picked]
        score_top = max(scores)
        score_mid = sorted(scores)[len(scores) // 2]
        dispersion = score_top - score_mid
        # Squash to [0, 1] via sigmoid centered around dispersion=2.
        conviction = 1.0 / (1.0 + math.exp(-(dispersion - 2.0)))

        # Strategy's own realized vol (of an equal-weight basket of the
        # picks). Used by the allocator's risk-parity sizing.
        # Approximate: average of the picked symbols' individual vols.
        # (Correlation correction lives in the allocator's net-out step.)
        basket_vol = sum(v for _, v in symbols) / len(symbols)

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=1.0,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "picked": [{"class": cls, "score": s} for cls, s in picked],
                "raw_weights": dict(raw),
                "dispersion": dispersion,
            },
        )
