"""Report copertura raccolta per istanza per ciclo (WU118 — 04/05).

Per ogni istanza × ciclo elenca gli invii raccolta con:
  - tipo nodo (campo, segheria, acciaio, petrolio)
  - livello (-1 = sconosciuto)
  - cap_nodo (quantità residua del nodo letta dal popup gather)
  - load_squadra (carico effettivo squadra dalla maschera invio, WU116)
  - verdetto: SATURA (load >= cap × 0.95) | NON SATURA (load < cap × 0.95)
              SATURA = squadra basta a chiudere il nodo (rigenera al max)
              NON SATURA = squadra underprovisioned, residuo lasciato

  - ?  = OCR mancante (load=-1 marcia non riuscita / record pre-WU116)

Uso:
    python tools/report_copertura_ciclo.py [--prod] [--days N]
                                           [--istanza X] [--last N]

Esempio output:
    FAU_00 — ciclo 142 (04/05 11:11→11:21 UTC, 600s, ok):
        🍅 campo    L7 | cap=1.32M | load=1.32M | SATURA
        🍅 campo    L7 | cap=1.32M | load=1.32M | SATURA
        ⚙ acciaio  L7 | cap= 660K | load= 660K | SATURA
        ── 3/3 satura (100%)

    FAU_09 — ciclo 142 (04/05 11:30→11:40 UTC, 600s, ok):
        🍅 campo    L6 | cap=1.20M | load=708K  | NON SATURA ⚠ (59%)
        🍅 campo    L6 | cap=1.20M | load=500K  | NON SATURA ⚠ (42%)
        🛢 petrolio L6 | cap= 240K | load= 240K | SATURA
        ── 1/3 satura (33%) ⚠ truppe insufficienti

Il dataset si trova in:
    - dev:  c:/doomsday-engine/data/istanza_metrics.jsonl
    - prod: c:/doomsday-engine-prod/data/istanza_metrics.jsonl (con --prod)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Soglia OCR noise per giudicare saturazione (load >= cap * 0.95 → satura)
SOGLIA_SATURA = 0.95

ICO = {
    "campo":    "🍅",
    "segheria": "🪵",
    "acciaio":  "⚙",
    "petrolio": "🛢",
}


def fmt_n(n: int) -> str:
    """Format number compatto: 1320012 → 1.32M, 708822 → 708K, 240 → 240."""
    if n < 0:
        return "  ?  "
    if n >= 1_000_000:
        return f"{n/1_000_000:>4.2f}M"
    if n >= 10_000:
        return f"{n/1000:>4.0f}K"
    if n >= 1_000:
        return f"{n/1000:>4.1f}K"
    return f"{n:>5d}"


def fmt_ts(iso: str) -> str:
    """ISO UTC → DD/MM HH:MM locale."""
    try:
        dt = datetime.fromisoformat(iso)
        local = dt.astimezone()
        return local.strftime("%d/%m %H:%M")
    except Exception:
        return iso[:16] if iso else "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true",
                        help="Usa C:/doomsday-engine-prod/data invece di dev")
    parser.add_argument("--days", type=int, default=0,
                        help="Solo ultimi N giorni (0=tutto)")
    parser.add_argument("--istanza", type=str, default="",
                        help="Filtra per nome istanza (es. FAU_09)")
    parser.add_argument("--last", type=int, default=0,
                        help="Solo gli ultimi N record per istanza (0=tutti)")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    path = root / "data" / "istanza_metrics.jsonl"

    if not path.exists():
        print(f"Dataset non trovato: {path}")
        return 1

    cutoff = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    # Read e filtra
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
                ts = datetime.fromisoformat(r["ts"])
                if ts < cutoff:
                    continue
            if args.istanza and r.get("instance") != args.istanza:
                continue
            records.append(r)

    if not records:
        print("Nessun record nel periodo/filtri.")
        return 0

    # Raggruppa per istanza
    by_inst: dict[str, list] = defaultdict(list)
    for r in records:
        by_inst[r["instance"]].append(r)

    # Sort per ts ascending dentro ogni istanza
    for inst in by_inst:
        by_inst[inst].sort(key=lambda r: r.get("ts", ""))
        if args.last > 0:
            by_inst[inst] = by_inst[inst][-args.last:]

    # Aggregati globali
    n_satura_g  = 0
    n_total_g   = 0
    n_unknown_g = 0   # load=-1 (record pre-WU116 o marcia fail)
    cycle_count = 0

    for inst in sorted(by_inst.keys()):
        cicli_inst = by_inst[inst]
        if not cicli_inst:
            continue
        print(f"\n{'═' * 70}")
        print(f"=== {inst} — {len(cicli_inst)} cicli ===")
        print(f"{'═' * 70}")

        for ciclo in cicli_inst:
            cycle_count += 1
            cid = ciclo.get("cycle_id", "?")
            ts  = fmt_ts(ciclo.get("ts", ""))
            tts = ciclo.get("tick_total_s", 0) or 0
            outc = ciclo.get("outcome", "?")
            rac = ciclo.get("raccolta", {}) or {}
            invii = rac.get("invii", []) or []

            n_inv  = len(invii)
            n_sat  = 0
            n_unk  = 0
            for inv in invii:
                cap  = int(inv.get("cap_nodo", -1))
                load = int(inv.get("load_squadra", -1))
                if load < 0 or cap <= 0:
                    n_unk += 1
                elif load >= cap * SOGLIA_SATURA:
                    n_sat += 1

            if n_inv == 0:
                continue   # ciclo senza invii raccolta — skip

            print(f"\n{inst} — ciclo {cid} ({ts} UTC, {tts:.0f}s, {outc})")
            for inv in invii:
                tipo = inv.get("tipo", "?")
                lv   = inv.get("livello", -1)
                cap  = int(inv.get("cap_nodo", -1))
                load = int(inv.get("load_squadra", -1))
                ico  = ICO.get(tipo, " ")
                lv_s = f"L{lv}" if lv > 0 else "L?"

                if load < 0:
                    verdetto = "?    (no OCR load)"
                elif cap <= 0:
                    verdetto = "?    (no OCR cap)"
                elif load >= cap * SOGLIA_SATURA:
                    verdetto = "SATURA"
                else:
                    pct = 100 * load / cap if cap > 0 else 0
                    verdetto = f"NON SATURA ⚠ ({pct:.0f}%)"

                print(f"    {ico} {tipo:<8s} {lv_s} | "
                      f"cap={fmt_n(cap)} | load={fmt_n(load)} | {verdetto}")

            # Aggregato del ciclo
            n_known = n_inv - n_unk
            if n_known > 0:
                pct_sat = 100 * n_sat / n_known
                mark = "" if pct_sat >= 95 else (" ⚠" if pct_sat < 50 else "")
                unk_s = f" (+{n_unk}?)" if n_unk else ""
                print(f"    ── {n_sat}/{n_known} satura ({pct_sat:.0f}%){unk_s}{mark}")
            else:
                print(f"    ── {n_inv} invii senza dati OCR completi (?)")

            n_satura_g  += n_sat
            n_total_g   += n_known
            n_unknown_g += n_unk

    # Riepilogo globale
    print(f"\n{'═' * 70}")
    print(f"=== RIEPILOGO ({cycle_count} cicli, {len(by_inst)} istanze) ===")
    print(f"{'═' * 70}")
    if n_total_g > 0:
        pct_g = 100 * n_satura_g / n_total_g
        print(f"  Invii con dati OCR completi: {n_total_g}")
        print(f"  Satura totale: {n_satura_g}/{n_total_g} ({pct_g:.1f}%)")
    if n_unknown_g > 0:
        print(f"  Invii senza dati OCR (load=-1): {n_unknown_g} (record pre-WU116 o marcia fail)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
