import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from combiner import Combiner
import config

load_dotenv()

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

# ── Compte ────────────────────────────────────────────────────────────────────
account = trading.get_account()

print("=" * 55)
print(f"  Bot Trading · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"  Cash disponible : ${float(account.cash):,.2f}")
print(f"  Mode            : {config.COMBINE_MODE.upper()}")
print(f"  Symboles        : {len(config.SYMBOLS)} actions")
print("=" * 55)
print()

# ── Analyser chaque action ────────────────────────────────────────────────────
combiner = Combiner(mode=config.COMBINE_MODE)

for symbol in config.SYMBOLS:
    try:
        # Récupérer les prix
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=200),
        )
        bars   = data.get_stock_bars(request).df
        prices = bars.loc[symbol]["close"]

        # Décision
        decision, results = combiner.decide(prices)

        # Affichage
        signals = " · ".join(f"{ICON[s]} {n}" for n, s, _ in results)
        print(f"  {symbol:<6}  {signals}  →  {ICON[decision]} {decision.upper()}")

        # Position actuelle
        try:
            pos = trading.get_open_position(symbol)
            in_position = int(pos.qty) > 0
        except Exception:
            in_position = False

        # Ordre
        if decision == "buy" and not in_position:
            order = MarketOrderRequest(
                symbol=symbol,
                qty=config.QTY,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            trading.submit_order(order)
            print(f"         ✅ Ordre BUY {config.QTY}x {symbol} soumis")

        elif decision == "sell" and in_position:
            order = MarketOrderRequest(
                symbol=symbol,
                qty=config.QTY,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            trading.submit_order(order)
            print(f"         ✅ Ordre SELL {config.QTY}x {symbol} soumis")

    except Exception as e:
        print(f"  {symbol:<6}  ⚠️  Erreur : {e}")

print()
print("=" * 55)
print("Done.")