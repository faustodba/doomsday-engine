# ==============================================================================
#  DOOMSDAY ENGINE V6 — reset_schedule.py
#
#  Rimuove il timestamp di schedule per un task da state/<ISTANZA>.json.
#  Utile per forzare la riesecuzione di un task al prossimo tick
#  senza usare --force (che bypassa anche i guard di stato).
#
#  Uso:
#    python reset_schedule.py --istanza FAU_00 --task store
#    python reset_schedule.py --istanza FAU_01 --task vip
# ==============================================================================

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="Doomsday Engine V6 — Reset schedule singolo task",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--istanza", required=True, help="Nome istanza (es. FAU_00)")
    parser.add_argument("--task",    required=True, help="Nome task (es. store)")
    args = parser.parse_args()

    path = os.path.join(ROOT, "state", f"{args.istanza}.json")

    if not os.path.exists(path):
        print(f"[ERRORE] File non trovato: {path}")
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[ERRORE] JSON non valido: {exc}")
        sys.exit(1)

    schedule = data.get("schedule", {})

    if args.task not in schedule:
        print(f"[INFO] Chiave '{args.task}' non presente in schedule — nessuna modifica.")
        sys.exit(0)

    valore_precedente = schedule.pop(args.task)
    data["schedule"] = schedule

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[OK] {args.istanza} — schedule '{args.task}' rimosso (era: {valore_precedente})")
    print(f"     File: {path}")


if __name__ == "__main__":
    main()
