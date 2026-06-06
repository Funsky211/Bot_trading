import pandas as pd


class TrendFollowingPerAsset:
    """
    Trend-following par titre (signal binaire, agrégé en poids equal-weight).

    Pour chaque titre, on compare le prix de fin du dernier mois observé
    à sa propre moyenne mobile sur `window_months` (par défaut 10 mois,
    fenêtre incluant le prix courant). Si prix > MM → LONG ; sinon → FLAT.

    Contrairement aux 3 autres stratégies (classements cross-sectionnels),
    celle-ci est binaire par titre indépendamment des autres. Le nombre de
    titres LONG peut varier de 0 (tous flat, marché baissier) à N (tous
    haussiers). On répartit ensuite le poids equal-weight entre les LONG
    (1/N_long), 0 pour les FLAT.

    Poids sommant à 1 — sauf si aucun titre n'est LONG (somme = 0). C'est
    le comportement voulu : en marché entièrement baissier, le trend-following
    reste flat (pas d'allocation forcée).

    Anti look-ahead : on utilise uniquement les prix ≤ `iloc[-1]` (close
    du dernier mois achevé). Le moteur applique ces poids à l'ouverture du
    mois suivant.

    Convention de notation (B) : `iloc[-1]` = P[t-1] = close du dernier mois
    achevé. La MM inclut ce prix : MM = moyenne de iloc[-window_months:].

    Hypothèse : `prices_df` est déjà en fréquence mensuelle (index = dates de
    fin de mois, colonnes = tickers, valeurs = prix de clôture).
    """

    def __init__(self, window_months: int = 10):
        self.window_months = window_months

    def generate_weights(self, prices_df: pd.DataFrame) -> pd.Series:
        cols = prices_df.columns
        # Il faut au moins `window_months` prix pour calculer la MM.
        if len(prices_df) < self.window_months:
            return pd.Series(0.0, index=cols)

        # Fenêtre des N derniers prix mensuels INCLUANT le prix de référence.
        window = prices_df.iloc[-self.window_months:]
        # mean(skipna=False) : un seul NaN dans la fenêtre du titre → MM = NaN
        # → titre exclu (traité comme FLAT, poids = 0).
        mm    = window.mean(axis=0, skipna=False)
        price = prices_df.iloc[-1]

        # Comparaison stricte. NaN dans price ou mm → False (titre exclu).
        is_long = (price > mm) & price.notna() & mm.notna()
        longs   = is_long[is_long].index

        weights = pd.Series(0.0, index=cols)
        n_long  = len(longs)
        if n_long == 0:
            return weights                # tous flat → somme = 0

        weights.loc[longs] = 1.0 / n_long  # equal-weight entre les LONG
        return weights
