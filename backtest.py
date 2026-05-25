import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from combiner import Combiner
import config

load_dotenv()

# ── Client Alpaca ─────────────────────────────────────────────────────────────
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

combiner = Combiner(mode=config.COMBINE_MODE)
results  = []

print("=" * 60)
print(f"  Backtest · {len(config.SYMBOLS)} actions · {config.BACKTEST_DAYS} jours")
print(f"  Capital initial par action : ${config.INITIAL_CASH:,.2f}")
print("=" * 60)
print()

# ── Boucle sur chaque action ──────────────────────────────────────────────────
for symbol in config.SYMBOLS:
    try:
        # Récupérer l'historique
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=config.BACKTEST_DAYS),
        )
        bars   = client.get_stock_bars(request).df
        prices = bars.loc[symbol]["close"]

        # Simulation
        cash        = config.INITIAL_CASH
        in_position = False
        buy_price   = 0.0
        trades      = []
        MIN_DATA    = 52

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
                pnl         = (price - buy_price) * config.QTY
                cash       += pnl
                trades[-1].update({"date_sell": date, "price_sell": price, "pnl": pnl})

        # Position encore ouverte
        if in_position and trades:
            last_price = prices.iloc[-1]
            pnl        = (last_price - buy_price) * config.QTY
            cash      += pnl
            trades[-1].update({
                "date_sell":  prices.index[-1].date(),
                "price_sell": last_price,
                "pnl":        pnl,
            })

        # Métriques
        closed   = [t for t in trades if "pnl" in t]
        wins     = [t for t in closed if t["pnl"] > 0]
        rendement = (cash - config.INITIAL_CASH) / config.INITIAL_CASH * 100
        win_rate  = len(wins) / len(closed) * 100 if closed else 0

        results.append({
            "symbol":    symbol,
            "cash":      cash,
            "rendement": rendement,
            "trades":    len(closed),
            "win_rate":  win_rate,
            "detail":    closed,
        })

        icon = "✅" if rendement > 0 else "❌" if rendement < 0 else "⚪"
        print(f"  {icon}  {symbol:<6}  {rendement:>+7.2f}%  |  {len(closed)} trades  |  win rate {win_rate:.0f}%")

    except Exception as e:
        print(f"  ⚠️  {symbol:<6}  Erreur : {e}")

# ── Résumé global ─────────────────────────────────────────────────────────────
if results:
    total_cash  = sum(r["cash"] for r in results)
    total_start = config.INITIAL_CASH * len(results)
    total_return = (total_cash - total_start) / total_start * 100

    best  = max(results, key=lambda r: r["rendement"])
    worst = min(results, key=lambda r: r["rendement"])

    print()
    print("=" * 60)
    print("  Résumé global")
    print("=" * 60)
    print(f"  Rendement moyen  : {sum(r['rendement'] for r in results) / len(results):+.2f}%")
    print(f"  Meilleure action : {best['symbol']} ({best['rendement']:+.2f}%)")
    print(f"  Pire action      : {worst['symbol']} ({worst['rendement']:+.2f}%)")
    print("=" * 60)