"""SingleNameMomentum strategy.

Top-K curated mega-cap names by composite momentum score. Earnings-gated
in live mode (skip names with earnings within ~2 trading days). Capped
hard at max_share_cap=0.15 — single-name idiosyncratic risk means this
strategy can't dominate the book even when it looks great.

Per-symbol cap of 0.10 is applied by the allocator (vs 0.25 for ETFs)
because a single META-style earnings blowup is a 25% drawdown in that
name in one day. The allocator detects single names by their absence
from asset_classes.yaml.

Why curated, not scanner-driven:
- Mega-caps have multi-year history → backtest is honest
- Mid/small caps in the scanner output have survivorship issues
- The user's thesis is "outsized bets on conviction," not "scrape every
  small-cap breakout"
- Sector cap (max 3 per sector) forces diversification at the universe
  level so the strategy can't degenerate into pure tech

Conviction = sigmoid of top pick's momentum z-score vs its own 252d
history. Same shape as EquityLeveragedMomentum.

Regime gate:
- cross_asset_trend["equity_us_broad"] > 1.0 → 1.0
- ≥ 0.0 → 0.5
- else → 0.0
"""

from __future__ import annotations

import math
from datetime import date

from data.prices import PriceProvider
from strategies.raec_v6.base import BaseStrategyV6
from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.signals.earnings_gate import (
    names_near_earnings_backtest,
    names_near_earnings_live,
)
from strategies.raec_v6.single_name_universe import (
    SECTOR_MAP,
    UNIVERSE,
    apply_sector_cap,
)
from strategies.raec_v6.strategy_output import StrategyOutput


# Strategy modes for earnings-gate backend selection. Live mode reads
# the scanner-maintained cache; backtest mode uses the PIT calendar
# (currently empty — gate effectively disabled in backtest, accepted
# limitation).
MODE_LIVE = "live"
MODE_BACKTEST = "backtest"


_MANIFEST = StrategyManifest(
    strategy_id="V6_SINGLE_NAME_MOMENTUM",
    asset_classes=("equity_single_name",),  # synthetic class — not in taxonomy
    history_quality="moderate",  # 5y backtest available but no earnings gate
    max_share_cap=0.15,
    backtest_oos_sharpe=0.5,  # rough — will be calibrated post-backtest
    description="Top-K curated mega-cap names by momentum; earnings-gated; sector-cap 3/sector.",
    tags=("single_name", "momentum", "conviction"),
)


def _closes_up_to(provider: PriceProvider, sym: str, asof: date, n: int = 280) -> list[float]:
    series = provider.get_daily_close_series(sym)
    closes = [c for d, c in series if d <= asof]
    return closes[-n:]


def _momentum_score(closes: list[float]) -> float | None:
    """Composite momentum: 6m return + 12m return + 50d slope-pct."""
    if len(closes) < 260:
        return None
    last = closes[-1]
    if last <= 0:
        return None
    six_mo = closes[-126]
    twelve_mo = closes[-252]
    if six_mo <= 0 or twelve_mo <= 0:
        return None
    six_mo_ret = (last / six_mo) - 1.0
    twelve_mo_ret = (last / twelve_mo) - 1.0
    window = closes[-50:]
    n = len(window)
    mean_x = (n - 1) / 2.0
    mean_y = sum(window) / n
    num = sum((i - mean_x) * (window[i] - mean_y) for i in range(n))
    den = sum((i - mean_x) ** 2 for i in range(n))
    slope = (num / den) if den > 0 else 0.0
    slope_pct = slope / mean_y if mean_y > 0 else 0.0
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


def _historical_scores(provider: PriceProvider, sym: str, asof: date) -> list[float]:
    """Sample of the symbol's score across the trailing 252 days for z-score."""
    closes = _closes_up_to(provider, sym, asof, n=520)
    out: list[float] = []
    step = 5
    if len(closes) < 260 + step:
        return out
    for end in range(260, len(closes), step):
        s = _momentum_score(closes[:end])
        if s is not None:
            out.append(s)
    return out


def _zscore(provider: PriceProvider, sym: str, asof: date, current: float) -> float:
    hist = _historical_scores(provider, sym, asof)
    if len(hist) < 10:
        return 0.0
    mean = sum(hist) / len(hist)
    var = sum((x - mean) ** 2 for x in hist) / (len(hist) - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd <= 0:
        return 0.0
    return (current - mean) / sd


class SingleNameMomentum(BaseStrategyV6):
    def __init__(
        self,
        *,
        top_k: int = 5,
        max_single_weight: float = 0.40,  # within the strategy's slice
        mode: str = MODE_LIVE,
    ) -> None:
        if mode not in (MODE_LIVE, MODE_BACKTEST):
            raise ValueError(f"mode must be {MODE_LIVE!r} or {MODE_BACKTEST!r}, got {mode!r}")
        self._top_k = top_k
        self._max_single_weight = max_single_weight
        self._mode = mode

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
        scores: list[tuple[str, float]] = []
        vols: dict[str, float] = {}
        for sym in UNIVERSE:
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
                diagnostics={"reason": "no_scored_names"},
            )

        # Earnings gate.
        candidate_syms = [s for s, _ in scores]
        if self._mode == MODE_LIVE:
            flagged = names_near_earnings_live(candidate_syms)
        else:
            flagged = names_near_earnings_backtest(candidate_syms, asof=asof_date)
        gated_scores = [(s, sc) for s, sc in scores if s not in flagged]

        gated_scores.sort(key=lambda kv: -kv[1])
        ranked = [s for s, _ in gated_scores if _ > 0]
        # Sector cap: no more than 3 names from any one sector.
        picked = apply_sector_cap(ranked, top_k=self._top_k)

        if not picked:
            return StrategyOutput(
                weights={},
                conviction=0.0,
                regime_gate=0.5,
                realized_vol_60d=0.0,
                manifest=self.manifest,
                diagnostics={
                    "reason": "no_picks_post_gates",
                    "earnings_flagged": sorted(flagged),
                    "positive_count": sum(1 for _, s in gated_scores if s > 0),
                },
            )

        # Inverse-vol weights within picks.
        usable: list[tuple[str, float]] = [(s, vols[s]) for s in picked if s in vols]
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

        # Regime gate from cross-asset equity trend.
        eq_trend = signal_state.cross_asset_trend.get("equity_us_broad", 0.0)
        if eq_trend > 1.0:
            gate = 1.0
        elif eq_trend >= 0.0:
            gate = 0.5
        else:
            gate = 0.0

        # Conviction = sigmoid of top pick's z-score (centered at 1.0).
        top_sym, top_score = gated_scores[0]
        z = _zscore(price_provider, top_sym, asof_date, top_score)
        conviction = 1.0 / (1.0 + math.exp(-(z - 1.0)))

        basket_vol = sum(vols[s] for s in picked if s in vols) / max(1, len(usable))

        return StrategyOutput(
            weights=capped,
            conviction=conviction,
            regime_gate=gate,
            realized_vol_60d=basket_vol,
            manifest=self.manifest,
            diagnostics={
                "picked": [{"symbol": s, "sector": SECTOR_MAP.get(s)} for s in picked],
                "top_z": z,
                "earnings_flagged": sorted(flagged),
                "mode": self._mode,
            },
        )
