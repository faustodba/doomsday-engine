"""Analisi capacità nodi raccolta + copertura squadra dal dataset JSONL.

Uso:
    python tools/analisi_cap_nodi.py [--prod] [--days N]

Output:
    1. Capacità nominale per (tipo, livello) — max osservato
    2. Distribuzione campioni per istanza
    3. Saturazione media per istanza (capacita_attuale / max_nominale)
       → indica % residuo medio quando il bot trova un nodo
    4. COPERTURA SQUADRA per istanza (load_squadra / cap_nodo)
       → 100% squadra satura il nodo, <100% squadra underprovisioned

Il dataset si trova in:
    - dev:  c:/doomsday-engine/data/cap_nodi_dataset.jsonl
    - prod: c:/doomsday-engine-prod/data/cap_nodi_dataset.jsonl (con --prod)

Riferimento capacità nominale (memory/reference_capacita_nodi.md):
    pomodoro/segheria L7=1,320,000  L6=1,200,000
    acciaio          L7=  660,000  L6=  600,000
    petrolio         L7=  264,000  L6=  240,000
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Capacità nominale attesa (validata 30/04/2026 FAU_07)
NOMINALE = {
    ("campo", 6):    1_200_000,
    ("campo", 7):    1_320_000,
    ("segheria", 6): 1_200_000,
    ("segheria", 7): 1_320_000,
    ("acciaio", 6):    600_000,
    ("acciaio", 7):    660_000,
    ("petrolio", 6):   240_000,
    ("petrolio", 7):   264_000,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true",
                        help="Usa C:/doomsday-engine-prod/data invece di dev")
    parser.add_argument("--days", type=int, default=0,
                        help="Solo ultimi N giorni (0 = tutto)")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    path = root / "data" / "cap_nodi_dataset.jsonl"

    if not path.exists():
        print(f"Dataset non trovato: {path}")
        return 1

    cutoff = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    samples = []
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
                ts = datetime.fromisoformat(r["ts"])
                if ts < cutoff:
                    continue
            samples.append(r)

    if not samples:
        print("Nessun campione nel periodo.")
        return 0

    # Sezione 1: Capacità nominale max osservato
    by_kl: dict[tuple, list] = defaultdict(list)
    for s in samples:
        if s["capacita"] > 0 and s["livello"] > 0:
            by_kl[(s["tipo"], s["livello"])].append(s["capacita"])

    print(f"=== Campioni totali: {len(samples)} ===\n")
    print("--- Capacità osservata per (tipo, livello) ---")
    print(f'{"tipo":<12} {"liv":>3} {"n":>4} {"max":>10} {"media":>10} {"min":>10} {"nominale":>10}')
    for (tipo, liv), vals in sorted(by_kl.items()):
        nom = NOMINALE.get((tipo, liv), 0)
        print(f'{tipo:<12} {liv:>3} {len(vals):>4} {max(vals):>10} '
              f'{sum(vals)//len(vals):>10} {min(vals):>10} {nom:>10}')

    # Sezione 2: Campioni per istanza
    by_inst: dict[str, list] = defaultdict(list)
    for s in samples:
        by_inst[s["instance"]].append(s)

    print("\n--- Campioni per istanza ---")
    print(f'{"istanza":<14} {"n":>5} {"%cap":>6} {"media_residuo":>14}')
    for inst in sorted(by_inst.keys()):
        rs = by_inst[inst]
        # Saturazione: se capacita > 0 e max nominale noto → ratio
        ratios = []
        for r in rs:
            nom = NOMINALE.get((r["tipo"], r["livello"]), 0)
            if r["capacita"] > 0 and nom > 0:
                ratios.append(r["capacita"] / nom)
        n_ocr_ok = sum(1 for r in rs if r["capacita"] > 0)
        pct_ocr = 100 * n_ocr_ok / len(rs) if rs else 0
        avg_resid = (sum(ratios) / len(ratios) * 100) if ratios else 0
        print(f'{inst:<14} {len(rs):>5} {pct_ocr:>5.1f}% {avg_resid:>13.1f}%')

    # Sezione 3: % saturazione per (istanza, tipo)
    print("\n--- Residuo medio % per (istanza, tipo) — solo OCR OK ---")
    by_it: dict[tuple, list] = defaultdict(list)
    for s in samples:
        nom = NOMINALE.get((s["tipo"], s["livello"]), 0)
        if s["capacita"] > 0 and nom > 0:
            by_it[(s["instance"], s["tipo"])].append(s["capacita"] / nom)
    print(f'{"istanza":<14} {"tipo":<12} {"n":>4} {"residuo%":>9}')
    for (inst, tipo), ratios in sorted(by_it.items()):
        avg = sum(ratios) / len(ratios) * 100
        print(f'{inst:<14} {tipo:<12} {len(ratios):>4} {avg:>8.1f}%')

    # Sezione 4: Copertura squadra (load_squadra / cap_nodo) per (istanza, tipo)
    # Misura quanto la squadra satura il nodo: 100% = squadra abbastanza grossa,
    # <100% = squadra underprovisioned (poche truppe), il nodo non chiude e non
    # rigenera al max. Dati disponibili solo dopo deploy WU115b (load_squadra
    # nel dataset). Record con load_squadra=-1 (record vecchi pre-deploy o
    # marce non andate in maschera) sono esclusi.
    print("\n--- Copertura squadra (load_squadra / cap_nodo) per (istanza, tipo) ---")
    by_cov: dict[tuple, list] = defaultdict(list)
    n_records_with_load = 0
    for s in samples:
        cap_v = int(s.get("capacita", -1))
        load_v = int(s.get("load_squadra", -1))
        if cap_v > 0 and load_v > 0:
            by_cov[(s["instance"], s["tipo"])].append(load_v / cap_v)
            n_records_with_load += 1
    if n_records_with_load == 0:
        print("  (nessun record con load_squadra valido — deploy recente?)")
    else:
        print(f'{"istanza":<14} {"tipo":<12} {"n":>4} {"copertura%":>11} {"verdetto":>20}')
        for (inst, tipo), ratios in sorted(by_cov.items()):
            avg = sum(ratios) / len(ratios) * 100
            if avg >= 95:
                verdetto = "OK satura"
            elif avg >= 75:
                verdetto = "marginale"
            else:
                verdetto = "⚠ underprovisioned"
            print(f'{inst:<14} {tipo:<12} {len(ratios):>4} {avg:>10.1f}% {verdetto:>20}')

        # Aggregato per istanza (media coperture su tutti i tipi)
        print("\n--- Copertura media per istanza (tutti i tipi) ---")
        by_inst_cov: dict[str, list] = defaultdict(list)
        for (inst, _), ratios in by_cov.items():
            by_inst_cov[inst].extend(ratios)
        print(f'{"istanza":<14} {"n":>4} {"copertura media%":>17}')
        for inst, ratios in sorted(by_inst_cov.items()):
            avg = sum(ratios) / len(ratios) * 100
            mark = "✓" if avg >= 95 else ("~" if avg >= 75 else "⚠")
            print(f'{inst:<14} {len(ratios):>4} {avg:>16.1f}% {mark}')

    return 0


if __name__ == "__main__":
    sys.exit(main())
