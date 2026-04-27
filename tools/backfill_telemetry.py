"""
Backfill telemetria retroattiva da logs/FAU_*.jsonl.

Genera eventi TaskTelemetry sintetici parsando le coppie
"Orchestrator: avvio task X" + "...completato/fallito" presenti nei log
e li scrive negli events_<date>.jsonl. Idempotente (dedup su ts_start+task+instance).

Uso:
  py -3.14 tools/backfill_telemetry.py                    # tutto bot.log + logs/
  py -3.14 tools/backfill_telemetry.py --days 7           # ultimi 7gg
  py -3.14 tools/backfill_telemetry.py --since 2026-04-25T00:00:00+00:00
  py -3.14 tools/backfill_telemetry.py --rebuild-rollup   # rigenera rollup_*.json

Limiti backfill:
  - output telemetry vuoto (Step 3 attivo solo da bot restart in poi)
  - cycle=0 (non determinabile dal log)
  - retry_count=0
  - anomalies inferite solo per ADB UNHEALTHY e eccezioni generiche
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.telemetry import backfill_from_logs, compute_and_save_rollup


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill telemetria da logs/")
    p.add_argument("--logs-dir", default=str(_ROOT / "logs"),
                   help="directory con FAU_*.jsonl (default: <root>/logs)")
    p.add_argument("--days", type=int, default=None,
                   help="indietro di N giorni (overrides --since)")
    p.add_argument("--since", default=None,
                   help="ISO timestamp limite inferiore (es. 2026-04-25T00:00:00+00:00)")
    p.add_argument("--until", default=None,
                   help="ISO timestamp limite superiore")
    p.add_argument("--rebuild-rollup", action="store_true",
                   help="dopo backfill, rigenera rollup_<date>.json per ogni giorno coperto")
    args = p.parse_args()

    logs_dir = Path(args.logs_dir)
    if not logs_dir.exists():
        print(f"ERR: logs dir non esistente: {logs_dir}")
        return 1

    since_iso = args.since
    if args.days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        since_iso = cutoff.isoformat()

    print(f"[BACKFILL] logs_dir={logs_dir}")
    if since_iso:
        print(f"[BACKFILL] since={since_iso}")
    if args.until:
        print(f"[BACKFILL] until={args.until}")

    stats = backfill_from_logs(logs_dir, since_iso=since_iso, until_iso=args.until)
    print(f"[BACKFILL] files_scanned={stats['files_scanned']}")
    print(f"[BACKFILL] events_parsed={stats['events_parsed']}")
    print(f"[BACKFILL] events_written={stats['events_written']}")
    print(f"[BACKFILL] deduped={stats['deduped']}")
    print(f"[BACKFILL] errors={stats['errors']}")

    if args.rebuild_rollup:
        # Determina date range coperte
        if since_iso:
            start = datetime.fromisoformat(since_iso).date()
        else:
            start = datetime.now(timezone.utc).date() - timedelta(days=7)
        end = datetime.now(timezone.utc).date()
        d = start
        rebuilt = 0
        while d <= end:
            r = compute_and_save_rollup(d.isoformat())
            if r:
                rebuilt += 1
                tot = r.get("totals", {}).get("events", 0)
                print(f"  rollup {d.isoformat()}: events={tot}")
            d += timedelta(days=1)
        print(f"[ROLLUP] rebuilt {rebuilt} files")

    return 0


if __name__ == "__main__":
    sys.exit(main())
