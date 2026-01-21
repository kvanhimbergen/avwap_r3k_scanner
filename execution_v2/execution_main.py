"""
Execution V2 – Orchestration Entrypoint
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus

from alerts.slack import (
    slack_alert,
    send_verbose_alert,
    maybe_send_heartbeat,
    maybe_send_daily_summary,
)
from datetime import timezone
from execution_v2 import buy_loop, sell_loop
from execution_v2 import live_gate
from execution_v2.market_data import from_env as market_data_from_env
from execution_v2.orders import generate_idempotency_key
from execution_v2.state_store import StateStore


def _now_et() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _log(msg: str) -> None:
    print(f"[{_now_et()}] {msg}", flush=True)


def _get_trading_client() -> TradingClient:
    api_key = os.getenv("APCA_API_KEY_ID") or ""
    api_secret = os.getenv("APCA_API_SECRET_KEY") or ""
    if not api_key or not api_secret:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    paper = os.getenv("ALPACA_PAPER", "1") != "0"
    return TradingClient(api_key, api_secret, paper=paper)


def _market_open(trading_client: TradingClient) -> bool:
    try:
        clock = trading_client.get_clock()
        return bool(clock.is_open)
    except Exception as exc:
        _log(f"WARNING: failed to fetch Alpaca clock ({exc}); assuming market closed")
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
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[sym])
        orders = trading_client.get_orders(filter=req)
        return len(orders) > 0
    except Exception:
        return True


def _submit_bracket_order(trading_client: TradingClient, intent, dry_run: bool) -> str | None:
    if dry_run:
        import json
        from datetime import datetime
        
        ledger_path = "/root/avwap_r3k_scanner/state/dry_run_ledger.json"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{today}:{intent.symbol}"
        
        try:
            with open(ledger_path, "r") as f:
                ledger = json.load(f)
        except Exception:
            ledger = {}
        
        if key in ledger:
            _log(f"DRY_RUN: already submitted today -> {intent.symbol}; skipping")
            return "dry-run-skipped"

        _log(f"DRY_RUN: would submit {intent.symbol} qty={intent.size_shares} SL={intent.stop_loss} TP={intent.take_profit}")

        ledger[key] = {
            "symbol": intent.symbol,
            "qty": intent.size_shares,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        try:
            with open(ledger_path, "w") as f:
                json.dump(ledger, f)
        except Exception as exc:
            _log(f"WARNING: failed to write dry run ledger: {exc}")

        return "dry-run"

    order = MarketOrderRequest(
        symbol=intent.symbol,
        qty=intent.size_shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit={"limit_price": round(float(intent.take_profit), 2)},
        stop_loss={"stop_price": round(float(intent.stop_loss), 2)},
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


def run_once(cfg) -> None:
    store = StateStore(cfg.db_path)
    if cfg.entry_delay_min_sec > cfg.entry_delay_max_sec:
        cfg.entry_delay_min_sec, cfg.entry_delay_max_sec = cfg.entry_delay_max_sec, cfg.entry_delay_min_sec
    buy_cfg = buy_loop.BuyLoopConfig(
        candidates_csv=cfg.candidates_csv,
        entry_delay_min_sec=cfg.entry_delay_min_sec,
        entry_delay_max_sec=cfg.entry_delay_max_sec,
    )
    sell_cfg = sell_loop.SellLoopConfig(candidates_csv=cfg.candidates_csv)
    trading_client = _get_trading_client()
    md = market_data_from_env()
    # Diagnostics: confirm which candidates CSV execution will use (observability only).
    try:
        import os as _os
        from datetime import datetime as _dt

        p = _os.path.abspath(cfg.candidates_csv)
        exists = _os.path.exists(p)
        mtime = _dt.fromtimestamp(_os.path.getmtime(p), tz=timezone.utc).isoformat()
        _log(f"Candidates CSV: {p} | exists={exists} | mtime_utc={mtime}")
    except Exception:
        pass
    
    market_is_open = _market_open(trading_client)
    maybe_send_heartbeat(dry_run=cfg.dry_run, market_open=market_is_open)
    maybe_send_daily_summary(dry_run=cfg.dry_run, market_open=market_is_open)

    if (not market_is_open) and (not getattr(cfg, 'ignore_market_hours', False)):
        _log("Market closed; skipping cycle.")
        return

    gate_result = live_gate.resolve_live_mode(cfg.dry_run)
    allowlist = live_gate.parse_allowlist()
    caps = live_gate.CapsConfig.from_env()
    live_active = gate_result.live_enabled
    live_reason = gate_result.reason
    live_ledger = None
    positions_count = None

    if live_active:
        live_ledger, ledger_reason = live_gate.load_live_ledger()
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

    account_equity = _get_account_equity(trading_client)
    created = buy_loop.evaluate_and_create_entry_intents(store, md, buy_cfg, account_equity)
    if created:
        _log(f"Created {created} entry intents.")
    sell_loop.evaluate_positions(store, trading_client, sell_cfg)

    now_ts = time.time()
    intents = store.pop_due_entry_intents(now_ts)
    if not intents:
        intents = []

    for intent in intents:
        effective_dry_run = not live_active
        if effective_dry_run and allowlist and intent.symbol.upper() not in allowlist:
            _log(f"Gate DRY_RUN allowlist would block {intent.symbol}")

        if _has_open_order_or_position(trading_client, intent.symbol):
            _log(f"SKIP {intent.symbol}: open order/position exists")
            continue

        key = generate_idempotency_key(intent.symbol, "buy", intent.size_shares, intent.ref_price)
        if not effective_dry_run:
            if not store.record_order_once(key, intent.symbol, "buy", intent.size_shares):
                _log(f"SKIP {intent.symbol}: idempotency key already used")
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
                continue

        try:
            order_id = _submit_bracket_order(trading_client, intent, effective_dry_run)
            _log(f"SUBMITTED {intent.symbol}: qty={intent.size_shares} order_id={order_id}")
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
            if order_id and not effective_dry_run:
                store.update_external_order_id(key, order_id)
                if live_active and live_ledger is not None:
                    try:
                        from datetime import datetime

                        notional = float(intent.size_shares) * float(intent.ref_price)
                        live_ledger.add_entry(
                            order_id or key,
                            intent.symbol,
                            notional,
                            datetime.now(tz=timezone.utc).isoformat(),
                        )
                        live_ledger.save()
                    except Exception as exc:
                        _log(f"WARNING: failed to update live ledger: {exc}")
        except Exception as exc:
            _log(f"ERROR submitting {intent.symbol}: {exc}")
            slack_alert(
                "ERROR",
                f"Execution error for {intent.symbol}",
                f"{type(exc).__name__}: {exc}",
                component="EXECUTION_V2",
                throttle_key=f"submit_error_{intent.symbol}",
                throttle_seconds=300,
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
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("DRY_RUN", "0") == "1")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single execution cycle then exit cleanly",
    )

    return parser.parse_args()


def main() -> None:
    cfg = _parse_args()
    db_dir = os.path.dirname(cfg.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    slack_alert(
        "INFO",
        "Execution V2 started",
        f"dry_run={cfg.dry_run} poll_seconds={cfg.poll_seconds}",
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
