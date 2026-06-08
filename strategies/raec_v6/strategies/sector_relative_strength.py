"""SectorRelativeStrength strategy.

Picks top-K US sector ETFs by relative strength vs SPY over a 3-month
window. Inverse-vol weighted within the picked set.

Relative strength here = sector_3mo_return - SPY_3mo_return. Positive RS
means the sector has outperformed the broad market over the period;
negative means underperformed.

Conviction = dispersion (top RS minus median RS of the picked set).
A clearly leading sector boosts conviction; tight cluster lowers it.

Regime gate:
- 1.0 if cross_asset_trend["equity_us_broad"] >= 0 (sectors of a non-falling
  market generally still rotate)
- 0.5 if marginally negative
- 0.0 if clearly negative (let inverse/crisis strategies own the down-tape)
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


_SECTORS = ac.get_symbols_in_class("sector")
_BENCHMARK = "SPY"


_MANIFEST = StrategyManifest(
    strategy_id="V6_SECTOR_RS",
    asset_classes=("sector",),
    history_quality="robust",
    max_share_cap=0.30,
    backtest_oos_sharpe=0.5,
    description="Top-K sectors by 3mo RS vs SPY, inverse-vol weighted.",
    tags=("rotation", "sector", "relative_strength"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 90) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _three_month_return(closes: list[float]) -> float | None:
    if len(closes) < 63:
        return None
    start = closes[-63]
    last = closes[-1]
    if start <= 0:
        return None
    return (last / start) - 1.0


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


class SectorRelativeStrength(BaseStrategyV6):
    def __init__(
        self,
        *,
        top_k: int = 4,
        max_single_weight: float = 0.30,
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
        # Benchmark return.
        spy_closes = _closes_up_to(price_provider, _BENCHMARK, asof_date, n=90)
        spy_ret = _three_month_return(spy_closes)
        if spy_ret is None:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_benchmark_data"},
            )

        # Per-sector RS.
        rs: list[tuple[str, float]] = []
        vols: dict[str, float] = {}
        for sym in _SECTORS:
            closes = _closes_up_to(price_provider, sym, asof_date, n=90)
            r = _three_month_return(closes)
            if r is None:
                continue
            rs.append((sym, r - spy_ret))
            vol = _annualized_vol(closes)
            if vol > 0:
                vols[sym] = vol

        if not rs:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_sector_data"},
            )

        rs.sort(key=lambda kv: -kv[1])
        # Only pick sectors with positive RS — losing sectors aren't a momentum bet.
        picked = [(s, score) for s, score in rs if score > 0][: self._top_k]
        if not picked:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.5,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "no_positive_rs",
                    "all_rs": rs,
                },
            )

        usable = [(s, vols[s]) for s, _ in picked if s in vols]
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
        capped = {s: min(w, self._max_single_weight) for s, w in raw.items()}

        # Regime gate from cross-asset trend.
        eq_trend = signal_state.cross_asset_trend.get("equity_us_broad", 0.0)
        if eq_trend >= 0.0:
            regime_gate = 1.0
        elif eq_trend >= -1.0:
            regime_gate = 0.5
        else:
            regime_gate = 0.0

        # Conviction from RS dispersion (sigmoid centered at 5% dispersion).
        # Use lower-median index so dispersion is well-defined for even-length
        # lists (avoids collapsing to 0 when len==2).
        rs_scores = sorted([score for _, score in picked])
        top_rs = rs_scores[-1]
        med_rs = rs_scores[(len(rs_scores) - 1) // 2]
        dispersion = top_rs - med_rs
        conviction = 1.0 / (1.0 + math.exp(-(dispersion - 0.05) * 20))

        basket_vol = sum(vols[s] for s, _ in picked if s in vols) / max(1, len(usable))

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=regime_gate,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "picked": [{"symbol": s, "rs": rs_v} for s, rs_v in picked],
                "spy_3mo_return": spy_ret,
                "dispersion": dispersion,
                "eq_trend": eq_trend,
            },
        )
