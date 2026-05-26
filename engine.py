import pandas as pd
from strategies.TrendFollowingStrategy import TrendFollowingStrategy
from strategies.MeanReversionStrategy import MeanReversionStrategy
import config

LONG, SHORT, NONE = "LONG", "SHORT", "NONE"


class Engine:
    """
    Orchestrateur long-only. Chaque stratégie est indépendante et renvoie
    LONG / SHORT / NONE. Le moteur traduit l'ensemble des signaux en une action :
      - à plat      : 'buy'  si au moins une stratégie veut être LONG, sinon 'hold'
      - en position : 'hold' tant qu'une stratégie veut rester LONG, sinon 'sell'
    Une seule position par actif, aucune pondération.
    """

    def __init__(self):
        self.strategies = [
            ("Trend", TrendFollowingStrategy(
                sma_window=config.TREND_SMA,
                macd_fast=config.MACD_FAST,
                macd_slow=config.MACD_SLOW,
                macd_signal=config.MACD_SIGNAL,
                use_macd=config.MACD_CONFIRM,
            )),
            ("MeanRev", MeanReversionStrategy(
                rsi_period=config.RSI_PERIOD,
                oversold=config.RSI_OVERSOLD,
                overbought=config.RSI_OVERBOUGHT,
                bb_period=config.BB_PERIOD,
                bb_num_std=config.BB_NUM_STD,
            )),
        ]

    def decide(self, prices: pd.Series, in_position: bool = False) -> tuple:
        results    = [(name, s.get_signal(prices)) for name, s in self.strategies]
        wants_long = any(signal == LONG for _, signal in results)

        if not in_position:
            decision = "buy" if wants_long else "hold"
        else:
            decision = "hold" if wants_long else "sell"

        return decision, results

    @staticmethod
    def describe_decision(symbol: str, decision: str, results: list, in_position: bool) -> str:
        bullish = [name for name, sig in results if sig == "LONG"]
        bearish = [name for name, sig in results if sig == "SHORT"]
        if decision == "buy":
            return f"         → {symbol} : signal d'achat ({', '.join(bullish)} haussier{'s' if len(bullish) > 1 else ''})"
        if decision == "sell":
            return f"         → {symbol} : signal de vente ({', '.join(bearish) or 'aucune stratégie haussière'})"
        if in_position:
            return f"         → {symbol} : position conservée ({', '.join(bullish) or 'signal mixte'})"
        return f"         → {symbol} : pas de signal, attente"
