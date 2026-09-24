# Bot_trading

Bot long-only sur les **50 plus grosses capitalisations du S&P 500**, à
rebalancement **mensuel**, branché sur le **paper trading Alpaca**.

Quatre stratégies cross-sectionnelles produisent chacune un vecteur de poids ;
un moteur les combine en une allocation cible, exécutée au premier jour de
bourse de chaque mois.

## Principe

À la fin de chaque mois, chaque stratégie note les titres de l'univers et
renvoie un `pd.Series` de poids sommant à 1. L'Engine en fait une moyenne
pondérée (voir `STRATEGY_WEIGHTS` dans [config.py](config.py)), puis
renormalise. Le portefeuille est rebalancé vers ces poids à l'ouverture du
mois suivant.

| Stratégie | Signal |
|---|---|
| **Momentum** (`MomentumCrossSectional`) | Momentum 12-1 : rendement des mois t-12 à t-2, top quintile |
| **Reversal** (`ShortTermReversal`) | Réversion 1 mois : bottom quintile du dernier rendement |
| **LowVol** (`LowVolatility`) | Volatilité 12 mois : bottom quintile |
| **Trend** (`TrendFollowingPerAsset`) | Prix > sa MM 10 mois → LONG, sinon FLAT |

Un **filtre de régime** optionnel (`RegimeFilter`, désactivé par défaut) passe
tout en cash quand le SPY casse sa moyenne mobile mensuelle.

**Anti-look-ahead** : le signal du mois M n'utilise que des prix ≤ fin du mois
M-1 ; l'exécution se fait à l'open de M. L'univers est *point-in-time* (les
titres réellement dans le S&P 500 à cette date), ce qui élimine le biais de
survivance.

## Structure

| Fichier | Rôle |
|---|---|
| `config.py` | Paramètres : pondérations, frais, filtre de régime, backtest. |
| `data.py` | Chargement des prix Alpaca + cache Parquet incrémental. **Partagé backtest / live.** |
| `universe_selector.py` | Univers S&P 500 point-in-time : `build_universe_history()` + `get_universe()`. |
| `build_universe.py` | CLI de construction de la table d'univers (SQLite). |
| `strategies/engine.py` | Combine les 4 vecteurs de poids en une allocation cible. |
| `strategies/` | Les 4 stratégies + le filtre de régime. |
| `backtest.py` | Backtest mensuel. Exposé comme `run_backtest(...)`. |
| `report.py` | Rapport HTML comparé au SPY. |
| `live.py` | Rebalancement mensuel sur le compte **paper** Alpaca. |

## Installation

Créer un `.env` à la racine :

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

```bash
py -3.10 -m pip install -r requirements.txt
```

## Utilisation

### 1. Construire l'univers (une fois, puis mensuellement)

```bash
py -3.10 build_universe.py --start 2015-01-01
```

Génère `universe_history.db`. Idempotent et reprenable : les mois déjà
calculés sont sautés, seul le delta est téléchargé. Options : `--top N`,
`--force`, `--refresh`.

### 2. Backtester

```bash
py -3.10 backtest.py
```

Écrit `results/backtest_results.json`. Le premier run remplit le cache prix
(`cache/`) ; les suivants ne re-téléchargent que le delta.

Pour balayer une matrice de configurations sans rien re-télécharger :

```python
from backtest import run_backtest

for w in [{"Trend": 1.0}, {"Trend": .8, "Momentum": .2}, None]:
    r = run_backtest(strategy_weights=w, verbose=False)
    print(w, f"{r['total_return']:+.2f}%")
```

`run_backtest()` accepte aussi `regime_filter`, `regime_exit`, `regime_entry`,
`backtest_days`, `initial_cash`, `txn_cost_bp`. Tout paramètre omis retombe
sur [config.py](config.py).

### 3. Rapport HTML

```bash
py -3.10 report.py
```

### 4. Live (paper)

```bash
py -3.10 live.py
```

Par défaut en **dry-run** : affiche le plan de rebalancement, n'envoie rien.

```bash
py -3.10 live.py --execute
```

Soumet les ordres après confirmation interactive. Options : `--yes` (sans
confirmation, pour une tâche planifiée), `--force` (rebalancer à nouveau dans
le mois — un seul rebalancement par mois sinon, état dans `live_state.json`).

## Verrou paper trading

`live.py` **ne peut pas trader en réel** :

- `paper=True` est écrit en dur — aucun flag ni variable d'environnement ne le change
- l'endpoint effectif est vérifié à la connexion **et avant chaque ordre** ; s'il
  ne pointe pas sur `paper-api.alpaca.markets`, le script s'arrête
- aucun ordre n'est envoyé sans `--execute`, et sans confirmation sauf `--yes`

À noter : Alpaca utilise des **clés distinctes** pour paper et live — des clés
live sur l'endpoint paper échouent à l'authentification.

## Limites connues

- Les métriques se limitent au rendement total : **pas de Sharpe ni de max
  drawdown**. Les pondérations documentées dans `config.py` sont comparées sur
  du rendement brut, sur une fenêtre 2019-2026 très majoritairement haussière.
- Pas de tests automatisés.
- Quantités entières uniquement (pas de fractional shares), en backtest comme
  en live.
