import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytz
from dotenv import load_dotenv
from alerts.slack import slack_alert

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
    QueryOrderStatus,
)

# ----------------------------
# ENV / SETTINGS
# ----------------------------
load_dotenv()

WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "daily_candidates.csv")
EXEC_LOG = os.getenv("EXEC_LOG", "execution_internal.log")  # keep distinct from tmux redirection log
POLL_SECONDS = int(os.getenv("EXEC_POLL_SECONDS", "300"))  # 5 minutes
MAX_ORDERS_PER_DAY = int(os.getenv("MAX_ORDERS_PER_DAY", "20"))
WATCHLIST_MAX_AGE_MINUTES = int(os.getenv("WATCHLIST_MAX_AGE_MINUTES", "240"))  # 4 hours default

# Safety: allow dry-run mode
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

# Risk sizing default (can override via env)
DEFAULT_RISK_PCT = float(os.getenv("DEFAULT_RISK_PCT", "0.05"))

# Paper/live selection (default paper=True to preserve current behavior)
PAPER = os.getenv("ALPACA_PAPER", "1") != "0"

ET = pytz.timezone("America/New_York")

# ----------------------------
# ALPACA TRADING CLIENT
# ----------------------------
trading_client = TradingClient(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    paper=PAPER,
)

# ----------------------------
# STATE
# ----------------------------
SUBMITTED_TODAY: set[str] = set()
SUBMITTED_DATE = None  # date object


# ----------------------------
# LOGGING
# ----------------------------
def now_et_str() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")


