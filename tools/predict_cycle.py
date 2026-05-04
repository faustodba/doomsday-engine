"""CLI tool per predict_cycle_duration — stima durata ciclo bot.

Uso:
    python tools/predict_cycle.py [--prod] [--verbose] [--istanza X]
    python tools/predict_cycle.py --prod --tasks boost,rifornimento,raccolta

Output: T_ciclo predicted + breakdown per istanza + confidence.

Utile per:
  - Sapere quanto durerà il prossimo ciclo dopo un cambio config
  - Planning post-restart (se faccio partire ora N istanze, quanto dura?)
  - Debug: vedere quale istanza/task domina il tempo
  - Calibrare tick_sleep_min in base a durata reale ciclo
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Forza utf-8
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def fmt_min(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h = m // 60
    m = m % 60
    return f"{h}h{m:02d}m{s:02d}s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true", help="Usa C:/doomsday-engine-prod")
    parser.add_argument("--verbose", action="store_true", help="Mostra task breakdown")
    parser.add_argument("--istanza", type=str, default="", help="Filtra solo istanza X")
    parser.add_argument("--tasks", type=str, default="",
                        help="Lista comma-separated task per override (es. boost,raccolta)")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    os.environ["DOOMSDAY_ROOT"] = str(root)
    sys.path.insert(0, str(root))

    from core.cycle_duration_predictor import (
        predict_cycle_from_config, predict_istanza_duration, refresh_stats,
    )

    refresh_stats()

    # Singola istanza
    if args.istanza:
        tasks = args.tasks.split(",") if args.tasks else []
        p = predict_istanza_duration(args.istanza, tasks)
        print(f"Istanza: {p['istanza']}")
        print(f"T_istanza:  {fmt_min(p['T_s'])} ({p['T_s']:.0f}s)")
        print(f"  boot_home: {p['boot_home_s']:.1f}s")
        for tname, ts in sorted(p['tasks'].items(), key=lambda x: -x[1]):
            marker = " ⚠" if tname in p['missing_stats'] else ""
            print(f"  {tname:22s}  {ts:>6.1f}s{marker}")
        print(f"Confidence: {p['confidence']}")
        if p['missing_stats']:
            print(f"⚠ Task senza dati storici: {', '.join(p['missing_stats'])}")
        return 0

    # Ciclo intero da config
    res = predict_cycle_from_config()
    if "error" in res:
        print(f"ERRORE: {res['error']}")
        return 1

    print("=" * 70)
    print(f"PREDICT CYCLE — {root.name}")
    print("=" * 70)
    print(f"T_ciclo totale:   {fmt_min(res['T_ciclo_s'])} = {res['T_ciclo_min']:.1f} min")
    print(f"  Σ istanze:      {fmt_min(res['T_ciclo_s'] - res['tick_sleep_s'])}")
    print(f"  + tick_sleep:   {fmt_min(res['tick_sleep_s'])}")
    print(f"Numero istanze:   {res['n_istanze']}")
    print(f"Confidence min:   {res['confidence']}")
    print()
    print("Breakdown per istanza (sorted by T desc):")
    sorted_inst = sorted(
        res['per_istanza'].items(),
        key=lambda kv: -kv[1]['T_s'],
    )
    print(f'{"istanza":<14} {"T_s":>6}  {"boot":>5}  {"confidence":>10}')
    for inst, p in sorted_inst:
        print(f'{inst:<14} {p["T_s"]:>6.0f}  {p["boot_home_s"]:>5.1f}  {p["confidence"]:>10}')
        if args.verbose:
            for tname, ts in sorted(p['tasks'].items(), key=lambda x: -x[1])[:5]:
                marker = " ⚠" if tname in p['missing_stats'] else ""
                print(f'    └─ {tname:18s} {ts:>6.1f}s{marker}')

    return 0


if __name__ == "__main__":
    sys.exit(main())
