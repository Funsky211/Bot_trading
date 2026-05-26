import sys
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
import os
import json
from datetime import datetime, timedelta
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from engine import Engine
import config

load_dotenv()

# ── Client Alpaca ─────────────────────────────────────────────────────────────
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

engine   = Engine()
LOOKBACK = 150   # nb de barres passées au moteur (≥ besoins SMA/MACD/BB/RSI)
MIN_DATA = 52
N_TP     = len(config.TAKE_PROFIT_LEVELS)

print("=" * 60)
print(f"  Backtest portefeuille · {len(config.SYMBOLS)} actions · {config.BACKTEST_DAYS} jours")
print(f"  Capital initial (pool partagé) : ${config.INITIAL_CASH:,.2f}")
print(f"  Taille de position : {config.BUY_PCT*100:.0f}% de l'equity  →  ~{int(1/config.BUY_PCT)} positions max")
print("=" * 60)
print()

# ── 1) Récupérer toutes les séries de clôture ─────────────────────────────────
series = {}
for symbol in config.SYMBOLS:
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=config.BACKTEST_DAYS),
        )
        bars = client.get_stock_bars(request).df
        series[symbol] = bars.loc[symbol]["close"]
    except Exception as e:
        print(f"  ⚠️  {symbol:<6} ignoré : {e}")

# ── 2) Aligner toutes les séries sur un index de dates commun ─────────────────
df    = pd.DataFrame(series).sort_index()
dates = df.index
cols  = list(df.columns)

# ── 3) Simulation : un seul pool de cash partagé sur tout le portefeuille ──────
cash         = config.INITIAL_CASH
positions    = {}     # symbol -> dict(qty, initial_qty, buy_price, tp_hit, pnl)
daily_values = []     # [date, equity]
stats = {s: {"pnl": 0.0, "trades": 0, "wins": 0, "sl": 0,
             "tp": [0] * N_TP, "price_start": None, "price_end": None} for s in cols}

for i in range(len(dates)):
    date     = dates[i]
    date_str = str(date.date()) if hasattr(date, "date") else str(date)
    row      = df.iloc[i]
    day_log  = []

    # Equity de début de journée → sert au dimensionnement (10% de l'equity)
    holdings   = sum(p["qty"] * row[s] for s, p in positions.items() if pd.notna(row[s]))
    day_equity = cash + holdings
    alloc      = day_equity * config.BUY_PCT

    for symbol in cols:
        price = row[symbol]
        if pd.isna(price):
            continue

        if stats[symbol]["price_start"] is None:
            stats[symbol]["price_start"] = float(price)
        stats[symbol]["price_end"] = float(price)

        # ── Position ouverte : take-profit (paliers) puis stop-loss ───────────
        if symbol in positions:
            pos    = positions[symbol]
            change = (price - pos["buy_price"]) / pos["buy_price"]

            for idx, (tp_pct, tp_frac) in enumerate(config.TAKE_PROFIT_LEVELS):
                if not pos["tp_hit"][idx] and change >= tp_pct:
                    pos["tp_hit"][idx] = True
                    is_last  = idx == N_TP - 1
                    qty_sell = pos["qty"] if is_last else min(pos["initial_qty"] * tp_frac, pos["qty"])
                    pnl      = (price - pos["buy_price"]) * qty_sell
                    cash                 += qty_sell * price
                    pos["pnl"]           += pnl
                    pos["qty"]           -= qty_sell
                    stats[symbol]["pnl"] += pnl
                    stats[symbol]["tp"][idx] += 1
                    day_log.append(f"🎯 TP{idx+1} {symbol} ({change*100:+.1f}%)")
                    if pos["qty"] < 0.001:
                        stats[symbol]["trades"] += 1
                        stats[symbol]["wins"]   += 1 if pos["pnl"] > 0 else 0
                        del positions[symbol]
                        break

            if symbol not in positions:
                continue

            pos    = positions[symbol]
            change = (price - pos["buy_price"]) / pos["buy_price"]
            if change <= -config.STOP_LOSS_PCT:
                pnl  = (price - pos["buy_price"]) * pos["qty"]
                cash                 += pos["qty"] * price
                pos["pnl"]           += pnl
                stats[symbol]["pnl"] += pnl
                stats[symbol]["sl"]  += 1
                stats[symbol]["trades"] += 1
                stats[symbol]["wins"]   += 1 if pos["pnl"] > 0 else 0
                day_log.append(f"🛑 SL {symbol} ({change*100:+.1f}%)")
                del positions[symbol]
                continue

        # ── Décision du moteur (historique jusqu'à la veille) ─────────────────
        window = df[symbol].iloc[max(0, i - LOOKBACK):i].dropna()
        if len(window) < MIN_DATA:
            continue
        decision, _ = engine.decide(window, symbol in positions)

        if decision == "buy" and symbol not in positions and cash >= alloc and alloc >= price:
            qty = float(int(alloc / price))
            if qty >= 1:
                cash -= qty * price
                positions[symbol] = {
                    "qty": qty, "initial_qty": qty, "buy_price": price,
                    "tp_hit": [False] * N_TP, "pnl": 0.0,
                }
                day_log.append(f"🟢 BUY {symbol} {qty:.0f}x @${price:.2f}")

        elif decision == "sell" and symbol in positions:
            pos  = positions[symbol]
            pnl  = (price - pos["buy_price"]) * pos["qty"]
            cash                 += pos["qty"] * price
            pos["pnl"]           += pnl
            stats[symbol]["pnl"] += pnl
            stats[symbol]["trades"] += 1
            stats[symbol]["wins"]   += 1 if pos["pnl"] > 0 else 0
            day_log.append(f"🔴 SELL {symbol} ({pnl:+.0f}$)")
            del positions[symbol]

    # Equity de fin de journée
    holdings    = sum(p["qty"] * row[s] for s, p in positions.items() if pd.notna(row[s]))
    end_equity  = round(cash + holdings, 2)
    daily_values.append([date_str, end_equity])
    if day_log:
        print(f"  {date_str}  ${end_equity:>10,.0f}  │  {' · '.join(day_log)}")

