"""
Univers S&P 500 point-in-time (anti biais de survivance).

Pré-calcule, pour le 1er jour de bourse de chaque mois, le top N des tickers
du S&P 500 valides à cette date, classés par dollar volume médian sur 20 jours.
Stocke le résultat dans universe_history.db (SQLite).

Cache prix incrémental (price_cache.parquet) :
  - Premier build : télécharge l'historique complet via yfinance (~20-40 min).
  - Relance suivante : seulement le delta (nouvelles dates + nouveaux tickers)
    → typiquement < 1 min par mois.

Interface publique :
    build_universe_history(start_date, end_date=None, force=False, top_n=TOP_N)
    get_universe(date, top_n=None)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import io
import os
import re
import time
import sqlite3
from datetime import datetime, date, timedelta

import requests
import pandas as pd
import yfinance as yf

# ── Constantes ─────────────────────────────────────────────────────────────────
BASE_DIR            = os.path.dirname(os.path.abspath(__file__))
DB_PATH             = os.path.join(BASE_DIR, "universe_history.db")
PRICE_CACHE         = os.path.join(BASE_DIR, "price_cache.parquet")
CONSTITUENTS_CACHE  = os.path.join(BASE_DIR, "sp500_constituents.csv")

GITHUB_API   = "https://api.github.com/repos/fja05680/sp500/contents/"
GITHUB_RAW   = "https://raw.githubusercontent.com/fja05680/sp500/master/"
WIKI_URL     = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

BATCH_SIZE            = 50      # tickers par appel yf.download
SLEEP_BETWEEN_BATCHES = 1.5     # secondes entre lots (rate limiting yfinance)
LOOKBACK_DAYS         = 20      # fenêtre dollar volume médian (jours de bourse)
TOP_N                 = 50      # taille du top stocké par snapshot
MIN_VALID_DAYS        = 10      # jours mini dans la fenêtre pour être éligible
PRICE_BUFFER_DAYS     = 40      # marge avant start_date (1re fenêtre 20j)
CALENDAR_TICKER       = "SPY"   # référence du calendrier de bourse


# ── Utilitaires ────────────────────────────────────────────────────────────────
def _to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def _to_yf(ticker: str) -> str:
    """BRK.B → BRK-B (format yfinance)."""
    return ticker.replace(".", "-")


def _from_yf(ticker: str) -> str:
    """BRK-B → BRK.B (format Alpaca/point)."""
    return ticker.replace("-", ".")


# ── Base de données ────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_snapshots (
            snapshot_date TEXT,
            ticker        TEXT,
            rank          INTEGER,
            PRIMARY KEY (snapshot_date, ticker)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_date ON universe_snapshots(snapshot_date)"
    )
    return conn


def _existing_snapshots(conn) -> set:
    rows = conn.execute("SELECT DISTINCT snapshot_date FROM universe_snapshots").fetchall()
    return {r[0] for r in rows}


# ── Constituents historiques ───────────────────────────────────────────────────
def _latest_constituents_filename() -> str:
    """Repère le fichier daté le plus récent sur le repo fja05680/sp500."""
    resp = requests.get(GITHUB_API, timeout=30)
    resp.raise_for_status()
    pat = re.compile(r"S&P 500 Historical Components & Changes\((\d{2})-(\d{2})-(\d{4})\)\.csv")
    best_name, best_key = None, None
    for item in resp.json():
        m = pat.fullmatch(item["name"])
        if m:
            mm, dd, yyyy = m.groups()
            key = (yyyy, mm, dd)
            if best_key is None or key > best_key:
                best_key, best_name = key, item["name"]
    if best_name is None:
        raise RuntimeError("Aucun fichier daté 'Historical Components & Changes' trouvé sur le repo.")
    return best_name


def _parse_ticker_list(raw: str) -> list:
    out, seen = [], set()
    for tok in str(raw).split(","):
        tok = re.sub(r"-\d{6}$", "", tok.strip().upper())
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _load_constituents() -> pd.DataFrame:
    if not os.path.exists(CONSTITUENTS_CACHE):
        name = _latest_constituents_filename()
        url  = GITHUB_RAW + requests.utils.quote(name)
        print(f"  ⬇  Constituents historiques : {name}")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(CONSTITUENTS_CACHE, "wb") as f:
            f.write(resp.content)
    else:
        print(f"  ♻  Constituents : {os.path.basename(CONSTITUENTS_CACHE)}")

    df = pd.read_csv(CONSTITUENTS_CACHE)
    df["date"]    = pd.to_datetime(df["date"]).dt.date
    df["tickers"] = df["tickers"].apply(_parse_ticker_list)
    df = df.sort_values("date").reset_index(drop=True)
    print(f"     {len(df)} lignes · {df['date'].min()} → {df['date'].max()}")
    return df


def _load_wikipedia_current() -> list:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Bot_trading/1.0)"}
        html    = requests.get(WIKI_URL, headers=headers, timeout=30).text
        tables  = pd.read_html(io.StringIO(html))
        for t in tables:
            if "Symbol" in t.columns:
                syms = [str(s).strip().upper() for s in t["Symbol"] if str(s).strip().upper() != "NAN"]
                print(f"  ⬇  Wikipedia : {len(syms)} constituents actuels")
                return syms
    except Exception as e:
        print(f"  ⚠️  Wikipedia indisponible ({e})")
    return []


def _membership_timeline(end: date) -> pd.DataFrame:
    hist = _load_constituents()
    wiki = _load_wikipedia_current()
    if wiki:
        today      = min(date.today(), end)
        synth_date = max(today, hist["date"].max() + timedelta(days=1))
        hist = pd.concat(
            [hist, pd.DataFrame([{"date": synth_date, "tickers": wiki}])],
            ignore_index=True,
        )
    return hist.sort_values("date").reset_index(drop=True)


def _constituents_at(snapshot_date: date, timeline: pd.DataFrame) -> list:
    eligible = timeline[timeline["date"] <= snapshot_date]
    if eligible.empty:
        return []
    return list(eligible.iloc[-1]["tickers"])


# ── Téléchargement des prix (dollar volume = Close × Volume) ───────────────────
def _download_dv_batched(yf_tickers: list, start: date, end: date) -> pd.DataFrame:
    """
    Télécharge Close × Volume pour la liste de tickers via yf.download par lots.
    Renvoie DataFrame (index=dates, colonnes=tickers yfinance).
    """
    frames, failed = [], []
    end_excl  = end + timedelta(days=1)
    n_batches = (len(yf_tickers) + BATCH_SIZE - 1) // BATCH_SIZE

    for bi in range(n_batches):
        batch = yf_tickers[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
        try:
            raw = yf.download(
                batch, start=start, end=end_excl,
                auto_adjust=False, progress=False, group_by="column", threads=True,
            )
        except Exception as e:
            print(f"     lot {bi+1}/{n_batches} : échec ({e})")
            failed.extend(batch)
            time.sleep(SLEEP_BETWEEN_BATCHES)
            continue

        if raw is None or raw.empty:
            failed.extend(batch)
        else:
            if isinstance(raw.columns, pd.MultiIndex):
                close, vol = raw["Close"], raw["Volume"]
            else:
                close = raw[["Close"]].rename(columns={"Close": batch[0]})
                vol   = raw[["Volume"]].rename(columns={"Volume": batch[0]})
            dv = (close * vol).dropna(axis=1, how="all")
            frames.append(dv)
            failed.extend([t for t in batch if t not in dv.columns])

        ok = sum(len(f.columns) for f in frames)
        print(f"     lot {bi+1}/{n_batches} ({len(batch)}) · OK cumulé {ok} · échecs {len(failed)}", flush=True)
        time.sleep(SLEEP_BETWEEN_BATCHES)

    if failed:
        print(f"  ⚠️  {len(failed)} tickers sans données (délistés / hors marché) : {', '.join(sorted(failed)[:20])}{'…' if len(failed) > 20 else ''}")
    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def _load_prices_incremental(yf_tickers: list, start: date, end: date,
                              refresh: bool) -> pd.DataFrame:
    """
    Cache Parquet incrémental :
      - Premier run   : télécharge tout [start, end] pour tous les tickers.
      - Relances      : seulement le delta (nouvelles dates + nouveaux tickers).
    Deux axes d'incrémental indépendants :
      1. Nouvelles dates  → delta [cache_end+1 → end] pour les tickers déjà en cache.
      2. Nouveaux tickers → full range [start → end] uniquement pour eux.
    """
    need = sorted(set(yf_tickers) | {CALENDAR_TICKER})

    # ── Chargement cache existant ──
    cached = pd.DataFrame()
    if not refresh and os.path.exists(PRICE_CACHE):
        cached = pd.read_parquet(PRICE_CACHE)
        cached.index = pd.to_datetime(cached.index)

    if cached.empty:
        print(f"  ⬇  Téléchargement complet : {len(need)} tickers · {start} → {end}")
        dv = _download_dv_batched(need, start, end)
        if not dv.empty:
            dv.to_parquet(PRICE_CACHE)
            print(f"  💾 Cache créé : {os.path.basename(PRICE_CACHE)} ({len(dv.columns)} tickers)")
        return dv

    have        = set(cached.columns)
    cache_start = cached.index.min().date()
    cache_end   = cached.index.max().date()
    parts       = [cached]
    updated     = False

    # ── 1) Extension date (vers le futur) ──────────────────────────────────────
    if cache_end < end - timedelta(days=7):
        delta_start = cache_end + timedelta(days=1)
        extend_tickers = sorted(have)   # seulement les tickers déjà en cache
        print(f"  ♻  Extension dates {delta_start} → {end} ({len(extend_tickers)} tickers)")
        delta = _download_dv_batched(extend_tickers, delta_start, end)
        if not delta.empty:
            parts.append(delta)
            updated = True
    else:
        print(f"  ♻  Dates déjà couvertes jusqu'au {cache_end}")

    # ── 2) Nouveaux tickers ────────────────────────────────────────────────────
    new_tickers = sorted(set(need) - have)
    if new_tickers:
        print(f"  ♻  {len(new_tickers)} nouveaux tickers → download complet {start} → {end}")
        new_cols = _download_dv_batched(new_tickers, start, end)
        if not new_cols.empty:
            parts.append(new_cols)
            updated = True
    else:
        print(f"  ♻  Aucun nouveau ticker ({len(have)} déjà en cache)")

    # ── Merge + sauvegarde ─────────────────────────────────────────────────────
    if updated:
        # concat axis=0 (nouvelles dates) puis dédupe les lignes
        row_parts  = [p for p in parts if set(p.columns) <= have | set()]
        # Approche simple : concat tout en axis=0, pivot sur (date, ticker)
        combined   = pd.concat(parts, axis=0)
        # Dédupe les lignes (même date dans cached et delta → garder la plus récente)
        combined   = combined[~combined.index.duplicated(keep="last")]
        # Ajouter les colonnes des nouveaux tickers (qui n'ont que leur plage propre)
        combined   = combined.sort_index()
        combined.to_parquet(PRICE_CACHE)
        print(f"  💾 Cache mis à jour : {os.path.basename(PRICE_CACHE)} ({len(combined.columns)} tickers · {combined.index.min().date()} → {combined.index.max().date()})")
        return combined

    # ── Vérification couverture start ──────────────────────────────────────────
    if cache_start > start:
        print(f"  ⚠️  Cache ne remonte pas à {start} (commence à {cache_start}).")
        print(f"      Lance avec --refresh pour re-télécharger depuis {start}.")

    return cached


# ── Calendrier de bourse / snapshots mensuels ─────────────────────────────────
def _monthly_snapshot_dates(start: date, end: date, calendar: pd.DatetimeIndex) -> list:
    """1er jour de bourse de chaque mois, via le calendrier SPY réel."""
    cal    = calendar[(calendar.date >= start) & (calendar.date <= end)]
    if len(cal) == 0:
        return []
    s      = pd.Series(cal, index=cal)
    firsts = s.groupby([cal.year, cal.month]).min()
    return [d.date() for d in sorted(firsts.tolist())]


# ── Construction de la table ───────────────────────────────────────────────────
def build_universe_history(start_date, end_date=None, force=False,
                           refresh=False, top_n=TOP_N) -> None:
    """
    Construit / met à jour universe_snapshots sur [start_date, end_date].

    Idempotent : les snapshots déjà présents sont sautés (sauf force=True).
    Incrémental : le cache prix n'est étendu que dans le delta manquant.
    Reprise après crash : commit par snapshot.

    Paramètres
    ----------
    start_date : str | date   Date de début.
    end_date   : str | date   Date de fin (défaut : aujourd'hui).
    force      : bool         Recalcule les snapshots déjà présents.
    refresh    : bool         Ignore le cache prix et re-télécharge tout.
    top_n      : int          Taille du top par snapshot (défaut : TOP_N).
    """
    start = _to_date(start_date)
    end   = _to_date(end_date) if end_date else date.today()
    print("=" * 64)
    print(f"  Construction univers · {start} → {end} · top {top_n}")
    print("=" * 64)

    conn = _connect()
    done = _existing_snapshots(conn)

    # 1) Timeline des constituents.
    timeline = _membership_timeline(end)

    # 2) Union des tickers sur la fenêtre [start, end] seulement.
    start_row  = timeline[timeline["date"] <= start]["date"]
    first_date = start_row.max() if not start_row.empty else timeline["date"].min()
    window     = timeline[(timeline["date"] >= first_date) & (timeline["date"] <= end)]
    union      = set()
    for _, row in window.iterrows():
        union.update(row["tickers"])
    yf_tickers = sorted({_to_yf(t) for t in union})
    print(f"  Tickers distincts sur la période : {len(yf_tickers)}")

    # 3) Chargement incrémental des prix.
    dl_start = start - timedelta(days=PRICE_BUFFER_DAYS)
    dv = _load_prices_incremental(yf_tickers, dl_start, end, refresh)
    if dv.empty or CALENDAR_TICKER not in dv.columns:
        raise RuntimeError("Données prix indisponibles — impossible de construire les snapshots.")

    calendar  = dv[CALENDAR_TICKER].dropna().index
    snapshots = _monthly_snapshot_dates(start, end, calendar)
    print(f"  {len(snapshots)} snapshots mensuels à traiter\n")

    # 4) Boucle mois par mois.
    built, skipped = 0, 0
    for snap in snapshots:
        snap_str = snap.isoformat()
        if snap_str in done and not force:
            skipped += 1
            print(f"  {snap_str}  ⏭  déjà présent, skip")
            continue

        consts   = _constituents_at(snap, timeline)
        const_yf = [_to_yf(t) for t in consts]
        cols     = [t for t in const_yf if t in dv.columns]

        # Anti look-ahead : prix STRICTEMENT avant la snapshot_date.
        window = dv.loc[dv.index < pd.Timestamp(snap), cols].tail(LOOKBACK_DAYS)
        valid  = window.count()
        medians = window.median(skipna=True)
        eligible = medians[(valid >= MIN_VALID_DAYS) & medians.notna()]
        ranked   = eligible.sort_values(ascending=False).head(top_n)

        rows = [(snap_str, _from_yf(t), i + 1) for i, t in enumerate(ranked.index)]
        conn.execute("DELETE FROM universe_snapshots WHERE snapshot_date = ?", (snap_str,))
        conn.executemany("INSERT OR REPLACE INTO universe_snapshots VALUES (?, ?, ?)", rows)
        conn.commit()
        built += 1
        print(f"  {snap_str}  {len(consts)} constituents · {len(cols)} avec prix · top {len(rows)} retenus")

    conn.close()
    print(f"\n  ✅ Terminé : {built} snapshots construits, {skipped} sautés.")


# ── Lecture de l'univers ───────────────────────────────────────────────────────
def get_universe(date_, top_n=None) -> list:
    """
    Renvoie les tickers (format Alpaca, ex. BRK.B) du snapshot le plus récent
    AVANT ou ÉGAL à `date_`, triés par rank. Renvoie [] si aucun snapshot.
    Fonctionne en live ET en backtest.
    """
    d    = _to_date(date_).isoformat()
    conn = _connect()
    snap = conn.execute(
        "SELECT snapshot_date FROM universe_snapshots "
        "WHERE snapshot_date <= ? ORDER BY snapshot_date DESC LIMIT 1",
        (d,),
    ).fetchone()
    if snap is None:
        conn.close()
        return []
    q      = "SELECT ticker FROM universe_snapshots WHERE snapshot_date = ? ORDER BY rank ASC"
    params = [snap[0]]
    if top_n:
        q += " LIMIT ?"
        params.append(int(top_n))
    tickers = [r[0] for r in conn.execute(q, params).fetchall()]
    conn.close()
    return tickers


# ── Démo ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Démo get_universe() — table :", DB_PATH)
    for d in ["2016-03-15", "2020-06-01", date.today().isoformat()]:
        tickers = get_universe(d)
        if tickers:
            print(f"\n  {d}  → {len(tickers)} tickers · top 5 : {', '.join(tickers[:5])}, …")
        else:
            print(f"\n  {d}  → aucun snapshot (lance build_universe.py d'abord)")
