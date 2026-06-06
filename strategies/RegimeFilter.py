import pandas as pd


class RegimeFilter:
    """
    Filtre de régime de marché basé sur SPY (proxy S&P 500).

    Logique : à la fin du dernier mois observé, on compare SPY[t-1] à sa
    moyenne mobile sur `window_months` derniers prix mensuels INCLUANT
    SPY[t-1]. Si prix > MM → régime haussier (bullish, True). Sinon → bearish.

    Effet attendu côté backtest : si bearish, on liquide tout et on reste
    cash jusqu'au retour au-dessus de la MM. Décision applicable au mois
    suivant (exécution à l'open).

    Anti look-ahead : on n'utilise QUE des prix ≤ `iloc[-1]` (close du
    dernier mois achevé). Convention B, cohérente avec TrendFollowingPerAsset.

    Hypothèse : `spy_prices` est une Series mensuelle (index = fin de mois,
    valeurs = close mensuel SPY).
    """

    def __init__(self, window_months: int = 10):
        self.window_months = window_months

    def is_bullish(self, spy_prices: pd.Series) -> bool:
        # Historique insuffisant → conservateur : pas haussier (= on n'investit pas).
        if len(spy_prices) < self.window_months:
            return False

        window = spy_prices.iloc[-self.window_months:]
        mm     = window.mean()
        price  = spy_prices.iloc[-1]

        if pd.isna(mm) or pd.isna(price):
            return False
        return bool(price > mm)
