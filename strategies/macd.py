import pandas as pd


class MACDStrategy:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast   = fast
        self.slow   = slow
        self.signal = signal

    def get_signal(self, prices: pd.Series) -> str:
        if len(prices) < self.slow + self.signal + 1:
            return "hold"

        ema_fast    = prices.ewm(span=self.fast,   adjust=False).mean()
        ema_slow    = prices.ewm(span=self.slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()

        prev_macd, curr_macd = macd_line.iloc[-2],   macd_line.iloc[-1]
        prev_sig,  curr_sig  = signal_line.iloc[-2], signal_line.iloc[-1]

        if prev_macd <= prev_sig and curr_macd > curr_sig:
            return "buy"
        if prev_macd >= prev_sig and curr_macd < curr_sig:
            return "sell"
        return "hold"