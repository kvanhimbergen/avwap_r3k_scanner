import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from alpaca.trading.models import TradeAccount
from dotenv import load_dotenv

load_dotenv()

# Initialize Trading Client (Paper Environment)
trading_client = TradingClient(
    os.getenv('APCA_API_KEY_ID'), 
    os.getenv('APCA_API_SECRET_KEY'), 
    paper=True
)

def get_account_details():
    """Returns total equity and available buying power."""
    account = trading_client.get_account()
    return {
        "equity": float(account.equity),
        "buying_power": float(account.buying_power),
        "buying_blocked": account.trading_blocked
    }

def calculate_position_size(symbol_price, risk_pct=0.05):
    """
    Calculates quantity based on a percentage of total equity.
    Default: Use 5% of total account equity per trade.
    """
    account = trading_client.get_account()
    equity = float(account.equity)
    
    # Calculate dollar amount to invest
    cash_to_spend = equity * risk_pct
    
    # Ensure we don't exceed available buying power
    if cash_to_spend > float(account.buying_power):
        cash_to_spend = float(account.buying_power) * 0.95 # Leave 5% buffer
        
    qty = int(cash_to_spend / symbol_price)
    return qty if qty > 0 else 0

def execute_buy_bracket(symbol, stop_loss_price, take_profit_price):
    """
    Executes a Market Buy with a attached Bracket (Stop Loss & Take Profit).
    """
    # 1. Get Current Price (approximation for sizing)
    # In production, use your data_client to get latest quote
    # For now, we assume the signal came with a price
    account = get_account_details()
    if account["buying_blocked"]:
        print(f"⚠️ Trading blocked for account.")
        return

    # 2. Calculate Qty (e.g., risk 5% of equity)
    # For a real price, we'd fetch the latest quote, 
    # but we'll use stop_loss as a base if needed.
    qty = calculate_position_size(take_profit_price * 0.9, risk_pct=0.05)
    
    if qty == 0:
        print(f"❌ Insufficient funds to buy {symbol}")
        return

    # 3. Create Bracket Order
    bracket_order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit={'limit_price': round(take_profit_price, 2)},
        stop_loss={'stop_price': round(stop_loss_price, 2)}
    )

    try:
        order = trading_client.submit_order(bracket_order)
        print(f"✅ Executed Bracket Buy for {symbol}: Qty {qty}")
        return order
    except Exception as e:
        print(f"❌ Execution Error for {symbol}: {e}")

def execute_partial_sell(symbol, sell_percentage=0.5):
    """
    Sells a portion of an existing position (e.g., 50% trim at R1).
    """
    try:
        position = trading_client.get_open_position(symbol)
        total_qty = float(position.qty)
        qty_to_sell = round(total_qty * sell_percentage, 2)
        
        # Alpaca close_position allows specific qty
        close_options = ClosePositionRequest(qty=str(qty_to_sell))
        trading_client.close_position(symbol, close_options=close_options)
        
        print(f"✂️ Trimmed {sell_percentage*100}% of {symbol} ({qty_to_sell} shares)")
    except Exception as e:
        print(f"❌ Trim Failed for {symbol}: {e}")