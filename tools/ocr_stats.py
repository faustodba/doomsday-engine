"""tools/ocr_stats.py — sintesi fallimenti lettura OCR risorse (WU183).

Legge `data/ocr_read_stats.jsonl` (append-only scritto da main.py ad ogni
lettura risorse) e stampa UNA riga di sintesi, adatta a un Monitor.

Uso:
    py -3.14 tools/ocr_stats.py [--root DIR] [--since ISO_TS]
"""
from __future__ import annotations
import argparse, json, os
from collections import Counter
from datetime import datetime

_RES = ("acciaio", "legno", "pomodoro", "petrolio")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"C:\doomsday-engine-prod")
    ap.add_argument("--since", default=None,
                    help="ISO ts UTC: conta solo record con ts >= since")
    args = ap.parse_args()

    path = os.path.join(args.root, "data", "ocr_read_stats.jsonl")
    now = datetime.now().strftime("%m-%d %H:%M")

    if not os.path.exists(path):
        print(f"[OCR-STATS {now}] nessun dato ancora (file assente) — "
              f"il bot non ha ancora letto risorse post-restart")
        return

    n_read = n_with_fb = n_tko = dia_ko = 0
    per_res: Counter = Counter()
    per_inst: Counter = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if args.since and (d.get("ts") or "") < args.since:
                continue
            n_read += 1
            fb = d.get("fallback") or []
            if fb:
                n_with_fb += 1
                per_inst[d.get("instance", "?")] += 1
                for r in fb:
                    per_res[r] += 1
            if d.get("tutte_ko"):
                n_tko += 1
            if not d.get("diamanti_ok", True):
                dia_ko += 1

    if n_read == 0:
        print(f"[OCR-STATS {now}] 0 letture nel periodo")
        return

    pct = n_with_fb / n_read * 100.0
    res_str = " ".join(f"{r}={per_res[r]}" for r in _RES if per_res[r]) or "-"
    top_str = " ".join(f"{i}={c}" for i, c in per_inst.most_common(3)) or "-"
    print(f"[OCR-STATS {now}] letture={n_read} | "
          f"con-fallback={n_with_fb} ({pct:.0f}%) | tutte_ko={n_tko} | "
          f"dia_ko={dia_ko} | risorse[{res_str}] | top-istanza[{top_str}]")


if __name__ == "__main__":
    main()
