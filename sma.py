from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from strategies.sma import SMAStrategy

load_dotenv()

# Récupérer les prix
client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

request = StockBarsRequest(
    symbol_or_symbols="AAPL",
    timeframe=TimeFrame.Day,
    start=datetime.now() - timedelta(days=200),
)

bars = client.get_stock_bars(request).df
prices = bars.loc["AAPL"]["close"]

# Tester la stratégie
sma = SMAStrategy(short_window=20, long_window=50)
signal = sma.get_signal(prices)

print(f"Nombre de jours : {len(prices)}")
print(f"Signal SMA      : {signal.upper()}")