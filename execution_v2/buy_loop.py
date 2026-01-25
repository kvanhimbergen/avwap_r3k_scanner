"""
Execution V2 – Buy Loop
Schedules entry intents from scan candidates using BOH + regime gating.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
from time import time
from typing import Iterable
import random

import pandas as pd

from execution_v2.boh import boh_confirmed_option2
from execution_v2.config_types import EntryIntent
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
    direction: str
    entry_level: float
    stop_loss: float
    target_r2: float
    target_r1: float | None
    dist_pct: float
    price: float
    anchor: str | None = None


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


def _load_candidates(path: str) -> list[Candidate]:
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
        if not symbol:
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
            continue
        if stop_loss >= target_r2:
            continue

        candidates.append(
            Candidate(
                symbol=symbol,
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


def ingest_watchlist_as_candidates(store, cfg: BuyLoopConfig) -> list[Candidate]:
    """
    Inserts scan candidates into the candidates table.
    """
    now_ts = time()
    candidates = _load_candidates(cfg.candidates_csv)
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


def evaluate_and_create_entry_intents(store, md, cfg: BuyLoopConfig, account_equity: float) -> int:
    """
    Evaluate scan candidates and create entry intents for BOH-confirmed names.
    """
    now_ts = time()
    exit_cfg = exits.ExitConfig.from_env()
    risk_controls = None
    risk_controls_result = None
    drawdown_value = None
    drawdown_threshold = None
    repo_root = Path(".")
    if risk_modulation_enabled():
        ny_date = exits.entry_day_from_ts(now_ts)
        drawdown_value, drawdown_threshold, _ = resolve_drawdown_guardrail()
        result = build_risk_controls(
            ny_date=ny_date,
            repo_root=repo_root,
            base_max_positions=None,
            base_max_gross_exposure=None,
            base_per_position_cap=cfg.sizing_cfg.max_position_pct,
            drawdown=drawdown_value,
            max_drawdown_pct_block=drawdown_threshold,
        )
        risk_controls = result.controls
        risk_controls_result = result
    candidates = ingest_watchlist_as_candidates(store, cfg)
    active_symbols = set(store.list_active_candidates(now_ts))

    created = 0
    for cand in _iter_active_candidates(candidates, active_symbols):
        if cand.direction != "Long":
            continue
        if store.get_entry_intent(cand.symbol) is not None:
            continue

        bars = md.get_last_two_closed_10m(cand.symbol)
        if len(bars) != 2:
            continue

        boh = boh_confirmed_option2(bars, cand.entry_level)
        if not boh.confirmed:
            continue

        base_size = compute_size_shares(
            account_equity=account_equity,
            price=cand.price,
            dist_pct=abs(cand.dist_pct),
            cfg=cfg.sizing_cfg,
        )
        if base_size <= 0:
            continue
        size = base_size
        if risk_controls is not None:
            size = adjust_order_quantity(
                base_qty=base_size,
                price=cand.price,
                account_equity=account_equity,
                risk_controls=risk_controls,
                gross_exposure=None,
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
                            gross_exposure=None,
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
            continue

        daily_bars = md.get_daily_bars(cand.symbol)
        entry_day = exits.entry_day_from_ts(now_ts)
        stop_price = exits.compute_stop_price(
            daily_bars,
            entry_day=entry_day,
            buffer_dollars=exit_cfg.stop_buffer_dollars,
        )
        if stop_price is None:
            continue
        if not exits.validate_risk(cand.price, stop_price, exit_cfg.max_risk_per_share):
            continue

        delay = random.uniform(cfg.entry_delay_min_sec, cfg.entry_delay_max_sec)
        intent = EntryIntent(
            strategy_id=DEFAULT_STRATEGY_ID,
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
        created += 1

    return created
