"""EquityLeveragedMomentum strategy.

Top-K momentum across broad-market US equity + sector ETFs, with the option
to use leveraged variants (TQQQ/SOXL/UPRO/TECL/FNGU) gated by vol regime.

Why: V3's role in the prior coordinator — concentrated equity-momentum
exposure that loads up on leverage when vol is calm and de-levers when
vol is elevated. The improvement over V3: the leverage cap here is a
*function* of the SPY vol percentile, not a hardcoded constant.

Leverage gate:
- vol_pct < 0.30 : full leverage allowed (no filter)
- 0.30 <= vol_pct < 0.70 : leveraged ETFs allowed only in top-K with
                            score > 70th percentile of the basket
- vol_pct >= 0.70 : leveraged ETFs excluded entirely

Conviction = z-score of the top pick's momentum vs trailing 252d
distribution of its own momentum scores. Higher z = unusual strength
= higher conviction.

Regime gate:
- cross_asset_trend["equity_us_broad"] > 1.0 : 1.0 (clear uptrend)
- cross_asset_trend["equity_us_broad"] >= 0.0 : 0.5 (marginal)
- else : 0.0 (downtrend — let crisis alpha take over)
"""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from data.prices import PriceProvider
from strategies.raec_v6 import asset_classes as ac
from strategies.raec_v6.base import BaseStrategyV6
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategy_output import StrategyOutput


_LEVERAGED_CLASSES = ("equity_us_lev", "sector_lev")
_RISK_CLASSES = ("equity_us_broad", "equity_us_lev", "sector", "sector_lev")


def _universe_for_classes(classes: Iterable[str]) -> tuple[str, ...]:
    syms: list[str] = []
    for cls in classes:
        try:
            syms.extend(ac.get_symbols_in_class(cls))
        except KeyError:
            continue
    return tuple(dict.fromkeys(syms))  # dedup preserve order


_RISK_UNIVERSE: tuple[str, ...] = _universe_for_classes(_RISK_CLASSES)
_LEVERAGED_SYMBOLS: frozenset[str] = frozenset(
    sym for cls in _LEVERAGED_CLASSES for sym in ac.get_symbols_in_class(cls)
)


