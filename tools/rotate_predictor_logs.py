"""Rotazione dei file JSONL append-only del sistema predittivo.

WU168 (19/06) — `data/istanza_metrics.jsonl` e
`data/predictions/cycle_snapshots.jsonl` non hanno mai retention/rotazione:
crescita illimitata (4.3MB/5.572 righe e 6.3MB/3.649 righe dopo 45 giorni,
misurato in prod il 19/06). Questo tool sposta le righe più vecchie di
--days in un archivio mensile, senza toccare i consumer (i predittori
continuano a leggere solo il file live, più piccolo).

WU186 (02/07) — la rotazione era rimasta SOLO manuale (mai eseguita in prod:
istanza_metrics.jsonl a 5.4MB/6.619 righe il 02/07, nessun `data/archive/`).
Aggiunta `run_retention()` riutilizzabile, chiamata automaticamente 1×/die da
`dashboard/app.py::_predictor_retention_loop` con cutoff 60 giorni. Aggiunto
anche `data/predictions/scheduler_ab.jsonl` ai target (stesso problema,
nessuna retention nemmeno manuale).

Uso CLI:
    py -3.14 tools/rotate_predictor_logs.py                  # dry-run, 180gg
    py -3.14 tools/rotate_predictor_logs.py --days 60 --apply
    py -3.14 tools/rotate_predictor_logs.py --prod --apply

Uso programmatico:
    from tools.rotate_predictor_logs import run_retention
    run_retention(root=Path(...), days=60, apply=True)

Output: data/archive/<nome_file>_<YYYY-MM>.jsonl (una riga = un mese,
append se il file archivio esiste già — più mesi possono confluire nello
stesso archivio se eseguito raramente).

Sicurezza: scrittura atomica (tmp + os.replace) sul file live — sicuro
anche con il bot in esecuzione, perché ogni write del bot è un
open("a")/write/close discreto, non un handle persistente.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT_DEV  = Path(__file__).parent.parent
_ROOT_PROD = Path("C:/doomsday-engine-prod")

# (path relativo da root, campo timestamp da usare per il cutoff)
_TARGETS = [
    ("data/istanza_metrics.jsonl", "ts"),
    ("data/predictions/cycle_snapshots.jsonl", "ts"),
    ("data/predictions/cycle_accuracy.jsonl", "ts_end"),
    ("data/predictions/scheduler_ab.jsonl", "ts"),
]

DEFAULT_RETENTION_DAYS = 60


def _parse_ts(record: dict, field: str) -> datetime | None:
    raw = record.get(field)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def rotate_file(path: Path, ts_field: str, cutoff: datetime, apply: bool) -> dict:
    if not path.exists():
        return {"path": str(path), "skip": "non esiste"}

    kept: list[str] = []
    archived_by_month: dict[str, list[str]] = defaultdict(list)
    n_total = 0
    n_unparsed = 0

    with path.open(encoding="utf-8") as f:
        for line in f:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            n_total += 1
            try:
                rec = json.loads(line_stripped)
            except Exception:
                kept.append(line)  # riga corrotta: meglio tenerla visibile che perderla
                continue
            ts = _parse_ts(rec, ts_field)
            if ts is None:
                kept.append(line)
                n_unparsed += 1
                continue
            if ts < cutoff:
                month_key = ts.strftime("%Y-%m")
                archived_by_month[month_key].append(line)
            else:
                kept.append(line)

    n_archived = sum(len(v) for v in archived_by_month.values())
    result = {
        "path":          str(path),
        "n_total":       n_total,
        "n_kept":        len(kept),
        "n_archived":    n_archived,
        "n_unparsed_ts": n_unparsed,
        "months":        sorted(archived_by_month.keys()),
    }

    if not apply or n_archived == 0:
        return result

    archive_dir = path.parent.parent / "archive" if path.parent.name in ("predictions",) \
        else path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem  # es. "istanza_metrics" o "cycle_snapshots"

    for month_key, lines in archived_by_month.items():
        archive_path = archive_dir / f"{stem}_{month_key}.jsonl"
        with archive_path.open("a", encoding="utf-8") as af:
            af.writelines(lines)

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as kf:
        kf.writelines(kept)
    os.replace(tmp, path)

    return result


def run_retention(root: Path, days: int = DEFAULT_RETENTION_DAYS,
                   apply: bool = True) -> dict:
    """Esegue la rotazione su tutti i `_TARGETS` per `root`. Riutilizzabile
    sia da CLI (`main()`) sia da chiamanti programmatici (dashboard loop).

    Returns:
        {
          "cutoff": iso str,
          "days": int,
          "results": [ {path, n_total, n_kept, n_archived, months}, ... ],
          "any_archived": bool,
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    any_archived = False
    for rel_path, ts_field in _TARGETS:
        res = rotate_file(root / rel_path, ts_field, cutoff, apply)
        results.append(res)
        if res.get("months"):
            any_archived = True
    return {
        "cutoff": cutoff.isoformat(),
        "days": days,
        "results": results,
        "any_archived": any_archived,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=180,
                   help="righe più vecchie di N giorni vengono archiviate (default 180 da CLI; "
                        f"il loop automatico usa {DEFAULT_RETENTION_DAYS}gg)")
    p.add_argument("--prod", action="store_true",
                   help=f"opera su {_ROOT_PROD} invece della working copy dev")
    p.add_argument("--apply", action="store_true",
                   help="senza questo flag: solo report, nessuna scrittura (dry-run)")
    args = p.parse_args()

    root = _ROOT_PROD if args.prod else _ROOT_DEV

    print(f"Root: {root}")
    print(f"Cutoff: righe più vecchie di {args.days}gg")
    print(f"Modalità: {'APPLY (scrittura reale)' if args.apply else 'DRY-RUN (solo report)'}")
    print()

    out = run_retention(root, days=args.days, apply=args.apply)
    for rel_path, res in zip((t[0] for t in _TARGETS), out["results"]):
        if res.get("skip"):
            print(f"  {rel_path}: {res['skip']}")
            continue
        print(f"  {rel_path}")
        print(f"    totale={res['n_total']}  da_archiviare={res['n_archived']}  "
              f"restano={res['n_kept']}  ts_non_parsabile={res['n_unparsed_ts']}")
        if res["months"]:
            print(f"    mesi coinvolti: {', '.join(res['months'])}")

    if not args.apply and out["any_archived"]:
        print("\nDry-run: nessuna scrittura eseguita. Rilancia con --apply per applicare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
