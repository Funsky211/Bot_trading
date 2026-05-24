from dotenv import load_dotenv
import os
from alpaca.trading.client import TradingClient

load_dotenv()

client = TradingClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
    paper=True,
)

account = client.get_account()
print(f"Connecté ! Cash disponible : ${float(account.cash):,.2f}")