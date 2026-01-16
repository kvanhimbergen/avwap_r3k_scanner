"""
Execution V2 – Buy Loop (Candidates + Adds)

PRD requirements implemented here:
- Trade longs only
- Regime gated (global + symbol)
- BOH confirmation (10-minute, Option 2)
- Entry timing: randomized 0–12 minutes after confirmation
- Candidate validity: 5 trading days OR until invalidated

This module:
- Reads daily_candidates.csv (today's scan output)
- Computes pivots (prior daily swing high) at execution time
- Creates EntryIntent records in SQLite

No broker order submission happens here.
"""

from __future__ import annotations

import csv
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from zoneinfo import ZoneInfo

from execution_v2.alerts import send_alert
from execution_v2.boh import Bar10m, boh_confirmed_option2
from execution_v2.clocks import now_snapshot
from execution_v2.config_types import GlobalRegime, SymbolRegime
from execution_v2.market_data import MarketData
from execution_v2.pivots import DailyBar, prior_swing_high
from execution_v2.regime_global import GlobalRegimeConfig, classify_global_regime
from execution_v2.regime_symbol import SymbolInputs, SymbolRegimeConfig, classify_symbol_regime
from execution_v2.sizing import SizingConfig, compute_size_shares
from execution_v2.state_store import StateStore


ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BuyLoopConfig:
    watchlist_path: str = "/root/avwap_r3k_scanner/daily_candidates.csv"

    # Entry delay window (PRD): 0–12 minutes after BOH confirmation
    entry_delay_min_sec: int = 0
    entry_delay_max_sec: int = 12 * 60

    # Candidate validity (PRD): 5 trading days
    candidate_ttl_trading_days: int = 5

    # Portfolio constraints (PRD mentions max concurrent positions; enforce later in execution_main)
    max_concurrent_positions: int = 20

    # Config packs for submodules
    global_regime: GlobalRegimeConfig = GlobalRegimeConfig()
    symbol_regime: SymbolRegimeConfig = SymbolRegimeConfig()
    sizing: SizingConfig = SizingConfig()


def _parse_dist_pct(row: dict) -> Optional[float]:
    # daily_candidates.csv uses "Dist%" (not "DistFromAVWAP%")
    v = row.get("Dist%")
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _trading_days_add(dt: datetime, n: int) -> datetime:
    """
    Add N trading days (Mon–Fri). Does not model holidays (acceptable baseline).
    """
    cur = dt
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() <= 4:
            added += 1
    return cur


def _read_watchlist_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        return [r for r in reader]


def _watchlist_dist_map(path: str) -> dict[str, float]:
    """
    Build {SYMBOL: dist_pct} from daily_candidates.csv using Dist% column.
    """
    out: dict[str, float] = {}
    rows = _read_watchlist_rows(path)
    for r in rows:
        sym = (r.get("Ticker") or "").strip().upper()
        if not sym:
            continue
        d = _parse_dist_pct(r)
        if d is None:
            continue
        out[sym] = float(d)
    return out

def ingest_watchlist_as_candidates(store: StateStore, cfg: BuyLoopConfig) -> int:
    """
    Upsert today's watchlist symbols into candidates table with TTL.
    """
    snap = now_snapshot()
    now_et = snap.now_et
    expires_et = _trading_days_add(now_et, cfg.candidate_ttl_trading_days)
    now_ts = now_et.timestamp()
    expires_ts = expires_et.timestamp()

    rows = _read_watchlist_rows(cfg.watchlist_path)
    if not rows:
        return 0

    n = 0
    for r in rows:
        sym = (r.get("Ticker") or "").strip().upper()
        if not sym:
            continue
        # We do NOT have pivot_level in CSV; leave None and compute later.
        store.upsert_candidate(
            symbol=sym,
            first_seen_ts=now_ts,
            expires_ts=expires_ts,
            pivot_level=None,
            notes="watchlist_ingest",
        )
        n += 1
    return n