# ── 4) Clôturer les positions encore ouvertes (mark-to-market) ────────────────
last_row = df.iloc[-1]
for symbol, pos in list(positions.items()):
    price = last_row[symbol]
    if pd.isna(price):
        price = df[symbol].dropna().iloc[-1]
    pnl  = (price - pos["buy_price"]) * pos["qty"]
    cash                 += pos["qty"] * price
    pos["pnl"]           += pnl
    stats[symbol]["pnl"] += pnl
    stats[symbol]["trades"] += 1
    stats[symbol]["wins"]   += 1 if pos["pnl"] > 0 else 0
    del positions[symbol]

final_equity = cash
total_return = (final_equity - config.INITIAL_CASH) / config.INITIAL_CASH * 100

# ── 5) Métriques par action ───────────────────────────────────────────────────
results = []
for symbol in cols:
    st = stats[symbol]
    if st["price_start"] is None:
        continue
    bh       = (st["price_end"] - st["price_start"]) / st["price_start"] * 100
    win_rate = st["wins"] / st["trades"] * 100 if st["trades"] else 0
    results.append({
        "symbol":      symbol,
        "pnl":         round(st["pnl"], 2),
        "trades":      st["trades"],
        "win_rate":    win_rate,
        "sl_count":    st["sl"],
        "tp_counts":   st["tp"],
        "price_start": st["price_start"],
        "price_end":   st["price_end"],
        "bh_return":   bh,
    })

# ── 6) Affichage ──────────────────────────────────────────────────────────────
for r in sorted(results, key=lambda x: x["pnl"], reverse=True):
    tp_info = "  ".join(f"TP{i+1} {n}" for i, n in enumerate(r["tp_counts"]))
    icon = "✅" if r["pnl"] > 0 else "❌" if r["pnl"] < 0 else "⚪"
    print(f"  {icon}  {r['symbol']:<6}  PnL {r['pnl']:>+11,.0f}$  |  {r['trades']} trades  |  win {r['win_rate']:.0f}%  |  SL {r['sl_count']}  {tp_info}")

if results:
    total_trades = sum(r["trades"] for r in results)
    total_sl     = sum(r["sl_count"] for r in results)
    total_tp     = [sum(r["tp_counts"][i] for r in results) for i in range(N_TP)]
    best  = max(results, key=lambda r: r["pnl"])
    worst = min(results, key=lambda r: r["pnl"])

    print()
    print("=" * 60)
    print("  Résumé portefeuille")
    print("=" * 60)
    print(f"  Capital initial  : ${config.INITIAL_CASH:,.0f}")
    print(f"  Equity finale    : ${final_equity:,.0f}")
    print(f"  Rendement total  : {total_return:+.2f}%")
    print(f"  Trades           : {total_trades}")
    print(f"  Meilleure action : {best['symbol']} ({best['pnl']:+,.0f}$)")
    print(f"  Pire action      : {worst['symbol']} ({worst['pnl']:+,.0f}$)")
    print(f"  Stop loss        : {total_sl} déclenchements")
    for i, (tp_pct, _) in enumerate(config.TAKE_PROFIT_LEVELS):
        print(f"  TP{i+1} (+{tp_pct*100:.0f}%)       : {total_tp[i]} déclenchements")
    print("=" * 60)

    # ── Sauvegarde JSON ───────────────────────────────────────────────────────
    payload = {
        "generated":          datetime.now().isoformat(),
        "backtest_days":      config.BACKTEST_DAYS,
        "initial_cash":       config.INITIAL_CASH,
        "buy_pct":            config.BUY_PCT,
        "strategies":         "Trend Following + Mean Reversion",
        "stop_loss_pct":      config.STOP_LOSS_PCT,
        "take_profit_levels": config.TAKE_PROFIT_LEVELS,
        "final_equity":       final_equity,
        "total_return":       total_return,
        "portfolio_daily":    daily_values,
        "results":            results,
    }
    with open("backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print()
    print("  💾 Résultats sauvegardés : backtest_results.json")
    print("  ▶  Lance report.py pour générer le rapport HTML")
