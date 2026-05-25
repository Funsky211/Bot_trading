import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from combiner import Combiner

load_dotenv()

SYMBOL       = "AAPL"
INITIAL_CASH = 10_000.0
QTY          = 1

# ── Récupérer l'historique ────────────────────────────────────────────────────
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

request = StockBarsRequest(
    symbol_or_symbols=SYMBOL,
    timeframe=TimeFrame.Day,
    start=datetime.now() - timedelta(days=730),
)

bars   = client.get_stock_bars(request).df
prices = bars.loc[SYMBOL]["close"]

print(f"Données : {len(prices)} jours ({str(prices.index[0].date())} → {str(prices.index[-1].date())})")
print()

# ── Simulation ────────────────────────────────────────────────────────────────
combiner    = Combiner(mode="majority")
cash        = INITIAL_CASH
in_position = False
buy_price   = 0.0
trades      = []

MIN_DATA = 52  # assez de données pour que les 3 stratégies calculent

for i in range(MIN_DATA, len(prices)):
    window   = prices.iloc[:i]
    price    = prices.iloc[i]
    date     = prices.index[i].date()

    decision, _ = combiner.decide(window)

    if decision == "buy" and not in_position:
        in_position = True
        buy_price   = price
        trades.append({"date_buy": date, "price_buy": price})

    elif decision == "sell" and in_position:
        in_position = False
        pnl         = (price - buy_price) * QTY
        cash       += pnl
        trades[-1].update({"date_sell": date, "price_sell": price, "pnl": pnl})

# Position encore ouverte à la fin
if in_position and trades:
    last_price = prices.iloc[-1]
    pnl        = (last_price - buy_price) * QTY
    cash      += pnl
    trades[-1].update({
        "date_sell":  prices.index[-1].date(),
        "price_sell": last_price,
        "pnl":        pnl,
    })




# ── Résultats ─────────────────────────────────────────────────────────────────
closed = [t for t in trades if "pnl" in t]
wins   = [t for t in closed if t["pnl"] > 0]

print(f"  Trades détectés  : {len(trades)}")
print(f"  Trades fermés    : {len(closed)}")

print("=" * 50)
print(f"  Backtest · {SYMBOL} · mode majority")
print("=" * 50)
print(f"  Capital initial  : ${INITIAL_CASH:,.2f}")
print(f"  Capital final    : ${cash:,.2f}")

print(f"  Rendement        : {(cash - INITIAL_CASH) / INITIAL_CASH * 100:+.2f}%")
print(f"  Nombre de trades : {len(closed)}")
if closed:
    print(f"  Win rate         : {len(wins) / len(closed) * 100:.1f}%")
print("=" * 50)

if closed:
    print("  Détail des trades :")
    for t in closed:
        icon = "✅" if t["pnl"] > 0 else "❌"
        print(f"    {icon}  {t['date_buy']} @ ${t['price_buy']:.2f} → {t['date_sell']} @ ${t['price_sell']:.2f}  PnL: ${t['pnl']:+.2f}")