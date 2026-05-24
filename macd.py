from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from strategies.macd import MACDStrategy

load_dotenv()

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

macd = MACDStrategy(fast=12, slow=26, signal=9)
signal = macd.get_signal(prices)

print(f"Nombre de jours : {len(prices)}")
print(f"Signal MACD     : {signal.upper()}")