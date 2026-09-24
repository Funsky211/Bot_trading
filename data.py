"""
Chargement des prix Alpaca, avec cache Parquet incrémental.

Partagé par backtest.py et live.py : les deux voient exactement les mêmes
prix, ce qui garantit que le live reproduit la logique validée en backtest.

Cache (cache/alpaca_daily_{close,open}.parquet) :
  - Premier appel  : télécharge [start, end] pour tous les tickers demandés.
  - Appels suivants: seulement le delta (nouvelles dates + nouveaux tickers).
    Une matrice de backtests sur 7 ans ne re-télécharge donc rien.

Interface publique :
    load_prices(symbols, start, end=None) -> (daily_close, daily_open)
    to_monthly(daily_close, daily_open)   -> (monthly_close, monthly_open)
    monthly_close_of(daily_series)        -> pd.Series mensuelle
"""
import os
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

CACHE_DIR   = os.path.join(BASE_DIR, "cache")
CLOSE_CACHE = os.path.join(CACHE_DIR, "alpaca_daily_close.parquet")
OPEN_CACHE  = os.path.join(CACHE_DIR, "alpaca_daily_open.parquet")

BATCH_SIZE = 100   # tickers par requête Alpaca

_client_singleton = None


def _client() -> StockHistoricalDataClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = StockHistoricalDataClient(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
        )
    return _client_singleton


def _to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


# ── Téléchargement ────────────────────────────────────────────────────────────
def _download(symbols, start: date, end: date, quiet: bool = False):
    """
    Télécharge les barres daily par lots. Renvoie (close_df, open_df) avec
    index = dates naïves normalisées à minuit, colonnes = tickers.
    Les tickers sans données (délistés / hors Alpaca) sont simplement absents.
    """
    symbols = sorted(set(symbols))
    closes, opens = [], []
    n_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

    for bi in range(n_batches):
        batch = symbols[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
        try:
            bars = _client().get_stock_bars(StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )).df
        except Exception as e:
            if not quiet:
                print(f"     lot {bi+1}/{n_batches} : échec ({e})")
            continue

        if bars is None or bars.empty:
            continue

        bars = bars.reset_index()
        ts = pd.to_datetime(bars["timestamp"])
        if ts.dt.tz is not None:
            ts = ts.dt.tz_localize(None)
        bars["timestamp"] = ts.dt.normalize()

        closes.append(bars.pivot(index="timestamp", columns="symbol", values="close"))
        opens.append(bars.pivot(index="timestamp", columns="symbol", values="open"))

        if not quiet:
            got = sum(len(f.columns) for f in closes)
            print(f"     lot {bi+1}/{n_batches} ({len(batch)}) · {got} tickers OK",
                  end="\r", flush=True)

    if not closes:
        return pd.DataFrame(), pd.DataFrame()

    close_df = pd.concat(closes, axis=1).sort_index()
    open_df  = pd.concat(opens,  axis=1).sort_index()
    close_df = close_df.loc[:, ~close_df.columns.duplicated()]
    open_df  = open_df.loc[:, ~open_df.columns.duplicated()]
    return close_df, open_df


def _merge(cached: pd.DataFrame, delta: pd.DataFrame) -> pd.DataFrame:
    """Fusionne un delta dans le cache : union des colonnes ET des lignes."""
    if cached.empty:
        return delta
    if delta.empty:
        return cached
    out = pd.concat([cached, delta], axis=0)
    # Lignes dupliquées (même date rechargée) : la dernière version gagne,
    # mais on ne veut pas écraser une valeur connue par un NaN du delta.
    out = out.groupby(level=0).last()
    return out.sort_index()


