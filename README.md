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
| `universe_selector.py` | Univers S&P 500 point-in-time : `build_universe_history()` + `get_universe()`. |
| `build_universe.py` | CLI de construction de la table d'univers (SQLite). |

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

## Univers dynamique (anti biais de survivance)

Plutôt qu'une liste figée, le bot lit la liste des **actions du S&P 500 réellement
présentes** au 1er jour de bourse de chaque mois (~500 par mois). Les constituents
historiques viennent du repo [fja05680/sp500](https://github.com/fja05680/sp500)
et le mois courant de Wikipedia. **Aucun prix n'est téléchargé** ici : le bot
récupère les prix lui-même via Alpaca au moment d'analyser chaque action.

### Construire la table (à lancer une fois)

```
py -3.10 build_universe.py --start 2015-01-01
```

Génère `universe_history.db` (table `universe_snapshots`). Ne télécharge que le CSV
des constituents + Wikipedia → **build quasi instantané (< 1 min sur 10 ans)**. Le
script est **idempotent** et **reprend après un crash** : les mois déjà calculés
sont sautés.

```
py -3.10 build_universe.py --start 2015-01-01 --force      # tout recalculer
py -3.10 build_universe.py --start 2015-01-01 --top 100    # tronquer à 100/mois
```

Le **backtest** utilise déjà cet univers : il faut donc avoir construit la table
sur une période couvrant `BACKTEST_DAYS` avant de lancer `backtest.py`.

### Intégrer en live (`bot.py`)

```python
from universe_selector import get_universe
from datetime import date

symbols = get_universe(date.today())   # remplace config.SYMBOLS
```

`get_universe(d)` renvoie les tickers du snapshot mensuel le plus récent ≤ `d`
(format Alpaca, ex. `BRK.B`) — fonctionne en backtest comme en live.

> `universe_history.db` et `sp500_constituents.csv` sont régénérables : gitignorés.
