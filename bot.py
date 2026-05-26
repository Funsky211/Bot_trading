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
from engine import Engine
import config
import json

load_dotenv()

ICON         = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}
SIGNAL_ICON  = {"LONG": "🟢", "SHORT": "🔴", "NONE": "⚪"}
TP_STATE_FILE = "tp_state.json"

def _load_tp_state():
    try:
        with open(TP_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_tp_state(state):
    with open(TP_STATE_FILE, "w") as f:
        json.dump(state, f)

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
print(f"  Stratégies      : Trend Following + Mean Reversion")
print(f"  Symboles        : {len(config.SYMBOLS)} actions")
print("=" * 55)
print()

# ── Analyser chaque action ────────────────────────────────────────────────────
engine   = Engine()
tp_state = _load_tp_state()

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

        # Position actuelle
        pos = None
        try:
            pos = trading.get_open_position(symbol)
            in_position = int(float(pos.qty)) > 0
        except Exception:
            in_position = False

        # Décision
        decision, results = engine.decide(prices, in_position)

        # Affichage
        signals = " · ".join(f"{SIGNAL_ICON[s]} {n}" for n, s in results)
        print(f"  {symbol:<6}  {signals}  →  {ICON[decision]} {decision.upper()}")
        print(Engine.describe_decision(symbol, decision, results, in_position))

        # Réinitialiser l'état TP si plus de position ouverte
        if not in_position and symbol in tp_state:
            del tp_state[symbol]
            _save_tp_state(tp_state)

        # Stop loss / paliers de take profit (prioritaires sur le signal)
        if in_position and pos is not None:
            current_price = float(prices.iloc[-1])
            entry_price   = float(pos.avg_entry_price)
            current_qty   = int(float(pos.qty))
            change        = (current_price - entry_price) / entry_price

            if symbol not in tp_state:
                tp_state[symbol] = {"hit": [False] * len(config.TAKE_PROFIT_LEVELS), "iqty": current_qty}

            # Paliers TP — fraction appliquée sur la quantité INITIALE (cohérent avec backtest)
            initial_qty = tp_state[symbol]["iqty"]
            qty_sold  = 0
            remaining = current_qty
            for idx, (tp_pct, tp_frac) in enumerate(config.TAKE_PROFIT_LEVELS):
                if not tp_state[symbol]["hit"][idx] and change >= tp_pct:
                    tp_state[symbol]["hit"][idx] = True
                    is_last  = idx == len(config.TAKE_PROFIT_LEVELS) - 1
                    qty_sell = remaining if is_last else max(1, round(initial_qty * tp_frac))
                    qty_sell = min(qty_sell, remaining)
                    qty_sold  += qty_sell
                    remaining -= qty_sell

            if qty_sold > 0:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty_sold,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order)
                lvl = sum(tp_state[symbol]["hit"])
                print(f"         🎯 TP{lvl} {symbol} | {change*100:+.1f}% | vente {qty_sold} action(s) | reste {remaining}")
                _save_tp_state(tp_state)
                continue

            # Stop loss (sur la totalité de la position restante)
            if change <= -config.STOP_LOSS_PCT:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=current_qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order)
                print(f"         🛑 STOP LOSS {symbol} | entrée ${entry_price:.2f} | actuel ${current_price:.2f} ({change*100:+.1f}%)")
                del tp_state[symbol]
                _save_tp_state(tp_state)
                continue

        # Ordre sur signal
        if decision == "buy" and not in_position:
            fresh_account = trading.get_account()
            equity        = float(fresh_account.equity)
            cash          = float(fresh_account.cash)
            alloc         = equity * config.BUY_PCT
            current_price = float(prices.iloc[-1])
            qty           = int(alloc / current_price)
            if qty >= 1 and cash >= alloc:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order)
                print(f"         ✅ Ordre BUY {qty}x {symbol} soumis ({config.BUY_PCT*100:.0f}% equity = ${alloc:,.2f})")
            else:
                print(f"         ⚠️  Cash insuffisant pour acheter {symbol} (besoin ${alloc:,.2f}, dispo ${cash:,.2f})")

        elif decision == "sell" and in_position:
            qty_left = int(float(pos.qty)) if pos else config.QTY
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty_left,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            trading.submit_order(order)
            print(f"         ✅ Ordre SELL {qty_left}x {symbol} soumis")

    except Exception as e:
        print(f"  {symbol:<6}  ⚠️  Erreur : {e}")

print()
print("=" * 55)
print("Done.")