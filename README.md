# Bot_trading

Bot de trading long-only sur les 50 plus grosses capitalisations du S&P 500,
branché sur le **paper trading Alpaca**. Deux stratégies indépendantes décident
des entrées/sorties ; un moteur central combine leurs signaux.

## Stratégies

- **Trend Following** — filtre SMA + confirmation MACD optionnelle.
- **Mean Reversion** — RSI (survente/surachat) filtré par les bandes de Bollinger.

Le moteur ([engine.py](engine.py)) achète si au moins une stratégie est `LONG`,
et conserve la position tant qu'une stratégie le reste. Gestion du risque par
stop-loss et paliers de take-profit (voir [config.py](config.py)).

## Structure

| Fichier | Rôle |
|---|---|
| `bot.py` | Exécution live (paper) : analyse chaque action, passe les ordres Alpaca. |
| `backtest.py` | Simulation historique sur un pool de cash partagé. |
| `report.py` | Génère un rapport HTML comparé au SPY à partir du backtest. |
| `engine.py` | Combine les signaux des stratégies en une décision. |
| `config.py` | Paramètres : symboles, indicateurs, risque, backtest. |
| `strategies/` | Implémentation des stratégies. |

## Configuration

Créer un fichier `.env` à la racine :

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Installer les dépendances :

```
py -3.10 -m pip install -r requirements.txt
```

## Lancement

```
py -3.10 bot.py          # exécution live (paper trading)
py -3.10 backtest.py     # backtest → backtest_results.json
py -3.10 report.py       # rapport HTML à partir du dernier backtest
```
