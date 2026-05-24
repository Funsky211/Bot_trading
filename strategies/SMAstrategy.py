import pandas as pd


class SMAStrategy:
    def __init__(self, short_window: int = 20, long_window: int = 50):
        self.short_window = short_window
        self.long_window  = long_window

    def get_signal(self, prices: pd.Series) -> str:
        if len(prices) < self.long_window + 1:
            return "hold"

        sma_short = prices.rolling(self.short_window).mean()
        sma_long  = prices.rolling(self.long_window).mean()

        prev_short, curr_short = sma_short.iloc[-2], sma_short.iloc[-1]
        prev_long,  curr_long  = sma_long.iloc[-2],  sma_long.iloc[-1]

        if prev_short <= prev_long and curr_short > curr_long:
            return "buy"
        if prev_short >= prev_long and curr_short < curr_long:
            return "sell"
        return "hold"