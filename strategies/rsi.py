import pandas as pd


class RSIStrategy:
    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        self.period     = period
        self.oversold   = oversold
        self.overbought = overbought

    def _compute_rsi(self, prices: pd.Series) -> pd.Series:
        delta = prices.diff()
        gain  = delta.clip(lower=0).rolling(self.period).mean()
        loss  = (-delta.clip(upper=0)).rolling(self.period).mean()
        rs    = gain / loss.replace(0, float("inf"))
        return 100 - (100 / (1 + rs))

    def get_signal(self, prices: pd.Series) -> str:
        if len(prices) < self.period + 1:
            return "hold"

        rsi = self._compute_rsi(prices)
        prev, curr = rsi.iloc[-2], rsi.iloc[-1]

        if prev >= self.oversold and curr < self.oversold:
            return "buy"
        if prev <= self.overbought and curr > self.overbought:
            return "sell"
        return "hold"