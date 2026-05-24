from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from combiner import Combiner

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

combiner = Combiner(mode="majority")
decision, results = combiner.decide(prices)

print("── Signaux individuels ──────────────")
for name, signal, _ in results:
    print(f"  {name:<6} → {signal.upper()}")

print("─────────────────────────────────────")
print(f"  Décision finale → {decision.upper()}")