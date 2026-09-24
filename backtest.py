"""
Backtest mensuel multi-stratégies cross-sectionnelles.

Architecture :
  1. Charge les prix daily (via data.py, cache Parquet) pour l'union des
     tickers ayant appartenu à l'univers top 50 S&P sur la période.
  2. Resample en deux séries mensuelles :
       - monthly_close : dernier close du mois (utilisé pour le SIGNAL)
       - monthly_open  : premier open du mois (utilisé pour l'EXÉCUTION)
  3. Boucle mensuelle. Pour chaque mois d'exécution M :
       a. Filtre les colonnes au top 50 éligible AU PREMIER JOUR DE M (anti
          biais de survivance + intégrité point-in-time).
       b. Signal = engine.decide(monthly_close jusqu'à M-1 inclus)
          → vecteur de poids cibles sommant à 1 ou 0.
       c. Exécution au monthly_open[M] : ventes d'abord, achats ensuite,
          frais TRANSACTION_COST_BP à chaque jambe.
       d. Mark-to-market au monthly_close[M].
  4. Warm-up : tant que toutes les stratégies renvoient zéro, on reste cash.

Garanties :
  - Aucun look-ahead : à la décision du mois M on n'utilise que des prix
    ≤ fin du mois M-1 ; exécution à l'open de M, inconnu avant.

Usage CLI :
    py -3.10 backtest.py

Usage programmatique (matrices de paramètres — aucun re-téléchargement) :
    from backtest import run_backtest
    for w in [{"Trend": 1.0}, {"Trend": .8, "Momentum": .2}, None]:
        r = run_backtest(strategy_weights=w, verbose=False)
        print(w, f"{r['total_return']:+.2f}%")
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
import data
from strategies.engine import Engine
from strategies.RegimeFilter import RegimeFilter
from universe_selector import get_universe

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR  = os.path.join(BASE_DIR, "results")
RESULTS_JSON = os.path.join(RESULTS_DIR, "backtest_results.json")

WARMUP_BUFFER_DAYS = 500   # ~16 mois d'historique avant start, pour les signaux
STRATEGY_WARMUP    = 13    # mois requis par la plus gourmande (Momentum, LowVol)

# Sentinelle « paramètre non fourni ». Indispensable pour strategy_weights :
# None y est une valeur MÉTIER valide (= equal-weight entre les 4 stratégies),
# on ne peut donc pas s'en servir pour signifier « retomber sur config.py ».
_UNSET = object()


def run_backtest(
    strategy_weights=_UNSET,
    regime_filter=_UNSET,
    regime_exit=_UNSET,
    regime_entry=_UNSET,
    backtest_days=_UNSET,
    initial_cash=_UNSET,
    txn_cost_bp=_UNSET,
    verbose=True,
) -> dict:
    """
    Lance un backtest et renvoie le payload de résultats (dict).

    Tout paramètre omis retombe sur config.py — ce qui rend la fonction
    utilisable telle quelle en CLI, et surchargeable une par une pour
    balayer une matrice de configurations.

    strategy_weights=None demande explicitement l'equal-weight (25% par
    stratégie), à ne pas confondre avec « paramètre omis ».
    """
    def _or_config(value, default):
        return default if value is _UNSET else value

    strategy_weights = _or_config(strategy_weights, config.STRATEGY_WEIGHTS)
    regime_on        = _or_config(regime_filter,    config.REGIME_FILTER)
    regime_exit      = _or_config(regime_exit,      config.REGIME_EXIT_WINDOW)
    regime_entry     = _or_config(regime_entry,     config.REGIME_ENTRY_WINDOW)
    backtest_days    = _or_config(backtest_days,    config.BACKTEST_DAYS)
    initial_cash     = _or_config(initial_cash,     config.INITIAL_CASH)
    txn_cost_bp      = _or_config(txn_cost_bp,      config.TRANSACTION_COST_BP)

    log      = print if verbose else (lambda *a, **k: None)
    txn_cost = txn_cost_bp / 10_000.0
    engine   = Engine()
    regime   = RegimeFilter(exit_window=regime_exit, entry_window=regime_entry)

    bt_start = datetime.now() - timedelta(days=backtest_days)
    bt_end   = datetime.now()

    # ── 1) Univers union sur la fenêtre ───────────────────────────────────────
    universe_cache = {}

    def universe_for(d) -> set:
        key = (d.year, d.month)
        if key not in universe_cache:
            universe_cache[key] = set(get_universe(d))
        return universe_cache[key]

    months = list(pd.date_range(bt_start, bt_end, freq="MS")) + [bt_start, bt_end]
    universe_union = sorted(set().union(*(set(get_universe(m)) for m in months)))

    if not universe_union:
        raise RuntimeError(
            f"Univers vide. Construis-le d'abord :\n"
            f"    py -3.10 build_universe.py --start {bt_start.date()}"
        )

    log("=" * 70)
    log(f"  Backtest mensuel multi-stratégies · {len(universe_union)} tickers")
    log(f"  Fenêtre : {bt_start.date()} → {bt_end.date()} ({backtest_days} jours)")
    log(f"  Capital initial : ${initial_cash:,.2f}")
    log(f"  Frais : {txn_cost_bp} bp / jambe ({2*txn_cost_bp} bp aller-retour)")
    log(f"  Pondération : {'equal-weight' if strategy_weights is None else strategy_weights}")
    log(f"  Filtre de régime SPY : {'ON' if regime_on else 'OFF'} "
        f"(sortie MM{regime_exit}, entrée MM{regime_entry})")
    log("=" * 70)

    # ── 2) Prix (cache Parquet partagé avec live.py) ──────────────────────────
    load_start = bt_start - timedelta(days=WARMUP_BUFFER_DAYS)
    daily_close, daily_open = data.load_prices(
        universe_union, load_start, bt_end, quiet=not verbose
    )
    if daily_close.empty:
        raise RuntimeError("Aucun prix chargé — vérifie les clés Alpaca et le cache.")

    monthly_close, monthly_open = data.to_monthly(daily_close, daily_open)
    common_months = list(monthly_close.index)
    log(f"  📅 {len(common_months)} mois : {common_months[0]} → {common_months[-1]}")

    # ── 2b) SPY pour le filtre de régime ──────────────────────────────────────
    spy_monthly = None
    if regime_on:
        spy_close, _ = data.load_prices(["SPY"], load_start, bt_end, quiet=True)
        if "SPY" in spy_close.columns:
            spy_monthly = data.monthly_close_of(spy_close["SPY"])
            log(f"  ✅ SPY chargé · {len(spy_monthly)} closes mensuels")
        else:
            log("  ⚠️  SPY indisponible — filtre de régime désactivé pour cette run.")
            regime_on = False

    # ── 3) Boucle mensuelle ───────────────────────────────────────────────────
    cash      = initial_cash
    positions = {}   # symbol -> {"qty": int, "avg_cost": float}
    stats     = {s: {"realized_pnl": 0.0, "trades": 0, "wins": 0,
                     "price_start": None, "price_end": None}
                 for s in daily_close.columns}
    equity_curve       = []
    first_alloc_period = None
    total_fees         = 0.0
    bearish_months     = 0
    n_regime_checks    = 0

    def mark_to_market(period, prices_row) -> float:
        """Equity = cash + Σ qty × prix. Prix manquant → dernier close connu."""
        val = cash
        for sym, p in positions.items():
            px = prices_row.get(sym, np.nan)
            if pd.isna(px):
                hist = (monthly_close.loc[:period, sym].dropna()
                        if sym in monthly_close.columns else None)
                if hist is None or hist.empty:
                    continue
                px = hist.iloc[-1]
            val += p["qty"] * px
        return val

    warmup_min_rows = max(STRATEGY_WARMUP, regime.warmup_min_rows if regime_on else 0)

    for i, exec_period in enumerate(common_months):
        exec_ts = exec_period.to_timestamp(how="start")
        if exec_ts < pd.Timestamp(bt_start.date()):
            continue   # antérieur au backtest : sert au warm-up des signaux
        if i == 0:
            continue   # besoin d'au moins 1 close passé pour un signal

        # a) Univers éligible au PREMIER JOUR du mois d'exécution
        eligible = universe_for(exec_ts)

        # b) Signal sur les closes STRICTEMENT avant exec_period
        signal_full   = monthly_close.loc[monthly_close.index < exec_period]
        cols_signal   = [c for c in signal_full.columns if c in eligible]
        signal_prices = signal_full[cols_signal] if cols_signal else signal_full.iloc[:, :0]

        in_warmup = len(signal_prices) < warmup_min_rows

        bullish = True
        if not in_warmup and regime_on and spy_monthly is not None:
            spy_hist = spy_monthly.loc[spy_monthly.index < exec_period]
            bullish  = regime.is_bullish(spy_hist, currently_invested=bool(positions))
            n_regime_checks += 1

        if in_warmup:
            if not positions:
                continue
            target_weights = pd.Series(0.0, index=signal_prices.columns)
        elif not bullish:
            # Régime baissier : cible zéro → la phase de ventes solde tout.
            target_weights = pd.Series(0.0, index=signal_prices.columns)
            bearish_months += 1
        else:
            target_weights = engine.decide(signal_prices, strategy_weights=strategy_weights)

        # c) Exécution au monthly_open[exec_period]
        open_row  = monthly_open.loc[exec_period]
        close_row = monthly_close.loc[exec_period]

        open_equity = cash
        for sym, p in positions.items():
            px = open_row.get(sym, np.nan)
            if pd.notna(px):
                open_equity += p["qty"] * px
            else:
                hist = (monthly_close.loc[:exec_period, sym].dropna()
                        if sym in monthly_close.columns else None)
                if hist is not None and len(hist) >= 2:
                    open_equity += p["qty"] * hist.iloc[-2]

        target_qty = {}
        for sym in target_weights.index:
            w = float(target_weights[sym])
            if w <= 0:
                continue
            px = open_row.get(sym, np.nan)
            if pd.isna(px) or px <= 0:
                continue
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
            if new_qty >= cur_qty:
                continue
            px = open_row.get(sym, np.nan)
            if pd.isna(px) or px <= 0:
                continue   # impossible à vendre → position conservée

            sold_qty    = cur_qty - new_qty
            proceeds    = sold_qty * px
            fee         = proceeds * txn_cost
            cash       += proceeds - fee
            total_fees += fee

            realized = (px - positions[sym]["avg_cost"]) * sold_qty
            stats[sym]["realized_pnl"] += realized
            stats[sym]["trades"]       += 1
            if realized > 0:
                stats[sym]["wins"] += 1
            day_log.append(f"🔴 SELL {sym} {sold_qty}@${px:.2f} ({realized:+.0f}$)")

            if new_qty == 0:
                del positions[sym]
            else:
                positions[sym]["qty"] = new_qty   # avg_cost inchangé

        # Phase 2 : ACHATS
        for sym, new_qty in target_qty.items():
            cur_qty = positions.get(sym, {}).get("qty", 0)
            if new_qty <= cur_qty:
                continue
            px      = open_row[sym]
            buy_qty = new_qty - cur_qty
            cost    = buy_qty * px
            fee     = cost * txn_cost

            if cost + fee > cash:
                # Cash insuffisant (rare) : on achète ce qu'on peut.
                buy_qty = int(cash / (px * (1.0 + txn_cost)))
                if buy_qty <= 0:
                    continue
                cost = buy_qty * px
                fee  = cost * txn_cost

            cash       -= cost + fee
            total_fees += fee

            if sym in positions:
                old_qty  = positions[sym]["qty"]
                tot_qty  = old_qty + buy_qty
                tot_cost = old_qty * positions[sym]["avg_cost"] + buy_qty * px
                positions[sym] = {"qty": tot_qty, "avg_cost": tot_cost / tot_qty}
            else:
                positions[sym] = {"qty": buy_qty, "avg_cost": px}
            stats[sym]["trades"] += 1
            day_log.append(f"🟢 BUY {sym} {buy_qty}@${px:.2f}")

        # d) Mark-to-market de fin de mois
        equity_end = mark_to_market(exec_period, close_row)

        for sym in close_row.index:
            px = close_row[sym]
            if pd.notna(px):
                if stats[sym]["price_start"] is None:
                    stats[sym]["price_start"] = float(px)
                stats[sym]["price_end"] = float(px)

        has_alloc = bool(positions) or target_weights.sum() > 0
        if first_alloc_period is None and has_alloc:
            first_alloc_period = exec_period
            equity_curve.append([str(exec_period), initial_cash])
            log(f"  ⏳ Fin du warm-up : 1ère allocation le {exec_period} "
                f"(après {i} mois sans signal exploitable)")

        if first_alloc_period is not None:
            equity_curve.append([str(exec_period), round(equity_end, 2)])

        if day_log:
            log(f"  {exec_period}  equity ${equity_end:>11,.0f}  cash ${cash:>10,.0f}  "
                f"pos {len(positions):>2}  │  {' · '.join(day_log[:6])}"
                f"{' …' if len(day_log) > 6 else ''}")

    # ── 4) Clôture : on solde au dernier close observé ────────────────────────
    last_close = monthly_close.loc[common_months[-1]]
    for sym, p in list(positions.items()):
        px = last_close.get(sym, np.nan)
        if pd.isna(px):
            hist = monthly_close[sym].dropna()
            if hist.empty:
                continue
            px = hist.iloc[-1]
        proceeds    = p["qty"] * px
        fee         = proceeds * txn_cost
        cash       += proceeds - fee
        total_fees += fee
        realized = (px - p["avg_cost"]) * p["qty"]
        stats[sym]["realized_pnl"] += realized
        stats[sym]["trades"]       += 1
        if realized > 0:
            stats[sym]["wins"] += 1
    positions = {}

    final_equity = cash
    total_return = (final_equity - initial_cash) / initial_cash * 100

    # ── 5) Métriques par action ───────────────────────────────────────────────
    results = []
    for sym in daily_close.columns:
        st = stats[sym]
        if st["price_start"] is None:
            continue
        results.append({
            "symbol":      sym,
            "pnl":         round(st["realized_pnl"], 2),
            "trades":      st["trades"],
            "win_rate":    (st["wins"] / st["trades"] * 100) if st["trades"] else 0.0,
            "price_start": st["price_start"],
            "price_end":   st["price_end"],
            "bh_return":   (st["price_end"] - st["price_start"]) / st["price_start"] * 100,
        })

    return {
        "generated":           datetime.now().isoformat(),
        "backtest_days":       backtest_days,
        "initial_cash":        initial_cash,
        "strategies":          "Momentum 12-1 + Reversal + LowVol + Trend (per-asset)",
        "transaction_cost_bp": txn_cost_bp,
        "strategy_weights":    strategy_weights,
        "regime_filter":       regime_on,
        "regime_exit_window":  regime_exit  if regime_on else None,
        "regime_entry_window": regime_entry if regime_on else None,
        "regime_checks":       n_regime_checks,
        "bearish_months":      bearish_months,
        "first_allocation":    str(first_alloc_period) if first_alloc_period else None,
        "total_fees":          round(total_fees, 2),
        "final_equity":        final_equity,
        "total_return":        total_return,
        "portfolio_daily":     equity_curve,
        "results":             results,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
def _print_summary(payload: dict) -> None:
    results = payload["results"]
    traded  = [r for r in results if r["trades"] > 0]

    for r in sorted(traded, key=lambda x: x["pnl"], reverse=True):
        icon = "✅" if r["pnl"] > 0 else "❌" if r["pnl"] < 0 else "⚪"
        print(f"  {icon}  {r['symbol']:<6}  PnL {r['pnl']:>+11,.0f}$  │  "
              f"{r['trades']:>3} trades  │  win {r['win_rate']:.0f}%")

    if not traded:
        print("\n  ⚠️  Aucune transaction. Vérifie l'historique et l'univers.")
        return

    best  = max(traded, key=lambda r: r["pnl"])
    worst = min(traded, key=lambda r: r["pnl"])
    cash0 = payload["initial_cash"]
    print()
    print("=" * 70)
    print("  Résumé portefeuille")
    print("=" * 70)
    print(f"  Capital initial         : ${cash0:,.0f}")
    print(f"  Equity finale           : ${payload['final_equity']:,.0f}")
    print(f"  Rendement total         : {payload['total_return']:+.2f}%")
    print(f"  Transactions totales    : {sum(r['trades'] for r in traded)}")
    print(f"  Frais cumulés           : ${payload['total_fees']:,.2f} "
          f"({payload['total_fees']/cash0*100:.2f}% du capital initial)")
    print(f"  Première allocation     : {payload['first_allocation']}")
    if payload["regime_filter"]:
        n = payload["regime_checks"]
        bull = (n - payload["bearish_months"]) / n * 100 if n else 0
        print(f"  Filtre de régime        : {payload['bearish_months']} mois bearish "
              f"sur {n} ({bull:.0f}% bullish)")
    print(f"  Meilleure action        : {best['symbol']} ({best['pnl']:+,.0f}$)")
    print(f"  Pire action             : {worst['symbol']} ({worst['pnl']:+,.0f}$)")
    print("=" * 70)


if __name__ == "__main__":
    payload = run_backtest()
    _print_summary(payload)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print()
    print(f"  💾 Résultats sauvegardés : {RESULTS_JSON}")
    print("  ▶  Lance « py -3.10 report.py » pour le rapport HTML")
