"""BondCarry strategy.

Three sub-bets in one pure function:
1. Duration bet from the yield-curve signal — long TLT/EDV when
   yields are falling (signal > +1); long TBT (inverse-treasury) when
   yields are rising hard (signal < -1).
2. Credit-spread bet from the credit signal — long HYG/JNK when spreads
   tightening (signal > +1); avoid credit when widening.
3. Short-end carry — always hold a small SHY/SGOV slug as base income
   when the directional bets are weak.

Conviction = magnitude of the dominant signal (yield-curve or credit).
Regime gate = 1.0 always (bonds work in any regime, just differently).
max_share_cap = 0.30 (meaningful diversifier but not dominant).

Universe: SHY, IEF, TLT, EDV, TBT, HYG, JNK, LQD, BIL, SGOV.
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
    strategy_id="V6_BOND_CARRY",
    asset_classes=("bond_short", "bond_mid", "bond_long", "bond_inverse", "credit"),
    history_quality="robust",
    # Cap lowered from 0.30 to 0.10 after Phase C calibration:
    # BondCarry's low basket vol (~3.5%) inflates its risk-parity share,
    # but its absolute return is low and its "diversification" failed
    # exactly when needed (2022 — bonds and equities both got crushed
    # by Fed hikes). At cap 0.10 the strategy is a tactical participant
    # in real bond regimes (curve breakouts, credit shifts) rather than
    # a structural ballast that drags returns in equity bull markets.
    max_share_cap=0.10,
    backtest_oos_sharpe=0.4,
    description="Yield-curve + credit-spread directional bonds, with short-end carry base.",
    tags=("bonds", "carry", "duration", "credit"),
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


class BondCarry(BaseStrategyV6):
    def __init__(
        self,
        *,
        duration_signal_threshold: float = 1.0,
        credit_signal_threshold: float = 1.0,
        max_single_weight: float = 0.50,
    ) -> None:
        self._duration_threshold = duration_signal_threshold
        self._credit_threshold = credit_signal_threshold
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
        yc = signal_state.yield_curve_signal
        cs = signal_state.credit_spread_signal

        candidates: list[str] = []
        # Duration bet
        if yc is not None:
            if yc > self._duration_threshold:
                candidates.append("TLT")
                if yc > 2.0:
                    candidates.append("EDV")  # extra long when very positive
            elif yc < -self._duration_threshold:
                candidates.append("TBT")
        # Credit bet
        if cs is not None and cs > self._credit_threshold:
            candidates.append("HYG")
            if cs > 2.0:
                candidates.append("JNK")
        # Base short-end carry. Always include unless we're aggressively
        # tilting elsewhere — provides positive baseline yield.
        if not candidates:
            candidates.extend(["SHY", "IEF"])
        else:
            candidates.append("SHY")

        # De-dup while preserving order.
        unique = list(dict.fromkeys(candidates))

        # Inverse-vol weights within the picked set.
        usable: list[tuple[str, float]] = []
        for sym in unique:
            closes = _closes_up_to(price_provider, sym, asof_date)
            vol = _annualized_vol(closes)
            if vol > 0:
                usable.append((sym, vol))

        if not usable:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "no_vol_data", "yc": yc, "cs": cs},
            )

        inv = [(s, 1.0 / v) for s, v in usable]
        total_inv = sum(w for _, w in inv)
        raw = {s: w / total_inv for s, w in inv}
        capped = {s: min(w, self._max_single_weight) for s, w in raw.items()}

        # Conviction = sigmoid of max(|yc|, |cs|) - threshold.
        signal_mag = max(abs(yc) if yc is not None else 0.0, abs(cs) if cs is not None else 0.0)
        conviction = 1.0 / (1.0 + math.exp(-(signal_mag - self._duration_threshold) * 2))

        basket_vol = sum(v for _, v in usable) / len(usable)

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=1.0,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "yc": yc,
                "cs": cs,
                "picked": list(capped.keys()),
                "signal_mag": signal_mag,
            },
        )
