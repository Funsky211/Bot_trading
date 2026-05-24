from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

request = StockBarsRequest(
    symbol_or_symbols="AAPL",
    timeframe=TimeFrame.Day,
    start=datetime.now() - timedelta(days=30),
)

bars = client.get_stock_bars(request).df
prices = bars.loc["AAPL"]["close"]

print(f"Nombre de jours récupérés : {len(prices)}")
print(f"Dernier cours AAPL : ${prices.iloc[-1]:.2f}")