def log(msg: str) -> None:
    line = f"[{now_et_str()}] {msg}"
    print(line, flush=True)
    try:
        with open(EXEC_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        # Logging must never break execution
        pass

# Track submitted orders we want to monitor for fills
# order_id -> {"symbol": str, "last_status": str}
TRACKED_ORDERS = {}
def track_order(order, symbol: str) -> None:
    """Add an order to tracked list for fill notifications."""
    try:
        oid = getattr(order, "id", None)
        status = str(getattr(order, "status", "")).lower()
        if oid:
            TRACKED_ORDERS[str(oid)] = {"symbol": symbol, "last_status": status}
    except Exception:
        pass


def check_tracked_orders() -> None:
    """
    Poll Alpaca for status changes on tracked orders and alert on
    filled/rejected/canceled. Keeps things in-memory (temporary).
    """
    if not TRACKED_ORDERS:
        return

    done_ids = []
    for oid, meta in list(TRACKED_ORDERS.items()):
        sym = meta.get("symbol", "UNKNOWN")
        last = meta.get("last_status", "")

        try:
            # alpaca-py supports get_order_by_id; if it ever changes, we will log and skip.
            o = trading_client.get_order_by_id(oid)
            status = str(getattr(o, "status", "")).lower()
        except Exception as e:
            log(f"WARNING: could not fetch order {oid} for {sym}: {e}")
            continue

        if status and status != last:
            TRACKED_ORDERS[oid]["last_status"] = status
            log(f"ORDER UPDATE {sym} {oid}: {last} -> {status}")

            if status in ("filled", "partially_filled"):
                avg_fill = getattr(o, "filled_avg_price", None) or getattr(o, "avg_fill_price", None)
                filled_qty = getattr(o, "filled_qty", None)
                slack_alert(
                    "TRADE",
                    f"FILLED {sym}" if status == "filled" else f"PARTIAL {sym}",
                    f"qty={filled_qty} avg={avg_fill} | order_id={oid}",
                    component="EXECUTION",
                    throttle_key=f"fill_{sym}_{oid}",
                    throttle_seconds=30,
                )
                # keep tracking partially_filled; remove only when filled
                if status == "filled":
                    done_ids.append(oid)

            elif status in ("rejected", "canceled", "expired"):
                reason = getattr(o, "rejection_reason", None)
                level = "ERROR" if status == "rejected" else "WARNING"
                slack_alert(
                    level,
                    f"{status.upper()} {sym}",
                    f"reason={reason} | order_id={oid}",
                    component="EXECUTION",
                    throttle_key=f"order_{status}_{sym}_{oid}",
                    throttle_seconds=30,
                )
                done_ids.append(oid)

    for oid in done_ids:
        TRACKED_ORDERS.pop(oid, None)


def after_trade_start_time(hour=9, minute=45) -> bool:
    """
    Enforce no trading before a fixed ET time (default 09:45 ET).
    """
    now = datetime.now(ET)
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= start

# ----------------------------
# MARKET / FILE GUARDS
# ----------------------------
def is_market_open() -> bool:
    """Alpaca clock is the authoritative market open/close signal."""
    try:
        clk = trading_client.get_clock()
        return bool(clk.is_open)
    except Exception as e:
        log(f"WARNING: failed to read Alpaca clock ({e}); assuming market closed")
        return False


def watchlist_is_stale(path: str, max_age_minutes: int) -> bool:
    """Avoid trading off an old file."""
    p = Path(path)
    if not p.exists():
        return True
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone(ET)
    age_min = (datetime.now(ET) - mtime).total_seconds() / 60.0
    return age_min > max_age_minutes


def has_open_order_or_position(symbol: str) -> bool:
    """Guardrail: do not submit if you already have an open position or open order."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return True

    # Open position?
    try:
        trading_client.get_open_position(sym)
        return True
    except Exception:
        pass

    # Open orders?
    try:
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[sym])
        orders = trading_client.get_orders(filter=req)
        return len(orders) > 0
    except Exception:
        # If order query fails, err on the safe side and pretend there is an open order
        return True


# ----------------------------
# EXISTING FUNCTIONALITY (RETAINED)
# ----------------------------
def get_account_details() -> dict:
    """Returns total equity and available buying power."""
    account = trading_client.get_account()
    return {
        "equity": float(account.equity),
        "buying_power": float(account.buying_power),
        "buying_blocked": bool(account.trading_blocked),
    }


def calculate_position_size(entry_price: float, stop_loss_price: float, risk_pct: float = DEFAULT_RISK_PCT) -> int:
    """
    Calculates quantity based on a percentage of total equity and per-share risk.
    Default: Use DEFAULT_RISK_PCT of total account equity per trade.
    """
    account = trading_client.get_account()
    equity = float(account.equity)

    cash_risk = equity * float(risk_pct)

    bp = float(account.buying_power)

    try:
        price = float(entry_price)
        stop = float(stop_loss_price)
    except Exception:
        return 0

    if price <= 0:
        return 0

    max_bp_qty = 0
    if bp > 0:
        max_bp_qty = int((bp * 0.95) / price)  # Leave 5% buffer

    risk_per_share = abs(price - stop)
    if risk_per_share <= 0:
        return 0

    qty_by_risk = int(cash_risk / risk_per_share)
    qty = qty_by_risk if max_bp_qty <= 0 else min(qty_by_risk, max_bp_qty)
    return qty if qty > 0 else 0


def execute_buy_bracket(symbol: str, stop_loss_price: float, take_profit_price: float, ref_price: float | None = None):
    """
    Executes a Market Buy with an attached Bracket (Stop Loss & Take Profit).
    - ref_price is used ONLY for sizing (optional).
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        log("SKIP: empty symbol")
        return None

    account = get_account_details()
    if account["buying_blocked"]:
        log("⚠️ Trading blocked for account.")
        return None

    # Use watchlist Price if available; otherwise use a conservative proxy
    base_price = float(ref_price) if ref_price and ref_price > 0 else float(take_profit_price) * 0.9
    qty = calculate_position_size(base_price, stop_loss_price, risk_pct=DEFAULT_RISK_PCT)

    if qty <= 0:
        log(f"❌ Insufficient funds/size to buy {sym}")
        return None

    bracket_order = MarketOrderRequest(
        symbol=sym,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit={"limit_price": round(float(take_profit_price), 2)},
        stop_loss={"stop_price": round(float(stop_loss_price), 2)},
    )

    if DRY_RUN:
        log(f"DRY_RUN: would submit BRACKET BUY {sym} qty={qty} SL={stop_loss_price} TP={take_profit_price}")
        return {"dry_run": True, "symbol": sym, "qty": qty}

    try:
        order = trading_client.submit_order(bracket_order)
        log(f"✅ Submitted BRACKET BUY {sym}: qty={qty} order_id={getattr(order, 'id', 'n/a')}")
        return order
    except Exception as e:
        log(f"❌ Execution Error for {sym}: {e}")
        return None


def execute_partial_sell(symbol: str, sell_percentage: float = 0.5) -> None:
    """
    Sells a portion of an existing position (e.g., 50% trim at R1).
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        log("SKIP trim: empty symbol")
        return

    if DRY_RUN:
        log(f"DRY_RUN: would trim {sell_percentage*100:.0f}% of {sym}")
        return

    try:
        position = trading_client.get_open_position(sym)
        total_qty = float(position.qty)
        qty_to_sell = round(total_qty * float(sell_percentage), 2)

        close_options = ClosePositionRequest(qty=str(qty_to_sell))
        trading_client.close_position(symbol_or_asset_id=sym, close_options=close_options)

        log(f"✂️ Trimmed {sell_percentage*100:.0f}% of {sym} ({qty_to_sell} shares)")
    except Exception as e:
        log(f"❌ Trim Failed for {sym}: {e}")


def execute_full_exit(symbol: str, reason: str | None = None) -> None:
    """Closes an entire position for the given symbol."""
    sym = (symbol or "").upper().strip()
    if not sym:
        log("SKIP exit: empty symbol")
        return

    if DRY_RUN:
        log(f"DRY_RUN: would close position for {sym} ({reason or 'no reason'})")
        return

    try:
        trading_client.close_position(symbol_or_asset_id=sym)
        log(f"🚪 Closed position for {sym} ({reason or 'no reason'})")
    except Exception as e:
        log(f"❌ Exit Failed for {sym}: {e}")


def get_daily_summary_data() -> dict:
    """Gathers equity, daily PnL, and a list of open positions."""
    account = trading_client.get_account()
    equity = float(account.equity)
    last_equity = float(account.last_equity)
    daily_pnl = equity - last_equity
    pnl_pct = (daily_pnl / last_equity) * 100 if last_equity != 0 else 0

    positions = trading_client.get_all_positions()
    pos_list = []
    for p in positions:
        pos_list.append(
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "val": float(p.market_value),
                "pnl": float(p.unrealized_pl),
                "pnl_pct": float(getattr(p, "unrealized_plpc", getattr(p, "unrealized_pl_pc", 0.0))) * 100,

            }
        )

    return {"equity": equity, "daily_pnl": daily_pnl, "pnl_pct": pnl_pct, "positions": pos_list}


# ----------------------------
# WATCHLIST EXECUTION LOOP
# ----------------------------
def submit_from_watchlist(csv_path: str) -> None:
    if watchlist_is_stale(csv_path, WATCHLIST_MAX_AGE_MINUTES):
        log(f"WATCHLIST stale or missing: {csv_path} (skipping)")
        return

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        log(f"ERROR: failed to read {csv_path}: {e}")
        return

    if df.empty:
        log(f"WATCHLIST loaded: {csv_path} | rows=0 (nothing to do)")
        return

    required = {"Ticker", "Stop_Loss", "R2_Target"}
    missing = required - set(df.columns)
    if missing:
        log(f"ERROR: watchlist missing required columns: {sorted(missing)}")
        return

    # Enforce max orders/day
    if len(SUBMITTED_TODAY) >= MAX_ORDERS_PER_DAY:
        log(f"MAX_ORDERS_PER_DAY reached ({MAX_ORDERS_PER_DAY}); skipping")
        return

    log(f"WATCHLIST loaded: {csv_path} | rows={len(df)} | DRY_RUN={DRY_RUN} | PAPER={PAPER}")

    # Optional sizing anchor if present
    has_price_col = "Price" in df.columns

    for _, r in df.iterrows():
        sym = str(r["Ticker"]).strip().upper()
        if not sym:
            continue

        # one-per-day guard (in-memory)
        if sym in SUBMITTED_TODAY:
            continue

        # prevent duplicates across restarts by checking Alpaca state
        if has_open_order_or_position(sym):
            log(f"SKIP {sym}: already has open order/position (or order query failed)")
            SUBMITTED_TODAY.add(sym)
            continue

        try:
            sl = float(r["Stop_Loss"])
            tp = float(r["R2_Target"])
        except Exception:
            log(f"SKIP {sym}: invalid Stop_Loss/R2_Target")
            continue

        # Basic sanity checks (avoid inverted brackets)
        if sl <= 0 or tp <= 0:
            log(f"SKIP {sym}: non-positive SL/TP")
            continue
        if sl >= tp:
            log(f"SKIP {sym}: SL >= TP (inverted bracket) sl={sl} tp={tp}")
            continue


        ref_price = None
        if has_price_col:
            try:
                if pd.notna(r["Price"]):
                    ref_price = float(r["Price"])
            except Exception:
                ref_price = None

        log(f"SUBMIT {sym}: bracket buy SL={sl} TP={tp} ref_price={ref_price}")
        order = execute_buy_bracket(sym, sl, tp, ref_price=ref_price)

        if order is not None:
            SUBMITTED_TODAY.add(sym)

            is_dry = DRY_RUN or isinstance(order, dict)
            oid = getattr(order, "id", None)

            if is_dry:
                log(f"DRY_RUN SUBMITTED {sym}: qty simulated SL={sl} TP={tp}")
                slack_alert(
                    "TRADE",
                    f"DRY_RUN {sym}",
                    f"SL={sl} TP={tp}",
                    component="EXECUTION",
                    throttle_key=f"dryrun_{sym}",
                    throttle_seconds=60,
                )
            else:
                log(f"SUBMITTED {sym}: order_id={oid}")
                slack_alert(
                    "TRADE",
                    f"SUBMITTED {sym}",
                    f"SL={sl} TP={tp} | order_id={oid}",
                    component="EXECUTION",
                    throttle_key=f"submitted_{sym}",
                    throttle_seconds=60,
                )
                track_order(order, sym)

        else:
            log(f"FAILED {sym}: submit returned None")
            slack_alert(
                "WARNING",
                f"FAILED submit {sym}",
                "submit returned None",
                component="EXECUTION",
                throttle_key=f"failed_submit_{sym}",
                throttle_seconds=300,
            )




        if len(SUBMITTED_TODAY) >= MAX_ORDERS_PER_DAY:
            log(f"MAX_ORDERS_PER_DAY reached ({MAX_ORDERS_PER_DAY}); stopping loop")
            break


def main() -> None:
    global SUBMITTED_DATE, SUBMITTED_TODAY

    log(f"Execution bot starting. PAPER={PAPER} DRY_RUN={DRY_RUN} POLL_SECONDS={POLL_SECONDS}")
    slack_alert(
        "INFO",
        "Execution started",
        f"PAPER={PAPER} DRY_RUN={DRY_RUN} POLL_SECONDS={POLL_SECONDS}",
        component="EXECUTION",
        throttle_key="execution_start",
        throttle_seconds=300,
    )

    while True:
        try:
            # Reset daily state when the ET date rolls
            today = datetime.now(ET).date()
            if SUBMITTED_DATE != today:
                SUBMITTED_DATE = today
                SUBMITTED_TODAY.clear()
                log(f"New trading day detected ({today}); cleared SUBMITTED_TODAY.")

            if is_market_open():
                if not after_trade_start_time(9, 45):
                    log("Market OPEN but before 09:45 ET; execution paused.")
                else:
                    submit_from_watchlist(WATCHLIST_FILE)
            else:
                log("Market CLOSED; standing by.")

            if TRACKED_ORDERS:
                check_tracked_orders()

     

        except Exception as e:
            log(f"ERROR: unexpected exception: {e}")
            slack_alert(
                "ERROR",
                "Execution exception",
                f"{type(e).__name__}: {e}",
                component="EXECUTION",
                throttle_key="execution_exception",
                throttle_seconds=300,
            )

        time.sleep(POLL_SECONDS)



if __name__ == "__main__":
    main()
