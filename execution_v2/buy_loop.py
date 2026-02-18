"""
Execution V2 – Buy Loop
Schedules entry intents from scan candidates using BOH + regime gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import os
from pathlib import Path
import time
from typing import Iterable
import random

import pandas as pd

from execution_v2.boh import boh_confirmed_option2
from execution_v2.config_types import EntryIntent
from config import cfg as scan_cfg
from execution_v2.sizing import SizingConfig, compute_size_shares
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID
from execution_v2 import exits
from portfolio.risk_controls import (
    adjust_order_quantity,
    build_risk_controls,
    resolve_drawdown_guardrail,
    risk_modulation_enabled,
)


@dataclass(frozen=True)
class Candidate:
    symbol: str
    strategy_id: str
    direction: str
    entry_level: float
    stop_loss: float
    target_r2: float
    target_r1: float | None
    dist_pct: float
    price: float
    anchor: str | None = None


REASON_MISSING_MARKET_DATA = "missing_market_data"
REASON_BOH_NOT_CONFIRMED = "boh_not_confirmed"
REASON_INVALID_CANDIDATE_ROW = "invalid_candidate_row"
REASON_EXISTING_OPEN_ORDERS = "existing_open_orders"
REASON_RISK_CONTROLS_BLOCKED = "risk_controls_blocked"
REASON_SECTOR_CAP_BLOCKED = "sector_cap_blocked"
REASON_OTHER_REJECTED = "other_rejected"

_KNOWN_REJECTION_REASONS = {
    REASON_MISSING_MARKET_DATA,
    REASON_BOH_NOT_CONFIRMED,
    REASON_INVALID_CANDIDATE_ROW,
    REASON_EXISTING_OPEN_ORDERS,
    REASON_RISK_CONTROLS_BLOCKED,
    REASON_SECTOR_CAP_BLOCKED,
    REASON_OTHER_REJECTED,
}


@dataclass
class EntryRejectionTelemetry:
    candidates_seen: int = 0
    accepted: int = 0
    rejected: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    first_rejection_reason_by_symbol: dict[str, str] = field(default_factory=dict)

    def record_candidate(self) -> None:
        self.candidates_seen += 1

    def record_accepted(self) -> None:
        self.accepted += 1

    def record_rejected(self, symbol: str | None, reason_code: str) -> None:
        normalized_reason = (
            reason_code if reason_code in _KNOWN_REJECTION_REASONS else REASON_OTHER_REJECTED
        )
        self.rejected += 1
        self.reason_counts[normalized_reason] = self.reason_counts.get(normalized_reason, 0) + 1

        normalized_symbol = (symbol or "").strip().upper()
        if not normalized_symbol:
            return
        if normalized_symbol not in self.first_rejection_reason_by_symbol:
            self.first_rejection_reason_by_symbol[normalized_symbol] = normalized_reason

    def to_decision_payload(
        self,
        *,
        max_rejected_symbols: int = 50,
        include_rejected_symbols: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidates_seen": int(self.candidates_seen),
            "accepted": int(self.accepted),
            "rejected": int(self.rejected),
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "rejected_symbols_truncated": 0,
        }
        if not include_rejected_symbols:
            return payload

        cap = max(0, int(max_rejected_symbols))
        rejected_symbols = [
            {"symbol": symbol, "reason": reason}
            for symbol, reason in self.first_rejection_reason_by_symbol.items()
        ]
        payload["rejected_symbols"] = rejected_symbols[:cap]
        payload["rejected_symbols_truncated"] = max(0, len(rejected_symbols) - cap)
        return payload


class BuyLoopConfig:
    """
    Configuration for buy-loop operations.
    """
    def __init__(
        self,
        *,
        candidates_csv: str = "daily_candidates.csv",
        entry_delay_min_sec: int = 60,
        entry_delay_max_sec: int = 240,
        candidate_ttl_sec: int = 6 * 60 * 60,
        sizing_cfg: SizingConfig | None = None,
    ) -> None:
        self.candidates_csv = candidates_csv
        self.entry_delay_min_sec = entry_delay_min_sec
        self.entry_delay_max_sec = entry_delay_max_sec
        self.candidate_ttl_sec = candidate_ttl_sec
        self.sizing_cfg = sizing_cfg or SizingConfig()


@dataclass(frozen=True)
class EdgeWindowConfig:
    enabled: bool = False
    rechecks: int = 3
    delay_sec: float = 5.0
    proximity_pct: float = 0.002

    @classmethod
    def from_env(cls) -> "EdgeWindowConfig":
        return cls(
            enabled=os.getenv("EDGE_WINDOW_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"},
            rechecks=int(os.getenv("EDGE_WINDOW_RECHECKS", "3")),
            delay_sec=float(os.getenv("EDGE_WINDOW_RECHECK_DELAY_SEC", "5")),
            proximity_pct=float(os.getenv("EDGE_WINDOW_PROXIMITY_PCT", "0.002")),
        )


@dataclass
class EdgeWindowReport:
    enabled: bool = False
    engaged_symbols: list[str] = field(default_factory=list)
    rechecks_attempted: int = 0
    confirmed_symbols: list[str] = field(default_factory=list)

    def mark_engaged(self, symbol: str) -> None:
        if symbol not in self.engaged_symbols:
            self.engaged_symbols.append(symbol)

    def mark_recheck(self) -> None:
        self.rechecks_attempted += 1

    def mark_confirmed(self, symbol: str) -> None:
        if symbol not in self.confirmed_symbols:
            self.confirmed_symbols.append(symbol)

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "engaged_count": len(self.engaged_symbols),
            "engaged_symbols_sample": self.engaged_symbols[:10],
            "rechecks_attempted": self.rechecks_attempted,
            "confirmed_count": len(self.confirmed_symbols),
            "confirmed_symbols_sample": self.confirmed_symbols[:10],
        }


@dataclass(frozen=True)
class EdgeWindowClock:
    now: callable
    sleep: callable


def _default_edge_clock() -> EdgeWindowClock:
    return EdgeWindowClock(now=time.time, sleep=time.sleep)


def _optional_env_int(name: str) -> int | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _optional_env_float(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _deterministic_delay(
    *,
    ny_date: str,
    symbol: str,
    min_sec: float,
    max_sec: float,
) -> float:
    if max_sec <= min_sec:
        return float(min_sec)
    payload = f"{ny_date}|{symbol.upper()}|{min_sec}|{max_sec}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    value = int.from_bytes(digest, "big")
    u = value / float(2**256)
    return float(min_sec) + u * (float(max_sec) - float(min_sec))


def _load_candidates(
    path: str, *, rejection_telemetry: EntryRejectionTelemetry | None = None
) -> list[Candidate]:
    p = Path(path)
    if not p.exists():
        return []

    df = pd.read_csv(p)
    if df.empty:
        return []

    required = {"Symbol", "Entry_Level", "Stop_Loss", "Target_R2", "Entry_DistPct", "Price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Candidates file missing required columns: {sorted(missing)}")

    candidates: list[Candidate] = []
    for _, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        strategy_cell = row.get("Strategy_ID", None)
        if strategy_cell is None or pd.isna(strategy_cell):
            strategy_id = DEFAULT_STRATEGY_ID
        else:
            raw_strategy_id = str(strategy_cell).strip()
            strategy_id = raw_strategy_id or DEFAULT_STRATEGY_ID
        if rejection_telemetry is not None:
            rejection_telemetry.record_candidate()
        if not symbol:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(
                    symbol,
                    REASON_INVALID_CANDIDATE_ROW,
                )
            continue

        direction = str(row.get("Direction", "Long")).strip().title()
        entry_level = float(row["Entry_Level"])
        stop_loss = float(row["Stop_Loss"])
        target_r2 = float(row["Target_R2"])
        target_r1 = None
        if "Target_R1" in row and pd.notna(row["Target_R1"]):
            target_r1 = float(row["Target_R1"])
        dist_pct = float(row["Entry_DistPct"]) if pd.notna(row["Entry_DistPct"]) else 0.0
        price = float(row["Price"])
        anchor = None
        if "Anchor" in row and pd.notna(row["Anchor"]):
            anchor = str(row["Anchor"])

        if entry_level <= 0 or stop_loss <= 0 or target_r2 <= 0:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(
                    symbol,
                    REASON_INVALID_CANDIDATE_ROW,
                )
            continue
        if stop_loss >= target_r2:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(
                    symbol,
                    REASON_INVALID_CANDIDATE_ROW,
                )
            continue

        candidates.append(
            Candidate(
                symbol=symbol,
                strategy_id=strategy_id,
                direction=direction,
                entry_level=entry_level,
                stop_loss=stop_loss,
                target_r2=target_r2,
                target_r1=target_r1,
                dist_pct=dist_pct,
                price=price,
                anchor=anchor,
            )
        )

    return candidates


def load_candidates(path: str) -> list[Candidate]:
    return _load_candidates(path)


def ingest_watchlist_as_candidates(
    store,
    cfg: BuyLoopConfig,
    *,
    rejection_telemetry: EntryRejectionTelemetry | None = None,
) -> list[Candidate]:
    """
    Inserts scan candidates into the candidates table.
    """
    now_ts = time.time()
    candidates = _load_candidates(cfg.candidates_csv, rejection_telemetry=rejection_telemetry)
    for cand in candidates:
        store.upsert_candidate(
            symbol=cand.symbol,
            first_seen_ts=now_ts,
            expires_ts=now_ts + cfg.candidate_ttl_sec,
            pivot_level=cand.entry_level,
            notes=f"scan:{cand.anchor or 'n/a'}",
        )
    return candidates


def _iter_active_candidates(candidates: Iterable[Candidate], active_symbols: set[str]) -> Iterable[Candidate]:
    for cand in candidates:
        if cand.symbol in active_symbols:
            yield cand


def evaluate_and_create_entry_intents(
    store,
    md,
    cfg: BuyLoopConfig,
    account_equity: float,
    created_intents: list[EntryIntent] | None = None,
    *,
    edge_window: EdgeWindowConfig | None = None,
    edge_report: EdgeWindowReport | None = None,
    edge_clock: EdgeWindowClock | None = None,
    rejection_telemetry: EntryRejectionTelemetry | None = None,
) -> int:
    """
    Evaluate scan candidates and create entry intents for BOH-confirmed names.
    """
    if edge_window is None:
        edge_window = EdgeWindowConfig()
    if edge_report is not None:
        edge_report.enabled = edge_window.enabled
    if edge_clock is None:
        edge_clock = _default_edge_clock()
    now_ts = edge_clock.now()
    entry_day = exits.entry_day_from_ts(now_ts)
    exit_cfg = exits.ExitConfig.from_env()
    risk_controls = None
    risk_controls_result = None
    drawdown_value = None
    drawdown_threshold = None
    base_max_positions = (
        _optional_env_int("MAX_LIVE_POSITIONS")
        or _optional_env_int("RISK_BASE_MAX_POSITIONS")
        or 5
    )
    base_max_gross_exposure = (
        _optional_env_float("MAX_LIVE_GROSS_NOTIONAL")
        or _optional_env_float("RISK_BASE_MAX_GROSS_EXPOSURE")
        or float(account_equity)
    )
    repo_root = Path(".")
    gross_exposure = 0.0
    open_positions_count = 0
    try:
        current_positions = list(store.list_positions())
        open_positions_count = len(current_positions)
        gross_exposure = sum(
            abs(float(getattr(pos, "avg_price", 0.0)) * float(getattr(pos, "size_shares", 0.0)))
            for pos in current_positions
        )
    except Exception:
        current_positions = []
    projected_positions_count = open_positions_count
    if risk_modulation_enabled():
        ny_date = exits.entry_day_from_ts(now_ts)
        drawdown_value, drawdown_threshold, _ = resolve_drawdown_guardrail()
        result = build_risk_controls(
            ny_date=ny_date,
            repo_root=repo_root,
            base_max_positions=base_max_positions,
            base_max_gross_exposure=base_max_gross_exposure,
            base_per_position_cap=cfg.sizing_cfg.max_position_pct,
            drawdown=drawdown_value,
            max_drawdown_pct_block=drawdown_threshold,
        )
        risk_controls = result.controls
        risk_controls_result = result
    candidates = ingest_watchlist_as_candidates(
        store,
        cfg,
        rejection_telemetry=rejection_telemetry,
    )
    active_symbols = set(store.list_active_candidates(now_ts))

    created = 0
    for cand in _iter_active_candidates(candidates, active_symbols):
        if cand.direction != "Long":
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_OTHER_REJECTED)
            continue
        if store.get_entry_intent(cand.symbol) is not None:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_EXISTING_OPEN_ORDERS)
            continue
        if (
            risk_controls is not None
            and risk_controls.max_positions is not None
            and projected_positions_count >= int(risk_controls.max_positions)
        ):
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_RISK_CONTROLS_BLOCKED)
            continue

        bars = md.get_last_two_closed_10m(cand.symbol)
        if len(bars) != 2:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_MISSING_MARKET_DATA)
            continue

        boh = boh_confirmed_option2(bars, cand.entry_level)
        if not boh.confirmed and edge_window.enabled:
            if _is_near_pivot(bars[-1], cand.entry_level, edge_window.proximity_pct):
                if edge_report is not None:
                    edge_report.mark_engaged(cand.symbol)
                for _ in range(max(edge_window.rechecks, 0)):
                    if edge_report is not None:
                        edge_report.mark_recheck()
                    if edge_window.delay_sec > 0:
                        edge_clock.sleep(edge_window.delay_sec)
                    bars = md.get_last_two_closed_10m(cand.symbol)
                    if len(bars) != 2:
                        continue
                    boh = boh_confirmed_option2(bars, cand.entry_level)
                    if boh.confirmed:
                        if edge_report is not None:
                            edge_report.mark_confirmed(cand.symbol)
                        break
        if not boh.confirmed:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_BOH_NOT_CONFIRMED)
            continue

        bar_close = None
        try:
            bar_close = float(bars[-1].close)
        except Exception:
            bar_close = None
        price_for_sizing = cand.price
        if bar_close is not None and bar_close > 0:
            price_for_sizing = bar_close
            if cand.price > 0:
                pct_diff = abs(bar_close - cand.price) / cand.price
                if pct_diff >= 0.03:
                    print(
                        "SIZING_PRICE_DRIFT "
                        f"symbol={cand.symbol} csv_price={cand.price} "
                        f"bar_close={bar_close} pct={pct_diff:.4f}"
                    )

        # Phase 5: Correlation-aware sizing (fail-open)
        corr_penalty_value = 0.0
        if getattr(scan_cfg, "CORRELATION_AWARE_SIZING_ENABLED", False):
            try:
                from execution_v2.correlation_sizing import correlation_penalty as _corr_pen, check_sector_cap
                _corr_mod = importlib.import_module("analytics.correlation_matrix")
                compute_rolling_correlation = _corr_mod.compute_rolling_correlation

                open_syms = [
                    str(getattr(pos, "symbol", "")).upper()
                    for pos in current_positions
                ]
                if open_syms:
                    # Build position dicts for sector cap check
                    open_pos_dicts = [
                        {
                            "symbol": str(getattr(pos, "symbol", "")).upper(),
                            "notional": abs(
                                float(getattr(pos, "avg_price", 0.0))
                                * float(getattr(pos, "size_shares", 0.0))
                            ),
                        }
                        for pos in current_positions
                    ]
                    # Sector cap check
                    sector_map = getattr(scan_cfg, "_sector_map", {})
                    cand_sector = sector_map.get(cand.symbol, "")
                    if cand_sector:
                        allowed, reason = check_sector_cap(
                            candidate_sector=cand_sector,
                            open_positions=open_pos_dicts,
                            sector_map=sector_map,
                            max_sector_pct=getattr(scan_cfg, "MAX_SECTOR_EXPOSURE_PCT", 0.3),
                            gross_exposure=gross_exposure,
                        )
                        if not allowed:
                            print(f"CORRELATION_BLOCK symbol={cand.symbol} {reason}")
                            if rejection_telemetry is not None:
                                rejection_telemetry.record_rejected(cand.symbol, REASON_SECTOR_CAP_BLOCKED)
                            continue

                    # Compute correlation penalty
                    daily_bars_for_corr = md.get_daily_bars(cand.symbol)
                    if daily_bars_for_corr is not None and hasattr(daily_bars_for_corr, "__len__") and len(daily_bars_for_corr) > 0:
                        try:
                            all_syms = open_syms + [cand.symbol]
                            # Try to build OHLCV DataFrame from available bars
                            ohlcv_frames = []
                            for sym in all_syms:
                                sym_bars = md.get_daily_bars(sym)
                                if sym_bars is not None and hasattr(sym_bars, "__len__") and len(sym_bars) > 0:
                                    if isinstance(sym_bars, pd.DataFrame):
                                        frame = sym_bars.copy()
                                        frame["Symbol"] = sym
                                        ohlcv_frames.append(frame)
                            if ohlcv_frames:
                                ohlcv_df = pd.concat(ohlcv_frames, ignore_index=True)
                                lookback = getattr(scan_cfg, "CORRELATION_LOOKBACK_DAYS", 60)
                                corr_matrix = compute_rolling_correlation(ohlcv_df, all_syms, lookback_days=lookback)
                                if not corr_matrix.empty:
                                    threshold = getattr(scan_cfg, "CORRELATION_PENALTY_THRESHOLD", 0.6)
                                    corr_penalty_value = _corr_pen(
                                        cand.symbol, open_syms, corr_matrix,
                                        threshold=threshold,
                                    )
                        except Exception as exc:
                            print(f"WARN: correlation penalty computation failed for {cand.symbol}: {exc}")
            except Exception as exc:
                print(f"WARN: correlation-aware sizing failed for {cand.symbol}: {exc}")

        base_size = compute_size_shares(
            account_equity=account_equity,
            price=price_for_sizing,
            dist_pct=abs(cand.dist_pct),
            cfg=cfg.sizing_cfg,
            correlation_penalty=corr_penalty_value,
        )
        if base_size <= 0:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_OTHER_REJECTED)
            continue
        size = base_size
        if risk_controls is not None:
            size = adjust_order_quantity(
                base_qty=base_size,
                price=price_for_sizing,
                account_equity=account_equity,
                risk_controls=risk_controls,
                gross_exposure=gross_exposure,
                min_qty=None,
            )
            if os.getenv("E3_RISK_ATTRIBUTION_WRITE", "0").strip() == "1" and risk_controls_result is not None:
                try:
                    risk_attribution = importlib.import_module("analytics.risk_attribution")
                except Exception as exc:
                    print(f"WARN: risk attribution import failed for {cand.symbol}: {exc}")
                else:
                    try:
                        throttle = risk_controls_result.throttle or {}
                        throttle_regime_label = throttle.get("regime_label")
                        throttle_policy_ref = risk_attribution.resolve_throttle_policy_reference(
                            repo_root=repo_root,
                            ny_date=ny_date,
                            source=risk_controls_result.source,
                        )
                        event = risk_attribution.build_attribution_event(
                            date_ny=ny_date,
                            symbol=cand.symbol,
                            baseline_qty=base_size,
                            modulated_qty=size,
                            price=cand.price,
                            account_equity=account_equity,
                            gross_exposure=gross_exposure,
                            risk_controls=risk_controls,
                            risk_control_reasons=risk_controls_result.reasons,
                            throttle_source=risk_controls_result.source,
                            throttle_regime_label=throttle_regime_label,
                            throttle_policy_ref=throttle_policy_ref,
                            drawdown=drawdown_value,
                            drawdown_threshold=drawdown_threshold,
                            min_qty=None,
                            source="execution_v2.buy_loop",
                        )
                        risk_attribution.write_attribution_event(event)
                    except Exception as exc:
                        print(f"WARN: risk attribution write failed for {cand.symbol}: {exc}")
        if size <= 0:
            if rejection_telemetry is not None:
                reason = REASON_RISK_CONTROLS_BLOCKED if risk_controls is not None else REASON_OTHER_REJECTED
                rejection_telemetry.record_rejected(cand.symbol, reason)
            continue

        daily_bars = md.get_daily_bars(cand.symbol)
        stop_price = exits.compute_stop_price(
            daily_bars,
            entry_day=entry_day,
            buffer_dollars=exit_cfg.stop_buffer_dollars,
        )
        if stop_price is None:
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_MISSING_MARKET_DATA)
            continue
        if not exits.validate_risk(cand.price, stop_price, exit_cfg.max_risk_per_share):
            if rejection_telemetry is not None:
                rejection_telemetry.record_rejected(cand.symbol, REASON_OTHER_REJECTED)
            continue

        deterministic_delay = (
            os.getenv("DRY_RUN", "0").strip() == "1"
            or os.getenv("EXECUTION_V2_DETERMINISTIC_DELAY", "0").strip() == "1"
        )
        if deterministic_delay:
            delay = _deterministic_delay(
                ny_date=entry_day,
                symbol=cand.symbol,
                min_sec=cfg.entry_delay_min_sec,
                max_sec=cfg.entry_delay_max_sec,
            )
        else:
            delay = random.uniform(cfg.entry_delay_min_sec, cfg.entry_delay_max_sec)
        intent = EntryIntent(
            strategy_id=cand.strategy_id,
            symbol=cand.symbol,
            pivot_level=cand.entry_level,
            boh_confirmed_at=boh.confirm_bar_ts or now_ts,
            scheduled_entry_at=now_ts + delay,
            size_shares=size,
            stop_loss=stop_price,
            take_profit=cand.target_r2,
            ref_price=bars[-1].close,
            dist_pct=cand.dist_pct,
        )
        store.put_entry_intent(intent)
        if created_intents is not None:
            created_intents.append(intent)
        created += 1
        projected_positions_count += 1
        gross_exposure += float(size) * float(price_for_sizing)
        if rejection_telemetry is not None:
            rejection_telemetry.record_accepted()

    return created


def _is_near_pivot(bar, pivot_level: float, proximity_pct: float) -> bool:
    if pivot_level <= 0:
        return False

    try:
        close = float(getattr(bar, "close"))
    except Exception:
        try:
            close = float(bar["close"])
        except Exception:
            return False

    distance = abs(close - pivot_level) / pivot_level
    return distance <= max(proximity_pct, 0.0)
