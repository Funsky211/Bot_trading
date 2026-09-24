"""
Bot live — rebalancement mensuel vers les poids cibles (PAPER TRADING UNIQUEMENT).

Reproduit exactement la logique validée en backtest :
  1. Univers = top 50 S&P 500 point-in-time au jour du rebalancement.
  2. Signal  = engine.decide(closes mensuels STRICTEMENT avant le mois courant).
  3. Filtre de régime SPY optionnel (config.REGIME_FILTER).
  4. Exécution : ventes d'abord (attente des fills), achats ensuite.

Les prix viennent de data.py — le même cache que le backtest, donc les mêmes
chiffres des deux côtés.

⚠️  VERROU PAPER
    Ce script ne peut pas trader en réel. `paper=True` est écrit en dur, et
    l'endpoint effectivement utilisé est vérifié avant toute soumission
    d'ordre. Aucun flag, aucune variable d'environnement ne lève ce verrou.

Usage :
    py -3.10 live.py                  # DRY-RUN : affiche le plan, n'envoie rien
    py -3.10 live.py --execute        # soumet les ordres après confirmation
    py -3.10 live.py --execute --yes  # sans confirmation interactive (cron)
    py -3.10 live.py --execute --force  # rebalance même si déjà fait ce mois-ci
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, OrderStatus, TimeInForce

import config
import data
from strategies.engine import Engine
from strategies.RegimeFilter import RegimeFilter
from universe_selector import get_universe

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "live_state.json")
load_dotenv(os.path.join(BASE_DIR, ".env"))

PAPER_ENDPOINT     = "paper-api.alpaca.markets"
WARMUP_BUFFER_DAYS = 800    # ~26 mois : large marge pour les 13 mois requis
STRATEGY_WARMUP    = 13     # mois requis par Momentum / LowVol
FILL_TIMEOUT_S     = 180

# Marge de sécurité live (absente du backtest, qui connaît le prix d'exécution).
# On dimensionne sur 98% de l'equity : si le marché ouvre en gap haussier, les
# derniers achats de la liste ne se retrouvent pas à court de cash.
CASH_BUFFER_PCT = 0.02


# ── Verrou paper ──────────────────────────────────────────────────────────────
def _assert_paper(client: TradingClient) -> str:
    """
    Vérifie que le client pointe bien sur l'endpoint paper. Appelé à la
    création ET juste avant toute soumission d'ordre — si une future version
    d'alpaca-py changeait le comportement par défaut, on s'arrête ici plutôt
    que de passer un ordre réel.
    """
    raw = getattr(client, "_base_url", "")
    url = str(getattr(raw, "value", raw))
    if PAPER_ENDPOINT not in url:
        raise RuntimeError(
            f"ABANDON : endpoint non-paper détecté ({url!r}). "
            f"Ce bot ne trade que sur {PAPER_ENDPOINT}."
        )
    return url


def paper_client() -> TradingClient:
    """Client Alpaca verrouillé sur le compte paper."""
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY absentes du .env")
    client = TradingClient(key, secret, paper=True)   # en dur, non surchargeable
    _assert_paper(client)
    return client


# ── État persistant ───────────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


# ── Signal ────────────────────────────────────────────────────────────────────
def compute_target_weights(today: date, verbose: bool = True):
    """
    Renvoie (signal_prices, latest_prices, info).

    signal_prices : closes MENSUELS strictement avant le mois courant — c'est
                    la seule chose que voient les stratégies (comme en backtest).
    latest_prices : dernier close JOURNALIER connu, uniquement pour dimensionner
                    les ordres. N'entre jamais dans le calcul du signal.
    info          : dict de diagnostic (univers, régime, mois de signal).
    """
    log = print if verbose else (lambda *a, **k: None)

    universe = get_universe(today)
    if not universe:
        raise RuntimeError(
            f"Univers vide pour {today}. Lance d'abord :\n"
            f"    py -3.10 build_universe.py --start 2015-01-01"
        )

    load_start = today - timedelta(days=WARMUP_BUFFER_DAYS)
    daily_close, daily_open = data.load_prices(universe, load_start, today, quiet=not verbose)
    monthly_close, _ = data.to_monthly(daily_close, daily_open)

    # Signal : closes STRICTEMENT avant le mois courant (mois d'exécution).
    current_period = pd.Period(today, freq="M")
    signal_prices  = monthly_close.loc[monthly_close.index < current_period]

    regime_on = config.REGIME_FILTER
    regime    = RegimeFilter(
        exit_window=config.REGIME_EXIT_WINDOW,
        entry_window=config.REGIME_ENTRY_WINDOW,
    )
    warmup_min = max(STRATEGY_WARMUP, regime.warmup_min_rows if regime_on else 0)
    if len(signal_prices) < warmup_min:
        raise RuntimeError(
            f"Historique insuffisant : {len(signal_prices)} mois disponibles, "
            f"{warmup_min} requis."
        )

    info = {
        "universe_size": len(universe),
        "signal_through": str(signal_prices.index[-1]),
        "exec_period": str(current_period),
        "regime_filter": regime_on,
        "bullish": True,
    }

    if regime_on:
        spy_close, _ = data.load_prices(["SPY"], load_start, today, quiet=True)
        spy_monthly  = data.monthly_close_of(spy_close["SPY"])
        spy_hist     = spy_monthly.loc[spy_monthly.index < current_period]
        # `currently_invested` est résolu par l'appelant côté portefeuille ;
        # ici on interroge le filtre en supposant l'état transmis par info.
        info["spy_history"] = spy_hist
        info["regime"] = regime

    # Dernier close journalier connu par ticker — sert UNIQUEMENT au
    # dimensionnement des ordres, jamais au signal.
    latest_prices = daily_close.ffill().iloc[-1]
    info["prices_asof"] = str(daily_close.index[-1].date())

    log(f"  Univers          : {len(universe)} tickers "
        f"(top 5 : {', '.join(universe[:5])}…)")
    log(f"  Signal calculé   : closes mensuels jusqu'à {signal_prices.index[-1]} inclus")
    log(f"  Prix de sizing   : closes journaliers au {info['prices_asof']}")
    log(f"  Mois d'exécution : {current_period}")

    return signal_prices, latest_prices, info


def resolve_weights(signal_prices, info, currently_invested: bool, verbose=True):
    """Applique le filtre de régime puis l'Engine. Renvoie pd.Series de poids."""
    log = print if verbose else (lambda *a, **k: None)

    if info["regime_filter"]:
        bullish = info["regime"].is_bullish(info["spy_history"], currently_invested)
        info["bullish"] = bullish
        log(f"  Régime SPY       : {'🐂 BULLISH' if bullish else '🐻 BEARISH → 100% cash'}")
        if not bullish:
            return pd.Series(0.0, index=signal_prices.columns)

    weights = Engine().decide(signal_prices, strategy_weights=config.STRATEGY_WEIGHTS)
    log(f"  Poids cibles     : {int((weights > 0).sum())} positions")
    return weights


