"""Base class and config for RAEC 401(k) momentum-rotation strategies (V3+)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable

from data.prices import PriceProvider, get_default_price_provider
from execution_v2 import book_ids, book_router
from execution_v2.schwab_manual_adapter import slack_post_enabled
from utils.atomic_write import atomic_write_text


# ---------------------------------------------------------------------------
# Shared dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeSignal:
    regime: str
    close: float
    sma50: float
    sma200: float
    vol_20d: float
    vol_252d: float
    drawdown_63d: float
    trend_up: bool
    vol_high: bool
    crash_mode: bool
    qqq_close: float = 0.0
    qqq_sma50: float = 0.0
    qqq_sma200: float = 0.0
    qqq_drawdown_63d: float = 0.0


@dataclass(frozen=True)
class SymbolFeature:
    symbol: str
    close: float
    mom_3m: float
    mom_6m: float
    mom_12m: float
    vol_20d: float
    vol_252d: float
    drawdown_63d: float
    score: float
    returns_window: tuple[float, ...]


@dataclass(frozen=True)
class RunResult:
    asof_date: str
    regime: str
    targets: dict[str, float]
    intents: list[dict]
    should_rebalance: bool
    posting_enabled: bool
    posted: bool
    notice: str | None


# ---------------------------------------------------------------------------
# Strategy configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyConfig:
    # Identity
    strategy_id: str
    book_id: str = book_ids.SCHWAB_401K_MANUAL

    # Universe
    risk_universe: tuple[str, ...] = ()
    defensive_universe: tuple[str, ...] = ()
    fallback_cash_symbol: str = "BIL"

    # Trading
    min_trade_pct: float = 0.5
    max_weekly_turnover_pct: float = 40.0
    drift_threshold_pct: float = 1.5
    target_portfolio_vol: float = 0.18
    max_single_etf_weight: float = 0.60

    # Risk-on
    risk_on_top_n: int = 2
    risk_on_max_budget: float = 1.0
    risk_on_min_budget: float = 0.40
    risk_on_base_budget: float = 1.0
    risk_on_crash_scale: float = 0.60
    risk_on_min_cash: float = 0.0

    # Transition
    transition_top_n_risk: int = 2
    transition_max_risk_budget: float = 0.70
    transition_min_risk_budget: float = 0.20
    transition_base_risk_budget: float = 0.65
    transition_crash_scale: float = 0.75
    transition_top_n_defensive: int = 2
    transition_defensive_budget: float = 0.25
    transition_min_cash: float = 0.05

    # Risk-off
    risk_off_top_n_defensive: int = 3
    risk_off_defensive_budget: float = 0.80
    risk_off_min_cash: float = 0.20

    # Display
    ticket_title: str = "RAEC 401(k) Rebalance Ticket"


# ---------------------------------------------------------------------------
# Base strategy class
# ---------------------------------------------------------------------------

class BaseRAECStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    # -- Identity properties (backward compat) --------------------------------

    @property
    def BOOK_ID(self) -> str:
        return self.config.book_id

    @property
    def STRATEGY_ID(self) -> str:
        return self.config.strategy_id

    @property
    def RISK_UNIVERSE(self) -> tuple[str, ...]:
        return self.config.risk_universe

    @property
    def DEFENSIVE_UNIVERSE(self) -> tuple[str, ...]:
        return self.config.defensive_universe

    @property
    def DEFAULT_UNIVERSE(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.config.risk_universe, *self.config.defensive_universe]))

    @property
    def FALLBACK_CASH_SYMBOL(self) -> str:
        return self.config.fallback_cash_symbol

    @property
    def MIN_TRADE_PCT(self) -> float:
        return self.config.min_trade_pct

    @property
    def MAX_WEEKLY_TURNOVER_PCT(self) -> float:
        return self.config.max_weekly_turnover_pct

    @property
    def DRIFT_THRESHOLD_PCT(self) -> float:
        return self.config.drift_threshold_pct

    @property
    def TARGET_PORTFOLIO_VOL(self) -> float:
        return self.config.target_portfolio_vol

    @property
    def MAX_SINGLE_ETF_WEIGHT(self) -> float:
        return self.config.max_single_etf_weight

    # -- State persistence ----------------------------------------------------

    def _state_path(self, repo_root: Path) -> Path:
        return repo_root / "state" / "strategies" / self.BOOK_ID / f"{self.STRATEGY_ID}.json"

    @staticmethod
    def _load_state(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    @staticmethod
    def _save_state(path: Path, state: dict) -> None:
        payload = json.dumps(state, sort_keys=True, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, payload)

    # -- Ledger ---------------------------------------------------------------

    def _write_raec_ledger(
        self,
        result: RunResult,
        *,
        repo_root: Path,
        targets: dict[str, float],
        current_allocations: dict[str, float],
        signals: dict[str, Any],
        momentum_scores: list[dict[str, Any]],
        build_git_sha: str | None = None,
    ) -> None:
        ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / self.STRATEGY_ID
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / f"{result.asof_date}.jsonl"
        record = {
            "record_type": "RAEC_REBALANCE_EVENT",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ny_date": result.asof_date,
            "book_id": self.BOOK_ID,
            "strategy_id": self.STRATEGY_ID,
            "regime": result.regime,
            "should_rebalance": result.should_rebalance,
            "rebalance_trigger": "daily",
            "targets": targets,
            "current_allocations": current_allocations,
            "intent_count": len(result.intents),
            "intents": result.intents,
            "signals": signals,
            "momentum_scores": momentum_scores,
            "portfolio_vol_target": self.TARGET_PORTFOLIO_VOL,
            "portfolio_vol_realized": None,
            "posted": result.posted,
            "notice": result.notice,
            "build_git_sha": build_git_sha,
        }
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    # -- Date / rounding helpers ----------------------------------------------

    @staticmethod
    def _parse_date(raw: str) -> date:
        return datetime.strptime(raw, "%Y-%m-%d").date()

    @staticmethod
    def _round_pct(value: float) -> float:
        return round(float(value), 1)

    # -- Intent ID ------------------------------------------------------------

    def _intent_id(
        self,
        *,
        asof_date: str,
        symbol: str,
        side: str,
        target_pct: float,
    ) -> str:
        canonical = {
            "book_id": self.BOOK_ID,
            "strategy_id": self.STRATEGY_ID,
            "asof_date": asof_date,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "target_pct": self._round_pct(target_pct),
        }
        packed = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(packed.encode("utf-8")).hexdigest()

    # -- Cash / universe helpers ----------------------------------------------

    def _get_cash_symbol(self, provider: PriceProvider) -> str:
        series = provider.get_daily_close_series("BIL")
        if series:
            return "BIL"
        return self.FALLBACK_CASH_SYMBOL

    def _universe(self, cash_symbol: str) -> list[str]:
        symbols = [sym for sym in self.DEFAULT_UNIVERSE if sym != "BIL"]
        symbols.append(cash_symbol)
        return symbols

    # -- Series / feature helpers ---------------------------------------------

    @staticmethod
    def _sorted_series(series: Iterable[tuple[date, float]], *, asof: date) -> list[tuple[date, float]]:
        filtered = [(day, close) for day, close in series if day <= asof]
        filtered.sort(key=lambda item: item[0])
        return filtered

    @staticmethod
    def _compute_volatility(returns: list[float]) -> float:
        if len(returns) < 2:
            raise ValueError("insufficient returns for volatility")
        return stdev(returns) * math.sqrt(252)

    def _compute_single_anchor_dict(self, series: list[tuple[date, float]]) -> dict:
        closes = [close for _, close in series]
        if len(closes) < 253:
            raise ValueError("insufficient price history for regime computation")

        close = closes[-1]
        sma50 = sum(closes[-50:]) / 50
        sma200 = sum(closes[-200:]) / 200
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        vol_20d = self._compute_volatility(returns[-20:])
        vol_252d = self._compute_volatility(returns[-252:])
        drawdown_63d = (close / max(closes[-63:])) - 1.0
        trend_up = close > sma200 and sma50 > sma200
        vol_high = vol_20d > vol_252d * 1.10
        crash_mode = drawdown_63d <= -0.08 or close < sma200

        if trend_up and drawdown_63d > -0.04 and not vol_high:
            regime = "RISK_ON"
        elif close > sma200 and drawdown_63d > -0.08:
            regime = "TRANSITION"
        else:
            regime = "RISK_OFF"

        return {
            "regime": regime,
            "close": close,
            "sma50": sma50,
            "sma200": sma200,
            "vol_20d": vol_20d,
            "vol_252d": vol_252d,
            "drawdown_63d": drawdown_63d,
            "trend_up": trend_up,
            "vol_high": vol_high,
            "crash_mode": crash_mode,
        }

    def _compute_single_anchor_signal(self, series: list[tuple[date, float]]) -> RegimeSignal:
        """Compute anchor from a single series (VTI) with -15% circuit breaker."""
        sig = self._compute_single_anchor_dict(series)
        regime = sig["regime"]
        crash_mode = sig["crash_mode"]

        # Circuit breaker: VTI drawdown > 15% forces RISK_OFF
        if sig["drawdown_63d"] <= -0.15:
            regime = "RISK_OFF"
            crash_mode = True

        return RegimeSignal(
            regime=regime,
            close=sig["close"],
            sma50=sig["sma50"],
            sma200=sig["sma200"],
            vol_20d=sig["vol_20d"],
            vol_252d=sig["vol_252d"],
            drawdown_63d=sig["drawdown_63d"],
            trend_up=sig["trend_up"],
            vol_high=sig["vol_high"],
            crash_mode=crash_mode,
        )

    # -- Hooks (overridable by subclasses) ------------------------------------

    def compute_anchor_signal(self, provider: PriceProvider, asof: date) -> RegimeSignal:
        """Default: single VTI anchor with -15% circuit breaker."""
        vti_series = self._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
        return self._compute_single_anchor_signal(vti_series)

    def _format_signal_block(self, signal: RegimeSignal) -> str:
        drawdown_pct = signal.drawdown_63d * 100.0
        return (
            "Signals: "
            f"SMA200={signal.sma200:.2f}, SMA50={signal.sma50:.2f}, "
            f"vol20={signal.vol_20d:.4f}, vol252={signal.vol_252d:.4f}, "
            f"dd63={drawdown_pct:.1f}%"
        )

    def _extra_state_fields(self, signal: RegimeSignal) -> dict:
        return {}

    def _extra_ledger_signals(self, signal: RegimeSignal) -> dict:
        return {}

    # -- Feature computation --------------------------------------------------

    @staticmethod
    def _feature_from_series(symbol: str, series: list[tuple[date, float]]) -> SymbolFeature | None:
        closes = [close for _, close in series]
        if len(closes) < 127:
            return None
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        if len(returns) < 20:
            return None

        close = closes[-1]
        mom_6m = (close / closes[-127]) - 1.0
        mom_3m = (close / closes[-64]) - 1.0 if len(closes) >= 64 else mom_6m
        mom_12m = (close / closes[-253]) - 1.0 if len(closes) >= 253 else mom_6m
        vol_20d = BaseRAECStrategy._compute_volatility(returns[-20:])
        if len(returns) >= 252:
            vol_252d = BaseRAECStrategy._compute_volatility(returns[-252:])
        else:
            vol_252d = BaseRAECStrategy._compute_volatility(returns)
        drawdown_63d = (close / max(closes[-63:])) - 1.0 if len(closes) >= 63 else (close / max(closes)) - 1.0
        score = ((mom_6m * 0.65) + (mom_12m * 0.35)) / max(vol_20d, 0.06)
        returns_window = tuple(float(value) for value in returns[-63:])
        return SymbolFeature(
            symbol=symbol,
            close=close,
            mom_3m=mom_3m,
            mom_6m=mom_6m,
            mom_12m=mom_12m,
            vol_20d=vol_20d,
            vol_252d=vol_252d,
            drawdown_63d=drawdown_63d,
            score=score,
            returns_window=returns_window,
        )

    def _load_symbol_features(
        self,
        *,
        provider: PriceProvider,
        asof: date,
        cash_symbol: str,
    ) -> dict[str, SymbolFeature]:
        features: dict[str, SymbolFeature] = {}
        for symbol in self._universe(cash_symbol):
            if symbol == cash_symbol:
                continue
            series = self._sorted_series(provider.get_daily_close_series(symbol), asof=asof)
            feature = self._feature_from_series(symbol, series)
            if feature is None:
                continue
            features[symbol] = feature
        return features

    # -- Ranking / weighting --------------------------------------------------

    @staticmethod
    def _rank_symbols(
        symbols: Iterable[str],
        feature_map: dict[str, SymbolFeature],
        *,
        require_positive_momentum: bool,
    ) -> list[str]:
        ranked: list[SymbolFeature] = []
        for symbol in symbols:
            feature = feature_map.get(symbol)
            if feature is None:
                continue
            if require_positive_momentum and feature.mom_3m <= 0:
                continue
            ranked.append(feature)
        ranked.sort(key=lambda item: (item.score, item.mom_6m, item.mom_12m, item.symbol), reverse=True)
        return [item.symbol for item in ranked]

    @staticmethod
    def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
        cleaned = {symbol: max(0.0, float(weight)) for symbol, weight in weights.items() if float(weight) > 0}
        total = sum(cleaned.values())
        if total <= 0:
            return {}
        return {symbol: weight / total for symbol, weight in cleaned.items()}

    @staticmethod
    def _apply_weight_cap(weights: dict[str, float], cap: float) -> dict[str, float]:
        if not weights:
            return {}
        capped = dict(BaseRAECStrategy._normalize_weights(weights))
        for _ in range(max(3, len(capped) * 4)):
            over = [symbol for symbol, weight in capped.items() if weight > cap + 1e-9]
            if not over:
                break
            excess = sum(capped[symbol] - cap for symbol in over)
            for symbol in over:
                capped[symbol] = cap
            under = [symbol for symbol, weight in capped.items() if weight < cap - 1e-9]
            if not under or excess <= 0:
                break
            under_total = sum(capped[symbol] for symbol in under)
            if under_total <= 0:
                share = excess / len(under)
                for symbol in under:
                    capped[symbol] += share
            else:
                for symbol in under:
                    capped[symbol] += excess * (capped[symbol] / under_total)
            capped = BaseRAECStrategy._normalize_weights(capped)
        return BaseRAECStrategy._normalize_weights(capped)

    def _inverse_vol_weights(self, symbols: list[str], feature_map: dict[str, SymbolFeature]) -> dict[str, float]:
        inverse: dict[str, float] = {}
        for symbol in symbols:
            feature = feature_map[symbol]
            inverse[symbol] = 1.0 / max(feature.vol_20d, 0.08)
        return self._apply_weight_cap(self._normalize_weights(inverse), self.MAX_SINGLE_ETF_WEIGHT)

    # -- Correlation / portfolio vol ------------------------------------------

    @staticmethod
    def _corr(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right) or len(left) < 2:
            return 0.0
        mean_left = sum(left) / len(left)
        mean_right = sum(right) / len(right)
        num = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
        den_left = sum((a - mean_left) ** 2 for a in left)
        den_right = sum((b - mean_right) ** 2 for b in right)
        if den_left <= 0 or den_right <= 0:
            return 0.0
        corr = num / math.sqrt(den_left * den_right)
        return max(-0.99, min(0.99, corr))

    def _estimate_portfolio_vol(self, weights: dict[str, float], feature_map: dict[str, SymbolFeature]) -> float:
        symbols = [symbol for symbol in weights if symbol in feature_map]
        if not symbols:
            return 0.0
        if len(symbols) == 1:
            symbol = symbols[0]
            return abs(weights[symbol]) * feature_map[symbol].vol_20d

        min_window = min(len(feature_map[symbol].returns_window) for symbol in symbols)
        if min_window < 2:
            total_var = 0.0
            for symbol in symbols:
                total_var += (weights[symbol] * feature_map[symbol].vol_20d) ** 2
            return math.sqrt(max(total_var, 0.0))

        annualized_vol: dict[str, float] = {}
        aligned_returns: dict[str, tuple[float, ...]] = {}
        for symbol in symbols:
            seq = feature_map[symbol].returns_window[-min_window:]
            aligned_returns[symbol] = tuple(seq)
            annualized_vol[symbol] = self._compute_volatility(list(seq))

        total_var = 0.0
        for sym_i in symbols:
            for sym_j in symbols:
                wi = float(weights[sym_i])
                wj = float(weights[sym_j])
                corr = self._corr(aligned_returns[sym_i], aligned_returns[sym_j])
                cov = annualized_vol[sym_i] * annualized_vol[sym_j] * corr
                total_var += wi * wj * cov
        return math.sqrt(max(total_var, 0.0))

    # -- Weight -> target pct -------------------------------------------------

    def _weights_to_target_pct(self, weights: dict[str, float], *, cash_symbol: str) -> dict[str, float]:
        normalized = self._normalize_weights(weights)
        if not normalized:
            return {cash_symbol: 100.0}
        targets = {symbol: round(weight * 100.0, 1) for symbol, weight in normalized.items()}
        delta = round(100.0 - sum(targets.values()), 1)
        if abs(delta) >= 0.1:
            if cash_symbol in targets:
                adjust_symbol = cash_symbol
            else:
                adjust_symbol = max(targets, key=lambda symbol: targets[symbol])
            targets[adjust_symbol] = round(targets[adjust_symbol] + delta, 1)
        return {symbol: pct for symbol, pct in targets.items() if pct > 0}

    # -- Regime target computation (config-driven) ----------------------------

    def _risk_on_targets(
        self,
        *,
        signal: RegimeSignal,
        feature_map: dict[str, SymbolFeature],
        cash_symbol: str,
    ) -> dict[str, float]:
        cfg = self.config
        ranked = self._rank_symbols(self.RISK_UNIVERSE, feature_map, require_positive_momentum=True)
        selected = ranked[:cfg.risk_on_top_n]
        if not selected:
            return {cash_symbol: 100.0}
        weights = self._inverse_vol_weights(selected, feature_map)
        basket_vol = self._estimate_portfolio_vol(weights, feature_map)
        vol_scale = min(1.0, cfg.target_portfolio_vol / max(basket_vol, 1e-6))
        crash_scale = cfg.risk_on_crash_scale if signal.crash_mode else 1.0
        risk_budget = min(cfg.risk_on_max_budget, max(cfg.risk_on_min_budget, cfg.risk_on_base_budget * vol_scale * crash_scale))
        scaled = {symbol: weight * risk_budget for symbol, weight in weights.items()}
        cash = max(cfg.risk_on_min_cash, 1.0 - sum(scaled.values()))
        if cash > 1e-9:
            scaled[cash_symbol] = cash
        return self._weights_to_target_pct(scaled, cash_symbol=cash_symbol)

    def _transition_targets(
        self,
        *,
        signal: RegimeSignal,
        feature_map: dict[str, SymbolFeature],
        cash_symbol: str,
    ) -> dict[str, float]:
        cfg = self.config
        ranked_risk = self._rank_symbols(self.RISK_UNIVERSE, feature_map, require_positive_momentum=True)
        selected_risk = ranked_risk[:cfg.transition_top_n_risk]
        scaled: dict[str, float] = {}
        if selected_risk:
            risk_weights = self._inverse_vol_weights(selected_risk, feature_map)
            basket_vol = self._estimate_portfolio_vol(risk_weights, feature_map)
            vol_scale = min(1.0, cfg.target_portfolio_vol / max(basket_vol, 1e-6))
            crash_scale = cfg.transition_crash_scale if signal.crash_mode else 1.0
            risk_budget = min(cfg.transition_max_risk_budget, max(cfg.transition_min_risk_budget, cfg.transition_base_risk_budget * vol_scale * crash_scale))
            for symbol, weight in risk_weights.items():
                scaled[symbol] = scaled.get(symbol, 0.0) + (weight * risk_budget)

        defensive_candidates = [sym for sym in self.DEFENSIVE_UNIVERSE if sym != cash_symbol]
        ranked_defensive = self._rank_symbols(defensive_candidates, feature_map, require_positive_momentum=False)
        selected_defensive = ranked_defensive[:cfg.transition_top_n_defensive]
        if selected_defensive:
            defensive_weights = self._inverse_vol_weights(selected_defensive, feature_map)
            for symbol, weight in defensive_weights.items():
                scaled[symbol] = scaled.get(symbol, 0.0) + (weight * cfg.transition_defensive_budget)

        invested = sum(scaled.values())
        if invested > 1.0:
            scale_factor = 1.0 / invested
            for symbol in list(scaled):
                scaled[symbol] *= scale_factor
            invested = sum(scaled.values())
        scaled[cash_symbol] = max(cfg.transition_min_cash, 1.0 - invested)
        return self._weights_to_target_pct(scaled, cash_symbol=cash_symbol)

    def _risk_off_targets(
        self,
        *,
        signal: RegimeSignal,
        feature_map: dict[str, SymbolFeature],
        cash_symbol: str,
    ) -> dict[str, float]:
        cfg = self.config
        defensive_candidates = [symbol for symbol in self.DEFENSIVE_UNIVERSE if symbol != cash_symbol]
        ranked = self._rank_symbols(defensive_candidates, feature_map, require_positive_momentum=False)
        selected = ranked[:cfg.risk_off_top_n_defensive]
        if not selected:
            return {cash_symbol: 100.0}

        weights = self._inverse_vol_weights(selected, feature_map)
        scaled = {symbol: weight * cfg.risk_off_defensive_budget for symbol, weight in weights.items()}
        scaled[cash_symbol] = max(cfg.risk_off_min_cash, 1.0 - sum(scaled.values()))
        return self._weights_to_target_pct(scaled, cash_symbol=cash_symbol)

    def _targets_for_regime(
        self,
        *,
        signal: RegimeSignal,
        feature_map: dict[str, SymbolFeature],
        cash_symbol: str,
    ) -> dict[str, float]:
        if signal.regime == "RISK_ON":
            return self._risk_on_targets(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)
        if signal.regime == "TRANSITION":
            return self._transition_targets(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)
        return self._risk_off_targets(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    # -- Allocation loading ---------------------------------------------------

    @staticmethod
    def _load_current_allocations(state: dict, universe: set[str]) -> tuple[dict[str, float] | None, str | None]:
        raw = state.get("last_known_allocations")
        if raw is None or not isinstance(raw, dict):
            return None, "no current allocs known"
        filtered: dict[str, float] = {}
        for symbol, pct in raw.items():
            normalized = str(symbol).upper()
            if normalized not in universe:
                continue
            filtered[normalized] = float(pct)
        return filtered, None

    @staticmethod
    def _load_latest_csv_allocations(
        *,
        repo_root: Path,
        universe: set[str],
    ) -> dict[str, float] | None:
        if os.getenv("RAEC_AUTO_SYNC_ALLOCATIONS_FROM_CSV", "1").strip() not in {"1", "true", "TRUE", "yes", "YES"}:
            return None
        try:
            from strategies import raec_401k_allocs

            csv_path = raec_401k_allocs._latest_csv_in_directory(
                repo_root / raec_401k_allocs.DEFAULT_CSV_DROP_SUBDIR
            )
            parsed = raec_401k_allocs.parse_schwab_positions_csv(csv_path)
        except Exception:
            return None

        filtered: dict[str, float] = {}
        for symbol, pct in parsed.items():
            normalized = str(symbol).upper()
            if normalized not in universe:
                continue
            filtered[normalized] = float(pct)
        return filtered or None

    # -- Drift / rebalance logic ----------------------------------------------

    @staticmethod
    def _compute_drift(current: dict[str, float], targets: dict[str, float]) -> dict[str, float]:
        symbols = set(current) | set(targets)
        return {symbol: float(targets.get(symbol, 0.0)) - float(current.get(symbol, 0.0)) for symbol in symbols}

    def _first_eval_of_day(self, asof: date, last_eval: str | None) -> bool:
        if not last_eval:
            return True
        prior = self._parse_date(last_eval)
        return prior != asof

    def _should_rebalance(
        self,
        *,
        asof: date,
        state: dict,
        regime: str,
        targets: dict[str, float],
        current_allocs: dict[str, float] | None,
    ) -> bool:
        if self._first_eval_of_day(asof, state.get("last_eval_date")):
            return True
        if state.get("last_regime") and state.get("last_regime") != regime:
            return True
        if current_allocs is None:
            return False
        drift = self._compute_drift(current_allocs, targets)
        return any(abs(delta) > self.DRIFT_THRESHOLD_PCT for delta in drift.values())

    # -- Turnover / intent building -------------------------------------------

    @staticmethod
    def _apply_turnover_cap(
        deltas: dict[str, float],
        *,
        max_weekly_turnover: float,
    ) -> dict[str, float]:
        buys = [delta for delta in deltas.values() if delta > 0]
        total_buys = sum(abs(delta) for delta in buys)
        if total_buys <= max_weekly_turnover or total_buys == 0:
            return deltas
        scale = max_weekly_turnover / total_buys
        return {symbol: delta * scale for symbol, delta in deltas.items()}

    def _build_intents(
        self,
        *,
        asof_date: str,
        targets: dict[str, float],
        current: dict[str, float],
        min_trade_pct: float | None = None,
        max_weekly_turnover: float | None = None,
    ) -> list[dict]:
        if min_trade_pct is None:
            min_trade_pct = self.MIN_TRADE_PCT
        if max_weekly_turnover is None:
            max_weekly_turnover = self.MAX_WEEKLY_TURNOVER_PCT

        symbols = sorted(set(targets) | set(current))
        deltas = {symbol: targets.get(symbol, 0.0) - current.get(symbol, 0.0) for symbol in symbols}

        non_target_symbols = set(current) - set(targets)
        deltas = {
            symbol: delta
            for symbol, delta in deltas.items()
            if (symbol not in non_target_symbols) or (delta >= 0) or (abs(delta) >= self.DRIFT_THRESHOLD_PCT)
        }
        deltas = {symbol: delta for symbol, delta in deltas.items() if abs(delta) >= min_trade_pct}
        deltas = self._apply_turnover_cap(deltas, max_weekly_turnover=max_weekly_turnover)
        deltas = {symbol: delta for symbol, delta in deltas.items() if abs(delta) >= min_trade_pct}

        intents: list[dict] = []
        for symbol, delta in deltas.items():
            side = "BUY" if delta > 0 else "SELL"
            target_pct = targets.get(symbol, 0.0)
            current_pct = current.get(symbol, 0.0)
            intents.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "delta_pct": delta,
                    "target_pct": target_pct,
                    "current_pct": current_pct,
                    "strategy_id": self.STRATEGY_ID,
                    "intent_id": self._intent_id(
                        asof_date=asof_date,
                        symbol=symbol,
                        side=side,
                        target_pct=target_pct,
                    ),
                }
            )

        sells = sorted((item for item in intents if item["side"] == "SELL"), key=lambda item: item["symbol"])
        buys = sorted((item for item in intents if item["side"] == "BUY"), key=lambda item: item["symbol"])
        return sells + buys

    # -- Ticket formatting ----------------------------------------------------

    @staticmethod
    def _format_top_ranked(symbols: list[str], feature_map: dict[str, SymbolFeature]) -> str:
        if not symbols:
            return "Top momentum: unavailable"
        parts: list[str] = []
        for symbol in symbols:
            feature = feature_map[symbol]
            parts.append(f"{symbol}(score={feature.score:.2f},6m={feature.mom_6m * 100.0:.1f}%)")
        return "Top momentum: " + ", ".join(parts)

    def _build_ticket_message(
        self,
        *,
        asof_date: str,
        regime: str,
        signal: RegimeSignal,
        top_ranked: list[str],
        feature_map: dict[str, SymbolFeature],
        intents: list[dict],
        notice: str | None,
    ) -> str:
        lines = [
            self.config.ticket_title,
            f"Strategy: {self.STRATEGY_ID}",
            f"Book: {self.BOOK_ID}",
            f"As-of (NY): {asof_date}",
            f"Regime: {regime}",
            self._format_signal_block(signal),
            self._format_top_ranked(top_ranked, feature_map),
        ]
        if notice:
            lines.append(f"NOTICE: {notice}")
        lines.append("")
        if intents:
            lines.append("Order intents (sells first):")
            for intent in intents:
                lines.append(
                    "INTENT "
                    f"{intent['intent_id']} | {intent['side']} {intent['symbol']} | "
                    f"delta {intent['delta_pct']:.1f}% | "
                    f"target {intent['target_pct']:.1f}% | "
                    f"current {intent['current_pct']:.1f}%"
                )
        else:
            lines.append("Order intents: none (allocations at target or missing current allocs).")
        lines.append("")
        lines.append("Checklist:")
        lines.append("- [ ] Confirm regime + top momentum roster.")
        lines.append("- [ ] Execute trades manually in Schwab 401(k).")
        lines.append("- [ ] Reply with execution status + intent_id.")
        lines.append("")
        lines.append("Reply protocol: EXECUTED / PARTIAL / SKIPPED / ERROR with intent_id.")
        return "\n".join(lines)

    # -- Main run_strategy template -------------------------------------------

    def run_strategy(
        self,
        *,
        asof_date: str,
        repo_root: Path,
        price_provider: PriceProvider | None = None,
        dry_run: bool = False,
        allow_state_write: bool = False,
        post_enabled: bool | None = None,
        adapter_override: object | None = None,
    ) -> RunResult:
        provider = price_provider or get_default_price_provider(str(repo_root))
        asof = self._parse_date(asof_date)
        cash_symbol = self._get_cash_symbol(provider)
        universe = self._universe(cash_symbol)
        universe_set = set(universe)

        signal = self.compute_anchor_signal(provider, asof)
        feature_map = self._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
        targets = self._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)
        ranked_snapshot = self._rank_symbols(self.RISK_UNIVERSE, feature_map, require_positive_momentum=False)[:5]

        state_path = self._state_path(repo_root)
        state = self._load_state(state_path)
        current_allocs = self._load_latest_csv_allocations(repo_root=repo_root, universe=universe_set)
        notice = None
        if current_allocs is None:
            current_allocs, notice = self._load_current_allocations(state, universe_set)
        if current_allocs is None:
            current_allocs = {symbol: targets[symbol] for symbol in targets}

        should_rebalance = self._should_rebalance(
            asof=asof,
            state=state,
            regime=signal.regime,
            targets=targets,
            current_allocs=None if notice else current_allocs,
        )
        if notice:
            should_rebalance = True

        intents: list[dict] = []
        if should_rebalance and not notice:
            intents = self._build_intents(asof_date=asof_date, targets=targets, current=current_allocs)

        ticket_message = self._build_ticket_message(
            asof_date=asof_date,
            regime=signal.regime,
            signal=signal,
            top_ranked=ranked_snapshot,
            feature_map=feature_map,
            intents=intents,
            notice=notice,
        )

        posting_enabled = slack_post_enabled() if post_enabled is None else post_enabled
        posted = False
        if should_rebalance:
            if dry_run:
                print(ticket_message)
            else:
                adapter = adapter_override or book_router.select_trading_client(self.BOOK_ID)
                summary_intents = intents
                if not intents:
                    summary_intents = [
                        {
                            "symbol": "NOTICE",
                            "side": "INFO",
                            "target_pct": 0.0,
                            "current_pct": 0.0,
                            "delta_pct": 0.0,
                            "strategy_id": self.STRATEGY_ID,
                            "intent_id": self._intent_id(
                                asof_date=asof_date,
                                symbol="NOTICE",
                                side="INFO",
                                target_pct=0.0,
                            ),
                        }
                    ]
                result = adapter.send_summary_ticket(
                    summary_intents,
                    message=ticket_message,
                    ny_date=asof_date,
                    repo_root=repo_root,
                    post_enabled=posting_enabled,
                )
                posted = result.sent > 0

        run_result = RunResult(
            asof_date=asof_date,
            regime=signal.regime,
            targets=targets,
            intents=intents,
            should_rebalance=should_rebalance,
            posting_enabled=posting_enabled,
            posted=posted,
            notice=notice,
        )

        if not dry_run or allow_state_write:
            state.update(
                {
                    "last_eval_date": asof_date,
                    "last_regime": signal.regime,
                    "last_targets": targets,
                }
            )
            state.update(self._extra_state_fields(signal))
            if notice is None:
                state["last_known_allocations"] = current_allocs
            self._save_state(state_path, state)

            signals_dict: dict[str, Any] = {
                "close": signal.close,
                "sma50": signal.sma50,
                "sma200": signal.sma200,
                "vol_20d": signal.vol_20d,
                "vol_252d": signal.vol_252d,
                "drawdown_63d": signal.drawdown_63d,
                "trend_up": signal.trend_up,
                "vol_high": signal.vol_high,
                "crash_mode": signal.crash_mode,
            }
            signals_dict.update(self._extra_ledger_signals(signal))
            self._write_raec_ledger(
                run_result,
                repo_root=repo_root,
                targets=targets,
                current_allocations=current_allocs,
                signals=signals_dict,
                momentum_scores=[
                    {"symbol": s, "score": feature_map[s].score, "mom_6m": feature_map[s].mom_6m}
                    for s in ranked_snapshot
                    if s in feature_map
                ],
            )

        return run_result

    # -- CLI helpers ----------------------------------------------------------

    def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description=f"Run {self.config.ticket_title}.")
        parser.add_argument("--asof", required=True, help="As-of date (YYYY-MM-DD)")
        parser.add_argument("--dry-run", action="store_true", default=False, help="Skip Slack post and ledger write")
        parser.add_argument(
            "--allow-state-write",
            action="store_true",
            default=False,
            help="Allow state updates even in dry-run",
        )
        return parser.parse_args(argv)

    def main(self, argv: list[str] | None = None) -> int:
        args = self.parse_args(argv)
        repo_root = Path(__file__).resolve().parents[1]
        dry_run = args.dry_run or (os.getenv("DRY_RUN", "0") == "1")
        result = self.run_strategy(
            asof_date=args.asof,
            repo_root=repo_root,
            dry_run=dry_run,
            allow_state_write=args.allow_state_write,
        )

        tickets_sent = 1 if result.posted else 0
        if result.posted:
            reason = "sent"
        elif not result.should_rebalance:
            reason = "notice_blocked" if result.notice else "no_rebalance_needed"
        elif dry_run:
            reason = "dry_run"
        elif not result.posting_enabled:
            reason = "posting_disabled"
        else:
            reason = "idempotent_or_adapter_skipped"

        notice_str = (result.notice or "none").replace("\n", " ").strip()
        print(
            "SCHWAB_401K_MANUAL: "
            f"tickets_sent={tickets_sent} "
            f"asof={result.asof_date} "
            f"should_rebalance={int(result.should_rebalance)} "
            f"posting_enabled={int(result.posting_enabled)} "
            f"posted={int(result.posted)} "
            f"reason={reason} "
            f"notice={notice_str}"
        )
        return 0