_MANIFEST = StrategyManifest(
    strategy_id="V6_EQUITY_LEV_MOMENTUM",
    asset_classes=_RISK_CLASSES,
    history_quality="robust",
    max_share_cap=0.35,
    backtest_oos_sharpe=0.7,
    description="Top-K equity/sector momentum with vol-percentile-gated leverage.",
    tags=("momentum", "equity", "leveraged"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 280) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _momentum_score(closes: list[float]) -> float | None:
    """Composite momentum score from 6m return + 12m return + 50d slope.

    Returns None if <260 trading days of data (need 12m + slope window).
    """
    if len(closes) < 260:
        return None
    last = closes[-1]
    if last <= 0:
        return None
    six_mo = closes[-126] if len(closes) >= 126 else None
    twelve_mo = closes[-252] if len(closes) >= 252 else None
    if six_mo is None or twelve_mo is None or six_mo <= 0 or twelve_mo <= 0:
        return None
    six_mo_ret = (last / six_mo) - 1.0
    twelve_mo_ret = (last / twelve_mo) - 1.0
    # 50d slope: linear regression slope as a fraction-of-price.
    window = closes[-50:]
    n = len(window)
    mean_x = (n - 1) / 2.0
    mean_y = sum(window) / n
    num = sum((i - mean_x) * (window[i] - mean_y) for i in range(n))
    den = sum((i - mean_x) ** 2 for i in range(n))
    slope = (num / den) if den > 0 else 0.0
    slope_pct = slope / mean_y if mean_y > 0 else 0.0
    # Weighted combo (rough — 6m is the strongest signal in cross-section).
    return six_mo_ret * 2.0 + twelve_mo_ret * 1.0 + slope_pct * 100.0


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


def _historical_momentum_scores(provider: PriceProvider, sym: str, asof: date) -> list[float]:
    """Sample of the symbol's momentum score across the trailing 252 days,
    used to compute the z-score of today's score (the conviction signal)."""
    closes = _closes_up_to(provider, sym, asof, n=520)
    scores: list[float] = []
    # Recompute the momentum score every 5 trading days to keep the cost low;
    # 252 / 5 = ~50 samples — enough for a stable z-score estimate.
    step = 5
    if len(closes) < 260 + step:
        return []
    for end in range(260, len(closes), step):
        win = closes[:end]
        s = _momentum_score(win)
        if s is not None:
            scores.append(s)
    return scores


def _zscore_of_top(provider: PriceProvider, sym: str, asof: date, current_score: float) -> float:
    history = _historical_momentum_scores(provider, sym, asof)
    if len(history) < 10:
        return 0.0
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / (len(history) - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd <= 0:
        return 0.0
    return (current_score - mean) / sd


def _filter_leverage_by_vol_regime(
    ranked: list[tuple[str, float]],
    spy_vol_pct: float,
) -> list[tuple[str, float]]:
    """Apply the vol-regime gate: filter out (or trim) leveraged ETFs."""
    if spy_vol_pct < 0.30:
        return ranked  # calm: full leverage allowed
    if spy_vol_pct >= 0.70:
        # Hot: exclude all leveraged.
        return [(s, score) for s, score in ranked if s not in _LEVERAGED_SYMBOLS]
    # Mid: leveraged ETF must be in the top 30% by score.
    if not ranked:
        return ranked
    score_threshold = sorted([sc for _, sc in ranked], reverse=True)[
        min(len(ranked) - 1, max(0, len(ranked) // 3))
    ]
    return [
        (s, score)
        for s, score in ranked
        if s not in _LEVERAGED_SYMBOLS or score >= score_threshold
    ]


class EquityLeveragedMomentum(BaseStrategyV6):
    def __init__(
        self,
        *,
        top_k: int = 5,
        max_single_weight: float = 0.35,
    ) -> None:
        self._top_k = top_k
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
        # Score the full universe.
        scores: list[tuple[str, float]] = []
        vols: dict[str, float] = {}
        for sym in _RISK_UNIVERSE:
            closes = _closes_up_to(price_provider, sym, asof_date)
            score = _momentum_score(closes)
            if score is None:
                continue
            scores.append((sym, score))
            vol = _annualized_vol(closes)
            if vol > 0:
                vols[sym] = vol

        if not scores:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_scored_symbols"},
            )

        # Vol-regime gate on leveraged ETFs. Use SPY vol percentile from
        # signal_state if present; otherwise default to mid regime (0.5)
        # which is conservative.
        spy_vol_pct = signal_state.vol_percentile_252d.get("SPY", 0.5)
        gated = _filter_leverage_by_vol_regime(scores, spy_vol_pct)
        gated.sort(key=lambda kv: -kv[1])

        picked = [(s, score) for s, score in gated if score > 0][: self._top_k]
        if not picked:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "no_positive_after_gate",
                    "spy_vol_pct": spy_vol_pct,
                },
            )

        # Inverse-vol weights within the picked set.
        usable: list[tuple[str, float]] = [(s, vols[s]) for s, _ in picked if s in vols]
        if not usable:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_vol_data"},
            )
        inv = [(s, 1.0 / v) for s, v in usable]
        total_inv = sum(w for _, w in inv)
        raw = {s: w / total_inv for s, w in inv}
        capped: dict[str, float] = {s: min(w, self._max_single_weight) for s, w in raw.items()}

        # Regime gate from cross-asset trend.
        eq_trend = signal_state.cross_asset_trend.get("equity_us_broad", 0.0)
        if eq_trend > 1.0:
            regime_gate = 1.0
        elif eq_trend >= 0.0:
            regime_gate = 0.5
        else:
            regime_gate = 0.0

        # Conviction = z-score of top pick's momentum vs its own history.
        top_sym, top_score = picked[0]
        z = _zscore_of_top(price_provider, top_sym, asof_date, top_score)
        # Squash to [0, 1] via sigmoid centered at z=1 (an above-average score).
        conviction = 1.0 / (1.0 + math.exp(-(z - 1.0)))

        # Realized vol of the basket (avg of components — allocator's correlation
        # derate adjusts for cross-correlation later).
        basket_vol = sum(vols[s] for s, _ in picked if s in vols) / max(1, len(usable))

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=regime_gate,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "picked": [{"symbol": s, "score": sc} for s, sc in picked],
                "spy_vol_pct": spy_vol_pct,
                "top_z": z,
                "eq_trend": eq_trend,
            },
        )
