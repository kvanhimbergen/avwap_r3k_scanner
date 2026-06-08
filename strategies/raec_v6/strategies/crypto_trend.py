"""CryptoTrend strategy.

Long IBIT/FBTC (bitcoin) and/or ETHA (ether) when their trend is up;
flip to BITI (inverse bitcoin) on a strong downtrend.

Why: crypto is uncorrelated with most traditional assets (especially in
calm equity regimes), which makes it valuable diversifier exposure when
it's trending. But the spot-ETF history is short (IBIT inception Jan
2024; ~2.5y at backtest end), so this strategy is rate-limited by a low
max_share_cap and history_quality="thin" until a live track record
accumulates.

Activation:
- Long mode: BTC trend signal > +1.0 (sigmoid of (price - SMA200) / SMA200)
- Inverse mode: BTC trend signal < -1.5 (only flip on strong downtrends to
  avoid whipsaws — the inverse ETF (BITI) has carry decay)
- Stand-down: trend in middle band → empty weights, conviction 0

Conviction from trend magnitude × signal-quality-of-ETHA (when ETH and
BTC trends agree, conviction higher).

Regime gate: 1.0 — crypto doesn't depend on equity regime.
max_share_cap: 0.05 until 12mo live track record per plan §risks.
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
    strategy_id="V6_CRYPTO_TREND",
    asset_classes=("crypto", "crypto_inverse"),
    history_quality="thin",  # IBIT only 2y old at backtest end
    max_share_cap=0.05,  # critique §2: cap until live track record exists
    backtest_oos_sharpe=0.5,
    description="Long crypto on trend up; BITI flip on strong downtrend.",
    tags=("crypto", "trend", "thin_history"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 220) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _trend_signal(closes: list[float]) -> float | None:
    """Composite trend: price-vs-SMA200 + 50d slope + 3mo return."""
    if len(closes) < 210:
        return None
    last = closes[-1]
    if last <= 0:
        return None
    sma200 = sum(closes[-200:]) / 200
    if sma200 <= 0:
        return None
    sma50 = sum(closes[-50:]) / 50
    three_mo = closes[-63] if len(closes) >= 63 else None
    if three_mo is None or three_mo <= 0:
        return None
    return (
        (last / sma200 - 1.0) * 10
        + (sma50 / sma200 - 1.0) * 30
        + (last / three_mo - 1.0) * 5
    )


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


class CryptoTrend(BaseStrategyV6):
    def __init__(
        self,
        *,
        long_threshold: float = 1.0,
        inverse_threshold: float = -1.5,
    ) -> None:
        self._long_threshold = long_threshold
        self._inverse_threshold = inverse_threshold

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
        btc_closes = _closes_up_to(price_provider, "IBIT", asof_date)
        eth_closes = _closes_up_to(price_provider, "ETHA", asof_date)
        btc_trend = _trend_signal(btc_closes)
        eth_trend = _trend_signal(eth_closes)

        if btc_trend is None:
            # Thin-history defense: if IBIT doesn't have 210 closes yet,
            # stand down entirely. Don't fall back to BITO (its different-
            # mechanism returns would change the signal's meaning).
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={"reason": "btc_history_too_short"},
            )

        # Long mode.
        if btc_trend > self._long_threshold:
            holdings: list[str] = ["IBIT"]
            if eth_trend is not None and eth_trend > self._long_threshold:
                holdings.append("ETHA")
            mode = "long"
        # Inverse mode (only on strong downtrend — BITI has decay risk).
        elif btc_trend < self._inverse_threshold:
            holdings = ["BITI"]
            mode = "inverse"
        else:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=1.0,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "no_strong_trend",
                    "btc_trend": btc_trend,
                    "eth_trend": eth_trend,
                },
            )

        # Inverse-vol weights.
        usable: list[tuple[str, float]] = []
        for sym in holdings:
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
                diagnostics={"reason": "no_vol_data", "mode": mode},
            )

        inv = [(s, 1.0 / v) for s, v in usable]
        total_inv = sum(w for _, w in inv)
        # Apply a deployed-fraction below 1.0 — crypto strategy declares
        # at most 80% of its own slice in holdings; 20% stays in strategy
        # cash so the basket vol isn't catastrophic for the allocator.
        deployed = 0.80
        raw = {s: deployed * w / total_inv for s, w in inv}

        # Conviction: magnitude of btc_trend, modulated up when eth_trend
        # agrees.
        signal_mag = abs(btc_trend)
        agreement_bonus = 0.0
        if eth_trend is not None and (
            (mode == "long" and eth_trend > 0)
            or (mode == "inverse" and eth_trend < 0)
        ):
            agreement_bonus = 0.2
        conviction = min(1.0, 1.0 / (1.0 + math.exp(-(signal_mag - 1.5))) + agreement_bonus)

        basket_vol = sum(v for _, v in usable) / len(usable)

        return StrategyOutput(
            weights=raw,
            conviction=conviction,
            regime_gate=1.0,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "mode": mode,
                "btc_trend": btc_trend,
                "eth_trend": eth_trend,
                "picked": list(raw.keys()),
            },
        )
