import pandas as pd


class ShortTermReversal:
    """
    Réversion court terme 1 mois (Jegadeesh 1990, Lehmann 1990).

    À la fin du dernier mois observé, on classe les titres sur leur SEUL
    rendement mensuel le plus récent : `r = P[t-1] / P[t-2] - 1`. On
    surpondère les pires performeurs (bottom quantile) — hypothèse que les
    perdants à court terme rebondissent le mois suivant.

    Long-only : on ne shorte pas les gagnants, seul le bottom quantile reçoit
    un poids (equal-weight, 0 ailleurs). Poids sommant à 1 — sauf si aucun
    titre n'est éligible (somme = 0).

    Anti look-ahead : le signal calculé sur prices_df[:T] (dernière ligne =
    close du dernier mois achevé) n'utilise QUE des prix ≤ ce close. Le moteur
    applique ces poids à l'ouverture du mois suivant.

    Convention de notation (B) : `iloc[-1]` = P[t-1] = close du dernier mois
    achevé. `iloc[-k]` = P[t-k].

    Hypothèse : `prices_df` est déjà en fréquence mensuelle (index = dates de
    fin de mois, colonnes = tickers, valeurs = prix de clôture).
    """

    def __init__(self, bottom_quantile: float = 0.2):
        self.bottom_quantile = bottom_quantile

    def generate_weights(self, prices_df: pd.DataFrame) -> pd.Series:
        cols = prices_df.columns
        # Il faut 2 observations mensuelles : iloc[-1] et iloc[-2].
        if len(prices_df) < 2:
            return pd.Series(0.0, index=cols)

        end_price   = prices_df.iloc[-1]     # P[t-1]
        start_price = prices_df.iloc[-2]     # P[t-2]

        score = end_price / start_price - 1.0
        score = score.dropna()               # exclut tickers à historique manquant
        if score.empty:
            return pd.Series(0.0, index=cols)

        # Bottom quantile : les `n_bot` rendements les plus faibles (= pires
        # performeurs sur le mois écoulé). Au moins 1 titre sélectionné.
        n_bot = max(1, int(round(len(score) * self.bottom_quantile)))
        losers = score.nsmallest(n_bot).index

        weights = pd.Series(0.0, index=cols)
        weights.loc[losers] = 1.0 / n_bot    # equal-weight dans le bottom
        return weights
