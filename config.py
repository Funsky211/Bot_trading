# ── Actions ───────────────────────────────────────────────────────────────────
SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "BRK.B", "UNH", "XOM",
    "JPM", "JNJ", "V", "PG", "MA",
    "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "AVGO", "COST", "TMO", "MCD",
    "ACN", "CSCO", "ABT", "DHR", "LIN",
    "WMT", "BAC", "CRM", "ADBE", "NFLX",
    "TXN", "NEE", "PM", "RTX", "QCOM",
    "HON", "UPS", "BMY", "SBUX", "GE",
    "AMGN", "LMT", "MDT", "T", "PYPL",
]

BUY_PCT = 0.10  # Fraction du capital disponible investie par achat

# ── Stratégie 1 : Trend Following ─────────────────────────────────────────────
TREND_SMA    = 50     # SMA servant de filtre de tendance principal
MACD_CONFIRM = True   # confirmation optionnelle par le MACD
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9

# ── Stratégie 2 : Mean Reversion ──────────────────────────────────────────────
RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
BB_PERIOD      = 20
BB_NUM_STD     = 2.0

# ── Gestion du risque : trailing stop ─────────────────────────────────────────
# On laisse courir les gagnants : pas de take-profit fixe. La position est vendue
# uniquement quand le prix retombe de TRAILING_STOP_PCT depuis son plus haut atteint.
# Au départ le plus haut = prix d'achat → agit aussi comme stop-loss initial (-25%).
TRAILING_STOP_PCT = 0.25

# ── Filtre de marché ──────────────────────────────────────────────────────────
# N'acheter que si le SPY est au-dessus de sa moyenne mobile (marché haussier).
# Coupe les achats en bear market (ex. 2022).
MARKET_FILTER = True
MARKET_SMA    = 200   # SMA du SPY utilisée comme filtre (jours de bourse)

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_DAYS = 2555
INITIAL_CASH  = 100_000.0

# ── Backtest mensuel multi-stratégies ─────────────────────────────────────────
# Coût de transaction : 5 bp à l'achat + 5 bp à la vente = 10 bp aller-retour.
# Appliqué sur le notional de chaque transaction (achat OU vente partielle).
TRANSACTION_COST_BP = 5          # par jambe (one-way), en points de base

# ── Pondération inter-stratégies ──────────────────────────────────────────────
# Pondère les 4 stratégies dans la combinaison de l'Engine.
#
# Noms valides : "Momentum", "Reversal", "LowVol", "Trend"
#                (= ceux enregistrés dans strategies/engine.py)
#
# Format       : dict {nom: poids} OU None pour equal-weight (25% chacune).
#
# Normalisation: automatique. La somme n'a PAS à valoir 1, on divise par
#                le total à l'exécution. Strat absente du dict = poids 0.
#                Ex: {"Momentum": 2, "Trend": 1} → 67% / 33%.
#
# Exemples :
#   STRATEGY_WEIGHTS = None
#       → toutes égales (baseline equal-weight, +118% sur 2019-2026)
#
#   STRATEGY_WEIGHTS = {"Momentum": 1.0}
#       → tester Momentum seul (les 3 autres désactivées)
#
#   STRATEGY_WEIGHTS = {"Trend": 0.5, "Momentum": 0.5}
#       → mix trend-following pur (LowVol + Reversal désactivées)
#
#   STRATEGY_WEIGHTS = {"Momentum": 0.40, "Trend": 0.30, "LowVol": 0.20, "Reversal": 0.10}
#       → momentum-heavy : favorise persistance, réduit la captation
#         des "faux rebonds" (HOOD/SMCI/MRNA) via Reversal léger
#
# Défaut acté après matrice de tests d'isolation (2026-06) :
#   - Trend seul         : +244.70%  (optimum brut)
#   - Trend 80/Mom 20    : +242.52%  ← choisi (perf -2pt, diversif strat)
#   - Equal-weight       : +118.26%
#   - Reversal et LowVol isolées : sous-performent (toxique / défensif inutile)
STRATEGY_WEIGHTS = {
    "Trend":    0.80,
    "Momentum": 0.20,
}

# ── Filtre de régime de marché ────────────────────────────────────────────────
# Filtre top-niveau : si SPY (proxy S&P 500) < sa moyenne mobile mensuelle au
# moment de la décision → on liquide tout et on reste 100% cash jusqu'au
# retour au-dessus. Logique cohérente avec TrendFollowingPerAsset (convention B,
# MM incluant le close du dernier mois achevé).
REGIME_FILTER       = False      # désactivé par défaut : sur 2019-2026 le filtre coupe la perf
                                  # (toutes configs testées : MM10 sym, MM6 sym, asym 3/12 → -49 à -73 pts vs OFF)
                                  # Réactiver si le marché entre en bear sustained type 2000-02 / 2007-09.
# Filtre asymétrique quand actif : sortir vite, rentrer prudemment.
# Si EXIT == ENTRY, on retombe sur un filtre symétrique classique.
REGIME_EXIT_WINDOW  = 3          # MM sortie : si SPY < MM3 mois et on est investi → cash
REGIME_ENTRY_WINDOW = 12         # MM entrée : si SPY > MM12 mois et on est cash → ré-investit