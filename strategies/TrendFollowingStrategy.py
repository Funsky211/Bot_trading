import pandas as pd

LONG, SHORT, NONE = "LONG", "SHORT", "NONE"


class TrendFollowingStrategy:
    """
    Suivi de tendance.
    Filtre principal  : SMA.
    Confirmation       : MACD (optionnelle, via use_macd).
    LONG  : prix au-dessus de la SMA (et MACD haussier si confirmation active).
    SHORT : prix sous la SMA (et MACD baissier si confirmation active).
    La sortie (cassure inverse de la SMA ou retournement net du MACD) est
    obtenue automatiquement : le signal cesse d'être LONG / SHORT.
    """

    def __init__(self, sma_window: int = 50, macd_fast: int = 12,
                 macd_slow: int = 26, macd_signal: int = 9, use_macd: bool = True):
        self.sma_window  = sma_window
        self.macd_fast   = macd_fast
        self.macd_slow   = macd_slow
        self.macd_signal = macd_signal
        self.use_macd    = use_macd

    def get_signal(self, prices: pd.Series) -> str:
        min_len = self.sma_window + 1
        if self.use_macd:
            min_len = max(min_len, self.macd_slow + self.macd_signal + 1)
        if len(prices) < min_len:
            return NONE

        sma   = prices.rolling(self.sma_window).mean().iloc[-1]
        price = prices.iloc[-1]

        macd_up = macd_down = True
        if self.use_macd:
            ema_fast    = prices.ewm(span=self.macd_fast, adjust=False).mean()
            ema_slow    = prices.ewm(span=self.macd_slow, adjust=False).mean()
            macd_line   = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
            macd_up   = macd_line.iloc[-1] > signal_line.iloc[-1]
            macd_down = macd_line.iloc[-1] < signal_line.iloc[-1]

        if price > sma and macd_up:
            return LONG
        if price < sma and macd_down:
            return SHORT
        return NONE
