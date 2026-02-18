"""RAEC 401(k) Strategy v5 (AI/future tech momentum rotation, dual anchor, manual execution)."""

from __future__ import annotations

from datetime import date

from data.prices import PriceProvider
from strategies.raec_401k_base import (
    BaseRAECStrategy,
    RegimeSignal,
    RunResult,
    StrategyConfig,
    SymbolFeature,
)
from strategies.raec_401k_registry import register

_CONFIG = StrategyConfig(
    strategy_id="RAEC_401K_V5",
    risk_universe=("SOXL", "TECL", "FNGU", "NVDL", "SMH", "IGV", "BOTZ", "WCLD", "HACK", "QQQ", "ARKK", "NVDA", "AMD", "AVGO", "MSFT", "GOOGL"),
    defensive_universe=("TLT", "GLD", "USMV", "IEF", "BIL"),
    fallback_cash_symbol="BIL",
    min_trade_pct=0.5,
    max_weekly_turnover_pct=45.0,
    drift_threshold_pct=1.5,
    target_portfolio_vol=0.22,
    max_single_etf_weight=0.70,
    # Risk-on: top 2, budget 0.40-1.0, base 1.0, crash 0.50, no cash floor
    risk_on_top_n=2,
    risk_on_max_budget=1.0,
    risk_on_min_budget=0.40,
    risk_on_base_budget=1.0,
    risk_on_crash_scale=0.50,
    risk_on_min_cash=0.0,
    # Transition: top 2 risk, budget 0.20-0.70, base 0.65, crash 0.75, top 2 def, 25% def, 5% cash
    transition_top_n_risk=2,
    transition_max_risk_budget=0.70,
    transition_min_risk_budget=0.20,
    transition_base_risk_budget=0.65,
    transition_crash_scale=0.75,
    transition_top_n_defensive=2,
    transition_defensive_budget=0.25,
    transition_min_cash=0.05,
    # Risk-off: top 3 defensive, 80% budget, 20% cash
    risk_off_top_n_defensive=3,
    risk_off_defensive_budget=0.80,
    risk_off_min_cash=0.20,
    ticket_title="RAEC 401(k) AI/Future Tech Rebalance Ticket",
)


class V5Strategy(BaseRAECStrategy):
    """V5 overrides for dual VTI+QQQ anchor and extra QQQ state/ledger fields."""

    def _compute_dual_anchor_signal(
        self,
        vti_series: list[tuple[date, float]],
        qqq_series: list[tuple[date, float]],
    ) -> RegimeSignal:
        vti_sig = self._compute_single_anchor_dict(vti_series)
        qqq_sig = self._compute_single_anchor_dict(qqq_series)

        # Combine: most conservative wins
        if vti_sig["regime"] == "RISK_OFF" or qqq_sig["regime"] == "RISK_OFF":
            regime = "RISK_OFF"
        elif vti_sig["regime"] == "RISK_ON" and qqq_sig["regime"] == "RISK_ON":
            regime = "RISK_ON"
        else:
            regime = "TRANSITION"

        crash_mode = vti_sig["crash_mode"] or qqq_sig["crash_mode"]

        # QQQ circuit breaker at -12%
        if qqq_sig["drawdown_63d"] <= -0.12:
            regime = "RISK_OFF"
            crash_mode = True

        # VTI circuit breaker at -15%
        if vti_sig["drawdown_63d"] <= -0.15:
            regime = "RISK_OFF"
            crash_mode = True

        return RegimeSignal(
            regime=regime,
            close=vti_sig["close"],
            sma50=vti_sig["sma50"],
            sma200=vti_sig["sma200"],
            vol_20d=vti_sig["vol_20d"],
            vol_252d=vti_sig["vol_252d"],
            drawdown_63d=vti_sig["drawdown_63d"],
            trend_up=vti_sig["trend_up"],
            vol_high=vti_sig["vol_high"],
            crash_mode=crash_mode,
            qqq_close=qqq_sig["close"],
            qqq_sma50=qqq_sig["sma50"],
            qqq_sma200=qqq_sig["sma200"],
            qqq_drawdown_63d=qqq_sig["drawdown_63d"],
        )

    def compute_anchor_signal(self, provider: PriceProvider, asof: date) -> RegimeSignal:
        vti_series = self._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
        qqq_series = self._sorted_series(provider.get_daily_close_series("QQQ"), asof=asof)
        return self._compute_dual_anchor_signal(vti_series, qqq_series)

    def _format_signal_block(self, signal: RegimeSignal) -> str:
        drawdown_pct = signal.drawdown_63d * 100.0
        qqq_drawdown_pct = signal.qqq_drawdown_63d * 100.0
        return (
            "Signals (VTI): "
            f"SMA200={signal.sma200:.2f}, SMA50={signal.sma50:.2f}, "
            f"vol20={signal.vol_20d:.4f}, vol252={signal.vol_252d:.4f}, "
            f"dd63={drawdown_pct:.1f}%\n"
            "Signals (QQQ): "
            f"SMA200={signal.qqq_sma200:.2f}, SMA50={signal.qqq_sma50:.2f}, "
            f"dd63={qqq_drawdown_pct:.1f}%"
        )

    def _extra_state_fields(self, signal: RegimeSignal) -> dict:
        return {
            "qqq_close": signal.qqq_close,
            "qqq_sma50": signal.qqq_sma50,
            "qqq_sma200": signal.qqq_sma200,
            "qqq_drawdown_63d": signal.qqq_drawdown_63d,
        }

    def _extra_ledger_signals(self, signal: RegimeSignal) -> dict:
        return {
            "qqq_close": signal.qqq_close,
            "qqq_sma50": signal.qqq_sma50,
            "qqq_sma200": signal.qqq_sma200,
            "qqq_drawdown_63d": signal.qqq_drawdown_63d,
        }


