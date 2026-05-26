import pandas as pd

LONG, SHORT, NONE = "LONG", "SHORT", "NONE"


class MeanReversionStrategy:
    """
    Retour à la moyenne.
    Signal principal : RSI.
    Filtre d'extrême  : bandes de Bollinger.
    LONG  : RSI survendu (< oversold) ET prix sous / à la bande basse.
    SHORT : RSI suracheté (> overbought) ET prix sur / au-dessus de la bande haute.
    Sortie : RSI redevient neutre ou prix revient vers la moyenne → signal NONE.
    """

    def __init__(self, rsi_period: int = 14, oversold: int = 30, overbought: int = 70,
                 bb_period: int = 20, bb_num_std: float = 2.0):
        self.rsi_period = rsi_period
        self.oversold   = oversold
        self.overbought = overbought
        self.bb_period  = bb_period
        self.bb_num_std = bb_num_std

    def _rsi(self, prices: pd.Series) -> pd.Series:
        delta = prices.diff()
        gain  = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss  = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs    = gain / loss.replace(0, float("inf"))
        return 100 - (100 / (1 + rs))

    def get_signal(self, prices: pd.Series) -> str:
        if len(prices) < max(self.rsi_period, self.bb_period) + 1:
            return NONE

        rsi = self._rsi(prices).iloc[-1]

        sma   = prices.rolling(self.bb_period).mean()
        std   = prices.rolling(self.bb_period).std()
        upper = (sma + self.bb_num_std * std).iloc[-1]
        lower = (sma - self.bb_num_std * std).iloc[-1]
        price = prices.iloc[-1]

        if rsi < self.oversold and price <= lower:
            return LONG
        if rsi > self.overbought and price >= upper:
            return SHORT
        return NONE
