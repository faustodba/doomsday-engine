"""
Genera il rollup giornaliero da events_<date>.jsonl.

Uso:
  py -3.14 tools/build_rollup.py                    # giorno corrente UTC
  py -3.14 tools/build_rollup.py --date 2026-04-26  # giorno specifico
  py -3.14 tools/build_rollup.py --date yesterday   # ieri
  py -3.14 tools/build_rollup.py --range 7          # ultimi 7 giorni
  py -3.14 tools/build_rollup.py --cleanup 365      # rimuove rollup > 365gg

Output: data/telemetry/rollup/rollup_<date>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Aggiungi root al sys.path per import core.telemetry
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.telemetry import (
    compute_and_save_rollup, cleanup_old_rollups, cleanup_old_events,
)


def _resolve_date(arg: str) -> str:
    if arg in ("today", "now", ""):
        return datetime.now(timezone.utc).date().isoformat()
    if arg == "yesterday":
        return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    # Validate ISO format
    datetime.strptime(arg, "%Y-%m-%d")
    return arg


def _print_rollup_summary(r: dict) -> None:
    t = r.get("totals", {})
    print(f"  date={r['date']} events={t.get('events',0)} "
          f"ok={t.get('ok',0)} skip={t.get('skip',0)} "
          f"fail={t.get('fail',0)} abort={t.get('abort',0)}")
    if r.get("per_task"):
        print(f"  per_task: {len(r['per_task'])} task ({', '.join(sorted(r['per_task'].keys()))})")
    if r.get("anomalies_global"):
        anom = r["anomalies_global"]
        print(f"  anomalies: {dict(sorted(anom.items(), key=lambda x: -x[1])[:5])}")


def main() -> int:
    p = argparse.ArgumentParser(description="Build telemetry rollup")
    p.add_argument("--date",    default="today",
                   help="data YYYY-MM-DD | today | yesterday")
    p.add_argument("--range",   type=int, default=None,
                   help="ultimi N giorni (sovrascrive --date)")
    p.add_argument("--cleanup", type=int, default=None,
                   help="rimuovi rollup > N giorni (e events > 30gg) DOPO il rollup")
    args = p.parse_args()

    if args.range:
        # Genera rollup per ogni giorno del range
        today = datetime.now(timezone.utc).date()
        dates = [(today - timedelta(days=i)).isoformat()
                 for i in range(args.range - 1, -1, -1)]
    else:
        dates = [_resolve_date(args.date)]

    for d in dates:
        print(f"[ROLLUP] computing date={d}")
        r = compute_and_save_rollup(d)
        if r is None:
            print(f"  ERR: save fallito per {d}")
            continue
        _print_rollup_summary(r)

    if args.cleanup:
        n_rollup = cleanup_old_rollups(retention_days=args.cleanup)
        n_events = cleanup_old_events(retention_days=30)
        print(f"[CLEANUP] rollup rimossi: {n_rollup}, events rimossi: {n_events}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
