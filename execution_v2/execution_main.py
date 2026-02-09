"""
Execution V2 – Orchestration Entrypoint
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import socket
import time
import traceback
from datetime import datetime, timedelta, timezone, time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from alerts.slack import (
    slack_alert,
    send_verbose_alert,
    maybe_send_heartbeat,
    maybe_send_daily_summary,
)
from execution_v2 import buy_loop, exits, sell_loop, state_machine
from execution_v2 import live_gate
from execution_v2 import config_check as _config_check
from execution_v2 import alpaca_paper
from execution_v2 import build_info
from execution_v2 import book_ids
from execution_v2 import book_router
from execution_v2 import paper_sim
from execution_v2 import clocks
from execution_v2 import portfolio_decisions
from execution_v2 import portfolio_decision_enforce
from execution_v2 import portfolio_arbiter
from execution_v2 import portfolio_decision as portfolio_decision_contract
from execution_v2 import portfolio_intents
from execution_v2 import shadow_strategies
from execution_v2 import portfolio_s2_enforcement
from execution_v2 import strategy_sleeves
from execution_v2 import entry_suppression
from execution_v2.orders import generate_idempotency_key, build_marketable_limit, SlippageConfig
from execution_v2.state_store import StateStore
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID
from utils.atomic_write import atomic_write_text

if TYPE_CHECKING:
    from alpaca.trading.client import TradingClient


def _now_et() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _log(msg: str) -> None:
    print(f"[{_now_et()}] {msg}", flush=True)


_WARNED_KEYS: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED_KEYS:
        return
    _WARNED_KEYS.add(key)
    _log(message)



def _write_portfolio_decision_latest(
    *,
    decision_record: dict,
    latest_path: Path,
    errors: list[dict],
    blocks: list[dict],
    record_error: bool = True,
) -> bool:
    try:
        portfolio_decisions.write_portfolio_decision_latest(decision_record, latest_path)
        return True
    except Exception as exc:
        if record_error:
            errors.append(
                {
                    "where": "portfolio_decision_latest",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
            )
            blocks.append(
                {
                    "code": "portfolio_decision_latest_write_failed",
                    "message": "latest portfolio decision artifact failed; submissions blocked",
                }
            )
        _log(
            f"WARNING: failed to write portfolio decision latest artifact: {type(exc).__name__}: {exc}"
        )
        return False


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_STATE_DIR = "/root/avwap_r3k_scanner/state"
HEARTBEAT_FILENAME = "execution_heartbeat.json"
ENTRY_REJECTIONS_MAX_SYMBOLS_DEFAULT = 50


def _state_dir() -> Path:
    base = os.getenv("AVWAP_STATE_DIR", DEFAULT_STATE_DIR).strip()
    if not base:
        base = DEFAULT_STATE_DIR
    return Path(base)


def _dry_run_ledger_path() -> Path:
    return _state_dir() / "dry_run_ledger.json"


def _resolve_execution_mode() -> str:
    env_mode = os.getenv("EXECUTION_MODE")
    dry_run_env = os.getenv("DRY_RUN", "0") == "1"
    valid_modes = {"DRY_RUN", "PAPER_SIM", "LIVE", "ALPACA_PAPER", "SCHWAB_401K_MANUAL"}

    if env_mode:
        mode = env_mode.strip().upper()
        if mode not in valid_modes:
            fallback = "DRY_RUN" if dry_run_env else "LIVE"
            _log(f"WARNING: unknown EXECUTION_MODE={env_mode}; defaulting to {fallback}")
            return fallback
        if mode != "DRY_RUN" and dry_run_env:
            _log(
                f"EXECUTION_MODE={mode} but DRY_RUN=1; forcing DRY_RUN "
                "(DRY_RUN overrides broker routing)"
            )
            return "DRY_RUN"
        return mode

    return "DRY_RUN" if dry_run_env else "LIVE"


def run_config_check(state_dir: str | None = None) -> tuple[bool, list[str]]:
    """Delegates to execution_v2.config_check (dependency-light, offline-only)."""
    return _config_check.run_config_check(state_dir=state_dir)


def _get_trading_client() -> TradingClient:
    from alpaca.trading.client import TradingClient

    api_key = os.getenv("APCA_API_KEY_ID") or ""
    api_secret = os.getenv("APCA_API_SECRET_KEY") or ""
    if not api_key or not api_secret:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    paper = os.getenv("ALPACA_PAPER", "1") != "0"
    return TradingClient(api_key, api_secret, paper=paper)


def _normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _warn_legacy_alpaca_paper_env() -> None:
    legacy_vars = [
        "ALPACA_API_KEY_PAPER",
        "ALPACA_API_SECRET_PAPER",
        "ALPACA_BASE_URL_PAPER",
    ]
    if any(os.getenv(name) for name in legacy_vars):
        _log(
            "WARNING: legacy ALPACA_*_PAPER variables detected; "
            "ignoring them in favor of APCA_API_KEY_ID/APCA_API_SECRET_KEY/APCA_API_BASE_URL"
        )


def _get_alpaca_paper_trading_client() -> TradingClient:
    _warn_legacy_alpaca_paper_env()
    if os.getenv("DRY_RUN", "0") == "1":
        _log("DRY_RUN=1; skipping ALPACA_PAPER client construction.")
        raise RuntimeError("DRY_RUN=1 set; ALPACA_PAPER disabled")
    api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
    api_secret = (os.getenv("APCA_API_SECRET_KEY") or "").strip()
    base_url = (os.getenv("APCA_API_BASE_URL") or "").strip()
    missing = [
        name
        for name, value in (
            ("APCA_API_KEY_ID", api_key),
            ("APCA_API_SECRET_KEY", api_secret),
            ("APCA_API_BASE_URL", base_url),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    normalized = _normalize_base_url(base_url)
    if normalized != PAPER_BASE_URL:
        _log(f"ALPACA_PAPER base URL invalid: {base_url}")
        raise RuntimeError(
            "APCA_API_BASE_URL must be "
            f"{PAPER_BASE_URL} for ALPACA_PAPER (got {base_url})"
        )
    from alpaca.trading.client import TradingClient

    return TradingClient(api_key, api_secret, paper=True, url_override=normalized)


def _select_trading_client(execution_mode: str) -> TradingClient:
    if execution_mode == "ALPACA_PAPER":
        return _get_alpaca_paper_trading_client()
    return _get_trading_client()


def _alpaca_clock_snapshot(trading_client: TradingClient) -> tuple[bool, datetime | None]:
    try:
        clock = trading_client.get_clock()
        _log(
            f"Alpaca clock: is_open={clock.is_open}"
            f"ts={clock.timestamp} next_open={clock.next_open} next_close={clock.next_close}"
        )
        now_et = None
        try:
            if getattr(clock, "timestamp", None) is not None:
                now_et = clock.timestamp.astimezone(clocks.ET)
        except Exception:
            now_et = None
        return bool(clock.is_open), now_et
    except Exception as exc:
        _log(
            f"WARNING: Alpaca clock unavailable ({type(exc).__name__}: {exc}); failing closed"
        )
        return False, None


def _has_open_order_or_position(trading_client: TradingClient, symbol: str) -> bool:
    sym = (symbol or "").upper().strip()
    if not sym:
        return True

    try:
        trading_client.get_open_position(sym)
        return True
    except Exception:
        pass

    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[sym])
        orders = trading_client.get_orders(filter=req)
        return len(orders) > 0
    except Exception:
        return True


def _submit_market_entry(trading_client: TradingClient, intent, dry_run: bool) -> str | None:
    if dry_run:
        import json

        ledger_path = _dry_run_ledger_path()
        ledger_enabled = True
        try:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            ledger_enabled = False
            _log(f"WARNING: unable to create dry run ledger directory: {exc}")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{today}:{intent.symbol}"
        
        ledger = {}
        if ledger_enabled:
            try:
                with ledger_path.open("r", encoding="utf-8") as f:
                    ledger = json.load(f)
            except Exception:
                ledger = {}
        
        if ledger_enabled and key in ledger:
            _log(f"DRY_RUN: already submitted today -> {intent.symbol}; skipping")
            return "dry-run-skipped"

        _log(f"DRY_RUN: would submit {intent.symbol} qty={intent.size_shares}")

        ledger[key] = {
            "symbol": intent.symbol,
            "qty": intent.size_shares,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        if ledger_enabled:
            try:
                payload = json.dumps(ledger)
                atomic_write_text(ledger_path, payload)
            except Exception as exc:
                _log(f"WARNING: failed to write dry run ledger: {exc}")

        return "dry-run"

    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    slippage_cfg = SlippageConfig(
        max_slippage_pct=float(
            os.getenv("ENTRY_LIMIT_MAX_SLIPPAGE_PCT", str(SlippageConfig().max_slippage_pct))
        ),
        randomization_pct=float(
            os.getenv("ENTRY_LIMIT_RANDOMIZATION_PCT", str(SlippageConfig().randomization_pct))
        ),
    )
    order_spec = build_marketable_limit(
        strategy_id=getattr(intent, "strategy_id", DEFAULT_STRATEGY_ID),
        date_ny=paper_sim.resolve_date_ny(datetime.now(timezone.utc)),
        symbol=intent.symbol,
        side="buy",
        qty=int(intent.size_shares),
        ref_price=float(intent.ref_price),
        cfg=slippage_cfg,
    )
    order = LimitOrderRequest(
        symbol=intent.symbol,
        qty=intent.size_shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=float(order_spec.limit_price),
    )
    response = trading_client.submit_order(order)
    return getattr(response, "id", None)


def _get_account_equity(trading_client: Optional["TradingClient"]) -> float:
    """
    Return account equity for sizing.

    In DRY_RUN / offline validation flows, trading_client may be None.
    In that case, return a deterministic stub equity so the pipeline can execute.
    """
    if trading_client is None:
        return float(os.getenv("DRY_RUN_EQUITY", "25000"))
    account = trading_client.get_account()
    return float(account.equity)


def _format_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return "unknown"


def _snapshot_candidates_csv(path: str) -> dict:
    abs_path = os.path.abspath(path)
    mtime_utc = None
    row_count = 0
    try:
        mtime = os.path.getmtime(abs_path)
        mtime_utc = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except Exception:
        mtime_utc = None
    try:
        with open(abs_path, "r", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            row_count = sum(1 for _ in reader)
    except Exception:
        row_count = 0
    return {"path": abs_path, "mtime_utc": mtime_utc, "row_count": row_count}


def _iso_utc(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _resolve_db_path_metadata(db_path: str) -> dict[str, Any]:
    abs_path = Path(db_path).expanduser().resolve()
    exists = abs_path.exists()
    size_bytes = None
    mtime_utc = None
    if exists:
        try:
            stat = abs_path.stat()
            size_bytes = int(stat.st_size)
            mtime_utc = _iso_utc(stat.st_mtime)
        except Exception:
            size_bytes = None
            mtime_utc = None
    return {
        "db_path": db_path,
        "db_path_abs": str(abs_path),
        "db_exists": bool(exists),
        "db_mtime_utc": mtime_utc,
        "db_size_bytes": size_bytes,
    }


def _sqlite_db_snapshot(path: Path, *, now_ts: float | None = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "schema_version": None,
        "entry_intents_total": None,
        "entry_intents_due_now": None,
        "error": None,
    }
    if not path.exists():
        return snapshot
    if now_ts is None:
        now_ts = time.time()
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        cur = conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key='schema_version';")
        row = cur.fetchone()
        if row is not None and row[0] is not None:
            snapshot["schema_version"] = str(row[0])
        cur.execute("SELECT COUNT(*) FROM entry_intents;")
        total_row = cur.fetchone()
        snapshot["entry_intents_total"] = int(total_row[0] if total_row else 0)
        cur.execute("SELECT COUNT(*) FROM entry_intents WHERE scheduled_entry_at <= ?;", (float(now_ts),))
        due_row = cur.fetchone()
        snapshot["entry_intents_due_now"] = int(due_row[0] if due_row else 0)
    except Exception as exc:
        snapshot["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            conn.close()
    return snapshot


def _db_debug_enabled() -> bool:
    raw = (os.getenv("EXECUTION_V2_DB_DEBUG") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _summarize_skip_reasons(skipped_actions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in skipped_actions:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _increment_lifecycle_reason_count(decision_record: dict, reason: str, count: int) -> None:
    if count <= 0:
        return
    counts = (
        decision_record.setdefault("intents_meta", {})
        .setdefault("entry_intent_lifecycle_reason_counts", {})
    )
    counts[reason] = int(counts.get(reason, 0)) + int(count)


def _decision_cycle_info(cfg) -> dict:
    service_name = os.getenv("SYSTEMD_UNIT") or None
    return {
        "loop_interval_sec": getattr(cfg, "poll_seconds", None),
        "service_name": service_name,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
    }


def _init_decision_record(cfg, candidates_snapshot: dict, now_utc: datetime, repo_root: Path) -> dict:
    now_ny = now_utc.astimezone(clocks.ET)
    dry_run_env = os.getenv("DRY_RUN", "0") == "1"
    exec_env = os.getenv("EXECUTION_MODE")
    dry_run_forced = dry_run_env and bool(exec_env and exec_env.strip().upper() != "DRY_RUN")
    ny_date = now_ny.date().isoformat()
    decisions_path = portfolio_decisions.resolve_portfolio_decisions_path(repo_root, now_ny)
    record = {
        "schema_version": "1.0",
        "decision_id": "",
        "ts_utc": now_utc.isoformat(),
        "ny_date": ny_date,
        "cycle": _decision_cycle_info(cfg),
        "mode": {
            "execution_mode": cfg.execution_mode,
            "dry_run_forced": dry_run_forced,
        },
        "inputs": {
            "candidates_csv": candidates_snapshot,
            "db_path": None,
            "db_path_abs": None,
            "db_exists": None,
            "db_mtime_utc": None,
            "db_size_bytes": None,
            "entry_intent_lifecycle": {
                "ttl_sec": None,
                "reschedule_on_gate": None,
            },
            "account": {
                "equity": None,
                "buying_power": None,
                "source": "unknown",
            },
            "s2_daily_pnl_by_strategy": {},
            "constraints_snapshot": {
                "allowlist_symbols": None,
                "max_new_positions": None,
                "max_gross_exposure": None,
                "max_notional_per_symbol": None,
            },
        },
        "intents": {"intent_count": 0, "intents": []},
        "intents_meta": {
            "entry_intents_created_count": 0,
            "entry_intents_created_sample": [],
            "entry_intents_pre_s2_count": 0,
            "entry_intents_post_s2_count": 0,
            "drop_reason_counts": {},
            "entry_intent_lifecycle": {},
            "entry_intent_lifecycle_reason_counts": {},
            "entry_rejections": {
                "candidates_seen": 0,
                "accepted": 0,
                "rejected": 0,
                "reason_counts": {},
                "rejected_symbols_truncated": 0,
            },
        },
        "sleeves": {},
        "s2_enforcement": {},
        "gates": {
            "market": {"is_open": None, "clock_source": None},
            "freshness": {"candidates_fresh": None, "reason": None},
            "live_gate_applied": False,
            "blocks": [],
        },
        "actions": {"submitted_orders": [], "skipped": [], "errors": []},
        "artifacts": {
            "ledgers_written": [],
            "portfolio_decisions_path": str(decisions_path.resolve()),
        },
    }
    record["decision_id"] = portfolio_decisions.build_decision_id(
        ny_date=ny_date,
        execution_mode=cfg.execution_mode,
        candidates_path=candidates_snapshot.get("path", ""),
        candidates_mtime_utc=candidates_snapshot.get("mtime_utc"),
        pid=record["cycle"]["pid"],
        ts_utc=record["ts_utc"],
    )
    return record


def _record_s2_inputs(decision_record: dict, sleeve_config: strategy_sleeves.SleeveConfig) -> None:
    decision_record.setdefault("inputs", {})["s2_daily_pnl_by_strategy"] = (
        sleeve_config.daily_pnl_by_strategy
    )


def _slim_entry_intent(intent) -> dict[str, object]:
    return {
        "symbol": getattr(intent, "symbol", ""),
        "strategy_id": getattr(intent, "strategy_id", ""),
        "side": "buy",
        "qty": getattr(intent, "size_shares", None),
    }


def _slim_popped_entry_intent(intent) -> dict[str, object]:
    scheduled_entry_at = getattr(intent, "scheduled_entry_at", None)
    return {
        "symbol": getattr(intent, "symbol", ""),
        "scheduled_entry_at": scheduled_entry_at,
        "scheduled_entry_at_utc": _iso_utc(scheduled_entry_at),
    }


def _record_created_intents_meta(
    decision_record: dict, created_intents: list, created: int
) -> None:
    if not created:
        return
    meta = decision_record.setdefault("intents_meta", {})
    meta["entry_intents_created_count"] = created
    meta["entry_intents_created_sample"] = [
        _slim_entry_intent(intent) for intent in created_intents[:5]
    ]


def _record_edge_window_meta(decision_record: dict, edge_report: buy_loop.EdgeWindowReport) -> None:
    decision_record.setdefault("intents_meta", {})["edge_window"] = edge_report.to_dict()


def _record_one_shot_meta(decision_record: dict, config: entry_suppression.OneShotConfig) -> None:
    decision_record.setdefault("intents_meta", {})["one_shot"] = {
        "enabled": config.enabled,
        "reset_mode": config.reset_mode,
        "cooldown_minutes": config.cooldown_minutes,
    }


def _default_entry_rejections_snapshot() -> dict[str, Any]:
    return {
        "candidates_seen": 0,
        "accepted": 0,
        "rejected": 0,
        "reason_counts": {},
        "rejected_symbols_truncated": 0,
    }


def _record_entry_rejections_meta(
    decision_record: dict,
    *,
    telemetry: buy_loop.EntryRejectionTelemetry,
    max_rejected_symbols: int,
    errors: list[dict],
    include_rejected_symbols: bool,
) -> None:
    try:
        payload = telemetry.to_decision_payload(
            max_rejected_symbols=max_rejected_symbols,
            include_rejected_symbols=include_rejected_symbols,
        )
        decision_record.setdefault("intents_meta", {})["entry_rejections"] = payload
        if _parse_bool_env("ENTRY_REJECTION_TELEMETRY_DEBUG", False):
            _log(
                "ENTRY_REJECTIONS "
                f"seen={payload.get('candidates_seen', 0)} "
                f"accepted={payload.get('accepted', 0)} "
                f"rejected={payload.get('rejected', 0)} "
                f"reasons={payload.get('reason_counts', {})}"
            )
    except Exception as exc:
        errors.append(
            {
                "where": "entry_rejection_telemetry",
                "message": str(exc),
                "exception_type": type(exc).__name__,
            }
        )
        decision_record.setdefault("intents_meta", {})[
            "entry_rejections"
        ] = _default_entry_rejections_snapshot()


def _apply_one_shot_suppression(
    *,
    intents: list,
    store: StateStore,
    date_ny: str,
    now_ts: float,
    config: entry_suppression.OneShotConfig,
    decision_record: dict,
) -> list:
    if not config.enabled:
        return intents
    allowed: list = []
    for intent in intents:
        decision = entry_suppression.evaluate_one_shot(
            store=store,
            date_ny=date_ny,
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            now_ts=now_ts,
            config=config,
        )
        if decision.blocked:
            decision_record["actions"]["skipped"].append(
                {
                    "symbol": intent.symbol,
                    "reason": decision.reason or "one_shot_blocked",
                }
            )
            continue
        allowed.append(intent)
    return allowed


def _update_intents_meta(
    decision_record: dict,
    *,
    created_intents: list,
    entry_intents: list,
    approved_intents: list,
    s2_snapshot: dict | None = None,
) -> None:
    meta = decision_record.setdefault("intents_meta", {})
    if created_intents:
        meta["entry_intents_created_count"] = len(created_intents)
        meta["entry_intents_created_sample"] = [
            _slim_entry_intent(intent) for intent in created_intents[:5]
        ]
    else:
        meta.setdefault("entry_intents_created_count", 0)
        meta.setdefault("entry_intents_created_sample", [])
    meta["entry_intents_pre_s2_count"] = len(entry_intents)
    meta["entry_intents_post_s2_count"] = len(approved_intents)
    if (
        meta.get("entry_intents_created_count", 0) == 0
        and meta["entry_intents_pre_s2_count"] > 0
    ):
        meta["entry_intents_created_count"] = meta["entry_intents_pre_s2_count"]
        if not meta.get("entry_intents_created_sample"):
            meta["entry_intents_created_sample"] = [
                _slim_entry_intent(intent) for intent in entry_intents[:5]
            ]
    if s2_snapshot is None:
        s2_snapshot = decision_record.get("s2_enforcement") or {}
    reason_counts = s2_snapshot.get("reason_counts")
    if reason_counts is not None:
        meta["drop_reason_counts"] = dict(reason_counts)
    else:
        meta.setdefault("drop_reason_counts", {})


def _build_execution_heartbeat(
    *,
    cfg,
    decision_record: dict,
    candidates_snapshot: dict,
) -> dict:
    now_utc = datetime.now(timezone.utc)
    ny_date = now_utc.astimezone(clocks.ET).date().isoformat()
    blocks = decision_record.get("gates", {}).get("blocks", [])
    block_codes = [block.get("code") for block in blocks if isinstance(block, dict)]
    intents = decision_record.get("intents", {})
    actions = decision_record.get("actions", {})
    errors = actions.get("errors", [])
    submitted_orders = actions.get("submitted_orders", [])
    market_is_open = decision_record.get("gates", {}).get("market", {}).get("is_open")
    return {
        "ts_utc": now_utc.isoformat(),
        "ny_date": ny_date,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "execution_mode": cfg.execution_mode,
        "dry_run": bool(getattr(cfg, "dry_run", False)),
        "poll_seconds": int(getattr(cfg, "poll_seconds", 0) or 0),
        "market_is_open": market_is_open,
        "blocks": block_codes,
        "errors_count": len(errors),
        "intents_count": max(
            int(intents.get("intent_count", 0) or 0),
            len(intents.get("intents") or []),
        ),
        "orders_submitted_count": len(submitted_orders),
        "candidates_csv": {
            "path": candidates_snapshot.get("path"),
            "mtime_utc": candidates_snapshot.get("mtime_utc"),
            "row_count": candidates_snapshot.get("row_count"),
        },
    }


def _write_execution_heartbeat(cfg, decision_record: dict, candidates_snapshot: dict) -> None:
    heartbeat_path = _state_dir() / HEARTBEAT_FILENAME
    heartbeat = _build_execution_heartbeat(
        cfg=cfg, decision_record=decision_record, candidates_snapshot=candidates_snapshot
    )
    try:
        payload = json.dumps(heartbeat, sort_keys=True, separators=(",", ":")) + "\n"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(heartbeat_path, payload)
    except Exception as exc:
        _log(f"WARNING: failed to write execution heartbeat: {exc}")


def _is_material_cycle(decision_record: dict, cfg, market_is_open: bool | None) -> bool:
    # If the market is open (or we're explicitly running closed-market cycles),
    # portfolio decisions are material by definition.
    if market_is_open or getattr(cfg, "ignore_market_hours", False):
        return True

    # Market is closed: only write portfolio decision artifacts if something actually happened.
    actions = decision_record.get("actions", {}) or {}
    intents = decision_record.get("intents", {}) or {}

    errors = actions.get("errors") or []
    if errors:
        return True

    # Some codepaths store intents as {"intent_count":..., "intents":[...]}.
    if isinstance(intents, dict):
        intent_count = int(intents.get("intent_count", 0) or 0)
        intent_list = intents.get("intents") or []
    else:
        intent_count = 0
        intent_list = intents or []

    if intent_count > 0 or intent_list:
        return True

    submitted_orders = actions.get("submitted_orders") or []
    if submitted_orders:
        return True

    # Otherwise: heartbeat-only cycle when market is closed.
    return False


def _parse_int_env(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        _warn_once(
            name,
            f"WARNING: invalid {name}={raw!r}; using default {default}",
        )
        return default
    if min_value is not None and value < min_value:
        _warn_once(
            name,
            f"WARNING: {name}={value} below minimum {min_value}; using default {default}",
        )
        return default
    return value


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    _warn_once(name, f"WARNING: invalid {name}={raw!r}; using default {int(default)}")
    return default


def _parse_float_env(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        _warn_once(
            name,
            f"WARNING: invalid {name}={raw!r}; using default {default}",
        )
        return default
    if min_value is not None and value < min_value:
        _warn_once(
            name,
            f"WARNING: {name}={value} below minimum {min_value}; using default {default}",
        )
        return default
    return value


def _resolve_candidates_freshness(
    *,
    candidates_snapshot: dict,
    now_utc: datetime,
    ny_date: str,
) -> tuple[bool, str]:
    mtime_raw = candidates_snapshot.get("mtime_utc")
    if not mtime_raw:
        return False, "candidates_mtime_missing"
    try:
        mtime_utc = datetime.fromisoformat(str(mtime_raw).replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except Exception:
        return False, "candidates_mtime_invalid"

    mtime_ny = mtime_utc.astimezone(clocks.ET)
    mtime_ny_date = mtime_ny.date().isoformat()
    if mtime_ny_date != ny_date:
        return False, f"candidates_stale_date:file={mtime_ny_date} expected={ny_date}"

    max_age_minutes = _parse_int_env("CANDIDATES_MAX_AGE_MINUTES", 24 * 60, min_value=0)
    age_minutes = (now_utc - mtime_utc).total_seconds() / 60.0
    if age_minutes > float(max_age_minutes):
        return False, f"candidates_stale_age:age_min={age_minutes:.1f} max={max_age_minutes}"

    return True, "fresh"


def _entry_submit_quality_check(intent, md) -> tuple[bool, str]:
    try:
        symbol = str(getattr(intent, "symbol", "")).upper()
    except Exception:
        symbol = ""
    if not symbol:
        return False, "submit_quality:symbol_missing"

    try:
        ref_price = float(getattr(intent, "ref_price", 0.0))
    except Exception:
        ref_price = 0.0
    if ref_price <= 0:
        return False, "submit_quality:ref_price_invalid"

    try:
        stop_loss = float(getattr(intent, "stop_loss", 0.0))
    except Exception:
        stop_loss = 0.0
    if stop_loss > 0:
        risk_per_share = ref_price - stop_loss
        max_risk = _parse_float_env("MAX_RISK_PER_SHARE_DOLLARS", 3.0, min_value=0.0)
        if risk_per_share > max_risk:
            return False, "submit_quality:risk_too_wide"

    try:
        pivot_level = float(getattr(intent, "pivot_level", 0.0))
    except Exception:
        pivot_level = 0.0
    if pivot_level > 0:
        pivot_tolerance = _parse_float_env("ENTRY_PIVOT_BREAK_TOLERANCE_PCT", 0.002, min_value=0.0)
        if ref_price < pivot_level * (1.0 - pivot_tolerance):
            return False, "submit_quality:below_pivot"

    max_age_sec = _parse_int_env("ENTRY_INTENT_MAX_AGE_SEC", 2 * 60 * 60, min_value=0)
    if max_age_sec > 0:
        try:
            confirmed_at = float(getattr(intent, "boh_confirmed_at", 0.0) or 0.0)
        except Exception:
            confirmed_at = 0.0
        if confirmed_at > 0 and (time.time() - confirmed_at) > float(max_age_sec):
            return False, "submit_quality:intent_stale"

    if md is not None and hasattr(md, "get_last_two_closed_10m"):
        try:
            bars = md.get_last_two_closed_10m(symbol)
        except Exception:
            bars = []
        if len(bars) == 2:
            last_close = None
            try:
                last_close = float(getattr(bars[-1], "close"))
            except Exception:
                try:
                    last_close = float(bars[-1]["close"])
                except Exception:
                    last_close = None
            if last_close is not None and last_close > 0:
                drift_cap = _parse_float_env("ENTRY_SUBMIT_PRICE_DRIFT_PCT", 0.03, min_value=0.0)
                drift = abs(last_close - ref_price) / ref_price
                if drift > drift_cap:
                    return False, "submit_quality:price_drift"

    return True, "ok"


def _requeue_entry_intent(store: StateStore, intent, *, delay_seconds: int, reason: str) -> None:
    try:
        scheduled_entry_at = float(getattr(intent, "scheduled_entry_at"))
    except Exception:
        scheduled_entry_at = time.time()
    try:
        retry_intent = buy_loop.EntryIntent(
            strategy_id=getattr(intent, "strategy_id"),
            symbol=getattr(intent, "symbol"),
            pivot_level=float(getattr(intent, "pivot_level")),
            boh_confirmed_at=float(getattr(intent, "boh_confirmed_at")),
            scheduled_entry_at=max(
                scheduled_entry_at,
                time.time() + max(int(delay_seconds), 0),
            ),
            size_shares=int(getattr(intent, "size_shares")),
            stop_loss=float(getattr(intent, "stop_loss")),
            take_profit=float(getattr(intent, "take_profit")),
            ref_price=float(getattr(intent, "ref_price")),
            dist_pct=float(getattr(intent, "dist_pct")),
        )
        store.put_entry_intent(retry_intent)
        _log(f"ENTRY_REQUEUE symbol={retry_intent.symbol} reason={reason}")
    except Exception as exc:
        _log(f"WARNING: failed to requeue entry intent ({type(exc).__name__}: {exc})")


def _parse_time_env(name: str, default_value: str) -> dt_time:
    raw = os.getenv(name)
    value = raw.strip() if raw else ""
    if not value:
        value = default_value
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        _warn_once(
            name,
            f"WARNING: invalid {name}={raw!r}; using default {default_value}",
        )
        return datetime.strptime(default_value, "%H:%M").time()


def resolve_poll_seconds(cfg, now_et: datetime | None = None) -> int:
    base_seconds = int(getattr(cfg, "poll_seconds", 0) or 0)
    if base_seconds <= 0:
        base_seconds = 300
    market_seconds_default = min(base_seconds, 60)
    tight_seconds = _parse_int_env("EXECUTION_POLL_TIGHT_SECONDS", 15, min_value=1)
    market_seconds = _parse_int_env(
        "EXECUTION_POLL_MARKET_SECONDS", market_seconds_default, min_value=1
    )
    tight_start = _parse_time_env("EXECUTION_POLL_TIGHT_START_ET", "09:30")
    tight_end = _parse_time_env("EXECUTION_POLL_TIGHT_END_ET", "10:05")
    if now_et is None:
        now_et = datetime.now(tz=ZoneInfo("America/New_York"))
    now_et = now_et.astimezone(clocks.ET)
    weekday = now_et.weekday()
    is_weekday = weekday <= 4
    now_time = now_et.time()
    market_open = is_weekday and (clocks.REG_OPEN <= now_time < clocks.REG_CLOSE)
    if not market_open:
        return base_seconds
    if tight_start <= now_time < tight_end:
        return tight_seconds
    return market_seconds

def _market_open(cfg, trading_client, repo_root):
    """Resolve market-open status deterministically and provide a stable seam for tests.

    Returns:
      (market_is_open: bool, now_et: datetime|None, clock_source: str, ledger_path: str|None)
    """
    ledger_path = None
    if cfg.execution_mode in {"PAPER_SIM", "DRY_RUN", "SCHWAB_401K_MANUAL"}:
        clock_snapshot = clocks.now_snapshot()
        market_is_open = clock_snapshot.market_open
        now_et = getattr(clock_snapshot, "now_et", None)
        return market_is_open, now_et, "clock_snapshot", ledger_path

    # Live modes (incl ALPACA_PAPER) use broker clock snapshot.
    if cfg.execution_mode == "ALPACA_PAPER":
        date_ny = paper_sim.resolve_date_ny(datetime.now(timezone.utc))
        ledger_path = str(alpaca_paper.ledger_path(repo_root, date_ny))
        _log(f"ALPACA_PAPER ledger_path={ledger_path} (date_ny={date_ny})")

    market_is_open, now_et = _alpaca_clock_snapshot(trading_client)
    return market_is_open, now_et, "alpaca_clock", ledger_path


def _resolve_market_settle_minutes() -> int:
    return _parse_int_env("MARKET_SETTLE_MINUTES", 0, min_value=0)


def _resolve_entry_delay_after_open_minutes() -> int:
    return _parse_int_env("ENTRY_DELAY_AFTER_OPEN_MINUTES", 20, min_value=0)


def _resolve_entry_intent_ttl_sec() -> int:
    return _parse_int_env("ENTRY_INTENT_TTL_SEC", 3600, min_value=0)


def _resolve_entry_intent_reschedule_on_gate() -> bool:
    return _parse_bool_env("ENTRY_INTENT_RESCHEDULE_ON_GATE", False)


def _entry_delay_after_open_active(
    delay_minutes: int,
    *,
    market_is_open: bool,
    now_et: datetime | None,
) -> tuple[bool, str | None]:
    if delay_minutes <= 0 or not market_is_open or now_et is None:
        return False, None
    now_et = now_et.astimezone(clocks.ET)
    open_dt = datetime.combine(now_et.date(), clocks.REG_OPEN, tzinfo=clocks.ET)
    delta_minutes = (now_et - open_dt).total_seconds() / 60.0
    if 0 <= delta_minutes < delay_minutes:
        msg = (
            f"entry delay after open active for {delay_minutes}m "
            f"(now {now_et.strftime('%H:%M:%S %Z')})"
        )
        return True, msg
    return False, None



def _market_settle_gate_active(
    settle_minutes: int,
    *,
    market_is_open: bool,
    now_et: datetime | None,
) -> tuple[bool, str | None]:
    if settle_minutes <= 0 or not market_is_open or now_et is None:
        return False, None
    now_et = now_et.astimezone(clocks.ET)
    open_dt = datetime.combine(now_et.date(), clocks.REG_OPEN, tzinfo=clocks.ET)
    delta_minutes = (now_et - open_dt).total_seconds() / 60.0
    if 0 <= delta_minutes < settle_minutes:
        msg = (
            f"market settle delay active for {settle_minutes}m "
            f"(now {now_et.strftime('%H:%M:%S %Z')})"
        )
        return True, msg
    return False, None


def _finalize_portfolio_enforcement(
    *,
    records: list[dict],
    date_ny: str,
    context: portfolio_decision_enforce.DecisionContext | None,
) -> None:
    if not context:
        return
    enforcement_path = portfolio_decision_enforce.resolve_enforcement_artifact_path(date_ny)
    portfolio_decision_enforce.write_enforcement_records(records, enforcement_path)
    blocked_symbols, reason_codes = portfolio_decision_enforce.summarize_blocked_records(records)
    portfolio_decision_enforce.send_blocked_alert(
        date_ny=date_ny,
        blocked_symbols=blocked_symbols,
        reason_codes=reason_codes,
        slack_sender=slack_alert,
    )


def run_once(cfg) -> None:
    if cfg.execution_mode == "ALPACA_PAPER":
        api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
        api_secret = (os.getenv("APCA_API_SECRET_KEY") or "").strip()
        base_url = (os.getenv("APCA_API_BASE_URL") or "").strip()
        if not api_key or not api_secret or not base_url:
            _log("ERROR: Missing Alpaca API credentials in environment")
            raise RuntimeError("Missing Alpaca API credentials in environment")
    decision_ts_utc = datetime.now(timezone.utc)
    cycle_now_ts = decision_ts_utc.timestamp()
    candidates_snapshot = _snapshot_candidates_csv(cfg.candidates_csv)
    repo_root = Path(getattr(cfg, "base_dir", "") or os.getenv("AVWAP_REPO_ROOT", "") or Path(__file__).resolve().parents[1]).resolve()
    decision_record = _init_decision_record(cfg, candidates_snapshot, decision_ts_utc, repo_root)
    candidates_fresh, candidates_fresh_reason = _resolve_candidates_freshness(
        candidates_snapshot=candidates_snapshot,
        now_utc=decision_ts_utc,
        ny_date=decision_record["ny_date"],
    )
    decision_record["gates"]["freshness"]["candidates_fresh"] = bool(candidates_fresh)
    decision_record["gates"]["freshness"]["reason"] = candidates_fresh_reason
    decision_path = Path(decision_record["artifacts"]["portfolio_decisions_path"])
    latest_path = _state_dir() / "portfolio_decision_latest.json"
    decision_record["artifacts"]["portfolio_decision_latest_path"] = str(latest_path.resolve())
    errors = decision_record["actions"]["errors"]
    blocks = decision_record["gates"]["blocks"]
    ledgers_written = decision_record["artifacts"]["ledgers_written"]
    positions_count: int | None = None
    entry_intents_created: list = []
    entry_rejection_symbol_cap = _parse_int_env(
        "ENTRY_REJECTION_REJECTED_SYMBOLS_MAX",
        ENTRY_REJECTIONS_MAX_SYMBOLS_DEFAULT,
        min_value=1,
    )
    entry_rejection_telemetry = buy_loop.EntryRejectionTelemetry()
    now_et: datetime | None = None
    entry_delay_after_open_active = False
    entry_delay_after_open_message: str | None = None
    symbol_state_store: state_machine.SymbolExecutionStateStore | None = None
    consumed_entries_store: state_machine.ConsumedEntriesStore | None = None
    entry_intent_ttl_sec = _resolve_entry_intent_ttl_sec()
    entry_intent_reschedule_on_gate = _resolve_entry_intent_reschedule_on_gate()
    decision_record["inputs"]["entry_intent_lifecycle"] = {
        "ttl_sec": entry_intent_ttl_sec,
        "reschedule_on_gate": entry_intent_reschedule_on_gate,
    }
    if not candidates_fresh:
        blocks.append(
            {
                "code": "candidates_stale",
                "message": f"candidate freshness gate failed ({candidates_fresh_reason})",
            }
        )
        _log(f"Gate candidates_stale active ({candidates_fresh_reason}).")
    lifecycle_meta = decision_record.setdefault("intents_meta", {}).setdefault(
        "entry_intent_lifecycle", {}
    )
    lifecycle_meta.setdefault("purge", {})
    lifecycle_reschedules = lifecycle_meta.setdefault("reschedules", [])
    db_debug = _db_debug_enabled()
    db_meta = _resolve_db_path_metadata(cfg.db_path)
    decision_record["inputs"].update(db_meta)
    _log(
        "Execution DB: "
        f"configured={db_meta['db_path']} "
        f"resolved={db_meta['db_path_abs']} "
        f"exists={db_meta['db_exists']} "
        f"size_bytes={db_meta['db_size_bytes']} "
        f"mtime_utc={db_meta['db_mtime_utc']}"
    )
    active_db_path = Path(str(db_meta["db_path_abs"]))
    if active_db_path.as_posix().endswith("/data/execution_v2.sqlite"):
        alternate_db_path = (repo_root / "execution_v2.sqlite").resolve()
        if alternate_db_path != active_db_path and alternate_db_path.exists():
            active_snapshot = _sqlite_db_snapshot(active_db_path, now_ts=decision_ts_utc.timestamp())
            alternate_snapshot = _sqlite_db_snapshot(
                alternate_db_path, now_ts=decision_ts_utc.timestamp()
            )
            active_due = active_snapshot.get("entry_intents_due_now")
            alternate_due = alternate_snapshot.get("entry_intents_due_now")
            active_total = active_snapshot.get("entry_intents_total")
            alternate_total = alternate_snapshot.get("entry_intents_total")
            mismatch = False
            if isinstance(active_due, int) and isinstance(alternate_due, int):
                mismatch = (active_due > 0 and alternate_due == 0) or (
                    alternate_due > 0 and active_due == 0
                )
            if isinstance(active_total, int) and isinstance(alternate_total, int):
                mismatch = mismatch or (active_total != alternate_total)
            if (
                active_snapshot.get("schema_version") is not None
                and alternate_snapshot.get("schema_version") is not None
            ):
                mismatch = mismatch or (
                    active_snapshot["schema_version"] != alternate_snapshot["schema_version"]
                )
            decision_record["inputs"]["db_sanity_check"] = {
                "active": active_snapshot,
                "alternate": alternate_snapshot,
                "mismatch": mismatch,
            }
            if mismatch:
                _warn_once(
                    f"db_split_brain:{active_db_path}:{alternate_db_path}",
                    "WARNING: multiple execution DB files detected with divergent "
                    f"entry_intent counts; active={active_db_path} alt={alternate_db_path} "
                    f"active_due={active_due} alt_due={alternate_due}",
                )
            elif db_debug:
                _log(
                    "DB sanity check passed: "
                    f"active_due={active_due} alt_due={alternate_due} "
                    f"active_total={active_total} alt_total={alternate_total}"
                )

    try:
        try:
            store = StateStore(cfg.db_path)
        except Exception as exc:
            errors.append(
                {
                    "where": "state_store_init",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                    "db_path": cfg.db_path,
                    "db_path_abs": db_meta["db_path_abs"],
                }
            )
            blocks.append(
                {
                    "code": "state_store_init_failed",
                    "message": "state store initialization failed; submissions blocked",
                }
            )
            _log(
                "ERROR: failed to initialize StateStore "
                f"({type(exc).__name__}: {exc}) path={db_meta['db_path_abs']}"
            )
            return
        purge_stats: dict[str, Any] = {
            "purged_count": 0,
            "oldest_age_sec": 0.0,
            "min_sched": None,
            "max_sched": None,
            "ttl_sec": entry_intent_ttl_sec,
            "now_ts": cycle_now_ts,
        }
        if hasattr(store, "purge_stale_entry_intents"):
            try:
                raw = store.purge_stale_entry_intents(cycle_now_ts, entry_intent_ttl_sec)
                if isinstance(raw, dict):
                    purge_stats.update(raw)
            except Exception as exc:
                errors.append(
                    {
                        "where": "entry_intent_lifecycle_purge",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                        "db_path": cfg.db_path,
                    }
                )
                blocks.append(
                    {
                        "code": "entry_intent_lifecycle_purge_failed",
                        "message": "entry intent lifecycle purge failed; submissions blocked",
                    }
                )
                _log(
                    "ERROR: failed to purge stale entry intents "
                    f"({type(exc).__name__}: {exc})"
                )
                return
        lifecycle_meta["purge"] = purge_stats
        purged_count = int(purge_stats.get("purged_count", 0) or 0)
        if purged_count > 0:
            _log(
                "ENTRY_INTENTS: purged stale intents "
                f"count={purged_count} "
                f"oldest_age_sec={float(purge_stats.get('oldest_age_sec', 0.0)):.1f} "
                f"ttl_sec={entry_intent_ttl_sec}"
            )
            _increment_lifecycle_reason_count(
                decision_record, "entry_intent_ttl_purged", purged_count
            )
        if cfg.entry_delay_min_sec > cfg.entry_delay_max_sec:
            cfg.entry_delay_min_sec, cfg.entry_delay_max_sec = cfg.entry_delay_max_sec, cfg.entry_delay_min_sec
        buy_cfg = buy_loop.BuyLoopConfig(
            candidates_csv=cfg.candidates_csv,
            entry_delay_min_sec=cfg.entry_delay_min_sec,
            entry_delay_max_sec=cfg.entry_delay_max_sec,
        )
        edge_window_cfg = buy_loop.EdgeWindowConfig.from_env()
        edge_report = buy_loop.EdgeWindowReport()
        edge_report.enabled = edge_window_cfg.enabled
        one_shot_cfg = entry_suppression.OneShotConfig.from_env()
        _record_edge_window_meta(decision_record, edge_report)
        _record_one_shot_meta(decision_record, one_shot_cfg)

        def _evaluate_entry_candidates(account_equity: float) -> int:
            created = buy_loop.evaluate_and_create_entry_intents(
                store,
                md,
                buy_cfg,
                account_equity,
                created_intents=entry_intents_created,
                edge_window=edge_window_cfg,
                edge_report=edge_report,
                rejection_telemetry=entry_rejection_telemetry,
            )
            _record_entry_rejections_meta(
                decision_record,
                telemetry=entry_rejection_telemetry,
                max_rejected_symbols=entry_rejection_symbol_cap,
                errors=errors,
                include_rejected_symbols=True,
            )
            return created

        # repo_root already resolved near top of run_once
        decision_record["build"] = {
            "git_sha": build_info.get_git_sha_short(repo_root),
            "git_dirty": build_info.is_git_dirty(repo_root),
            "python_version": build_info.get_python_version(),
            "app_version": build_info.APP_VERSION,
        }
        if os.getenv("DRY_RUN", "0") == "1":
            _log(f"DRY_RUN=1 active; execution_mode={cfg.execution_mode}")
        else:
            _log(f"Execution mode={cfg.execution_mode}")


        # ---- Alpaca runtime context (non-secret) ----
        try:
            alpaca_env = {
                "EXECUTION_MODE": cfg.execution_mode,
                "ALPACA_PAPER": os.getenv("ALPACA_PAPER"),
                "APCA_API_BASE_URL": os.getenv("APCA_API_BASE_URL"),
                "HAS_APCA_API_KEY_ID": bool(os.getenv("APCA_API_KEY_ID")),
                "HAS_APCA_API_SECRET_KEY": bool(os.getenv("APCA_API_SECRET_KEY")),
            }
            _log("Alpaca env: " + " ".join(f"{k}={v}" for k, v in alpaca_env.items()))
        except Exception as exc:
            _log(f"WARNING: failed to log Alpaca env ({type(exc).__name__}: {exc})")
        # --------------------------------------------

        if cfg.execution_mode not in {"PAPER_SIM", "DRY_RUN"}:
            book_id = book_ids.resolve_book_id(cfg.execution_mode)
            if book_id == book_ids.SCHWAB_401K_MANUAL:
                trading_client = book_router.select_trading_client(book_id)
                md = None
            else:
                from execution_v2.market_data import from_env as market_data_from_env

                try:
                    if book_id:
                        trading_client = book_router.select_trading_client(book_id)
                    else:
                        trading_client = _select_trading_client(cfg.execution_mode)
                except Exception as exc:
                    _log(f"ERROR: failed to initialize trading client: {type(exc).__name__}: {exc}")
                    raise
                md = market_data_from_env()
        else:
            trading_client = None
            md = None
        if md is None:
            class _NoMarketData:
                def get_last_two_closed_10m(self, symbol: str) -> list:
                    return []

                def get_daily_bars(self, symbol: str) -> list:
                    return []

            md = _NoMarketData()
        # Diagnostics: confirm which candidates CSV execution will use (observability only).
        try:
            p = candidates_snapshot.get("path", cfg.candidates_csv)
            exists = os.path.exists(p)
            mtime = candidates_snapshot.get("mtime_utc")
            _log(f"Candidates CSV: {p} | exists={exists} | mtime_utc={mtime}")
        except Exception:
            pass
        
        market_is_open, now_et, clock_source, ledger_path = _market_open(cfg, trading_client, repo_root)
        decision_record["gates"]["market"]["is_open"] = market_is_open
        decision_record["gates"]["market"]["clock_source"] = clock_source
        entry_delay_minutes = _resolve_entry_delay_after_open_minutes()
        entry_delay_after_open_active, entry_delay_after_open_message = _entry_delay_after_open_active(
            entry_delay_minutes,
            market_is_open=market_is_open,
            now_et=now_et,
        )
        if entry_delay_after_open_active and entry_delay_after_open_message:
            blocks.append(
                {"code": "entry_delay_after_open", "message": entry_delay_after_open_message}
            )
            _log(f"Gate entry_delay_after_open active ({entry_delay_minutes}m).")
        maybe_send_heartbeat(
            dry_run=(cfg.dry_run if cfg.execution_mode != "PAPER_SIM" else True),
            market_open=market_is_open,
            execution_mode=cfg.execution_mode,
        )
        maybe_send_daily_summary(
            dry_run=(cfg.dry_run if cfg.execution_mode != "PAPER_SIM" else True),
            market_open=market_is_open,
            execution_mode=cfg.execution_mode,
            ledger_path=ledger_path,
        )

        if cfg.execution_mode == "SCHWAB_401K_MANUAL" and not market_is_open:
            _log("Market closed; skipping manual cycle.")
            decision_record["gates"]["blocks"].append(
                {"code": "market_closed", "message": "market closed; manual cycle skipped"}
            )
            return

        if (not market_is_open) and (not getattr(cfg, 'ignore_market_hours', False)):
            _log("Market closed; skipping cycle.")
            decision_record["gates"]["blocks"].append(
                {"code": "market_closed", "message": "market closed; cycle skipped"}
            )
            return

        settle_minutes = _resolve_market_settle_minutes()
        settle_active, settle_message = _market_settle_gate_active(
            settle_minutes,
            market_is_open=market_is_open,
            now_et=now_et,
        )
        if settle_active and settle_message:
            blocks.append({"code": "market_settle_delay", "message": settle_message})
            _log(f"Gate market_settle_delay active ({settle_minutes}m).")
        if (
            entry_intent_reschedule_on_gate
            and market_is_open
            and (settle_active or entry_delay_after_open_active)
            and now_et is not None
            and hasattr(store, "reschedule_due_entry_intents")
        ):
            now_et_local = now_et.astimezone(clocks.ET)
            open_dt = datetime.combine(now_et_local.date(), clocks.REG_OPEN, tzinfo=clocks.ET)
            reschedule_targets: list[tuple[str, float]] = []
            if settle_active:
                reschedule_targets.append(
                    (
                        "settle",
                        (open_dt + timedelta(minutes=settle_minutes)).timestamp(),
                    )
                )
            if entry_delay_after_open_active:
                reschedule_targets.append(
                    (
                        "entry_delay",
                        (open_dt + timedelta(minutes=entry_delay_minutes)).timestamp(),
                    )
                )
            if reschedule_targets:
                reason, new_scheduled_at = max(reschedule_targets, key=lambda item: item[1])
                try:
                    raw = store.reschedule_due_entry_intents(cycle_now_ts, new_scheduled_at)
                except Exception as exc:
                    errors.append(
                        {
                            "where": "entry_intent_lifecycle_reschedule",
                            "message": str(exc),
                            "exception_type": type(exc).__name__,
                            "db_path": cfg.db_path,
                        }
                    )
                    blocks.append(
                        {
                            "code": "entry_intent_lifecycle_reschedule_failed",
                            "message": "entry intent lifecycle reschedule failed; submissions blocked",
                        }
                    )
                    _log(
                        "ERROR: failed to reschedule due entry intents "
                        f"({type(exc).__name__}: {exc})"
                    )
                    return
                reschedule_stats = {
                    "reason": reason,
                    "rescheduled_count": 0,
                    "new_scheduled_at": new_scheduled_at,
                }
                if isinstance(raw, dict):
                    reschedule_stats.update(raw)
                    reschedule_stats["reason"] = reason
                lifecycle_reschedules.append(reschedule_stats)
                rescheduled_count = int(reschedule_stats.get("rescheduled_count", 0) or 0)
                if rescheduled_count > 0:
                    _log(
                        "ENTRY_INTENTS: rescheduled due intents "
                        f"count={rescheduled_count} "
                        f"new_scheduled_at={_iso_utc(float(reschedule_stats['new_scheduled_at']))} "
                        f"reason={reason}"
                    )
                    _increment_lifecycle_reason_count(
                        decision_record,
                        f"entry_intent_rescheduled_{reason}",
                        rescheduled_count,
                    )
        if settle_active and cfg.execution_mode == "DRY_RUN":
            _log("DRY_RUN: settle delay active; skipping entry workflow.")
            return

        if cfg.execution_mode == "PAPER_SIM":
            account_equity = float(os.getenv("PAPER_SIM_EQUITY", "100000"))
            decision_record["inputs"]["account"]["equity"] = account_equity
            decision_record["inputs"]["account"]["source"] = "none"
            if md is None:
                class _NoMarketData:
                    def get_last_two_closed_10m(self, symbol: str) -> list:
                        return []

                    def get_daily_bars(self, symbol: str) -> list:
                        return []

                md = _NoMarketData()
            if candidates_fresh and not settle_active and not entry_delay_after_open_active:
                created = _evaluate_entry_candidates(account_equity)
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                if not candidates_fresh:
                    _log("PAPER_SIM: candidates stale; skipping entry intent creation.")
                if settle_active:
                    _log("PAPER_SIM: settle delay active; skipping entry intent creation.")
                if entry_delay_after_open_active:
                    _log("PAPER_SIM: entry delay active; skipping entry intent creation.")
            _log("PAPER_SIM: skipping live gate checks and broker position lookups.")
        elif cfg.execution_mode == "SCHWAB_401K_MANUAL":
            allowlist = live_gate.parse_allowlist()
            caps = live_gate.CapsConfig.from_env()
            decision_record["gates"]["live_gate_applied"] = False
            decision_record["inputs"]["account"]["source"] = "manual"
            if md is None:
                class _NoMarketData:
                    def get_last_two_closed_10m(self, symbol: str) -> list:
                        return []

                    def get_daily_bars(self, symbol: str) -> list:
                        return []

                md = _NoMarketData()
            account_equity = float(os.getenv("MANUAL_ACCOUNT_EQUITY", "0") or 0.0)
            decision_record["inputs"]["account"]["equity"] = account_equity
            if candidates_fresh and not settle_active and not entry_delay_after_open_active:
                created = _evaluate_entry_candidates(account_equity)
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                if not candidates_fresh:
                    _log("SCHWAB_401K_MANUAL: candidates stale; skipping entry intent creation.")
                if settle_active:
                    _log("SCHWAB_401K_MANUAL: settle delay active; skipping entry intent creation.")
                if entry_delay_after_open_active:
                    _log("SCHWAB_401K_MANUAL: entry delay active; skipping entry intent creation.")
        elif cfg.execution_mode == "ALPACA_PAPER":
            decision_record["gates"]["live_gate_applied"] = True
            allowlist = live_gate.parse_allowlist()
            caps = live_gate.CapsConfig.from_env()
            kill_switch_active, kill_reason = live_gate.is_kill_switch_active()
            live_gate.notify_kill_switch(kill_switch_active)
            paper_active = not kill_switch_active
            paper_reason = "alpaca_paper_enabled" if paper_active else f"kill switch active ({kill_reason})"
            positions_count = None
            try:
                positions = trading_client.get_all_positions()
                positions_count = len(positions)
            except Exception as exc:
                paper_active = False
                paper_reason = f"positions unavailable ({type(exc).__name__})"
            _log(f"Gate mode=ALPACA_PAPER status={'PASS' if paper_active else 'FAIL'} reason={paper_reason}")
            _log(f"Gate {live_gate.allowlist_summary(allowlist)}")
            _log(f"Gate {caps.summary()}")

            try:
                account = trading_client.get_account()
                decision_record["inputs"]["account"]["equity"] = float(account.equity)
                decision_record["inputs"]["account"]["buying_power"] = float(account.buying_power)
                decision_record["inputs"]["account"]["source"] = "alpaca"
            except Exception as exc:
                errors.append(
                    {
                        "where": "alpaca_account",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    }
                )
            account_equity = _get_account_equity(trading_client)
            if candidates_fresh and not settle_active and not entry_delay_after_open_active:
                created = _evaluate_entry_candidates(account_equity)
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                if not candidates_fresh:
                    _log("ALPACA_PAPER: candidates stale; skipping entry intent creation.")
                if settle_active:
                    _log("ALPACA_PAPER: settle delay active; skipping entry intent creation.")
                if entry_delay_after_open_active:
                    _log("ALPACA_PAPER: entry delay active; skipping entry intent creation.")
            if trading_client is None:
                _log("EXIT: skipping (no trading_client)")
            else:
                exits.manage_positions(
                    trading_client=trading_client,
                    md=md,
                    cfg=exits.ExitConfig.from_env(),
                    repo_root=repo_root,
                    dry_run=cfg.dry_run,
                    log=_log,
                    entry_delay_active=entry_delay_after_open_active,
                )
                try:
                    sell_loop.evaluate_positions(
                        store,
                        trading_client,
                        sell_loop.SellLoopConfig(candidates_csv=cfg.candidates_csv),
                    )
                except Exception as exc:
                    _log(f"WARNING: sell loop evaluation failed ({type(exc).__name__}: {exc})")

        else:
            decision_record["gates"]["live_gate_applied"] = True
            gate_result = live_gate.resolve_live_mode(cfg.dry_run)
            allowlist = live_gate.parse_allowlist()
            caps = live_gate.CapsConfig.from_env()
            live_active = gate_result.live_enabled
            live_reason = gate_result.reason
            live_ledger = None
            positions_count = None

            if live_active:
                live_ledger, ledger_reason = live_gate.load_live_ledger(repo_root)
                if live_ledger is None:
                    live_active = False
                    live_reason = f"ledger unavailable ({ledger_reason})"
                else:
                    if live_ledger.was_reset:
                        _log("Live ledger reset for new NY day.")
                    try:
                        positions = trading_client.get_all_positions()
                        positions_count = len(positions)
                    except Exception as exc:
                        live_active = False
                        live_reason = f"positions unavailable ({type(exc).__name__})"

            live_gate.notify_kill_switch(gate_result.kill_switch_active)
            live_gate.notify_live_status(live_active)

            mode = "LIVE" if live_active else "DRY_RUN"
            status = "PASS" if live_active else "FAIL"
            _log(f"Gate mode={mode} status={status} reason={live_reason}")
            _log(f"Gate {live_gate.allowlist_summary(allowlist)}")
            _log(f"Gate {caps.summary()}")

            if trading_client is not None:
                try:
                    account = trading_client.get_account()
                    decision_record["inputs"]["account"]["equity"] = float(account.equity)
                    decision_record["inputs"]["account"]["buying_power"] = float(account.buying_power)
                    decision_record["inputs"]["account"]["source"] = "alpaca"
                except Exception as exc:
                    errors.append(
                        {
                            "where": "alpaca_account",
                            "message": str(exc),
                            "exception_type": type(exc).__name__,
                        }
                    )
            account_equity = _get_account_equity(trading_client)
            if candidates_fresh and not settle_active and not entry_delay_after_open_active:
                created = _evaluate_entry_candidates(account_equity)
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                if not candidates_fresh:
                    _log("LIVE: candidates stale; skipping entry intent creation.")
                if settle_active:
                    _log("LIVE: settle delay active; skipping entry intent creation.")
                if entry_delay_after_open_active:
                    _log("LIVE: entry delay active; skipping entry intent creation.")
            if trading_client is None:
                _log("EXIT: skipping (no trading_client)")
            else:
                exits.manage_positions(
                    trading_client=trading_client,
                    md=md,
                    cfg=exits.ExitConfig.from_env(),
                    repo_root=repo_root,
                    dry_run=cfg.dry_run,
                    log=_log,
                    entry_delay_active=entry_delay_after_open_active,
                )
                try:
                    sell_loop.evaluate_positions(
                        store,
                        trading_client,
                        sell_loop.SellLoopConfig(candidates_csv=cfg.candidates_csv),
                    )
                except Exception as exc:
                    _log(f"WARNING: sell loop evaluation failed ({type(exc).__name__}: {exc})")

        now_ts = time.time()
        _log(
            "Entry intent consume gate: "
            f"settle_active={settle_active} "
            f"entry_delay_after_open_active={entry_delay_after_open_active} "
            f"candidates_fresh={candidates_fresh} "
            f"now_ts={now_ts:.3f}"
        )
        pop_diag: dict[str, Any] = {
            "now_ts": now_ts,
            "now_utc": _iso_utc(now_ts),
            "settle_active": bool(settle_active),
            "entry_delay_after_open_active": bool(entry_delay_after_open_active),
            "popped_count": 0,
            "popped_sample": [],
            "gate_blocked": False,
        }
        decision_record.setdefault("intents_meta", {})["entry_intent_pop"] = pop_diag

        # Defensive guard: never consume entry intents in SCHWAB manual mode while market is closed
        if (
            cfg.execution_mode == "SCHWAB_401K_MANUAL"
            and not decision_record["gates"]["market"]["is_open"]
        ):
            entry_intents = []
            pop_diag["gate_blocked"] = True
            pop_diag["block_reason"] = "manual_market_closed"
        else:
            if settle_active or entry_delay_after_open_active or (not candidates_fresh):
                entry_intents = []
                pop_diag["gate_blocked"] = True
                if not candidates_fresh:
                    pop_diag["block_reason"] = "candidates_stale"
                else:
                    pop_diag["block_reason"] = "entry_settle_gate"
            else:
                entry_intents = store.pop_due_entry_intents(now_ts)
                popped_count = len(entry_intents)
                pop_diag["popped_count"] = popped_count
                pop_diag["popped_sample"] = [
                    _slim_popped_entry_intent(intent) for intent in entry_intents[:5]
                ]
                if popped_count > 0 or db_debug:
                    _log(
                        f"Popped due entry intents: count={popped_count} "
                        f"sample={pop_diag['popped_sample']}"
                    )
                if popped_count == 0:
                    active_snapshot = _sqlite_db_snapshot(active_db_path, now_ts=now_ts)
                    pop_diag["db_counts_after_pop_attempt"] = {
                        "entry_intents_total": active_snapshot.get("entry_intents_total"),
                        "entry_intents_due_now": active_snapshot.get("entry_intents_due_now"),
                    }
                    due_now = active_snapshot.get("entry_intents_due_now")
                    if isinstance(due_now, int) and due_now > 0:
                        warning_payload = {
                            "where": "entry_intent_pop_consistency",
                            "message": "pop_due_entry_intents returned 0 while DB still reports due intents",
                            "db_path": str(active_db_path),
                            "entry_intents_due_now": due_now,
                            "entry_intents_total": active_snapshot.get("entry_intents_total"),
                            "now_ts": now_ts,
                        }
                        errors.append(warning_payload)
                        pop_diag["mismatch_warning"] = warning_payload
                        _log(
                            "WARNING: due entry intents remain after pop attempt; "
                            "possible DB path mismatch or timebase mismatch "
                            f"path={active_db_path} due_now={due_now}"
                        )
        intent_projection = []
        for intent in entry_intents:
            intent_projection.append(
                {
                    "symbol": getattr(intent, "symbol", ""),
                    "side": "buy",
                    "qty": getattr(intent, "size_shares", None),
                    "ref_price": getattr(intent, "ref_price", None),
                }
            )
        decision_record["intents"]["intents"] = intent_projection
        decision_record["intents"]["intent_count"] = len(intent_projection)
        positions = store.list_positions()
        open_positions_by_strategy: dict[str, int] = {}
        for position in positions:
            open_positions_by_strategy[position.strategy_id] = (
                open_positions_by_strategy.get(position.strategy_id, 0) + 1
            )
        state_symbols = {position.symbol for position in positions}
        open_positions_count = positions_count if positions_count is not None else len(state_symbols)
        max_positions = None
        if cfg.execution_mode not in {"PAPER_SIM", "DRY_RUN"}:
            max_positions = getattr(caps, "max_positions", None)
        constraints = portfolio_arbiter.PortfolioConstraints(
            max_positions=max_positions,
            max_positions_per_strategy=None,
            max_symbol_concentration=1,
            open_positions_count=open_positions_count,
            open_positions_by_strategy=open_positions_by_strategy,
            existing_symbols=sorted(state_symbols),
        )
        # Phase S1 arbitration per docs/ROADMAP.md: trade intents -> portfolio decision gate.
        trade_intents = [
            portfolio_intents.trade_intent_from_entry_intent(intent)
            for intent in entry_intents
        ]
        shadow_intents = shadow_strategies.clone_trade_intents_as_shadow(trade_intents)
        trade_intents.extend(shadow_intents)
        portfolio_decision = None
        try:
            portfolio_decision = portfolio_arbiter.arbitrate_intents(
                trade_intents,
                now_ts_utc=decision_ts_utc.timestamp(),
                constraints=constraints,
                run_id=decision_record["decision_id"],
                date_ny=decision_record["ny_date"],
            )
        except Exception as exc:
            traceback_lines = traceback.format_exc().splitlines()
            max_lines = 10
            short_traceback = "\n".join(traceback_lines[-max_lines:])

            # Hard cap to prevent pathological single-line tracebacks
            max_chars = 4096
            if len(short_traceback) > max_chars:
                short_traceback = short_traceback[-max_chars:]
            errors.append(
                {
                    "where": "portfolio_arbiter",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                    "traceback": short_traceback,
                    "context": {
                        "intent_count": len(entry_intents),
                        "symbols": [
                            getattr(intent, "symbol", "")
                            for intent in entry_intents[:10]
                        ],
                        "execution_mode": cfg.execution_mode,
                        "dry_run_forced": decision_record["mode"]["dry_run_forced"],
                    },
                }
            )
            decision_record["gates"]["blocks"].append(
                {
                    "code": "portfolio_decision_failed",
                    "message": "portfolio arbitration failed; entries blocked",
                }
            )
            _log(f"Portfolio arbitration failed: {exc}")
        approved_intents: list = []
        entry_intents_for_s2: list = []
        if portfolio_decision is not None:
            intent_lookup = {
                (intent.symbol, intent.strategy_id): intent for intent in entry_intents
            }
            for order in portfolio_decision.approved_orders:
                matched = intent_lookup.get((order.symbol, order.strategy_id))
                if matched is not None:
                    approved_intents.append(matched)
            entry_intents_for_s2 = list(approved_intents)
        s2_blocked = False
        if portfolio_decision is not None:
            try:
                sleeve_config, sleeve_errors = strategy_sleeves.load_sleeve_config()
                decision_record["sleeves"] = sleeve_config.to_snapshot()
                _record_s2_inputs(decision_record, sleeve_config)
                decision_record.setdefault("intents_meta", {})[
                    "entry_intents_pre_s2_count"
                ] = len(entry_intents_for_s2)
                if sleeve_errors:
                    decision_record["sleeves"]["errors"] = sleeve_errors[:10]
                    s2_blocked = True
                    decision_record["gates"]["blocks"].append(
                        {
                            "code": "s2_config_invalid",
                            "message": "strategy sleeve configuration invalid; entries blocked",
                        }
                    )
                    portfolio_s2_enforcement.append_rejections(
                        rejected=portfolio_decision.rejected_intents,
                        blocked=[
                            portfolio_s2_enforcement.BlockedIntent(
                                intent=intent,
                                rejection_reason="s2_config_invalid",
                                reason_codes=["s2_config_invalid"],
                            )
                            for intent in approved_intents
                        ],
                    )
                    portfolio_decision = portfolio_decision_contract.PortfolioDecision(
                        run_id=portfolio_decision.run_id,
                        date_ny=portfolio_decision.date_ny,
                        approved_orders=portfolio_decision.approved_orders,
                        rejected_intents=portfolio_decision.rejected_intents,
                        constraints_snapshot=portfolio_decision.constraints_snapshot,
                        decision_hash=portfolio_decision_contract.build_decision_hash(
                            portfolio_decision.to_payload()
                        ),
                    )
                    decision_record["s2_enforcement"] = {
                        "blocked_all": True,
                        "blocked_count": len(approved_intents),
                        "blocked_sample": [
                            {
                                "strategy_id": intent.strategy_id,
                                "symbol": intent.symbol,
                                "reason_codes": ["s2_config_invalid"],
                            }
                            for intent in approved_intents[:25]
                        ],
                        "reason_counts": {"s2_config_invalid": len(approved_intents)},
                        "portfolio_summary": {},
                        "strategy_summaries": {},
                        "pnl_source": sleeve_config.daily_pnl_source,
                        "pnl_parse_error": sleeve_config.daily_pnl_parse_error,
                    }
                    approved_intents = []
                else:
                    s2_result = portfolio_s2_enforcement.enforce_sleeves(
                        intents=entry_intents_for_s2,
                        positions=positions,
                        config=sleeve_config,
                    )
                    s2_blocked = s2_result.blocked_all
                    if s2_result.blocked or s2_result.blocked_all:
                        portfolio_s2_enforcement.append_rejections(
                            rejected=portfolio_decision.rejected_intents,
                            blocked=s2_result.blocked,
                        )
                    if s2_result.approved != approved_intents:
                        approved_intents = s2_result.approved
                        approved_keys = {
                            (intent.symbol, intent.strategy_id) for intent in approved_intents
                        }
                        approved_orders = [
                            order
                            for order in portfolio_decision.approved_orders
                            if (order.symbol, order.strategy_id) in approved_keys
                        ]
                        portfolio_decision = portfolio_decision_contract.PortfolioDecision(
                            run_id=portfolio_decision.run_id,
                            date_ny=portfolio_decision.date_ny,
                            approved_orders=approved_orders,
                            rejected_intents=portfolio_decision.rejected_intents,
                            constraints_snapshot=portfolio_decision.constraints_snapshot,
                            decision_hash="",
                        )
                    portfolio_decision = portfolio_decision_contract.PortfolioDecision(
                        run_id=portfolio_decision.run_id,
                        date_ny=portfolio_decision.date_ny,
                        approved_orders=portfolio_decision.approved_orders,
                        rejected_intents=portfolio_decision.rejected_intents,
                        constraints_snapshot=portfolio_decision.constraints_snapshot,
                        decision_hash=portfolio_decision_contract.build_decision_hash(
                            portfolio_decision.to_payload()
                        ),
                    )
                    decision_record["s2_enforcement"] = (
                        portfolio_s2_enforcement.build_enforcement_snapshot(
                            result=s2_result,
                            config=sleeve_config,
                        )
                    )
                    if s2_blocked:
                        decision_record["gates"]["blocks"].append(
                            {
                                "code": "s2_enforcement_blocked",
                                "message": "strategy sleeve enforcement blocked entries",
                            }
                        )
            except Exception as exc:
                decision_record["gates"]["blocks"].append(
                    {
                        "code": "s2_enforcement_failed",
                        "message": "strategy sleeve enforcement failed; entries blocked",
                    }
                )
                errors.append(
                    {
                        "where": "portfolio_s2_enforcement",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    }
                )
                approved_intents = []
                s2_blocked = True
        _update_intents_meta(
            decision_record,
            created_intents=entry_intents_created,
            entry_intents=entry_intents_for_s2,
            approved_intents=approved_intents,
            s2_snapshot=decision_record.get("s2_enforcement"),
        )
        _record_edge_window_meta(decision_record, edge_report)
        _record_one_shot_meta(decision_record, one_shot_cfg)
        if portfolio_decision is not None:
            decision_state_path = _state_dir() / "portfolio_decision_latest.json"
            portfolio_decision_contract.write_portfolio_decision(
                portfolio_decision, decision_state_path
            )
            decision_record["artifacts"]["portfolio_decision_state_path"] = str(
                decision_state_path.resolve()
            )
            decision_record["artifacts"]["portfolio_decision_hash"] = (
                portfolio_decision.decision_hash
            )
        intents = approved_intents
        entries_blocked = (
            portfolio_decision is None and bool(entry_intents)
        ) or s2_blocked
        if not entries_blocked:
            intents = _apply_one_shot_suppression(
                intents=intents,
                store=store,
                date_ny=decision_record["ny_date"],
                now_ts=decision_ts_utc.timestamp(),
                config=one_shot_cfg,
                decision_record=decision_record,
            )
        enforcement_context = None
        enforcement_records: list[dict] = []
        if portfolio_decision_enforce.enforcement_enabled():
            enforcement_context = portfolio_decision_enforce.load_decision_context(decision_record["ny_date"])
        if cfg.execution_mode not in {"PAPER_SIM", "DRY_RUN"}:
            decision_record["inputs"]["constraints_snapshot"]["allowlist_symbols"] = (
                sorted(allowlist) if allowlist else None
            )
            decision_record["inputs"]["constraints_snapshot"]["max_new_positions"] = getattr(
                caps, "max_positions", None
            )
            decision_record["inputs"]["constraints_snapshot"]["max_gross_exposure"] = getattr(
                caps, "max_gross_notional", None
            )
            decision_record["inputs"]["constraints_snapshot"]["max_notional_per_symbol"] = getattr(
                caps, "max_notional_per_symbol", None
            )

        symbol_state_store = state_machine.SymbolExecutionStateStore(
            date_ny=decision_record["ny_date"],
            state_dir=_state_dir(),
        )
        consumed_entries_store = state_machine.ConsumedEntriesStore(
            date_ny=decision_record["ny_date"],
            state_dir=_state_dir(),
        )
        if trading_client is not None:
            try:
                open_positions = trading_client.get_all_positions()
                open_symbols = [getattr(pos, "symbol", "") for pos in open_positions]
                entry_fill_ts = {}
                for pos in open_positions:
                    symbol = str(getattr(pos, "symbol", "")).upper()
                    if not symbol:
                        continue
                    strategy_id = DEFAULT_STRATEGY_ID
                    pos_state = store.get_position(symbol)
                    if pos_state is not None:
                        strategy_id = pos_state.strategy_id
                    record = store.get_entry_fill(
                        decision_record["ny_date"],
                        strategy_id,
                        symbol,
                    )
                    entry_fill_ts_value = state_machine.resolve_entry_fill_ts_utc(record)
                    if entry_fill_ts_value:
                        entry_fill_ts[symbol] = entry_fill_ts_value
                symbol_state_store.apply_open_positions(
                    open_symbols,
                    now_utc=decision_ts_utc,
                    entry_fill_ts_utc=entry_fill_ts,
                )
            except Exception:
                pass
        symbol_state_store.save()

        if cfg.execution_mode == "PAPER_SIM":
            if entries_blocked:
                _log("PAPER_SIM: portfolio decision unavailable; skipping entry simulation.")
                return
            now_utc = datetime.now(timezone.utc)
            date_ny = paper_sim.resolve_date_ny(now_utc)
            intent_by_symbol = {intent.symbol: intent for intent in intents}
            fills = paper_sim.simulate_fills(
                intents,
                date_ny=date_ny,
                now_utc=now_utc,
                repo_root=repo_root,
            )
            for fill in fills:
                if str(fill.get("side", "")).lower() != "buy":
                    continue
                symbol = str(fill.get("symbol", "")).upper()
                if not symbol:
                    continue
                matched_intent = intent_by_symbol.get(symbol)
                strategy_id = matched_intent.strategy_id if matched_intent else DEFAULT_STRATEGY_ID
                store.record_entry_fill(
                    date_ny=date_ny,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    filled_ts=now_utc.timestamp(),
                    source="paper_sim",
                )
            skipped = max(0, len(intents) - len(fills))
            ledger_rel = Path("ledger") / "PAPER_SIM" / f"{date_ny}.jsonl"
            for fill in fills:
                decision_record["actions"]["submitted_orders"].append(
                    {
                        "symbol": fill.get("symbol"),
                        "side": fill.get("side"),
                        "qty": fill.get("qty"),
                        "order_type": "paper_sim",
                        "client_order_id": fill.get("intent_id"),
                        "broker_order_id": None,
                        "idempotency_key": fill.get("intent_id"),
                        "intent_id": fill.get("intent_id"),
                        "status": "submitted",
                    }
                )
            if fills:
                ledgers_written.append(str((repo_root / ledger_rel).resolve()))
            _log(
                f"PAPER_SIM: wrote {len(fills)} fills to {ledger_rel} "
                f"(skipped {skipped} duplicates)"
            )
            return

        if cfg.execution_mode == "SCHWAB_401K_MANUAL":
            if entries_blocked:
                _log("SCHWAB_401K_MANUAL: portfolio decision unavailable; skipping entry tickets.")
                return
            if not intents:
                _log("SCHWAB_401K_MANUAL: no approved entry intents; skipping entry tickets.")
                return
            from execution_v2.schwab_manual_adapter import send_manual_tickets

            now_utc = datetime.now(timezone.utc)
            date_ny = paper_sim.resolve_date_ny(now_utc)
            result = send_manual_tickets(
                intents,
                ny_date=date_ny,
                repo_root=repo_root,
                now_utc=now_utc,
            )
            for intent_id in result.intent_ids:
                decision_record["actions"]["submitted_orders"].append(
                    {
                        "symbol": None,
                        "side": "buy",
                        "qty": None,
                        "order_type": "manual_ticket",
                        "client_order_id": intent_id,
                        "broker_order_id": None,
                        "idempotency_key": intent_id,
                        "intent_id": intent_id,
                        "status": "submitted" if result.posting_enabled else "skipped",
                    }
                )
            if result.ledger_path:
                ledgers_written.append(str(Path(result.ledger_path).resolve()))
            _log(
                f"SCHWAB_401K_MANUAL: tickets_sent={result.sent} "
                f"skipped={result.skipped} ledger={result.ledger_path or 'disabled'}"
            )
            return

        if cfg.execution_mode == "ALPACA_PAPER":
            if entries_blocked:
                _log("ALPACA_PAPER: portfolio decision unavailable; skipping entry orders.")
                _finalize_portfolio_enforcement(
                    records=enforcement_records,
                    date_ny=decision_record["ny_date"],
                    context=enforcement_context,
                )
                return
            now_utc = datetime.now(timezone.utc)
            date_ny = paper_sim.resolve_date_ny(now_utc)
            ledger_path = alpaca_paper.ledger_path(repo_root, date_ny)
            caps_ledger = alpaca_paper.load_caps_ledger(repo_root, date_ny)
            submitted = 0
            fills = 0
            wrote_ledger = False
            projected_open_positions = int(positions_count or 0)

            for intent in intents:
                if not paper_active:
                    _log(f"ALPACA_PAPER disabled; skipping {intent.symbol} ({paper_reason})")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": paper_reason}
                    )
                    continue
                if entry_delay_after_open_active:
                    _log(f"SKIP {intent.symbol}: entry delay after open active")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "entry_delay_after_open"}
                    )
                    continue
                if enforcement_context:
                    enforcement_result = portfolio_decision_enforce.evaluate_action(
                        "entry", intent.symbol, enforcement_context
                    )
                    enforcement_records.append(
                        portfolio_decision_enforce.build_enforcement_record(
                            date_ny=enforcement_context.date_ny,
                            symbol=enforcement_result.symbol,
                            decision=enforcement_result.decision,
                            enforced=enforcement_result.enforced,
                            reason_codes=enforcement_result.reason_codes,
                            decision_id=enforcement_result.decision_id,
                            decision_artifact_path=enforcement_context.artifact_path,
                            decision_batch_generated_at=(
                                enforcement_context.batch.generated_at
                                if enforcement_context.batch
                                else None
                            ),
                        )
                    )
                    if enforcement_result.decision == "BLOCK":
                        reason_codes = ",".join(enforcement_result.reason_codes)
                        _log(
                            "Gate PORTFOLIO_DECISION FAIL "
                            f"{intent.symbol}: {reason_codes}"
                        )
                        decision_record["actions"]["skipped"].append(
                            {
                                "symbol": intent.symbol,
                                "reason": f"portfolio_decision_block:{reason_codes}",
                            }
                        )
                        continue
                if _has_open_order_or_position(trading_client, intent.symbol):
                    _log(f"SKIP {intent.symbol}: open order/position exists")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "open_order_or_position"}
                    )
                    continue
                quality_ok, quality_reason = _entry_submit_quality_check(intent, md)
                if not quality_ok:
                    _log(f"SKIP {intent.symbol}: {quality_reason}")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": quality_reason}
                    )
                    continue
                if consumed_entries_store and consumed_entries_store.is_consumed(intent.symbol):
                    _log(f"SKIP {intent.symbol}: already consumed today")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "already_consumed_today"}
                    )
                    continue
                if symbol_state_store:
                    symbol_state = symbol_state_store.get(intent.symbol)
                    if symbol_state.state != "FLAT":
                        _log(
                            f"SKIP {intent.symbol}: symbol state {symbol_state.state} not flat"
                        )
                        decision_record["actions"]["skipped"].append(
                            {"symbol": intent.symbol, "reason": "symbol_state_not_flat"}
                        )
                        continue

                key = generate_idempotency_key(
                    intent.strategy_id,
                    date_ny,
                    intent.symbol,
                    "buy",
                    intent.size_shares,
                )
                if store.has_order_idempotency_key(key):
                    _log(f"SKIP {intent.symbol}: idempotency key already used")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "idempotency_key_used"}
                    )
                    continue

                allowed, cap_reason = live_gate.enforce_caps(
                    intent,
                    caps_ledger,
                    allowlist,
                    caps,
                    open_positions=projected_open_positions,
                )
                status = "PASS" if allowed else "FAIL"
                _log(f"Gate {status} {intent.symbol}: {cap_reason}")
                if not allowed:
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": cap_reason}
                    )
                    continue

                try:
                    order_id = _submit_market_entry(trading_client, intent, dry_run=False)
                    order_id_str = str(order_id) if order_id is not None else None
                    store.record_order_once(
                        key,
                        intent.strategy_id,
                        intent.symbol,
                        "buy",
                        intent.size_shares,
                        external_order_id=order_id_str,
                    )
                    store.record_order_submission(
                        decision_id=decision_record["decision_id"],
                        intent_id=key,
                        symbol=intent.symbol,
                        side="buy",
                        qty=intent.size_shares,
                        idempotency_key=key,
                        external_order_id=order_id_str,
                    )
                    submitted += 1
                    _log(f"SUBMITTED {intent.symbol}: qty={intent.size_shares} order_id={order_id}")
                    decision_record["actions"]["submitted_orders"].append(
                        {
                            "symbol": intent.symbol,
                            "side": "buy",
                            "qty": intent.size_shares,
                            "order_type": "market",
                            "client_order_id": key,
                            "broker_order_id": order_id_str,
                            "idempotency_key": key,
                            "intent_id": key,
                            "status": "submitted",
                        }
                    )
                    if symbol_state_store:
                        symbol_state_store.transition(
                            intent.symbol,
                            "ENTERING",
                            now_utc=now_utc,
                            entry_intent_id=key,
                            entry_order_id=order_id_str or key,
                        )
                        symbol_state_store.save()
                    if consumed_entries_store:
                        consumed_entries_store.mark(intent.symbol, now_utc)
                    projected_open_positions += 1
                    candidate_notes = store.get_candidate_notes(intent.symbol) or "scan:n/a"
                    send_verbose_alert(
                        "TRADE",
                        f"SUBMITTED {intent.symbol}",
                        (
                            f"qty={intent.size_shares} ref={intent.ref_price} "
                            f"pivot={intent.pivot_level} dist={intent.dist_pct:.2f}% "
                            f"SL={intent.stop_loss} TP={intent.take_profit} "
                            f"boh_at={_format_ts(intent.boh_confirmed_at)} reason={candidate_notes}"
                        ),
                        component="EXECUTION_V2",
                        throttle_key=f"submit_{intent.symbol}",
                        throttle_seconds=60,
                    )
                    order_info = None
                    if order_id:
                        try:
                            order_info = trading_client.get_order_by_id(order_id)
                        except Exception as exc:
                            _log(f"WARNING: failed to fetch Alpaca order {order_id}: {exc}")
                    if order_info is None:
                        order_info = SimpleNamespace(id=order_id)
                    event = alpaca_paper.build_order_event(
                        intent_id=key,
                        symbol=intent.symbol,
                        qty=intent.size_shares,
                        ref_price=float(intent.ref_price),
                        order=order_info,
                        now_utc=now_utc,
                    )
                    written, skipped = alpaca_paper.append_events(ledger_path, [event])
                    # ALPACA_PAPER observability: bounded post-submit refresh for near-instant fills
                    # Append-only: if broker state materially changes (new -> filled), append a second ORDER_STATUS event.
                    def _evt_sig(evt: dict) -> tuple:
                        return (
                            str(evt.get("status")),
                            float(evt.get("filled_qty") or 0.0),
                            evt.get("filled_avg_price"),
                            evt.get("updated_at"),
                            evt.get("filled_at"),
                        )

                    _sig0 = _evt_sig(event)
                    _refresh_sleeps = (0.05, 0.10, 0.15, 0.30, 0.50, 0.70, 1.00, 1.00)  # total ~= 3.80s
                    if order_id:
                        for _sleep_s in _refresh_sleeps:
                            try:
                                time.sleep(_sleep_s)
                                refreshed_order = trading_client.get_order_by_id(order_id)
                                refreshed_event = alpaca_paper.build_order_event(
                                    intent_id=key,
                                    symbol=intent.symbol,
                                    qty=intent.size_shares,
                                    ref_price=float(intent.ref_price),
                                    order=refreshed_order,
                                    now_utc=datetime.now(timezone.utc),
                                )
                                _sig1 = _evt_sig(refreshed_event)
                                if _sig1 != _sig0:
                                    alpaca_paper.append_events(ledger_path, [refreshed_event])
                                    # If filled_qty transitions 0 -> >0, record fill + OPEN transition (best-effort)
                                    try:
                                        if float(_sig0[1]) <= 0 and float(refreshed_event.get("filled_qty") or 0) > 0:
                                            fills += 1
                                            store.record_entry_fill(
                                                date_ny=date_ny,
                                                strategy_id=intent.strategy_id,
                                                symbol=intent.symbol,
                                                filled_ts=datetime.now(timezone.utc).timestamp(),
                                                source="alpaca_paper",
                                            )
                                            if symbol_state_store:
                                                symbol_state_store.transition(
                                                    intent.symbol,
                                                    "OPEN",
                                                    now_utc=datetime.now(timezone.utc),
                                                    entry_fill_ts_utc=datetime.now(timezone.utc).isoformat(),
                                                )
                                                symbol_state_store.save()
                                    except Exception:
                                        pass
                                    break
                            except Exception as exc:
                                _log(f"WARNING: post-submit refresh failed for {intent.symbol} order {order_id}: {exc}")
                                continue

                    if written:
                        if not wrote_ledger:
                            ledgers_written.append(str(ledger_path.resolve()))
                            wrote_ledger = True
                        try:
                            caps_ledger.add_entry(
                                order_id_str or key,
                                intent.symbol,
                                float(intent.size_shares) * float(intent.ref_price),
                                now_utc.isoformat(),
                            )
                        except Exception:
                            pass
                    if event.get("filled_qty"):
                        try:
                            if float(event["filled_qty"]) > 0:
                                fills += 1
                                store.record_entry_fill(
                                    date_ny=date_ny,
                                    strategy_id=intent.strategy_id,
                                    symbol=intent.symbol,
                                    filled_ts=now_utc.timestamp(),
                                    source="alpaca_paper",
                                )
                                if symbol_state_store:
                                    symbol_state_store.transition(
                                        intent.symbol,
                                        "OPEN",
                                        now_utc=now_utc,
                                        entry_fill_ts_utc=now_utc.isoformat(),
                                    )
                                    symbol_state_store.save()
                        except Exception:
                            pass
                    if skipped:
                        _log(f"ALPACA_PAPER: skipped duplicate intent {intent.symbol}")
                except Exception as exc:
                    _log(f"ERROR submitting {intent.symbol}: {exc}")
                    retry_delay = _parse_int_env("ENTRY_SUBMIT_RETRY_DELAY_SECONDS", 60, min_value=0)
                    _requeue_entry_intent(
                        store,
                        intent,
                        delay_seconds=retry_delay,
                        reason="alpaca_paper_submit_error",
                    )
                    decision_record["actions"]["errors"].append(
                        {
                            "where": "alpaca_paper_submit",
                            "message": str(exc),
                            "exception_type": type(exc).__name__,
                        }
                    )
                    slack_alert(
                        "ERROR",
                        f"Execution error for {intent.symbol}",
                        f"{type(exc).__name__}: {exc}",
                        component="EXECUTION_V2",
                        throttle_key=f"submit_error_{intent.symbol}",
                        throttle_seconds=300,
                    )

            _log(
                f"ALPACA_PAPER: orders_submitted={submitted} fills_received={fills} ledger={ledger_path}"
            )
            _finalize_portfolio_enforcement(
                records=enforcement_records,
                date_ny=decision_record["ny_date"],
                context=enforcement_context,
            )
            return

        if entries_blocked:
            _log("Portfolio decision unavailable; skipping entry orders.")
        projected_open_positions = int(positions_count or 0)
        for intent in intents:
            effective_dry_run = not live_active
            if enforcement_context:
                enforcement_result = portfolio_decision_enforce.evaluate_action(
                    "entry", intent.symbol, enforcement_context
                )
                enforcement_records.append(
                    portfolio_decision_enforce.build_enforcement_record(
                        date_ny=enforcement_context.date_ny,
                        symbol=enforcement_result.symbol,
                        decision=enforcement_result.decision,
                        enforced=enforcement_result.enforced,
                        reason_codes=enforcement_result.reason_codes,
                        decision_id=enforcement_result.decision_id,
                        decision_artifact_path=enforcement_context.artifact_path,
                        decision_batch_generated_at=(
                            enforcement_context.batch.generated_at
                            if enforcement_context.batch
                            else None
                        ),
                    )
                )
                if enforcement_result.decision == "BLOCK":
                    reason_codes = ",".join(enforcement_result.reason_codes)
                    _log(
                        "Gate PORTFOLIO_DECISION FAIL "
                        f"{intent.symbol}: {reason_codes}"
                    )
                    decision_record["actions"]["skipped"].append(
                        {
                            "symbol": intent.symbol,
                            "reason": f"portfolio_decision_block:{reason_codes}",
                        }
                    )
                    continue
            if _has_open_order_or_position(trading_client, intent.symbol):
                _log(f"SKIP {intent.symbol}: open order/position exists")
                decision_record["actions"]["skipped"].append(
                    {"symbol": intent.symbol, "reason": "open_order_or_position"}
                )
                continue
            quality_ok, quality_reason = _entry_submit_quality_check(intent, md)
            if not quality_ok:
                _log(f"SKIP {intent.symbol}: {quality_reason}")
                decision_record["actions"]["skipped"].append(
                    {"symbol": intent.symbol, "reason": quality_reason}
                )
                continue
            if entry_delay_after_open_active:
                _log(f"SKIP {intent.symbol}: entry delay after open active")
                decision_record["actions"]["skipped"].append(
                    {"symbol": intent.symbol, "reason": "entry_delay_after_open"}
                )
                continue
            if consumed_entries_store and consumed_entries_store.is_consumed(intent.symbol):
                _log(f"SKIP {intent.symbol}: already consumed today")
                decision_record["actions"]["skipped"].append(
                    {"symbol": intent.symbol, "reason": "already_consumed_today"}
                )
                continue
            if symbol_state_store:
                symbol_state = symbol_state_store.get(intent.symbol)
                if symbol_state.state != "FLAT":
                    _log(
                        f"SKIP {intent.symbol}: symbol state {symbol_state.state} not flat"
                    )
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "symbol_state_not_flat"}
                    )
                    continue

            key = generate_idempotency_key(
                intent.strategy_id,
                decision_record["ny_date"],
                intent.symbol,
                "buy",
                intent.size_shares,
            )
            if not effective_dry_run:
                if store.has_order_idempotency_key(key):
                    _log(f"SKIP {intent.symbol}: idempotency key already used")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "idempotency_key_used"}
                    )
                    continue

            if live_active and live_ledger is not None:
                allowed, cap_reason = live_gate.enforce_caps(
                    intent,
                    live_ledger,
                    allowlist,
                    caps,
                    open_positions=projected_open_positions,
                )
                status = "PASS" if allowed else "FAIL"
                _log(f"Gate {status} {intent.symbol}: {cap_reason}")
                if not allowed:
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": cap_reason}
                    )
                    continue

            try:
                order_id = _submit_market_entry(trading_client, intent, effective_dry_run)
                order_id_str = str(order_id) if order_id is not None else None
                _log(f"SUBMITTED {intent.symbol}: qty={intent.size_shares} order_id={order_id}")
                if order_id == "dry-run-skipped":
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "dry_run_ledger_duplicate"}
                    )
                else:
                    if not effective_dry_run:
                        store.record_order_once(
                            key,
                            intent.strategy_id,
                            intent.symbol,
                            "buy",
                            intent.size_shares,
                            external_order_id=order_id_str,
                        )
                        store.record_order_submission(
                            decision_id=decision_record["decision_id"],
                            intent_id=key,
                            symbol=intent.symbol,
                            side="buy",
                            qty=intent.size_shares,
                            idempotency_key=key,
                            external_order_id=order_id_str,
                        )
                    decision_record["actions"]["submitted_orders"].append(
                        {
                            "symbol": intent.symbol,
                            "side": "buy",
                            "qty": intent.size_shares,
                            "order_type": "market",
                            "client_order_id": key,
                            "broker_order_id": order_id_str,
                            "idempotency_key": key,
                            "intent_id": key,
                            "status": "submitted",
                        }
                    )
                    if symbol_state_store:
                        symbol_state_store.transition(
                            intent.symbol,
                            "ENTERING",
                            now_utc=datetime.now(timezone.utc),
                            entry_intent_id=key,
                            entry_order_id=order_id_str or key,
                        )
                        symbol_state_store.save()
                    if consumed_entries_store:
                        consumed_entries_store.mark(intent.symbol, datetime.now(timezone.utc))
                    projected_open_positions += 1
                    if effective_dry_run:
                        ledgers_written.append("/root/avwap_r3k_scanner/state/dry_run_ledger.json")
                candidate_notes = store.get_candidate_notes(intent.symbol) or "scan:n/a"
                send_verbose_alert(
                    "TRADE",
                    f"SUBMITTED {intent.symbol}",
                    (
                        f"qty={intent.size_shares} ref={intent.ref_price} "
                        f"pivot={intent.pivot_level} dist={intent.dist_pct:.2f}% "
                        "SL=managed TP=managed "
                        f"boh_at={_format_ts(intent.boh_confirmed_at)} reason={candidate_notes}"
                    ),
                    component="EXECUTION_V2",
                    throttle_key=f"submit_{intent.symbol}",
                    throttle_seconds=60,
                )
                if order_id_str and not effective_dry_run:
                    store.update_external_order_id(key, order_id_str)
                    if live_active and live_ledger is not None:
                        try:

                            notional = float(intent.size_shares) * float(intent.ref_price)
                            live_ledger.add_entry(
                                order_id_str or key,
                                intent.symbol,
                                notional,
                                datetime.now(tz=timezone.utc).isoformat(),
                            )
                            live_ledger.save()
                            ledgers_written.append(str(Path(live_ledger.path).resolve()))
                        except Exception as exc:
                            _log(f"WARNING: failed to update live ledger: {exc}")
            except Exception as exc:
                _log(f"ERROR submitting {intent.symbol}: {exc}")
                retry_delay = _parse_int_env("ENTRY_SUBMIT_RETRY_DELAY_SECONDS", 60, min_value=0)
                _requeue_entry_intent(
                    store,
                    intent,
                    delay_seconds=retry_delay,
                    reason="live_submit_error",
                )
                decision_record["actions"]["errors"].append(
                    {
                        "where": "live_submit",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    }
                )
                slack_alert(
                    "ERROR",
                    f"Execution error for {intent.symbol}",
                    f"{type(exc).__name__}: {exc}",
                    component="EXECUTION_V2",
                    throttle_key=f"submit_error_{intent.symbol}",
                    throttle_seconds=300,
                )

        _finalize_portfolio_enforcement(
            records=enforcement_records,
            date_ny=decision_record["ny_date"],
            context=enforcement_context,
        )
        trim_intents = store.pop_trim_intents()
        if not trim_intents:
            return

        for intent in trim_intents:
            symbol = str(intent["symbol"]).upper()
            if symbol_state_store:
                symbol_state = symbol_state_store.get(symbol)
                entry_fill_ts = symbol_state.entry_fill_ts_utc
                closed_bars = None
                if md is not None:
                    try:
                        closed_bars = md.get_last_two_closed_10m(symbol)
                    except Exception:
                        closed_bars = None
                min_exit_seconds = _parse_int_env("MIN_EXIT_ARMING_SECONDS", 120, min_value=0)
                if not state_machine.is_exit_armed(
                    entry_fill_ts_utc=entry_fill_ts,
                    now_utc=datetime.now(timezone.utc),
                    min_seconds=min_exit_seconds,
                    closed_10m_bars=closed_bars,
                ):
                    _log(f"SKIP {symbol}: exit not armed yet")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": symbol, "reason": "exit_not_armed_yet"}
                    )
                    continue
            try:
                position = trading_client.get_open_position(symbol)
            except Exception:
                continue

            try:
                current_price = float(getattr(position, "current_price", position.market_value))
            except Exception:
                current_price = None

            try:
                total_qty = int(float(position.qty))
            except Exception:
                continue
            state = store.get_position(symbol)
            stop_price = None
            if state is not None:
                stop_price = state.stop_price

            pct = float(intent["pct"])
            reason = intent["reason"]
            if pct <= 0:
                continue

            if pct >= 1.0:
                if not live_active:
                    _log(f"DRY_RUN: would close {symbol} (reason={reason})")
                    continue
                from alpaca.trading.requests import ClosePositionRequest

                close_opts = ClosePositionRequest(qty=str(total_qty))
                trading_client.close_position(symbol, close_options=close_opts)
                send_verbose_alert(
                    "TRADE",
                    f"CLOSE {symbol}",
                    (
                        f"reason={reason} qty={total_qty} "
                        f"price={current_price} stop={stop_price}"
                    ),
                    component="EXECUTION_V2",
                    throttle_key=f"close_{symbol}",
                    throttle_seconds=60,
                )
                continue

            qty = int(total_qty * pct)
            if qty <= 0:
                continue

            ref_price = current_price or float(position.avg_entry_price)
            key = generate_idempotency_key(
                state.strategy_id if state is not None else DEFAULT_STRATEGY_ID,
                decision_record["ny_date"],
                symbol,
                "sell",
                qty,
            )
            if live_active:
                if store.has_order_idempotency_key(key):
                    _log(f"SKIP {symbol}: idempotency key already used")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": symbol, "reason": "idempotency_key_used"}
                    )
                    continue

            if not live_active:
                _log(f"DRY_RUN: would trim {symbol} qty={qty} reason={reason}")
                continue

            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            response = trading_client.submit_order(order)
            order_id = getattr(response, "id", None)
            # ALPACA_PAPER observability: record SELL submissions to the paper ledger.
            # (BUY path already records; without this, SELLs can appear broker-side with no repo trace.)
            if cfg.execution_mode == "ALPACA_PAPER":
                try:
                    from types import SimpleNamespace
                    now_utc = datetime.now(timezone.utc)
                    order_info = None
                    if order_id:
                        try:
                            order_info = trading_client.get_order_by_id(order_id)
                        except Exception as exc:
                            _log(f"WARNING: failed to fetch Alpaca order {order_id}: {exc}")
                    if order_info is None:
                        order_info = SimpleNamespace(id=order_id)
                    event = alpaca_paper.build_order_event(
                        intent_id=key,
                        symbol=symbol,
                        qty=qty,
                        ref_price=float(ref_price),
                        order=order_info,
                        now_utc=now_utc,
                    )
                    written, skipped = alpaca_paper.append_events(ledger_path, [event])
                    # ALPACA_PAPER observability: bounded post-submit refresh for near-instant fills
                    # Append-only: if broker state materially changes (new -> filled), append a second ORDER_STATUS event.
                    def _evt_sig(evt: dict) -> tuple:
                        return (
                            str(evt.get("status")),
                            float(evt.get("filled_qty") or 0.0),
                            evt.get("filled_avg_price"),
                            evt.get("updated_at"),
                            evt.get("filled_at"),
                        )

                    _sig0 = _evt_sig(event)
                    _refresh_sleeps = (0.05, 0.10, 0.15, 0.30, 0.50, 0.70, 1.00, 1.00)  # total ~= 3.80s
                    if order_id:
                        for _sleep_s in _refresh_sleeps:
                            try:
                                time.sleep(_sleep_s)
                                refreshed_order = trading_client.get_order_by_id(order_id)
                                refreshed_event = alpaca_paper.build_order_event(
                                    intent_id=key,
                                    symbol=symbol,
                                    qty=qty,
                                    ref_price=float(ref_price),
                                    order=refreshed_order,
                                    now_utc=datetime.now(timezone.utc),
                                )
                                _sig1 = _evt_sig(refreshed_event)
                                if _sig1 != _sig0:
                                    alpaca_paper.append_events(ledger_path, [refreshed_event])
                                    lp = str(ledger_path.resolve())
                                    if lp not in ledgers_written:
                                        ledgers_written.append(lp)
                                    break
                            except Exception as exc:
                                _log(f"WARNING: post-submit refresh failed for {symbol} order {order_id}: {exc}")
                                continue

                    if written:
                        lp = str(ledger_path.resolve())
                        if lp not in ledgers_written:
                            ledgers_written.append(lp)
                        _log(f"ALPACA_PAPER: wrote SELL event for {symbol} order_id={order_id}")
                except Exception as exc:
                    _log(f"WARNING: failed to write ALPACA_PAPER SELL ledger event for {symbol}: {exc}")
            if order_id:
                store.record_order_once(
                    key,
                    state.strategy_id if state is not None else DEFAULT_STRATEGY_ID,
                    symbol,
                    "sell",
                    qty,
                    external_order_id=str(order_id),
                )
                store.update_external_order_id(key, order_id)
                store.record_order_submission(
                    decision_id=decision_record["decision_id"],
                    intent_id=key,
                    symbol=symbol,
                    side="sell",
                    qty=qty,
                    idempotency_key=key,
                    external_order_id=str(order_id),
                )
            decision_record["actions"]["submitted_orders"].append(
                {
                    "symbol": symbol,
                    "side": "sell",
                    "qty": qty,
                    "order_type": "market",
                    "client_order_id": key,
                    "broker_order_id": str(order_id) if order_id else None,
                    "idempotency_key": key,
                    "intent_id": key,
                    "status": "submitted",
                }
            )
            if symbol_state_store:
                symbol_state_store.transition(
                    symbol,
                    "EXITING",
                    now_utc=datetime.now(timezone.utc),
                    exit_order_id=str(order_id) if order_id else key,
                )
                symbol_state_store.save()
            send_verbose_alert(
                "TRADE",
                f"TRIM {symbol}",
                (
                    f"reason={reason} qty={qty} pct={pct:.2f} "
                    f"price={current_price} stop={stop_price}"
                ),
                component="EXECUTION_V2",
                throttle_key=f"trim_{symbol}_{reason}",
                throttle_seconds=60,
            )
    except Exception as exc:
        errors.append(
            {
                "where": "run_once",
                "message": str(exc),
                "exception_type": type(exc).__name__,
            }
        )
        raise
    finally:
        skipped_actions = decision_record.get("actions", {}).get("skipped", []) or []
        skip_reason_counts = _summarize_skip_reasons(skipped_actions)
        lifecycle_reason_counts = (
            decision_record.get("intents_meta", {})
            .get("entry_intent_lifecycle_reason_counts", {})
        )
        for reason, count in lifecycle_reason_counts.items():
            skip_reason_counts[reason] = skip_reason_counts.get(reason, 0) + int(count)
        decision_record["actions"]["skipped_reason_counts"] = skip_reason_counts
        decision_record.setdefault("intents_meta", {})["skip_reason_counts"] = skip_reason_counts
        market_is_open = decision_record.get("gates", {}).get("market", {}).get("is_open")
        is_material = _is_material_cycle(decision_record, cfg, market_is_open)
        if is_material:
            _write_portfolio_decision_latest(
                decision_record=decision_record,
                latest_path=latest_path,
                errors=errors,
                blocks=blocks,
                record_error=True,
            )
            portfolio_decisions.write_portfolio_decision(decision_record, decision_path)
            _log(f"Portfolio decision recorded: {decision_path}")
        else:
            # Non-material (e.g., market-closed) cycles should still refresh the operator-facing
            # "latest decision" artifact for observability, but MUST NOT append a ledger row.
            _write_portfolio_decision_latest(
                decision_record=decision_record,
                latest_path=latest_path,
                errors=errors,
                blocks=blocks,
                record_error=False,
            )
        _write_execution_heartbeat(cfg, decision_record, candidates_snapshot)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execution V2 - Trading Orchestration")
    parser.add_argument("--candidates-csv", default=os.getenv("WATCHLIST_FILE", "daily_candidates.csv"))
    parser.add_argument(
        "--db-path",
        default=os.getenv("EXECUTION_V2_DB", "data/execution_v2.sqlite"),
        help="SQLite path for execution state (default: EXECUTION_V2_DB or data/execution_v2.sqlite)",
    )
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("EXECUTION_POLL_SECONDS", "300")))
    parser.add_argument("--ignore-market-hours", action="store_true", default=(os.getenv("EXEC_V2_IGNORE_MARKET_HOURS","0").strip() in ("1","true","TRUE","yes","YES")), help="Test-only: run cycles even when market is closed")
    parser.add_argument(
        "--entry-delay-min",
        dest="entry_delay_min_sec",
        type=int,
        default=int(os.getenv("ENTRY_DELAY_MIN_SECONDS", "60")),
    )
    parser.add_argument(
        "--entry-delay-max",
        dest="entry_delay_max_sec",
        type=int,
        default=int(os.getenv("ENTRY_DELAY_MAX_SECONDS", "240")),
    )
    parser.add_argument(
        "--config-check",
        action="store_true",
        help="Validate execution environment and exit (offline, no network)",
    )
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("DRY_RUN", "0") == "1")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single execution cycle then exit cleanly",
    )

    return parser.parse_args()


def main() -> None:
    cfg = _parse_args()
    cfg.execution_mode = _resolve_execution_mode()
    if cfg.config_check:
        ok, issues = run_config_check()
        if ok:
            _log("CONFIG_CHECK_OK")
            raise SystemExit(0)
        for issue in issues:
            _log(f"CONFIG_CHECK_FAIL {issue}")
        raise SystemExit(1)
    if cfg.execution_mode in {"LIVE", "ALPACA_PAPER"}:
        cfg.dry_run = False
    else:
        cfg.dry_run = True
    db_dir = os.path.dirname(cfg.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    slack_alert(
        "INFO",
        "Execution V2 started",
        f"execution_mode={cfg.execution_mode} dry_run={cfg.dry_run} poll_seconds={cfg.poll_seconds}",
        component="EXECUTION_V2",
        throttle_key="execution_v2_start",
        throttle_seconds=300,
    )

    if cfg.run_once:
        run_once(cfg)
        _log("Execution V2 run_once complete.")
        return

    while True:
        try:
            run_once(cfg)
        except Exception as exc:
            _log(f"ERROR: unexpected exception: {exc}")
            slack_alert(
                "ERROR",
                "Execution V2 exception",
                f"{type(exc).__name__}: {exc}",
                component="EXECUTION_V2",
                throttle_key="execution_v2_exception",
                throttle_seconds=300,
            )

        if cfg.run_once:
            slack_alert("execution_v2: --run-once enabled; exiting after single cycle.")
            break
        
        time.sleep(resolve_poll_seconds(cfg))


if __name__ == "__main__":
    main()
