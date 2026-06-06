import pandas as pd
from .MomentumCrossSectional import MomentumCrossSectional
from .ShortTermReversal     import ShortTermReversal
from .LowVolatility         import LowVolatility
from .TrendFollowingPerAsset import TrendFollowingPerAsset


class Engine:
    """
    Orchestrateur multi-stratégies cross-sectionnelles.

    Chaque stratégie expose `generate_weights(prices_df) -> pd.Series` qui
    retourne un vecteur de poids indexé par ticker, sommant à 1 (ou à 0 si
    historique insuffisant / aucune sélection possible).

    L'Engine combine les vecteurs par moyenne pondérée (par défaut equal-
    weight entre stratégies), puis renormalise pour que le vecteur final
    somme à 1. Si toutes les stratégies sont inactives (somme=0), le
    vecteur final est zéro — pas d'allocation forcée.

    Le moteur n'introduit aucun look-ahead : il délègue intégralement le
    calcul du signal aux stratégies sur le `prices_df` fourni.
    """

    def __init__(self):
        self.strategies = [
            ("Momentum",  MomentumCrossSectional()),
            ("Reversal",  ShortTermReversal()),
            ("LowVol",    LowVolatility()),
            ("Trend",     TrendFollowingPerAsset()),
        ]

    def _resolve_strategy_weights(self, strategy_weights):
        """
        Convertit `strategy_weights` (None / dict / list) en liste de floats
        alignée sur `self.strategies`, normalisée pour sommer à 1.
        """
        n = len(self.strategies)
        if strategy_weights is None:
            return [1.0 / n] * n

        if isinstance(strategy_weights, dict):
            sw = [float(strategy_weights.get(name, 0.0)) for name, _ in self.strategies]
        else:
            sw = [float(x) for x in strategy_weights]
            if len(sw) != n:
                raise ValueError(
                    f"strategy_weights doit avoir {n} éléments alignés sur "
                    f"self.strategies, reçu {len(sw)}"
                )

        total = sum(sw)
        if total <= 0:
            raise ValueError("strategy_weights doit avoir une somme > 0")
        return [x / total for x in sw]

    def decide(self, prices_df: pd.DataFrame, strategy_weights=None) -> pd.Series:
        """
        Combine les vecteurs de poids des 4 stratégies en un vecteur cible.

        prices_df         : DataFrame mensuel (index=dates de fin de mois,
                            colonnes=tickers, valeurs=prix de clôture).
        strategy_weights  : None (egal-weight) | dict {name: w} | list alignée
                            sur self.strategies. Normalisé en interne.

        Returns : pd.Series indexée par les colonnes de prices_df, dtype=float,
                  somme=1 (allocation cible) ou somme=0 (toutes inactives).
        """
        sw      = self._resolve_strategy_weights(strategy_weights)
        cols    = prices_df.columns
        combined = pd.Series(0.0, index=cols)

        for (_, strat), w in zip(self.strategies, sw):
            weights = strat.generate_weights(prices_df)
            # Réalignement défensif : si la stratégie renvoie un index différent
            # (titre absent, ordre différent), on aligne sur les colonnes de
            # prices_df en comblant par 0.
            weights = weights.reindex(cols, fill_value=0.0)
            combined = combined + w * weights

        # Renormalisation finale : la moyenne pondérée peut sommer à < 1 si
        # certaines stratégies sont inactives (somme=0). On force somme=1
        # quand possible, zéro sinon.
        total = combined.sum()
        if total > 0:
            combined = combined / total
        else:
            combined = pd.Series(0.0, index=cols)

        return combined

    def decide_with_breakdown(self, prices_df: pd.DataFrame, strategy_weights=None):
        """
        Variante diagnostique : renvoie aussi les poids individuels par
        stratégie (utile pour reporting / debug — quelle stratégie contribue
        quoi sur quel titre).

        Returns : (combined, breakdown)
            combined  : pd.Series, vecteur final renormalisé (somme=1 ou 0).
            breakdown : dict {name: pd.Series} des poids bruts par stratégie
                        (avant pondération inter-stratégies).
        """
        sw        = self._resolve_strategy_weights(strategy_weights)
        cols      = prices_df.columns
        combined  = pd.Series(0.0, index=cols)
        breakdown = {}

        for (name, strat), w in zip(self.strategies, sw):
            weights = strat.generate_weights(prices_df).reindex(cols, fill_value=0.0)
            breakdown[name] = weights
            combined = combined + w * weights

        total = combined.sum()
        if total > 0:
            combined = combined / total
        else:
            combined = pd.Series(0.0, index=cols)

        return combined, breakdown
