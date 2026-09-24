"""
Paramètres du bot — architecture mensuelle multi-stratégies cross-sectionnelles.

L'univers n'est PAS défini ici : il est lu dynamiquement depuis
universe_history.db (top 50 S&P 500 point-in-time). Voir universe_selector.py.
"""

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_DAYS = 2555          # ~7 ans
INITIAL_CASH  = 100_000.0

# Coût de transaction : 5 bp à l'achat + 5 bp à la vente = 10 bp aller-retour.
# Appliqué sur le notional de chaque jambe (achat OU vente, même partielle).
TRANSACTION_COST_BP = 5       # par jambe (one-way), en points de base

# ── Pondération inter-stratégies ──────────────────────────────────────────────
# Pondère les 4 stratégies dans la combinaison de l'Engine.
#
# Noms valides : "Momentum", "Reversal", "LowVol", "Trend"
#                (= ceux enregistrés dans strategies/engine.py)
#
# Format       : dict {nom: poids} OU None pour equal-weight (25% chacune).
#
# Normalisation: automatique. La somme n'a PAS à valoir 1, on divise par le
#                total à l'exécution. Strat absente du dict = poids 0.
#                Ex: {"Momentum": 2, "Trend": 1} → 67% / 33%.
#
# Défaut acté après matrice de tests d'isolation (2026-06) :
#   - Trend seul         : +244.70%  (optimum brut)
#   - Trend 80/Mom 20    : +242.52%  ← choisi (perf -2pt, diversification)
#   - Equal-weight       : +118.26%
#   - Reversal et LowVol isolées : sous-performent (toxique / défensif inutile)
#
# ⚠️  Ces chiffres sont des rendements BRUTS, sans ajustement du risque.
#     Comparer aussi Sharpe et max drawdown avant de figer une pondération.
STRATEGY_WEIGHTS = {
    "Trend":    0.80,
    "Momentum": 0.20,
}

# ── Filtre de régime de marché ────────────────────────────────────────────────
# Filtre top-niveau : si SPY (proxy S&P 500) passe sous sa moyenne mobile
# mensuelle au moment de la décision → on liquide tout et on reste 100% cash
# jusqu'au retour au-dessus. Convention B (MM incluant le close du dernier mois
# achevé), cohérente avec TrendFollowingPerAsset.
REGIME_FILTER = False    # désactivé : sur 2019-2026 le filtre coupe la perf
                         # (MM10 sym, MM6 sym, asym 3/12 → -49 à -73 pts vs OFF).
                         # Réactiver en bear sustained type 2000-02 / 2007-09.

# Filtre asymétrique quand actif : sortir vite, rentrer prudemment.
# Si EXIT == ENTRY, on retombe sur un filtre symétrique classique.
REGIME_EXIT_WINDOW  = 3   # MM sortie : SPY < MM3 mois et investi  → cash
REGIME_ENTRY_WINDOW = 12  # MM entrée : SPY > MM12 mois et en cash → ré-investit
