from dotenv import load_dotenv
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from combiner import Combiner

load_dotenv()

SYMBOL = "AAPL"
QTY    = 1
MODE   = "majority"  # "majority" | "unanimous" | "weighted"

ICON = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}

# ── Clients Alpaca ────────────────────────────────────────────────────────────
trading = TradingClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
    paper=True,
)

data = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

# ── Récupérer les prix ────────────────────────────────────────────────────────
request = StockBarsRequest(
    symbol_or_symbols=SYMBOL,
    timeframe=TimeFrame.Day,
    start=datetime.now() - timedelta(days=200),
)

bars   = data.get_stock_bars(request).df
prices = bars.loc[SYMBOL]["close"]

# ── Décision ──────────────────────────────────────────────────────────────────
combiner = Combiner(mode=MODE)
decision, results = combiner.decide(prices)

# ── Affichage ─────────────────────────────────────────────────────────────────
account = trading.get_account()

print("=" * 45)
print(f"  Bot Trading · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"  Symbole : {SYMBOL}  |  Cash : ${float(account.cash):,.2f}")
print("=" * 45)
print(f"  Dernier cours : ${prices.iloc[-1]:.2f}")
print()
print("  Signaux :")
for name, signal, _ in results:
    print(f"    {ICON[signal]}  {name:<6} → {signal.upper()}")
print()
print(f"  Décision [{MODE}] → {decision.upper()}")
print("=" * 45)

# ── Position actuelle ─────────────────────────────────────────────────────────
try:
    pos = trading.get_open_position(SYMBOL)
    in_position = int(pos.qty) > 0
except Exception:
    in_position = False

print(f"  Position ouverte : {'oui' if in_position else 'non'}")
print()

# ── Exécution de l'ordre ──────────────────────────────────────────────────────
if decision == "buy" and not in_position:
    order = MarketOrderRequest(
        symbol=SYMBOL,
        qty=QTY,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    trading.submit_order(order)
    print(f"  ✅ Ordre BUY {QTY}x {SYMBOL} soumis")

elif decision == "sell" and in_position:
    order = MarketOrderRequest(
        symbol=SYMBOL,
        qty=QTY,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    trading.submit_order(order)
    print(f"  ✅ Ordre SELL {QTY}x {SYMBOL} soumis")

else:
    print("  ⚪ Rien à faire, on attend le prochain signal.")

print()
print("Done.")