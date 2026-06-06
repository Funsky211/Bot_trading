import pandas as pd


class MomentumCrossSectional:
    """
    Momentum cross-sectionnel 12-1 (Jegadeesh & Titman).

    À la fin du mois t, pour chaque titre, on calcule le rendement cumulé
    des mois t-12 à t-2 INCLUS (on saute le dernier mois t-1 pour neutraliser
    l'effet de réversion de court terme). Le rendement cumulé sur cette
    fenêtre se réduit à `P[t-2] / P[t-13] - 1`.

    On classe les titres par ce score, et on alloue un poids uniforme aux
    titres du top quantile (équipondéré dans le top, zéro ailleurs). Les
    poids retournés somment à 1 — sauf si aucun titre n'est éligible (cas
    bord : historique insuffisant ou trop de NaN), auquel cas la somme vaut 0.

    Anti look-ahead : le signal calculé sur prices_df[:T] (dernière ligne =
    close du dernier mois achevé) n'utilise QUE des prix ≤ ce close. Le moteur
    applique ensuite ces poids à l'ouverture du mois suivant.

    Convention de notation (B) : `iloc[-1]` = P[t-1] = close du dernier mois
    achevé. `iloc[-k]` = P[t-k]. Donc t = mois cible d'investissement (futur),
    t-1 = dernier mois observé.

    Hypothèse : `prices_df` est déjà en fréquence mensuelle (index = dates de
    fin de mois, colonnes = tickers, valeurs = prix de clôture).
    """

    def __init__(self, lookback_months: int = 12, skip_months: int = 1,
                 top_quantile: float = 0.2):
        self.lookback_months = lookback_months
        self.skip_months     = skip_months
        self.top_quantile    = top_quantile

    def generate_weights(self, prices_df: pd.DataFrame) -> pd.Series:
        cols = prices_df.columns
        # Rendement cumulé des mois t-L à t-(S+1) inclus = P[t-(S+1)] / P[t-(L+1)]
        # (télescopage). Pour L=12, S=1 : P[t-2]/P[t-13] = iloc[-2]/iloc[-13].
        # Il faut donc au minimum (lookback + 1) observations mensuelles.
        min_rows = self.lookback_months + 1
        if len(prices_df) < min_rows:
            return pd.Series(0.0, index=cols)

        end_price   = prices_df.iloc[-(self.skip_months + 1)]
        start_price = prices_df.iloc[-(self.lookback_months + 1)]

        score = end_price / start_price - 1.0
        score = score.dropna()                # exclut tickers à historique manquant
        if score.empty:
            return pd.Series(0.0, index=cols)

        # Top quantile : nb de titres sélectionnés = ceil(N * q), au moins 1.
        n_top = max(1, int(round(len(score) * self.top_quantile)))
        winners = score.nlargest(n_top).index

        weights = pd.Series(0.0, index=cols)
        weights.loc[winners] = 1.0 / n_top    # equal-weight dans le top
        return weights
