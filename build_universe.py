"""
CLI de construction de l'univers S&P 500 point-in-time.

PREMIER BUILD (une seule fois, ~20-40 min) :
    py -3.10 build_universe.py --start 2015-01-01

MISE À JOUR MENSUELLE (< 1 min — seulement le delta) :
    py -3.10 build_universe.py --start 2015-01-01

    → Les snapshots déjà présents sont sautés automatiquement.
    → Le cache prix est étendu uniquement pour la période manquante.
    → Seul le nouveau mois est calculé et inséré dans la DB.

OPTIONS :
    --top N        Taille du top par snapshot (défaut : 50).
    --force        Recalcule tous les snapshots (conserve le cache prix).
    --refresh      Re-télécharge les prix depuis zéro (lent).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
from datetime import datetime

from universe_selector import build_universe_history, TOP_N


def main():
    p = argparse.ArgumentParser(description="Construit / met à jour universe_snapshots (SQLite).")
    p.add_argument("--start", required=True, help="Date de début (YYYY-MM-DD).")
    p.add_argument("--end",   default=None,  help="Date de fin (YYYY-MM-DD). Défaut : aujourd'hui.")
    p.add_argument("--top",   type=int, default=TOP_N, help=f"Top N par snapshot (défaut {TOP_N}).")
    p.add_argument("--force", action="store_true", help="Recalcule les snapshots déjà présents.")
    p.add_argument("--refresh", action="store_true", help="Re-télécharge les prix depuis zéro.")
    args = p.parse_args()

    t0 = datetime.now()
    build_universe_history(
        start_date=args.start,
        end_date=args.end,
        force=args.force,
        refresh=args.refresh,
        top_n=args.top,
    )
    print(f"  ⏱  Durée totale : {datetime.now() - t0}")


if __name__ == "__main__":
    main()
