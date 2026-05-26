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

# ── Gestion du risque ─────────────────────────────────────────────────────────
STOP_LOSS_PCT = 0.15  # Vendre tout si -15% par rapport au prix d'achat

# Paliers de take profit : (seuil de gain, fraction de la position initiale à vendre)
# Le dernier palier vend automatiquement le reste (peu importe la fraction indiquée)
TAKE_PROFIT_LEVELS = [
    (0.15, 0.20),   
    (0.30, 0.20),   
    (0.50, 0.20),   
]

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_DAYS = 1825
INITIAL_CASH  = 100_000.0