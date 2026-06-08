"""CrisisAlpha strategy.

Activates ONLY when E1 says STRESSED AND SPY vol is at high percentile —
both must be true. When inactive, regime_gate=0 and the strategy
contributes nothing to the book.

Holdings when active: equal-weight basket of inverse-equity ETFs
(PSQ, SDS, SH) + GLD. The thesis: in a real crisis, both equity short
and gold work; combining them diversifies the bet.

Why this is bounded:
- Backtest has 2-3 stressed events in 5y (2020-03, 2022, possibly
  2023). Two events ≠ a strategy.
- max_share_cap=0.10 permanently — even when this strategy "looks
  great" because of a recent shock, it can't dominate the book.
- history_quality="thin" — backtest can't validate it the way it
  validates trend-following strategies.

Regime gate logic:
- E1 label == "STRESSED" AND SPY vol_pct >= 0.85  → gate = 1.0
- E1 label == "STRESSED" AND SPY vol_pct >= 0.65  → gate = 0.5
- otherwise                                        → gate = 0.0

Conviction: when active, conviction is high (0.8) — this strategy is
designed for high-conviction tactical bets, not gradual leans.
"""

from __future__ import annotations

import math
from datetime import date

from data.prices import PriceProvider
from strategies.raec_v6.base import BaseStrategyV6
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategy_output import StrategyOutput


_MANIFEST = StrategyManifest(
    strategy_id="V6_CRISIS_ALPHA",
    asset_classes=("inverse_equity", "metal"),
    history_quality="thin",
    max_share_cap=0.10,  # plan §architecture: hard cap, anecdote not evidence
    backtest_oos_sharpe=0.3,
    description="Inverse-equity + gold; gated by E1=STRESSED and high vol percentile.",
    tags=("crisis", "hedge", "tactical"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 80) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


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


_HOLDINGS = ("PSQ", "SDS", "SH", "GLD")


class CrisisAlpha(BaseStrategyV6):
    def __init__(
        self,
        *,
        vol_pct_full: float = 0.85,
        vol_pct_half: float = 0.65,
    ) -> None:
        self._vol_pct_full = vol_pct_full
        self._vol_pct_half = vol_pct_half

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
        regime = signal_state.regime_label
        spy_vol_pct = signal_state.vol_percentile_252d.get("SPY", 0.0)

        # Gate logic.
        if regime == "STRESSED" and spy_vol_pct >= self._vol_pct_full:
            gate = 1.0
        elif regime == "STRESSED" and spy_vol_pct >= self._vol_pct_half:
            gate = 0.5
        else:
            gate = 0.0

        if gate == 0.0:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "gate_off",
                    "regime_label": regime,
                    "spy_vol_pct": spy_vol_pct,
                },
            )

        # Active: equal-weight the basket, inverse-vol normalized.
        usable: list[tuple[str, float]] = []
        for sym in _HOLDINGS:
            closes = _closes_up_to(price_provider, sym, asof_date)
            vol = _annualized_vol(closes)
            if vol > 0:
                usable.append((sym, vol))

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

        conviction = 0.8  # high-conviction tactical bet

        basket_vol = sum(v for _, v in usable) / len(usable)

        return StrategyOutput(
            weights=raw,
            conviction=conviction,
            regime_gate=gate,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "regime_label": regime,
                "spy_vol_pct": spy_vol_pct,
                "gate": gate,
            },
        )
