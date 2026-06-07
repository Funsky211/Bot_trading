import pandas as pd


class RegimeFilter:
    """
    Filtre de régime de marché basé sur SPY (proxy S&P 500), asymétrique.

    Logique :
      - Si on est EN MARCHÉ (positions > 0) : on compare SPY à sa MM
        `exit_window`. Sortir si SPY < MM_exit (réactif aux crashes).
      - Si on est EN CASH (positions = 0)   : on compare SPY à sa MM
        `entry_window`. Rentrer seulement si SPY > MM_entry (prudent).

    Si `exit_window == entry_window`, on retombe sur un filtre symétrique
    classique (sortir/rentrer sur la même MM).

    Crée une "bande morte" entre les transitions cash↔marché qui réduit
    le whipsaw : sortir vite quand le marché casse, ne rentrer que lorsque
    la reprise est confirmée par une fenêtre plus longue.

    Anti look-ahead : on n'utilise QUE des prix ≤ `iloc[-1]` (close du
    dernier mois achevé). Convention B, cohérente avec TrendFollowingPerAsset.

    Hypothèse : `spy_prices` est une Series mensuelle (index = fin de mois,
    valeurs = close mensuel SPY).
    """

    def __init__(self, exit_window: int = 3, entry_window: int = 12):
        self.exit_window  = exit_window
        self.entry_window = entry_window

    @property
    def warmup_min_rows(self) -> int:
        """Historique minimum requis = max des deux fenêtres."""
        return max(self.exit_window, self.entry_window)

    def is_bullish(self, spy_prices: pd.Series, currently_invested: bool) -> bool:
        """
        currently_invested : True si on a au moins une position au moment
                              de la décision. Détermine quelle MM appliquer.
        """
        window_size = self.exit_window if currently_invested else self.entry_window

        # Historique insuffisant → conservateur : pas haussier (= on n'investit pas).
        if len(spy_prices) < window_size:
            return False

        window = spy_prices.iloc[-window_size:]
        mm     = window.mean()
        price  = spy_prices.iloc[-1]

        if pd.isna(mm) or pd.isna(price):
            return False
        return bool(price > mm)
