"""
Backtest mensuel multi-stratégies cross-sectionnelles.

Architecture :
  1. Charge les prix daily Alpaca pour l'union des tickers ayant appartenu à
     l'univers (top 50 S&P) sur la période.
  2. Resample en deux séries mensuelles :
       - monthly_close : dernier close de chaque mois (utilisé pour SIGNAL)
       - monthly_open  : premier open de chaque mois (utilisé pour EXÉCUTION)
  3. Boucle mensuelle. Pour chaque mois d'exécution M (à partir du 2e mois) :
       a. Filtre les colonnes au top 50 éligible AU PREMIER JOUR DE M (anti
          biais de survivance + intégrité point-in-time).
       b. Signal = engine.decide(monthly_close.loc[: mois précédent M-1])
          → vecteur de poids cibles sommant à 1 ou 0.
       c. Exécution au monthly_open[M] :
          - vente d'abord (toutes les positions dont la qty cible < qty actuelle)
          - achat ensuite (toutes les positions dont la qty cible > qty actuelle)
          - frais : 5 bp à chaque jambe.
       d. Mark-to-market au monthly_close[M] → equity de fin de mois.
  4. Warm-up : tant que toutes les stratégies renvoient zéro (historique
     insuffisant), portefeuille reste 100% cash. La courbe equity ne démarre
     qu'à la première allocation effective (loggée dans le payload).

Garanties :
  - Aucun look-ahead : à la décision du mois M, on n'utilise que les prix
    ≤ fin du mois M-1 ; exécution au prix d'ouverture du mois M, qu'on
    n'aurait pas pu obtenir avant.
  - Aucun trailing stop, aucun filtre SPY (retirés vs ancienne version).
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')

# Ajouter la racine projet à sys.path pour pouvoir importer config /
# universe_selector / strategies depuis ce sous-dossier.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from strategies.engine import Engine
from strategies.RegimeFilter import RegimeFilter
from universe_selector import get_universe
import config

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Sortie des artefacts (JSON, HTML) : on les écrit à côté du script.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_JSON = os.path.join(SCRIPT_DIR, "backtest_results.json")

# ── Constantes ────────────────────────────────────────────────────────────────
TXN_COST = config.TRANSACTION_COST_BP / 10_000.0   # 5 bp → 0.0005
STRAT_WEIGHTS = config.STRATEGY_WEIGHTS            # None = equal-weight
REGIME_ON     = config.REGIME_FILTER
regime        = RegimeFilter(window_months=config.REGIME_SMA_MONTHS)

BACKTEST_START = datetime.now() - timedelta(days=config.BACKTEST_DAYS)
BACKTEST_END   = datetime.now()

# ── Client Alpaca ─────────────────────────────────────────────────────────────
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

engine = Engine()

# ── 1) Univers union sur la fenêtre ───────────────────────────────────────────
_universe_cache = {}
def universe_for(d) -> set:
    """Univers (set de tickers) du mois de la date d, mis en cache par mois."""
    key = (d.year, d.month)
    if key not in _universe_cache:
        _universe_cache[key] = set(get_universe(d))
    return _universe_cache[key]


universe_union = set()
for ms in list(pd.date_range(BACKTEST_START, BACKTEST_END, freq="MS")) + [BACKTEST_START, BACKTEST_END]:
    universe_union |= set(get_universe(ms))
universe_union = sorted(universe_union)

if not universe_union:
    print("  ⚠️  Univers vide. Construis-le d'abord :")
    print(f"      py -3.10 build_universe.py --start {BACKTEST_START.date()}")
    sys.exit(1)

print("=" * 70)
print(f"  Backtest mensuel multi-stratégies · univers dynamique · {len(universe_union)} tickers")
print(f"  Fenêtre : {BACKTEST_START.date()} → {BACKTEST_END.date()} ({config.BACKTEST_DAYS} jours)")
print(f"  Capital initial : ${config.INITIAL_CASH:,.2f}")
print(f"  Frais : {config.TRANSACTION_COST_BP} bp / jambe ({2*config.TRANSACTION_COST_BP} bp aller-retour)")
print(f"  Pondération inter-stratégies : {'equal-weight' if STRAT_WEIGHTS is None else STRAT_WEIGHTS}")
print(f"  Filtre de régime SPY > MM{config.REGIME_SMA_MONTHS} mois : {'ON' if REGIME_ON else 'OFF'}")
print("=" * 70)
print()

# ── 2) Charger OHLC daily pour tous les tickers de l'union ────────────────────
print(f"  ⬇  Chargement Alpaca (open + close) pour {len(universe_union)} tickers…")
close_series, open_series = {}, {}
failed = []
for i, symbol in enumerate(universe_union, 1):
    print(f"     {i:>3}/{len(universe_union)}  {symbol:<8}", end="\r", flush=True)
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=BACKTEST_START - timedelta(days=500),   # ~16 mois pour warm-up des 4 stratégies
        )
        bars = client.get_stock_bars(request).df
        df_t = bars.loc[symbol]
        close_series[symbol] = df_t["close"]
        open_series[symbol]  = df_t["open"]
    except Exception:
        failed.append(symbol)
print(f"  ✅ {len(close_series)} tickers chargés · {len(failed)} ignorés (délistés / hors Alpaca)     ")
if failed:
    print(f"     Ignorés : {', '.join(failed[:30])}{'…' if len(failed) > 30 else ''}")

# ── 2b) Charger SPY pour le filtre de régime ─────────────────────────────────
spy_monthly_close = None
if REGIME_ON:
    print(f"  ⬇  Chargement SPY (filtre de régime)…")
    try:
        spy_bars = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=BACKTEST_START - timedelta(days=500),
        )).df
        spy_daily = spy_bars.loc["SPY"]["close"]
        spy_daily.index = pd.to_datetime(spy_daily.index)
        if spy_daily.index.tz is not None:
            spy_daily.index = spy_daily.index.tz_localize(None)
        spy_monthly_close = spy_daily.groupby(spy_daily.index.to_period("M")).last()
        print(f"  ✅ SPY chargé · {len(spy_monthly_close)} closes mensuels")
    except Exception as e:
        print(f"  ⚠️  SPY indisponible ({e}) — filtre de régime désactivé pour cette run.")
        REGIME_ON = False

# ── 3) Aligner et resample mensuel ────────────────────────────────────────────
daily_close = pd.DataFrame(close_series).sort_index()
daily_open  = pd.DataFrame(open_series).sort_index()
daily_close.index = pd.to_datetime(daily_close.index)
daily_open.index  = pd.to_datetime(daily_open.index)

# Alpaca renvoie des dates tz-aware (UTC). On les drop pour pouvoir convertir
# en PeriodIndex sans warning. La fréquence reste journalière, calendrier US.
if daily_close.index.tz is not None:
    daily_close.index = daily_close.index.tz_localize(None)
if daily_open.index.tz is not None:
    daily_open.index = daily_open.index.tz_localize(None)

# Groupby PeriodIndex(M) : dernier close / premier open par mois calendaire.
# Hypothèse : daily_close et daily_open ont les mêmes dates (même calendrier).
periods_close = daily_close.index.to_period("M")
periods_open  = daily_open.index.to_period("M")

monthly_close = daily_close.groupby(periods_close).last()
monthly_open  = daily_open.groupby(periods_open).first()
# Index = PeriodIndex monthly. Alignement par période garanti.

# On ne garde que les mois communs (au cas où l'une ou l'autre série diverge).
common_months = sorted(set(monthly_close.index) & set(monthly_open.index))
monthly_close = monthly_close.loc[common_months]
monthly_open  = monthly_open.loc[common_months]

print(f"  📅 {len(common_months)} mois de données mensuelles : "
      f"{common_months[0]} → {common_months[-1]}")

# ── 4) Boucle mensuelle ───────────────────────────────────────────────────────
cash      = config.INITIAL_CASH
positions = {}   # symbol -> {"qty": int, "avg_cost": float}
stats     = {s: {"realized_pnl": 0.0, "trades": 0, "wins": 0,
                  "price_start": None, "price_end": None}
             for s in daily_close.columns}
equity_curve = []      # [str(period), equity]
first_alloc_period = None
total_fees      = 0.0
bearish_months  = 0    # nb de mois où le filtre de régime a forcé le cash
regime_log      = []   # [(period, bullish_bool)] pour debug optionnel


def mark_to_market(period, prices_row) -> float:
    """Equity = cash + Σ qty × prix. Prix manquant → dernier close connu."""
    val = cash
    for sym, p in positions.items():
        px = prices_row.get(sym, np.nan)
        if pd.isna(px):
            # fallback : dernier close connu pour ce ticker à ce mois ou avant
            hist = monthly_close.loc[:period, sym].dropna() if sym in monthly_close.columns else None
            if hist is None or hist.empty:
                continue  # impossible à valoriser, on ignore
            px = hist.iloc[-1]
        val += p["qty"] * px
    return val


for i, exec_period in enumerate(common_months):
    # ── Gating : exécution seulement à partir de BACKTEST_START ──────────────
    exec_ts  = exec_period.to_timestamp(how="start")
    if exec_ts < pd.Timestamp(BACKTEST_START.date()):
        continue   # période antérieure au backtest : on l'utilise pour warm-up des signaux uniquement
    if i == 0:
        continue   # besoin d'au moins 1 mois de close passé pour produire un signal

    # ── a) Univers éligible au PREMIER JOUR DU MOIS D'EXÉCUTION ───────────────
    eligible = universe_for(exec_ts)

    # ── b) Signal : monthly_close strictement avant exec_period ───────────────
    signal_full = monthly_close.loc[monthly_close.index < exec_period]
    cols_signal = [c for c in signal_full.columns if c in eligible]
    signal_prices = signal_full[cols_signal] if cols_signal else signal_full.iloc[:, :0]

    # Warm-up : on attend assez d'historique pour que TOUTES les stratégies
    # ET le filtre de régime aient leurs données. Max min_rows requis = 13
    # (momentum, lowvol). Le filtre SPY a besoin de REGIME_SMA_MONTHS observations.
    WARMUP_MIN_ROWS = max(13, config.REGIME_SMA_MONTHS if REGIME_ON else 0)
    in_warmup = len(signal_prices) < WARMUP_MIN_ROWS

    # Filtre de régime : évalué seulement hors warm-up et si activé.
    bullish = True
    if not in_warmup and REGIME_ON and spy_monthly_close is not None:
        spy_history = spy_monthly_close.loc[spy_monthly_close.index < exec_period]
        bullish = regime.is_bullish(spy_history)
        regime_log.append((str(exec_period), bullish))

    if in_warmup:
        if not positions:
            # Pas encore d'allocation : on saute ce mois entièrement.
            continue
        # Cas défensif (ne devrait pas arriver) : on ne génère pas de nouvelle cible.
        target_weights = pd.Series(0.0, index=signal_prices.columns)
    elif not bullish:
        # Régime baissier : on liquide tout et reste cash. target = zéro
        # → la phase de ventes ci-dessous solde toutes les positions.
        target_weights = pd.Series(0.0, index=signal_prices.columns)
        bearish_months += 1
    else:
        target_weights = engine.decide(signal_prices, strategy_weights=STRAT_WEIGHTS)

    # ── c) Exécution au monthly_open[exec_period] ────────────────────────────
    open_row  = monthly_open.loc[exec_period]
    close_row = monthly_close.loc[exec_period]

    # Equity d'ouverture du mois (pour dimensionner les poids cibles)
    open_equity = cash
    for sym, p in positions.items():
        px = open_row.get(sym, np.nan)
        if pd.notna(px):
            open_equity += p["qty"] * px
        else:
            # ticker sans open ce mois : on garde la valeur du close précédent
            hist = monthly_close.loc[:exec_period, sym].dropna() if sym in monthly_close.columns else None
            if hist is not None and not hist.empty and len(hist) >= 2:
                open_equity += p["qty"] * hist.iloc[-2]

    # Quantités cibles (no fractional shares)
    target_qty = {}
    for sym in target_weights.index:
        w = float(target_weights[sym])
        if w <= 0:
            continue
        px = open_row.get(sym, np.nan)
        if pd.isna(px) or px <= 0:
            continue   # pas de prix d'exécution → on ignore ce titre
        qty = int(w * open_equity / px)
        if qty > 0:
            target_qty[sym] = qty

    day_log = []
    if not bullish and not in_warmup:
        day_log.append("🐻 RÉGIME BEARISH → cash")

    # Phase 1 : VENTES (libère le cash avant les achats)
    for sym in list(positions.keys()):
        new_qty = target_qty.get(sym, 0)
        cur_qty = positions[sym]["qty"]
        if new_qty < cur_qty:
            px = open_row.get(sym, np.nan)
            if pd.isna(px) or px <= 0:
                continue   # impossible à vendre → position conservée
            sold_qty = cur_qty - new_qty
            proceeds = sold_qty * px
            fee      = proceeds * TXN_COST
            cash    += proceeds - fee
            total_fees += fee

            avg_cost = positions[sym]["avg_cost"]
            realized = (px - avg_cost) * sold_qty
            stats[sym]["realized_pnl"] += realized
            stats[sym]["trades"]       += 1
            if realized > 0:
                stats[sym]["wins"] += 1
            day_log.append(f"🔴 SELL {sym} {sold_qty}@${px:.2f} ({realized:+.0f}$)")

            if new_qty == 0:
                del positions[sym]
            else:
                positions[sym]["qty"] = new_qty
                # avg_cost inchangé : on ne vend pas à perte/gain au prorata du coût

    # Phase 2 : ACHATS
    for sym, new_qty in target_qty.items():
        cur_qty = positions.get(sym, {}).get("qty", 0)
        if new_qty <= cur_qty:
            continue
        px = open_row[sym]   # déjà vérifié non-NaN dans le calcul de target_qty
        buy_qty = new_qty - cur_qty
        cost   = buy_qty * px
        fee    = cost * TXN_COST
        total  = cost + fee
        if total > cash:
            # Cash insuffisant (rare) : on achète ce qu'on peut.
            buy_qty = int(cash / (px * (1.0 + TXN_COST)))
            if buy_qty <= 0:
                continue
            cost  = buy_qty * px
            fee   = cost * TXN_COST
            total = cost + fee

        cash       -= total
        total_fees += fee

        if sym in positions:
            old_qty  = positions[sym]["qty"]
            old_cost = positions[sym]["avg_cost"]
            tot_qty  = old_qty + buy_qty
            tot_cost = old_qty * old_cost + buy_qty * px
            positions[sym] = {"qty": tot_qty, "avg_cost": tot_cost / tot_qty}
        else:
            positions[sym] = {"qty": buy_qty, "avg_cost": px}
        stats[sym]["trades"] += 1
        day_log.append(f"🟢 BUY {sym} {buy_qty}@${px:.2f}")

    # ── d) Mark-to-market en fin de mois ──────────────────────────────────────
    equity_end = mark_to_market(exec_period, close_row)

    # Stats price_start / price_end par ticker (1ère et dernière valeur observable)
    for sym in close_row.index:
        px = close_row[sym]
        if pd.notna(px):
            if stats[sym]["price_start"] is None:
                stats[sym]["price_start"] = float(px)
            stats[sym]["price_end"] = float(px)

    # Warm-up : on n'enregistre l'equity curve qu'à partir de la 1ère allocation
    has_alloc = bool(positions) or target_weights.sum() > 0
    if first_alloc_period is None and has_alloc:
        first_alloc_period = exec_period
        # Point de départ : INITIAL_CASH (avant la 1ère exécution de ce mois)
        equity_curve.append([str(exec_period), config.INITIAL_CASH])
        print(f"  ⏳ Fin du warm-up : 1ère allocation le {exec_period} "
              f"(après {i} mois sans signal exploitable)")

    if first_alloc_period is not None:
        equity_curve.append([str(exec_period), round(equity_end, 2)])

    if day_log:
        n_pos = len(positions)
        print(f"  {exec_period}  equity ${equity_end:>11,.0f}  cash ${cash:>10,.0f}  "
              f"pos {n_pos:>2}  │  {' · '.join(day_log[:6])}"
              f"{' …' if len(day_log) > 6 else ''}")


# ── 5) Clôture finale : on solde les positions au dernier close observé ───────
last_period = common_months[-1]
last_close  = monthly_close.loc[last_period]
for sym, p in list(positions.items()):
    px = last_close.get(sym, np.nan)
    if pd.isna(px):
        hist = monthly_close.loc[:, sym].dropna()
        if hist.empty:
            continue
        px = hist.iloc[-1]
    proceeds = p["qty"] * px
    fee      = proceeds * TXN_COST
    cash    += proceeds - fee
    total_fees += fee
    realized = (px - p["avg_cost"]) * p["qty"]
    stats[sym]["realized_pnl"] += realized
    stats[sym]["trades"]       += 1
    if realized > 0:
        stats[sym]["wins"] += 1

positions = {}
final_equity = cash
total_return = (final_equity - config.INITIAL_CASH) / config.INITIAL_CASH * 100

# ── 6) Métriques par action ──────────────────────────────────────────────────
results = []
for sym in daily_close.columns:
    st = stats[sym]
    if st["price_start"] is None:
        continue
    bh       = (st["price_end"] - st["price_start"]) / st["price_start"] * 100
    win_rate = (st["wins"] / st["trades"] * 100) if st["trades"] else 0.0
    results.append({
        "symbol":      sym,
        "pnl":         round(st["realized_pnl"], 2),
        "trades":      st["trades"],
        "win_rate":    win_rate,
        "ts_count":    0,                          # trailing stop retiré
        "price_start": st["price_start"],
        "price_end":   st["price_end"],
        "bh_return":   bh,
    })

# ── 7) Affichage récap ────────────────────────────────────────────────────────
for r in sorted(results, key=lambda x: x["pnl"], reverse=True):
    if r["trades"] == 0:
        continue   # n'affiche que les tickers tradés
    icon = "✅" if r["pnl"] > 0 else "❌" if r["pnl"] < 0 else "⚪"
    print(f"  {icon}  {r['symbol']:<6}  PnL {r['pnl']:>+11,.0f}$  │  "
          f"{r['trades']:>3} trades  │  win {r['win_rate']:.0f}%")

traded = [r for r in results if r["trades"] > 0]
if traded:
    total_trades = sum(r["trades"] for r in traded)
    best  = max(traded, key=lambda r: r["pnl"])
    worst = min(traded, key=lambda r: r["pnl"])
    print()
    print("=" * 70)
    print("  Résumé portefeuille")
    print("=" * 70)
    print(f"  Capital initial         : ${config.INITIAL_CASH:,.0f}")
    print(f"  Equity finale           : ${final_equity:,.0f}")
    print(f"  Rendement total         : {total_return:+.2f}%")
    print(f"  Transactions totales    : {total_trades}")
    print(f"  Frais cumulés           : ${total_fees:,.2f} "
          f"({total_fees/config.INITIAL_CASH*100:.2f}% du capital initial)")
    print(f"  Première allocation     : {first_alloc_period}")
    if REGIME_ON:
        n_regime_checks = len(regime_log)
        bull_pct = (n_regime_checks - bearish_months) / n_regime_checks * 100 if n_regime_checks else 0
        print(f"  Filtre de régime        : {bearish_months} mois bearish "
              f"sur {n_regime_checks} ({bull_pct:.0f}% bullish)")
    print(f"  Meilleure action        : {best['symbol']} ({best['pnl']:+,.0f}$)")
    print(f"  Pire action             : {worst['symbol']} ({worst['pnl']:+,.0f}$)")
    print("=" * 70)
else:
    print()
    print("  ⚠️  Aucune transaction effectuée. Vérifie l'historique disponible "
          "et la construction de l'univers.")

# ── 8) Sauvegarde JSON ────────────────────────────────────────────────────────
payload = {
    "generated":            datetime.now().isoformat(),
    "backtest_days":        config.BACKTEST_DAYS,
    "initial_cash":         config.INITIAL_CASH,
    "buy_pct":              0,                              # legacy report.py
    "strategies":           "Momentum 12-1 + Reversal + LowVol + Trend (per-asset)",
    "trailing_stop_pct":    0,                              # legacy report.py
    "market_filter":        False,                          # legacy report.py
    "market_sma":           0,                              # legacy report.py
    "transaction_cost_bp":  config.TRANSACTION_COST_BP,
    "strategy_weights":     STRAT_WEIGHTS,
    "regime_filter":        REGIME_ON,
    "regime_sma_months":    config.REGIME_SMA_MONTHS if REGIME_ON else None,
    "bearish_months":       bearish_months,
    "first_allocation":     str(first_alloc_period) if first_alloc_period else None,
    "total_fees":           round(total_fees, 2),
    "final_equity":         final_equity,
    "total_return":         total_return,
    "portfolio_daily":      equity_curve,
    "results":              results,
}
with open(RESULTS_JSON, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, default=str)
print()
print(f"  💾 Résultats sauvegardés : {RESULTS_JSON}")
print("  ▶  Lance « py -3.10 backtest/report.py » pour générer le rapport HTML")
