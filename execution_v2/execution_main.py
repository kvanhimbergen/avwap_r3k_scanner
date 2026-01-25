"""
Execution V2 – Orchestration Entrypoint
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from types import SimpleNamespace

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
from execution_v2 import book_ids
from execution_v2 import book_router
from execution_v2 import paper_sim
from execution_v2 import clocks
from execution_v2 import portfolio_decisions
from execution_v2 import portfolio_decision_enforce
from execution_v2.orders import generate_idempotency_key
from execution_v2.state_store import StateStore

if TYPE_CHECKING:
    from alpaca.trading.client import TradingClient


def _now_et() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _log(msg: str) -> None:
    print(f"[{_now_et()}] {msg}", flush=True)


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_STATE_DIR = "/root/avwap_r3k_scanner/state"


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
    api_key = os.getenv("APCA_API_KEY_ID") or ""
    api_secret = os.getenv("APCA_API_SECRET_KEY") or ""
    base_url = os.getenv("APCA_API_BASE_URL") or ""
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
        _log(f"ALPACA_PAPER config missing: {', '.join(missing)}")
        raise RuntimeError(
            "Missing Alpaca paper credentials in environment "
            f"({', '.join(missing)})"
        )
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


def _market_open(trading_client: TradingClient) -> bool:
    try:
        clock = trading_client.get_clock()
        _log(
            f"Alpaca clock: is_open={clock.is_open}"
            f"ts={clock.timestamp} next_open={clock.next_open} next_close={clock.next_close}"
        )
        return bool(clock.is_open)
    except Exception as exc:
        _log(
            f"WARNING: Alpaca clock unavailable ({type(exc).__name__}: {exc}); failing closed"
        )
        return False


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
                with ledger_path.open("w", encoding="utf-8") as f:
                    json.dump(ledger, f)
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
            "constraints_snapshot": {
                "allowlist_symbols": None,
                "max_new_positions": None,
                "max_gross_exposure": None,
                "max_notional_per_symbol": None,
            },
        },
        "intents": {"intent_count": 0, "intents": []},
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
    decision_ts_utc = datetime.now(timezone.utc)
    candidates_snapshot = _snapshot_candidates_csv(cfg.candidates_csv)
    decision_record = _init_decision_record(cfg, candidates_snapshot, decision_ts_utc)
    decision_path = Path(decision_record["artifacts"]["portfolio_decisions_path"])
    errors = decision_record["actions"]["errors"]
    ledgers_written = decision_record["artifacts"]["ledgers_written"]

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
        if os.getenv("DRY_RUN", "0") == "1":
            _log(f"DRY_RUN=1 active; execution_mode={cfg.execution_mode}")
        else:
            _log(f"Execution mode={cfg.execution_mode}")
        if cfg.execution_mode != "PAPER_SIM":
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
                except RuntimeError as exc:
                    if cfg.execution_mode == "ALPACA_PAPER":
                        _log(f"ALPACA_PAPER disabled: {exc}")
                        return
                    raise
                except Exception as exc:
                    if cfg.execution_mode == "ALPACA_PAPER":
                        _log(
                            "ALPACA_PAPER disabled: unexpected "
                            f"{type(exc).__name__}: {exc}"
                        )
                        return
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
        
        if cfg.execution_mode == "PAPER_SIM":
            clock_snapshot = clocks.now_snapshot()
            market_is_open = clock_snapshot.market_open
            decision_record["gates"]["market"]["is_open"] = market_is_open
            decision_record["gates"]["market"]["clock_source"] = "clock_snapshot"
            maybe_send_heartbeat(dry_run=True, market_open=market_is_open, execution_mode=cfg.execution_mode)
            maybe_send_daily_summary(dry_run=True, market_open=market_is_open, execution_mode=cfg.execution_mode)
        elif cfg.execution_mode == "SCHWAB_401K_MANUAL":
            clock_snapshot = clocks.now_snapshot()
            market_is_open = clock_snapshot.market_open
            decision_record["gates"]["market"]["is_open"] = market_is_open
            decision_record["gates"]["market"]["clock_source"] = "clock_snapshot"
            maybe_send_heartbeat(
                dry_run=cfg.dry_run,
                market_open=market_is_open,
                execution_mode=cfg.execution_mode,
            )
            maybe_send_daily_summary(
                dry_run=cfg.dry_run,
                market_open=market_is_open,
                execution_mode=cfg.execution_mode,
            )
        else:
            ledger_path = None
            if cfg.execution_mode == "ALPACA_PAPER":
                date_ny = paper_sim.resolve_date_ny(datetime.now(timezone.utc))
                ledger_path = str(alpaca_paper.ledger_path(repo_root, date_ny))
                _log(
                    f"ALPACA_PAPER ledger_path={ledger_path} "
                    f"(date_ny={date_ny})"
                )
            market_is_open = _market_open(trading_client)
            decision_record["gates"]["market"]["is_open"] = market_is_open
            decision_record["gates"]["market"]["clock_source"] = "alpaca_clock"
            maybe_send_heartbeat(
                dry_run=cfg.dry_run,
                market_open=market_is_open,
                execution_mode=cfg.execution_mode,
            )
            maybe_send_daily_summary(
                dry_run=cfg.dry_run,
                market_open=market_is_open,
                execution_mode=cfg.execution_mode,
                ledger_path=ledger_path,
            )

        if (not market_is_open) and (not getattr(cfg, 'ignore_market_hours', False)):
            _log("Market closed; skipping cycle.")
            decision_record["gates"]["blocks"].append(
                {"code": "market_closed", "message": "market closed; cycle skipped"}
            )
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
            created = buy_loop.evaluate_and_create_entry_intents(store, md, buy_cfg, account_equity)
            if created:
                _log(f"Created {created} entry intents.")
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
            created = buy_loop.evaluate_and_create_entry_intents(store, md, buy_cfg, account_equity)
            if created:
                _log(f"Created {created} entry intents.")
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
            created = buy_loop.evaluate_and_create_entry_intents(store, md, buy_cfg, account_equity)
            if created:
                _log(f"Created {created} entry intents.")
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
            created = buy_loop.evaluate_and_create_entry_intents(store, md, buy_cfg, account_equity)
            if created:
                _log(f"Created {created} entry intents.")
            exits.manage_positions(
                trading_client=trading_client,
                md=md,
                cfg=exits.ExitConfig.from_env(),
                repo_root=repo_root,
                dry_run=cfg.dry_run,
                log=_log,
            )

        now_ts = time.time()
        intents = store.pop_due_entry_intents(now_ts)
        if not intents:
            intents = []
        intent_projection = []
        for intent in intents:
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
        enforcement_context = None
        enforcement_records: list[dict] = []
        if portfolio_decision_enforce.enforcement_enabled():
            enforcement_context = portfolio_decision_enforce.load_decision_context(decision_record["ny_date"])
        if cfg.execution_mode != "PAPER_SIM":
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
                if not store.record_order_once(key, intent.symbol, "buy", intent.size_shares):
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
                if not store.record_order_once(key, intent.symbol, "buy", intent.size_shares):
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
                if not store.record_order_once(key, symbol, "sell", qty):
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
        portfolio_decisions.write_portfolio_decision(decision_record, decision_path)
        _log(f"Portfolio decision recorded: {decision_path}")


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
        
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
