import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytz
from dotenv import load_dotenv

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


def calculate_position_size(symbol_price: float, risk_pct: float = DEFAULT_RISK_PCT) -> int:
    """
    Calculates quantity based on a percentage of total equity.
    Default: Use DEFAULT_RISK_PCT of total account equity per trade.
    """
    account = trading_client.get_account()
    equity = float(account.equity)

    cash_to_spend = equity * float(risk_pct)

    # Ensure we don't exceed available buying power
    bp = float(account.buying_power)
    if cash_to_spend > bp:
        cash_to_spend = bp * 0.95  # Leave 5% buffer

    try:
        price = float(symbol_price)
    except Exception:
        return 0

    if price <= 0:
        return 0

    qty = int(cash_to_spend / price)
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
    qty = calculate_position_size(base_price, risk_pct=DEFAULT_RISK_PCT)

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
        trading_client.close_position(sym, close_options=close_options)

        log(f"✂️ Trimmed {sell_percentage*100:.0f}% of {sym} ({qty_to_sell} shares)")
    except Exception as e:
        log(f"❌ Trim Failed for {sym}: {e}")


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
                "pnl_pct": float(p.unrealized_pl_pc) * 100,
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

        ref_price = None
        if has_price_col:
            try:
                if pd.notna(r["Price"]):
                    ref_price = float(r["Price"])
            except Exception:
                ref_price = None

        log(f"SUBMIT {sym}: bracket buy SL={sl} TP={tp} ref_price={ref_price}")
        order = execute_buy_bracket(sym, sl, tp, ref_price=ref_price)

        # Mark submitted even in DRY_RUN so we don't spam the log every cycle
        if order is not None:
            SUBMITTED_TODAY.add(sym)
        else:
            log(f"FAILED {sym}: submit returned None")

        if len(SUBMITTED_TODAY) >= MAX_ORDERS_PER_DAY:
            log(f"MAX_ORDERS_PER_DAY reached ({MAX_ORDERS_PER_DAY}); stopping loop")
            break


def main() -> None:
    global SUBMITTED_DATE, SUBMITTED_TODAY

    log(f"Execution bot starting. PAPER={PAPER} DRY_RUN={DRY_RUN} POLL_SECONDS={POLL_SECONDS}")

    while True:
        try:
            # Reset daily state when the ET date rolls
            today = datetime.now(ET).date()
            if SUBMITTED_DATE != today:
                SUBMITTED_DATE = today
                SUBMITTED_TODAY.clear()
                log(f"New trading day detected ({today}); cleared SUBMITTED_TODAY.")

            if is_market_open():
                submit_from_watchlist(WATCHLIST_FILE)
            else:
                log("Market CLOSED; standing by.")
        except Exception as e:
            log(f"ERROR: unexpected exception: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
