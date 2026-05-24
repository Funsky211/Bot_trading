import pandas as pd
from strategies.SMAstrategy import SMAStrategy
from strategies.RSIstrategy import RSIStrategy
from strategies.MACDstrategy import MACDStrategy


class Combiner:
    def __init__(self, mode: str = "majority"):
        self.mode = mode
        self.strategies = [
            ("SMA",  SMAStrategy(short_window=20, long_window=50),  1.0),
            ("RSI",  RSIStrategy(period=14, oversold=30, overbought=70), 1.5),
            ("MACD", MACDStrategy(fast=12, slow=26, signal=9),      1.0),
        ]

    def decide(self, prices: pd.Series) -> tuple:
        results = [(name, s.get_signal(prices), w) for name, s, w in self.strategies]
        decision = self._combine(results)
        return decision, results

    def _combine(self, results):
        if self.mode == "majority":
            return self._majority(results)
        if self.mode == "unanimous":
            return self._unanimous(results)
        if self.mode == "weighted":
            return self._weighted(results)

    def _majority(self, results):
        counts = {"buy": 0, "sell": 0, "hold": 0}
        for _, signal, _ in results:
            counts[signal] += 1
        return max(counts, key=lambda s: (counts[s], s == "hold"))

    def _unanimous(self, results):
        signals = {signal for _, signal, _ in results}
        if signals == {"buy"}:  return "buy"
        if signals == {"sell"}: return "sell"
        return "hold"

    def _weighted(self, results):
        scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        for _, signal, weight in results:
            scores[signal] += weight
        total = sum(scores.values()) or 1
        for signal in ("buy", "sell"):
            if scores[signal] / total > 0.5:
                return signal
        return "hold"