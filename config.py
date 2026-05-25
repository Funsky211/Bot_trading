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

QTY = 2  # Nombre d'actions achetées par symbole

# ── Stratégies ────────────────────────────────────────────────────────────────
SMA_SHORT      = 20
SMA_LONG       = 50
RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
MACD_FAST      = 12
MACD_SLOW      = 26
MACD_SIGNAL    = 9

# ── Combinaison ───────────────────────────────────────────────────────────────
COMBINE_MODE = "majority"  # "majority" | "unanimous" | "weighted"

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_DAYS = 730
INITIAL_CASH  = 10_000.0