_strategy = register(V5Strategy(_CONFIG))

# ---------------------------------------------------------------------------
# Module-level backward-compatibility shims
# ---------------------------------------------------------------------------

BOOK_ID = _strategy.BOOK_ID
STRATEGY_ID = _strategy.STRATEGY_ID
RISK_UNIVERSE = _strategy.RISK_UNIVERSE
DEFENSIVE_UNIVERSE = _strategy.DEFENSIVE_UNIVERSE
DEFAULT_UNIVERSE = _strategy.DEFAULT_UNIVERSE
FALLBACK_CASH_SYMBOL = _strategy.FALLBACK_CASH_SYMBOL
MIN_TRADE_PCT = _strategy.MIN_TRADE_PCT
MAX_WEEKLY_TURNOVER_PCT = _strategy.MAX_WEEKLY_TURNOVER_PCT
DRIFT_THRESHOLD_PCT = _strategy.DRIFT_THRESHOLD_PCT
TARGET_PORTFOLIO_VOL = _strategy.TARGET_PORTFOLIO_VOL
MAX_SINGLE_ETF_WEIGHT = _strategy.MAX_SINGLE_ETF_WEIGHT

# Functions
_state_path = _strategy._state_path
_load_state = _strategy._load_state
_save_state = _strategy._save_state
_parse_date = _strategy._parse_date
_get_cash_symbol = _strategy._get_cash_symbol
_sorted_series = _strategy._sorted_series
_compute_volatility = _strategy._compute_volatility
_load_symbol_features = _strategy._load_symbol_features
_rank_symbols = _strategy._rank_symbols
_normalize_weights = _strategy._normalize_weights
_apply_weight_cap = _strategy._apply_weight_cap
_inverse_vol_weights = _strategy._inverse_vol_weights
_corr = _strategy._corr
_estimate_portfolio_vol = _strategy._estimate_portfolio_vol
_weights_to_target_pct = _strategy._weights_to_target_pct
_targets_for_regime = _strategy._targets_for_regime
_compute_drift = _strategy._compute_drift
_apply_turnover_cap = _strategy._apply_turnover_cap
_build_intents = _strategy._build_intents
_intent_id = _strategy._intent_id


def _compute_anchor_signal(vti_series, qqq_series):
    """Dual-anchor signal (V5 signature: takes vti + qqq series)."""
    return _strategy._compute_dual_anchor_signal(vti_series, qqq_series)


def _compute_single_anchor(series):
    return _strategy._compute_single_anchor_dict(series)


def run_strategy(**kwargs):
    return _strategy.run_strategy(**kwargs)


def parse_args(argv=None):
    return _strategy.parse_args(argv)


def main(argv=None):
    return _strategy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
