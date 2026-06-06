"""
⚠️  CE FICHIER EST CASSÉ DEPUIS LA REFONTE MENSUELLE MULTI-STRATÉGIES.

Le code ci-dessous utilise l'ANCIENNE interface :
  - engine.decide(prices: pd.Series, in_position: bool) → (decision_str, results)
  - Engine.describe_decision(...)               (méthode supprimée)
  - config.SYMBOLS / BUY_PCT / TRAILING_STOP_PCT / MARKET_FILTER / MARKET_SMA
    (paradigme per-ticker LONG/NONE → buy/hold/sell)

La nouvelle architecture (vecteurs de poids cross-sectionnels, rebalancement
mensuel, filtre de régime SPY > MM10 mois) n'est pas encore portée en live.

À FAIRE (chantier séparé) :
  1. Adapter à la signature `engine.decide(prices_df, strategy_weights=None)`
     → renvoie pd.Series(weights, somme=1 ou 0).
  2. Remplacer la boucle per-ticker par un rebalancement vers poids cibles
     (sells d'abord, buys ensuite, frais Alpaca).
  3. Brancher RegimeFilter (SPY > MM10) avant decide.
  4. Persister état mensuel (date dernier rebalancement, dernière cible)
     plutôt que peak_state.json (qui était trailing stop, supprimé).
  5. Planifier exécution mensuelle (au 1er jour de bourse du mois, à l'open).

Pour relancer la version mensuelle = pour l'instant utiliser backtest/backtest.py
en mode paper-trading manuel ou attendre le refacteur.
"""
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
PEAK_STATE_FILE = "peak_state.json"   # plus haut prix atteint par position (trailing stop)

def _load_peak_state():
    try:
        with open(PEAK_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_peak_state(state):
    with open(PEAK_STATE_FILE, "w") as f:
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

# ── Filtre de marché : SPY vs sa SMA ──────────────────────────────────────────
market_bull = True
if config.MARKET_FILTER:
    try:
        spy_req   = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=config.MARKET_SMA * 2),
        )
        spy_close = data.get_stock_bars(spy_req).df.loc["SPY"]["close"]
        spy_sma   = float(spy_close.rolling(config.MARKET_SMA).mean().iloc[-1])
        spy_last  = float(spy_close.iloc[-1])
        market_bull = spy_last > spy_sma
        etat = "HAUSSIER → achats ON" if market_bull else "BAISSIER → achats OFF"
        print(f"  Marché SPY      : ${spy_last:.2f} vs SMA{config.MARKET_SMA} ${spy_sma:.2f}  ({etat})")
    except Exception as e:
        print(f"  ⚠️  Filtre marché indisponible ({e}) — achats autorisés")
print("=" * 55)
print()

# ── Analyser chaque action ────────────────────────────────────────────────────
engine     = Engine()
peak_state = _load_peak_state()

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

        # Réinitialiser l'état si plus de position ouverte
        if not in_position and symbol in peak_state:
            del peak_state[symbol]
            _save_peak_state(peak_state)

        # Trailing stop (prioritaire sur le signal)
        if in_position and pos is not None:
            current_price = float(prices.iloc[-1])
            entry_price   = float(pos.avg_entry_price)
            current_qty   = int(float(pos.qty))

            # Plus haut atteint depuis l'achat, persistant entre les runs du bot.
            peak = max(peak_state.get(symbol, entry_price), current_price)
            peak_state[symbol] = peak
            _save_peak_state(peak_state)

            drawdown = (current_price - peak) / peak
            if drawdown <= -config.TRAILING_STOP_PCT:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=current_qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                trading.submit_order(order)
                gain = (current_price - entry_price) / entry_price
                print(f"         🛑 TRAILING STOP {symbol} | {gain*100:+.1f}% depuis achat | pic ${peak:.2f} → ${current_price:.2f} ({drawdown*100:.1f}%)")
                del peak_state[symbol]
                _save_peak_state(peak_state)
                continue

        # Ordre sur signal
        if decision == "buy" and not in_position and market_bull:
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

        elif decision == "buy" and not in_position and not market_bull:
            print(f"         ⏸  Achat {symbol} bloqué : marché baissier (SPY < SMA{config.MARKET_SMA})")

        elif decision == "sell" and in_position:
            qty_left = int(float(pos.qty))
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