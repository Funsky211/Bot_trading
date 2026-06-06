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

# Pondération inter-stratégies dans l'Engine. None = equal-weight (1/N).
# Sinon dict {nom: poids} ou list alignée sur Engine.strategies. Normalisé.
STRATEGY_WEIGHTS = None

# ── Filtre de régime de marché ────────────────────────────────────────────────
# Filtre top-niveau : si SPY (proxy S&P 500) < sa moyenne mobile mensuelle au
# moment de la décision → on liquide tout et on reste 100% cash jusqu'au
# retour au-dessus. Logique cohérente avec TrendFollowingPerAsset (convention B,
# MM incluant le close du dernier mois achevé).
REGIME_FILTER     = True
REGIME_SMA_MONTHS = 10           # fenêtre MM mensuelle SPY (≈ SMA200 jours)