# ── Exécution ─────────────────────────────────────────────────────────────────
def _wait_for_fills(trading: TradingClient, order_ids, timeout=FILL_TIMEOUT_S):
    """Attend que les ordres soient terminés. Renvoie l'ensemble des non-résolus."""
    terminal = {OrderStatus.FILLED, OrderStatus.CANCELED,
                OrderStatus.REJECTED, OrderStatus.EXPIRED}
    pending  = set(order_ids)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        time.sleep(2)
        for oid in list(pending):
            try:
                if trading.get_order_by_id(oid).status in terminal:
                    pending.discard(oid)
            except Exception:
                pass
    return pending


def _submit(trading: TradingClient, symbol: str, qty: int, side: OrderSide):
    _assert_paper(trading)   # re-vérification avant CHAQUE ordre
    return trading.submit_order(MarketOrderRequest(
        symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY,
    ))


def main() -> int:
    p = argparse.ArgumentParser(description="Rebalancement mensuel (paper trading).")
    p.add_argument("--execute", action="store_true",
                   help="Soumet réellement les ordres. Sans ce flag : dry-run.")
    p.add_argument("--yes", action="store_true",
                   help="Saute la confirmation interactive (usage cron).")
    p.add_argument("--force", action="store_true",
                   help="Rebalance même si déjà fait ce mois-ci.")
    args = p.parse_args()

    trading   = paper_client()
    endpoint  = _assert_paper(trading)
    account   = trading.get_account()
    today     = date.today()
    period    = str(pd.Period(today, freq="M"))
    equity    = float(account.equity)
    cash      = float(account.cash)

    print("=" * 72)
    print(f"  Bot Trading · {datetime.now():%Y-%m-%d %H:%M} · "
          f"{'DRY-RUN' if not args.execute else 'EXÉCUTION'}")
    print(f"  Mode            : 🧪 PAPER ({endpoint})")
    print(f"  Compte          : {account.account_number}")
    print(f"  Equity          : ${equity:,.2f}   ·   Cash : ${cash:,.2f}")
    print("=" * 72)

    # ── Garde : un seul rebalancement par mois ────────────────────────────────
    state = _load_state()
    if state.get("last_rebalance_period") == period and not args.force:
        print(f"\n  ⏭  Rebalancement déjà effectué pour {period} "
              f"(le {state.get('last_rebalance_at', '?')[:10]}).")
        print("     Utilise --force pour le refaire.")
        return 0

    try:
        clock = trading.get_clock()
        if not clock.is_open:
            print(f"\n  ⚠️  Marché fermé. Prochaine ouverture : {clock.next_open}.")
            print("     Les ordres market seraient mis en file jusqu'à l'ouverture.")
    except Exception:
        pass

    # ── Signal ────────────────────────────────────────────────────────────────
    print()
    signal_prices, latest_prices, info = compute_target_weights(today)

    current = {p.symbol: int(float(p.qty)) for p in trading.get_all_positions()}
    weights = resolve_weights(signal_prices, info, currently_invested=bool(current))

    # ── Quantités cibles ──────────────────────────────────────────────────────
    budget     = equity * (1.0 - CASH_BUFFER_PCT)
    target_qty = {}
    for sym, w in weights.items():
        w = float(w)
        if w <= 0:
            continue
        px = latest_prices.get(sym)
        if px is None or pd.isna(px) or px <= 0:
            continue
        qty = int(w * budget / px)
        if qty > 0:
            target_qty[sym] = qty

    sells = {s: current[s] - target_qty.get(s, 0)
             for s in current if target_qty.get(s, 0) < current[s]}
    buys  = {s: q - current.get(s, 0)
             for s, q in target_qty.items() if q > current.get(s, 0)}

    # ── Plan ──────────────────────────────────────────────────────────────────
    print()
    print("─" * 72)
    print(f"  PLAN DE REBALANCEMENT · {period}")
    print("─" * 72)
    print(f"  Positions actuelles : {len(current):>3}   →   cibles : {len(target_qty):>3}")
    if not sells and not buys:
        print("\n  ✅ Portefeuille déjà aligné sur la cible — rien à faire.")
        if args.execute:
            state.update({"last_rebalance_period": period,
                          "last_rebalance_at": datetime.now().isoformat(),
                          "target": target_qty})
            _save_state(state)
        return 0

    for s, q in sorted(sells.items()):
        px = latest_prices.get(s, float("nan"))
        tag = "SOLDE" if target_qty.get(s, 0) == 0 else f"→ {target_qty[s]}"
        print(f"    🔴 SELL  {s:<6} {q:>5}  (~${q*px:>10,.0f})  {tag}")
    for s, q in sorted(buys.items()):
        px = latest_prices.get(s, float("nan"))
        print(f"    🟢 BUY   {s:<6} {q:>5}  (~${q*px:>10,.0f})  → {target_qty[s]}")
    notional = sum(target_qty[s] * float(latest_prices.get(s, 0) or 0) for s in target_qty)
    print("─" * 72)
    print(f"  Notional cible ~${notional:,.0f} / equity ${equity:,.0f} "
          f"({notional/equity*100:.1f}% investi, tampon {CASH_BUFFER_PCT:.0%})")
    print("─" * 72)

    if not args.execute:
        print("\n  🧪 DRY-RUN — aucun ordre envoyé.")
        print("     Relance avec --execute pour soumettre ces ordres (paper).")
        return 0

    if not args.yes:
        print(f"\n  ⚠️  {len(sells)} ventes et {len(buys)} achats vont être soumis "
              f"sur le compte PAPER {account.account_number}.")
        if input("     Confirmer ? [oui/N] ").strip().lower() not in ("oui", "o", "yes", "y"):
            print("     Annulé.")
            return 1

    # ── Phase 1 : ventes ──────────────────────────────────────────────────────
    print()
    sell_ids = []
    for s, q in sorted(sells.items()):
        try:
            sell_ids.append(_submit(trading, s, q, OrderSide.SELL).id)
            print(f"    🔴 SELL {s:<6} {q:>5}  soumis")
        except Exception as e:
            print(f"    ⚠️  SELL {s:<6} échec : {e}")

    if sell_ids:
        print(f"\n  ⏳ Attente des fills ({len(sell_ids)} ventes)…")
        stuck = _wait_for_fills(trading, sell_ids)
        if stuck:
            print(f"  ⚠️  {len(stuck)} vente(s) non résolue(s) après "
                  f"{FILL_TIMEOUT_S}s — achats réduits au cash réellement libéré.")

    # ── Phase 2 : achats ──────────────────────────────────────────────────────
    available = float(trading.get_account().cash)
    print(f"\n  💵 Cash disponible après ventes : ${available:,.2f}")

    for s, q in sorted(buys.items()):
        px = float(latest_prices.get(s, 0) or 0)
        if px <= 0:
            continue
        if q * px > available:
            q = int(available / px)
            if q <= 0:
                print(f"    ⏸  BUY  {s:<6} ignoré — cash insuffisant")
                continue
        try:
            _submit(trading, s, q, OrderSide.BUY)
            available -= q * px
            print(f"    🟢 BUY  {s:<6} {q:>5}  soumis")
        except Exception as e:
            print(f"    ⚠️  BUY  {s:<6} échec : {e}")

    state.update({
        "last_rebalance_period": period,
        "last_rebalance_at":     datetime.now().isoformat(),
        "target":                target_qty,
        "regime_bullish":        info.get("bullish", True),
    })
    _save_state(state)

    print()
    print("=" * 72)
    print(f"  ✅ Rebalancement {period} soumis · état écrit dans "
          f"{os.path.basename(STATE_FILE)}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
