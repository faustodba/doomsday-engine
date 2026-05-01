"""Analisi metriche per-istanza per-ciclo dal dataset JSONL.

Uso:
    python tools/analisi_istanza_metrics.py [--prod] [--days N]

Sezioni output:
  1. Boot HOME    - durata avvio per istanza (avg/std/min/max/n)
  2. Tick totale  - durata totale tick per istanza
  3. Task durata  - per (istanza, task) avg/std (per stime predittive)
  4. Raccolta     - n_invii / saturazione media / tipi inviati per istanza
  5. ETA marcia   - per (istanza, tipo) avg ETA (approxima durata raccolta)

Sorgenti dati:
  - data/istanza_metrics.jsonl (NEW WU89, append-only per ciclo*istanza)

Statistiche calcolate:
  - avg, std (population), min, max, count
  - filtro outlier opzionale via IQR Tukey k=1.5 (escluso default per dataset
    iniziale piccolo).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "avg": None, "std": None, "min": None, "max": None}
    n = len(values)
    avg = sum(values) / n
    var = sum((v - avg) ** 2 for v in values) / n
    std = math.sqrt(var)
    return {
        "n":   n,
        "avg": round(avg, 1),
        "std": round(std, 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true",
                        help="Usa C:/doomsday-engine-prod/data invece di dev")
    parser.add_argument("--days", type=int, default=0,
                        help="Solo ultimi N giorni (0 = tutto)")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    path = root / "data" / "istanza_metrics.jsonl"

    if not path.exists():
        print(f"Dataset non trovato: {path}")
        print("Verra' popolato al primo tick istanza completo.")
        return 1

    cutoff = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if cutoff is not None:
                ts = datetime.fromisoformat(r.get("ts", "1970-01-01T00:00:00+00:00"))
                if ts < cutoff:
                    continue
            records.append(r)

    if not records:
        print("Nessun campione nel periodo.")
        return 0

    print(f"=== Records totali: {len(records)} ===\n")

    # 1. Boot HOME per istanza
    by_inst_boot: dict[str, list[float]] = defaultdict(list)
    for r in records:
        v = r.get("boot_home_s")
        if v is not None and v > 0:
            by_inst_boot[r["instance"]].append(float(v))
    print("--- 1. Boot HOME (durata avvio in s) ---")
    print(f'{"istanza":<14} {"n":>4} {"avg":>6} {"std":>6} {"min":>6} {"max":>6}')
    for inst in sorted(by_inst_boot.keys()):
        s = _stats(by_inst_boot[inst])
        print(f'{inst:<14} {s["n"]:>4} {s["avg"]:>6} {s["std"]:>6} {s["min"]:>6} {s["max"]:>6}')

    # 2. Tick totale per istanza
    by_inst_tick: dict[str, list[float]] = defaultdict(list)
    for r in records:
        v = r.get("tick_total_s")
        if v is not None and v > 0:
            by_inst_tick[r["instance"]].append(float(v))
    print("\n--- 2. Tick totale (durata in s) ---")
    print(f'{"istanza":<14} {"n":>4} {"avg":>6} {"std":>6} {"min":>6} {"max":>6}')
    for inst in sorted(by_inst_tick.keys()):
        s = _stats(by_inst_tick[inst])
        print(f'{inst:<14} {s["n"]:>4} {s["avg"]:>6} {s["std"]:>6} {s["min"]:>6} {s["max"]:>6}')

    # 3. Task durata per (istanza, task)
    by_it_task: dict[tuple, list[float]] = defaultdict(list)
    for r in records:
        td = r.get("task_durations_s") or {}
        for tname, dur in td.items():
            if dur and dur > 0:
                by_it_task[(r["instance"], tname)].append(float(dur))
    print("\n--- 3. Task durata per (istanza, task) ---")
    print(f'{"istanza":<14} {"task":<20} {"n":>4} {"avg":>6} {"std":>6}')
    for (inst, tname) in sorted(by_it_task.keys()):
        s = _stats(by_it_task[(inst, tname)])
        print(f'{inst:<14} {tname:<20} {s["n"]:>4} {s["avg"]:>6} {s["std"]:>6}')

    # 4. Raccolta — n_invii / saturazione per istanza
    by_inst_invii: dict[str, list[int]] = defaultdict(list)
    by_inst_attive: dict[str, list[int]] = defaultdict(list)
    by_inst_pieni: dict[str, int] = defaultdict(int)
    for r in records:
        rac = r.get("raccolta") or {}
        invii = rac.get("invii") or []
        by_inst_invii[r["instance"]].append(len(invii))
        ap = rac.get("attive_post")
        if ap is not None:
            by_inst_attive[r["instance"]].append(int(ap))
            tot = rac.get("totali") or 0
            if tot > 0 and ap >= tot:
                by_inst_pieni[r["instance"]] += 1
    print("\n--- 4. Raccolta per istanza ---")
    print(f'{"istanza":<14} {"cicli":>5} {"avg_inv":>7} {"avg_att":>7} {"%pieni":>7}')
    for inst in sorted(by_inst_invii.keys()):
        cic = len(by_inst_invii[inst])
        avg_inv = sum(by_inst_invii[inst]) / cic if cic else 0
        avg_att = sum(by_inst_attive[inst]) / len(by_inst_attive[inst]) if by_inst_attive[inst] else 0
        pct_pieni = 100 * by_inst_pieni[inst] / cic if cic else 0
        print(f'{inst:<14} {cic:>5} {avg_inv:>7.2f} {avg_att:>7.2f} {pct_pieni:>6.1f}%')

    # 5. ETA marcia per (istanza, tipo)
    by_it_eta: dict[tuple, list[int]] = defaultdict(list)
    for r in records:
        for inv in (r.get("raccolta") or {}).get("invii", []) or []:
            eta = inv.get("eta_marcia_s")
            tipo = inv.get("tipo")
            if eta and eta > 0 and tipo:
                by_it_eta[(r["instance"], tipo)].append(int(eta))
    print("\n--- 5. ETA marcia per (istanza, tipo) ---")
    print(f'{"istanza":<14} {"tipo":<12} {"n":>4} {"avg":>6} {"std":>6}')
    for (inst, tipo) in sorted(by_it_eta.keys()):
        s = _stats(by_it_eta[(inst, tipo)])
        print(f'{inst:<14} {tipo:<12} {s["n"]:>4} {s["avg"]:>6} {s["std"]:>6}')

    return 0


if __name__ == "__main__":
    sys.exit(main())
