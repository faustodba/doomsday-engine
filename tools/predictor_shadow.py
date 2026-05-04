"""
WU89 Step 3 — Predictor Shadow Mode CLI.

Replay del predictor sui dati storici (data/istanza_metrics.jsonl)
per validare cosa avrebbe predetto/skippato.

Uso:
    python tools/predictor_shadow.py [--prod] [--days N]

Output:
  - Per ogni istanza: count predizioni skip per ragione
  - Saving stimato (cicli skippati × tempo medio per istanza)
  - Tabella decisioni recenti per ogni istanza

NON modifica nulla. Pura analisi.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, Counter
from pathlib import Path

# Path import
ROOT_DEV = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DEV))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", action="store_true",
                   help="Usa C:/doomsday-engine-prod come root")
    p.add_argument("--days", type=int, default=3,
                   help="Giorni di storico (default 3)")
    p.add_argument("--istanza", type=str, default=None,
                   help="Solo una specifica istanza")
    p.add_argument("--verbose", action="store_true",
                   help="Mostra ogni decisione, non solo aggregati")
    args = p.parse_args()

    if args.prod:
        os.environ["DOOMSDAY_ROOT"] = "C:/doomsday-engine-prod"

    from core.skip_predictor import predict, IstanzaSkipState, MAX_SKIP_CONSECUTIVI

    root = Path(os.environ.get("DOOMSDAY_ROOT", str(ROOT_DEV)))
    metrics_path = root / "data" / "istanza_metrics.jsonl"
    if not metrics_path.exists():
        print(f"ERROR: {metrics_path} non esiste")
        return 1

    # Carica records
    records = []
    with open(metrics_path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    # Filtro per giorni
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    records = [r for r in records
               if datetime.fromisoformat(r.get("ts", "1970-01-01T00:00:00+00:00")) >= cutoff]

    # Group by istanza, ordina per ts
    # Esclude istanze MASTER (FauMorfeus) — fuori dai ranking ordinari per scope
    from shared.instance_meta import is_master_instance
    by_inst = defaultdict(list)
    for r in records:
        if is_master_instance(r["instance"]):
            continue
        by_inst[r["instance"]].append(r)
    for k in by_inst:
        by_inst[k].sort(key=lambda x: x["ts"])

    if args.istanza:
        by_inst = {args.istanza: by_inst.get(args.istanza, [])}

    # Per ogni istanza, replay decisioni
    print(f"\n=== Predictor Shadow Replay — {args.days}gg, {len(records)} record ===\n")
    print(f"{'istanza':<10} {'cicli':>5} {'skip':>4} {'proceed':>7} {'ragioni skip':<40} {'guardrail_blocked':<8}")
    print("-" * 90)

    total_skip = 0
    total_cicli = 0
    total_blocked = 0

    for nome, seq in sorted(by_inst.items()):
        if not seq:
            continue
        skip_count = 0
        proceed_count = 0
        guardrail_blocked = 0
        reasons = Counter()
        state = IstanzaSkipState()

        if args.verbose:
            print(f"\n--- {nome} ({len(seq)} cicli) ---")

        for i, _r in enumerate(seq):
            # Per ogni record, simula: history = tutti i record fino a r-1
            history_subset = seq[:i + 1]
            state.cicli_totali = i + 1
            try:
                dec = predict(nome, history=history_subset, state=state)
            except Exception as exc:
                print(f"  ERROR predict {nome}@{_r['ts'][:19]}: {exc}")
                continue
            if dec.guardrail_triggered:
                guardrail_blocked += 1
                state.cicli_dall_ultimo_retry = 0
                state.last_skip_count_consec = 0
            elif dec.should_skip:
                skip_count += 1
                state.last_skip_count_consec += 1
                state.cicli_dall_ultimo_retry += 1
                reasons[dec.reason] += 1
            else:
                proceed_count += 1
                state.last_skip_count_consec = 0
                state.cicli_dall_ultimo_retry += 1

            if args.verbose:
                tag = "SKIP" if dec.should_skip else "OK"
                if dec.guardrail_triggered:
                    tag = "BLK"
                print(f"  c{i:>3} {_r['ts'][:19]} {tag:<5} reason={dec.reason} score={dec.score:.2f}"
                      f" gr={dec.guardrail_triggered or '-'}")

        reasons_str = " ".join(f"{k}:{v}" for k, v in reasons.most_common())
        print(f"{nome:<10} {len(seq):>5} {skip_count:>4} {proceed_count:>7} {reasons_str:<40} {guardrail_blocked:<8}")
        total_skip += skip_count
        total_cicli += len(seq)
        total_blocked += guardrail_blocked

    print("-" * 90)
    print(f"{'TOTALE':<10} {total_cicli:>5} {total_skip:>4} {total_cicli-total_skip-total_blocked:>7}     "
          f"  blocked_by_guardrail={total_blocked}")

    # Saving stimato
    saving_per_skip_s = 210  # boot 130s + raccolta tentativo 80s
    saving_total_s = total_skip * saving_per_skip_s
    print(f"\nSaving stimato: {total_skip} skip × {saving_per_skip_s}s = "
          f"{saving_total_s/60:.0f}min ({saving_total_s/3600:.1f}h)")
    if total_cicli > 0:
        print(f"Skip rate complessivo: {100*total_skip/total_cicli:.1f}% delle decisioni")

    # ── Valutazione rifornimento sempre-attivo vs on-demand ─────────────
    # Confronta avg total_invii (raccolta+rif) sui cicli con rifornimento
    # eseguito vs quelli senza, per stimare il rendimento del rifornimento.
    print(f"\n=== Valutazione rifornimento (target={5} invii/ciclo) ===")
    print(f"{'istanza':<10} {'cicli':>5} {'rif_on':>6} {'rif_off':>7} "
          f"{'avg_inv_on':>10} {'avg_inv_off':>11} {'delta':>6}")
    print("-" * 72)
    for nome, seq in sorted(by_inst.items()):
        if not seq:
            continue
        c_on, c_off = 0, 0
        sum_on, sum_off = 0, 0
        for r in seq:
            rif_invii = (r.get("rifornimento") or {}).get("invii", []) or []
            rac_invii = (r.get("raccolta")     or {}).get("invii", []) or []
            total = len(rac_invii) + len(rif_invii)
            if rif_invii:
                c_on += 1
                sum_on += total
            else:
                c_off += 1
                sum_off += total
        avg_on  = (sum_on / c_on)   if c_on  else 0.0
        avg_off = (sum_off / c_off) if c_off else 0.0
        delta   = avg_on - avg_off
        delta_s = f"{delta:+.2f}" if (c_on and c_off) else "—"
        print(f"{nome:<10} {len(seq):>5} {c_on:>6} {c_off:>7} "
              f"{avg_on:>10.2f} {avg_off:>11.2f} {delta_s:>6}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
