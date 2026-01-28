"""
Execution V2 – Orchestration Entrypoint
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import time
import traceback
from datetime import datetime, timezone, time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from alerts.slack import (
    slack_alert,
    send_verbose_alert,
    maybe_send_heartbeat,
    maybe_send_daily_summary,
)
from execution_v2 import buy_loop, exits
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
from execution_v2.orders import generate_idempotency_key
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

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    order = MarketOrderRequest(
        symbol=intent.symbol,
        qty=intent.size_shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    response = trading_client.submit_order(order)
    return getattr(response, "id", None)


def _get_account_equity(trading_client: TradingClient) -> float:
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


def _decision_cycle_info(cfg) -> dict:
    service_name = os.getenv("SYSTEMD_UNIT") or None
    return {
        "loop_interval_sec": getattr(cfg, "poll_seconds", None),
        "service_name": service_name,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
    }


def _init_decision_record(cfg, candidates_snapshot: dict, now_utc: datetime) -> dict:
    now_ny = now_utc.astimezone(clocks.ET)
    dry_run_env = os.getenv("DRY_RUN", "0") == "1"
    exec_env = os.getenv("EXECUTION_MODE")
    dry_run_forced = dry_run_env and bool(exec_env and exec_env.strip().upper() != "DRY_RUN")
    ny_date = now_ny.date().isoformat()
    decisions_path = portfolio_decisions.resolve_portfolio_decisions_path(now_ny)
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
    if market_is_open or getattr(cfg, "ignore_market_hours", False):
        return True
    actions = decision_record.get("actions", {})
    intents = decision_record.get("intents", {})
    errors = actions.get("errors") or []
    if errors:
        return True
    intent_count = int(intents.get("intent_count", 0) or 0)
    if intent_count > 0 or (intents.get("intents") or []):
        return True
    submitted_orders = actions.get("submitted_orders") or []
    if submitted_orders:
        return True
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
    candidates_snapshot = _snapshot_candidates_csv(cfg.candidates_csv)
    decision_record = _init_decision_record(cfg, candidates_snapshot, decision_ts_utc)
    decision_path = Path(decision_record["artifacts"]["portfolio_decisions_path"])
    latest_path = _state_dir() / "portfolio_decision_latest.json"
    decision_record["artifacts"]["portfolio_decision_latest_path"] = str(latest_path.resolve())
    errors = decision_record["actions"]["errors"]
    blocks = decision_record["gates"]["blocks"]
    ledgers_written = decision_record["artifacts"]["ledgers_written"]
    positions_count: int | None = None
    entry_intents_created: list = []
    now_et: datetime | None = None

    try:
        store = StateStore(cfg.db_path)
        if cfg.entry_delay_min_sec > cfg.entry_delay_max_sec:
            cfg.entry_delay_min_sec, cfg.entry_delay_max_sec = cfg.entry_delay_max_sec, cfg.entry_delay_min_sec
        buy_cfg = buy_loop.BuyLoopConfig(
            candidates_csv=cfg.candidates_csv,
            entry_delay_min_sec=cfg.entry_delay_min_sec,
            entry_delay_max_sec=cfg.entry_delay_max_sec,
        )
        repo_root = Path(__file__).resolve().parents[1]
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
            if not settle_active:
                created = buy_loop.evaluate_and_create_entry_intents(
                    store,
                    md,
                    buy_cfg,
                    account_equity,
                    created_intents=entry_intents_created,
                )
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                _log("PAPER_SIM: settle delay active; skipping entry intent creation.")
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
            if not settle_active:
                created = buy_loop.evaluate_and_create_entry_intents(
                    store,
                    md,
                    buy_cfg,
                    account_equity,
                    created_intents=entry_intents_created,
                )
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                _log("SCHWAB_401K_MANUAL: settle delay active; skipping entry intent creation.")
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
            if not settle_active:
                created = buy_loop.evaluate_and_create_entry_intents(
                    store,
                    md,
                    buy_cfg,
                    account_equity,
                    created_intents=entry_intents_created,
                )
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                _log("ALPACA_PAPER: settle delay active; skipping entry intent creation.")
            exits.manage_positions(
                trading_client=trading_client,
                md=md,
                cfg=exits.ExitConfig.from_env(),
                repo_root=repo_root,
                dry_run=cfg.dry_run,
                log=_log,
            )
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
            if not settle_active:
                created = buy_loop.evaluate_and_create_entry_intents(
                    store,
                    md,
                    buy_cfg,
                    account_equity,
                    created_intents=entry_intents_created,
                )
                if created:
                    _log(f"Created {created} entry intents.")
                    _record_created_intents_meta(decision_record, entry_intents_created, created)
            else:
                _log("LIVE: settle delay active; skipping entry intent creation.")
            exits.manage_positions(
                trading_client=trading_client,
                md=md,
                cfg=exits.ExitConfig.from_env(),
                repo_root=repo_root,
                dry_run=cfg.dry_run,
                log=_log,
            )

        now_ts = time.time()

        # Defensive guard: never consume entry intents in SCHWAB manual mode while market is closed
        if (
            cfg.execution_mode == "SCHWAB_401K_MANUAL"
            and not decision_record["gates"]["market"]["is_open"]
        ):
            entry_intents = []
        else:
            if settle_active:
                entry_intents = []
            else:
                entry_intents = store.pop_due_entry_intents(now_ts)
                if not entry_intents:
                    entry_intents = []
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

        if cfg.execution_mode == "PAPER_SIM":
            if entries_blocked:
                _log("PAPER_SIM: portfolio decision unavailable; skipping entry simulation.")
                return
            now_utc = datetime.now(timezone.utc)
            date_ny = paper_sim.resolve_date_ny(now_utc)
            fills = paper_sim.simulate_fills(
                intents,
                date_ny=date_ny,
                now_utc=now_utc,
                repo_root=repo_root,
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

            for intent in intents:
                if not paper_active:
                    _log(f"ALPACA_PAPER disabled; skipping {intent.symbol} ({paper_reason})")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": paper_reason}
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
                if allowlist and intent.symbol.upper() not in allowlist:
                    _log(f"Gate ALPACA_PAPER allowlist would block {intent.symbol}")
                if _has_open_order_or_position(trading_client, intent.symbol):
                    _log(f"SKIP {intent.symbol}: open order/position exists")
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "open_order_or_position"}
                    )
                    continue

                key = generate_idempotency_key(intent.symbol, "buy", intent.size_shares, intent.ref_price)
                if not store.record_order_once(
                    key,
                    intent.strategy_id,
                    intent.symbol,
                    "buy",
                    intent.size_shares,
                ):
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
                    open_positions=positions_count,
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
                    submitted += 1
                    _log(f"SUBMITTED {intent.symbol}: qty={intent.size_shares} order_id={order_id}")
                    decision_record["actions"]["submitted_orders"].append(
                        {
                            "symbol": intent.symbol,
                            "side": "buy",
                            "qty": intent.size_shares,
                            "order_type": "market",
                            "client_order_id": key,
                            "broker_order_id": order_id,
                            "status": "submitted",
                        }
                    )
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
                    if written:
                        if not wrote_ledger:
                            ledgers_written.append(str(ledger_path.resolve()))
                            wrote_ledger = True
                        try:
                            caps_ledger.add_entry(
                                order_id or key,
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
                        except Exception:
                            pass
                    if skipped:
                        _log(f"ALPACA_PAPER: skipped duplicate intent {intent.symbol}")
                except Exception as exc:
                    _log(f"ERROR submitting {intent.symbol}: {exc}")
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
        for intent in intents:
            effective_dry_run = not live_active
            if effective_dry_run and allowlist and intent.symbol.upper() not in allowlist:
                _log(f"Gate DRY_RUN allowlist would block {intent.symbol}")

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

            key = generate_idempotency_key(intent.symbol, "buy", intent.size_shares, intent.ref_price)
            if not effective_dry_run:
                if not store.record_order_once(
                    key,
                    intent.strategy_id,
                    intent.symbol,
                    "buy",
                    intent.size_shares,
                ):
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
                    open_positions=positions_count,
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
                _log(f"SUBMITTED {intent.symbol}: qty={intent.size_shares} order_id={order_id}")
                if order_id == "dry-run-skipped":
                    decision_record["actions"]["skipped"].append(
                        {"symbol": intent.symbol, "reason": "dry_run_ledger_duplicate"}
                    )
                else:
                    decision_record["actions"]["submitted_orders"].append(
                        {
                            "symbol": intent.symbol,
                            "side": "buy",
                            "qty": intent.size_shares,
                            "order_type": "market",
                            "client_order_id": key,
                            "broker_order_id": order_id,
                            "status": "submitted",
                        }
                    )
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
                if order_id and not effective_dry_run:
                    store.update_external_order_id(key, order_id)
                    if live_active and live_ledger is not None:
                        try:

                            notional = float(intent.size_shares) * float(intent.ref_price)
                            live_ledger.add_entry(
                                order_id or key,
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
            key = generate_idempotency_key(symbol, "sell", qty, ref_price)
            if live_active:
                strategy_id = state.strategy_id if state is not None else DEFAULT_STRATEGY_ID
                if not store.record_order_once(key, strategy_id, symbol, "sell", qty):
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
            if order_id:
                store.update_external_order_id(key, order_id)
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
        _write_execution_heartbeat(cfg, decision_record, candidates_snapshot)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execution V2 - Trading Orchestration")
    parser.add_argument("--candidates-csv", default=os.getenv("WATCHLIST_FILE", "daily_candidates.csv"))
    parser.add_argument("--db-path", default=os.getenv("EXECUTION_V2_DB", "data/execution_v2.sqlite"))
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
