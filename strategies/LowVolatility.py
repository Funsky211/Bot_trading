import pandas as pd


class LowVolatility:
    """
    Low-volatility cross-sectional.

    À la fin du dernier mois observé, on calcule la volatilité de chaque
    titre sur les `window_months` derniers rendements mensuels simples
    (fenêtre de `window_months + 1` prix). On surpondère les titres les
    moins volatils (bottom quantile), equal-weight, 0 ailleurs.

    Long-only : on ne shorte pas les titres très volatils, seul le bottom
    quantile reçoit un poids. Poids sommant à 1 — sauf si aucun titre n'est
    éligible (somme = 0).

    Anti look-ahead : tous les rendements utilisés sont datés ≤ t-1 (close
    du dernier mois achevé). Le moteur applique ces poids à l'ouverture du
    mois suivant.

    Convention de notation (B) : `iloc[-1]` = P[t-1] = close du dernier mois
    achevé. Pour window_months=12, on utilise les rendements des mois t-12
    à t-1 inclus (12 rendements).

    Hypothèse : `prices_df` est déjà en fréquence mensuelle (index = dates de
    fin de mois, colonnes = tickers, valeurs = prix de clôture).
    """

    def __init__(self, window_months: int = 12, bottom_quantile: float = 0.2):
        self.window_months   = window_months
        self.bottom_quantile = bottom_quantile

    def generate_weights(self, prices_df: pd.DataFrame) -> pd.Series:
        cols = prices_df.columns
        # 12 rendements requièrent 13 prix.
        min_rows = self.window_months + 1
        if len(prices_df) < min_rows:
            return pd.Series(0.0, index=cols)

        # Fenêtre des 13 prix → 12 rendements (le 1er est NaN, droppé par iloc[1:]).
        window  = prices_df.iloc[-(self.window_months + 1):]
        returns = window.pct_change().iloc[1:]

        # std d'échantillon (ddof=1). skipna=False : un seul NaN dans la
        # fenêtre du titre → vol = NaN → titre exclu.
        vol = returns.std(axis=0, ddof=1, skipna=False)
        vol = vol.dropna()
        # Volatilité nulle = prix constant sur 12 mois (titre halted / délisté /
        # données mortes). On exclut pour éviter qu'il sature le bottom quantile.
        vol = vol[vol > 0]

        if vol.empty:
            return pd.Series(0.0, index=cols)

        # Bottom quantile : les n_bot titres les MOINS volatils. Au moins 1.
        n_bot   = max(1, int(round(len(vol) * self.bottom_quantile)))
        low_vol = vol.nsmallest(n_bot).index

        weights = pd.Series(0.0, index=cols)
        weights.loc[low_vol] = 1.0 / n_bot
        return weights