# ── Interface publique ────────────────────────────────────────────────────────
def load_prices(symbols, start, end=None, use_cache: bool = True, quiet: bool = False):
    """
    Renvoie (daily_close, daily_open) pour `symbols` sur [start, end].

    Le cache est étendu sur deux axes indépendants :
      1. nouvelles dates  → delta [cache_end+1 → end] pour les tickers en cache
      2. nouveaux tickers → range complet [start → end] pour eux seuls
    """
    symbols = sorted(set(symbols))
    start_d = _to_date(start)
    end_d   = _to_date(end) if end else date.today()

    if not use_cache:
        return _download(symbols, start_d, end_d, quiet)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cached_close = pd.DataFrame()
    cached_open  = pd.DataFrame()
    if os.path.exists(CLOSE_CACHE) and os.path.exists(OPEN_CACHE):
        cached_close = pd.read_parquet(CLOSE_CACHE)
        cached_open  = pd.read_parquet(OPEN_CACHE)
        cached_close.index = pd.to_datetime(cached_close.index)
        cached_open.index  = pd.to_datetime(cached_open.index)

    if cached_close.empty:
        if not quiet:
            print(f"  ⬇  Cache vide → téléchargement {len(symbols)} tickers · {start_d} → {end_d}")
        close_df, open_df = _download(symbols, start_d, end_d, quiet)
        if not close_df.empty:
            close_df.to_parquet(CLOSE_CACHE)
            open_df.to_parquet(OPEN_CACHE)
            if not quiet:
                print(f"  💾 Cache créé · {len(close_df.columns)} tickers        ")
        return _slice(close_df, symbols, start_d, end_d), _slice(open_df, symbols, start_d, end_d)

    have        = set(cached_close.columns)
    cache_start = cached_close.index.min().date()
    cache_end   = cached_close.index.max().date()
    updated     = False

    # 1) Extension vers le futur, pour les tickers déjà en cache.
    if cache_end < end_d:
        if not quiet:
            print(f"  ♻  Extension dates {cache_end + timedelta(days=1)} → {end_d}")
        d_close, d_open = _download(sorted(have), cache_end + timedelta(days=1), end_d, quiet)
        if not d_close.empty:
            cached_close = _merge(cached_close, d_close)
            cached_open  = _merge(cached_open,  d_open)
            updated = True

    # 2) Nouveaux tickers, sur toute la fenêtre demandée (élargie au cache
    #    existant pour que les colonnes restent alignées dans le temps).
    new_symbols = sorted(set(symbols) - have)
    if new_symbols:
        if not quiet:
            print(f"  ♻  {len(new_symbols)} nouveaux tickers → {min(cache_start, start_d)} → {end_d}")
        n_close, n_open = _download(new_symbols, min(cache_start, start_d), end_d, quiet)
        if not n_close.empty:
            cached_close = cached_close.join(n_close, how="outer")
            cached_open  = cached_open.join(n_open,  how="outer")
            updated = True

    if updated:
        cached_close.to_parquet(CLOSE_CACHE)
        cached_open.to_parquet(OPEN_CACHE)
        if not quiet:
            print(f"  💾 Cache à jour · {len(cached_close.columns)} tickers · "
                  f"{cached_close.index.min().date()} → {cached_close.index.max().date()}")
    elif not quiet:
        print(f"  ♻  Cache déjà complet · {len(cached_close.columns)} tickers · "
              f"jusqu'au {cache_end}")

    if cache_start > start_d and not quiet:
        print(f"  ⚠️  Le cache ne remonte qu'au {cache_start} (demandé : {start_d}).")

    return (_slice(cached_close, symbols, start_d, end_d),
            _slice(cached_open,  symbols, start_d, end_d))


def _slice(df: pd.DataFrame, symbols, start: date, end: date) -> pd.DataFrame:
    """Restreint le cache aux colonnes demandées et à la fenêtre [start, end]."""
    if df.empty:
        return df
    cols = [s for s in symbols if s in df.columns]
    out  = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end)), cols]
    return out.dropna(axis=1, how="all")


def to_monthly(daily_close: pd.DataFrame, daily_open: pd.DataFrame):
    """
    Resample mensuel : dernier close et premier open de chaque mois calendaire.
    Index = PeriodIndex('M'), restreint aux mois présents dans les deux séries.
    """
    m_close = daily_close.groupby(daily_close.index.to_period("M")).last()
    m_open  = daily_open.groupby(daily_open.index.to_period("M")).first()
    common  = sorted(set(m_close.index) & set(m_open.index))
    return m_close.loc[common], m_open.loc[common]


def monthly_close_of(daily_series: pd.Series) -> pd.Series:
    """Dernier close mensuel d'une série journalière (utilisé pour SPY)."""
    s = daily_series.dropna()
    return s.groupby(s.index.to_period("M")).last()