def _compute_candidate_pivot_level(md: MarketData, symbol: str) -> Optional[float]:
    """
    Compute prior DAILY swing high (3L/3R) using completed daily bars excluding current day.
    """
    daily = md.get_daily_bars(symbol)
    if len(daily) < 8:
        return None

    # Exclude the most recent bar if it's "today" (best-effort).
    # Alpaca daily bars are completed end-of-day; during the day the latest daily bar may not be final.
    # We conservatively drop the last bar if its date equals ET "today".
    today_et = datetime.now(ET).date()
    def to_et_date(b: DailyBar) -> datetime.date:
        return datetime.fromtimestamp(b.ts, ET).date()

    if daily and to_et_date(daily[-1]) == today_et:
        daily = daily[:-1]

    return prior_swing_high(daily)


def _schedule_entry_ts(now_ts: float, cfg: BuyLoopConfig) -> float:
    delay = random.randint(cfg.entry_delay_min_sec, cfg.entry_delay_max_sec)
    return now_ts + float(delay)


def evaluate_and_create_entry_intents(
    *,
    store: StateStore,
    md: MarketData,
    cfg: BuyLoopConfig,
    account_equity: float,
) -> int:
    """
    Main buy-loop action:
    - Regime gate
    - For each active candidate, compute pivot + BOH confirm
    - Create entry intent with randomized schedule
    """
    snap = now_snapshot()
    if not snap.market_open:
        return 0

    # PRD: no new entries outside 09:45–15:30 ET
    if not snap.entry_window_open:
        return 0

    # Global regime from SPY daily bars
    spy_daily = md.get_daily_bars("SPY")
    global_regime = classify_global_regime(spy_daily, cfg.global_regime)

    # In DEFENSIVE: new entries disabled, adds only (handled later when has_position=True)
    # In OFF: no new entries or adds
    if global_regime == GlobalRegime.OFF:
        return 0

    created = 0
    now_ts = snap.now_et.timestamp()

    # Only consider unexpired candidates
    candidates = store.list_active_candidates(now_ts=now_ts)
    dist_map = _watchlist_dist_map(cfg.watchlist_path)


    for sym in candidates:
        # If an intent already exists, do not duplicate (idempotent)
        if store.get_entry_intent(sym) is not None:
            continue

        # Determine if we already have a position (for ADD eligibility)
        has_pos = store.get_position(sym) is not None

        # Global regime constraint
        if global_regime == GlobalRegime.DEFENSIVE and not has_pos:
            continue

        # Read symbol inputs from scan-derived fields.
        # We only have Dist% reliably from daily_candidates.csv; AVWAP_Slope is not in that file.
        # Therefore avwap_slope=None here; SymbolRegime will still enforce extension gate.
        # (If you later switch execution input to data/daily_candidates_*.csv, we can pass avwap_slope.)
        dist_pct = dist_map.get(sym)

        if dist_pct is None:
            continue

        sym_reg = classify_symbol_regime(
            SymbolInputs(symbol=sym, dist_pct=dist_pct, avwap_slope=None, has_position=has_pos),
            cfg.symbol_regime,
        )

        if not has_pos and sym_reg != SymbolRegime.ENTER:
            continue
        if has_pos and sym_reg not in (SymbolRegime.ADD,):
            continue

        pivot = _compute_candidate_pivot_level(md, sym)
        if pivot is None:
            continue

        bars_10m = md.get_last_two_closed_10m(sym)
        if len(bars_10m) != 2:
            continue

        boh = boh_confirmed_option2(bars_10m, pivot)
        if not boh.confirmed:
            continue

        # Size
        # Price reference: use the latest close of last 10m bar as ref.
        ref_price = bars_10m[-1].close
        qty = compute_size_shares(
            account_equity=account_equity,
            price=ref_price,
            dist_pct=dist_pct,
            cfg=cfg.sizing,
            atr_pct=None,
        )
        if qty <= 0:
            continue

        scheduled_ts = _schedule_entry_ts(now_ts, cfg)

        store.upsert_entry_intent(
            symbol=sym,
            pivot_level=pivot,
            boh_confirmed_at=float(boh.confirm_bar_ts or now_ts),
            scheduled_entry_at=float(scheduled_ts),
            size_shares=int(qty),
        )

        send_alert(
            title="BOH confirmed (intent scheduled)",
            message=f"{sym} | pivot={pivot:.2f} | qty={qty} | schedule_in={(scheduled_ts-now_ts):.0f}s | global={global_regime.name}",
            level="info",
            symbol=sym,
        )
        created += 1

    return created
# Execution V2 placeholder: buy_loop.py
