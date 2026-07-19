#!/usr/bin/env python3
# ==============================================================================
#  DOOMSDAY ENGINE V6 — tools/verifica_fix_revisione.py
#
#  Sistema di monitoraggio anti-regressione per i fix della revisione 07/2026
#  (docs/revisione_bot_2026-07.md). Verifica che i fix implementati:
#    R-02  dashboard field-wipe (extra='allow')        [richiede restart DASHBOARD]
#    R-03  raccolta screenshot post-marcia prudente     [richiede restart BOT]
#    R-04  rifornimento invio confermato                [richiede restart BOT]
#    R-05  alleanza gate HOME skip()->fail()            [richiede restart BOT]
#    R-09  static fallback max_squadre/livello          [effettivo al prossimo load config]
#  NON introducano regressioni o peggioramenti di comportamento.
#
#  Due fonti dati (sola LETTURA, nessuna azione sul bot):
#    - Telemetry events JSONL   -> KPI strutturati per task (fail_rate, throughput)
#    - Log per-istanza JSONL    -> segnali specifici dei fix + ERROR/eccezioni
#
#  Modi:
#    --baseline   fotografa i KPI correnti (PRIMA del restart) in un file snapshot
#    --check      calcola i KPI correnti, li confronta con la baseline, emette
#                 un verdetto di regressione (exit 0 = ok, 1 = regressione)
#
#  Windows-safe: usa pathlib con path Windows (default C:\doomsday-engine-prod).
#  Eseguire con:  py -3.14 tools\verifica_fix_revisione.py --check
# ==============================================================================

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Console Windows: forza UTF-8 così accenti e simboli non diventano mojibake.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

DEFAULT_ROOT = Path(r"C:\doomsday-engine-prod")
SNAPSHOT_NAME = "verifica_fix_baseline.json"

# Segnali di log specifici dei fix: quando il fix ENTRA IN AZIONE il bot scrive
# questa riga. Contarle NON è una regressione: è la prova che il path del fix
# viene esercitato. Sono informativi.
FIX_SIGNALS = {
    "R-03": {
        "pattern": "esito prudente FALLITO",
        "desc": "raccolta: screenshot post-marcia mancante -> marcia FALLITA (prudente, no falso OK)",
        "task": "raccolta",
    },
    "R-04": {
        "pattern": "invio NON confermato",
        "desc": "rifornimento: pannello VAI ancora aperto -> invio non confermato (no doppio invio)",
        "task": "rifornimento",
    },
    "R-05": {
        "pattern": "Navigator non ha raggiunto HOME",
        "desc": "alleanza: gate HOME fallito -> fail() (ritenta al tick dopo, no rinvio 4h)",
        "task": "alleanza",
    },
}

# Task il cui throughput NON deve calare per colpa dei fix (metriche di
# regressione vere). Per ciascuno definiamo il campo output "produttivo".
THROUGHPUT_TASK = {
    "raccolta": "inviate",           # marce inviate
    "raccolta_chiusura": "inviate",
    "rifornimento": "spedizioni",    # spedizioni al master
    "alleanza": "rivendiche",        # claim raccolti
}

# Soglie di regressione (delta rispetto alla baseline, su tassi normalizzati
# per-run così il confronto è robusto al numero di cicli).
TOL_FAIL_RATE_PP = 10.0    # +10 punti % di fail_rate su un task = sospetto
TOL_THROUGHPUT_PCT = 25.0  # -25% di throughput medio/run = sospetto
TOL_ERROR_PER_H = 5.0      # +5 ERROR/ora rispetto alla baseline = sospetto


# ---------------------------------------------------------------------------
# Lettura dati
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _iter_events(root: Path, since: datetime, until: datetime | None = None):
    """Itera gli eventi telemetria nell'intervallo [since, until) (giorni multipli)."""
    ev_dir = root / "data" / "telemetry" / "events"
    if not ev_dir.is_dir():
        return
    # I file sono events_YYYY-MM-DD.jsonl: leggiamo dal giorno di `since` in poi.
    for fp in sorted(ev_dir.glob("events_*.jsonl")):
        try:
            day = datetime.strptime(fp.stem.replace("events_", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < since.date():
            continue
        if until is not None and day > until.date():
            continue
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(ev.get("ts_start", "") or ev.get("ts_end", ""))
            if ts is None or ts < since:
                continue
            if until is not None and ts >= until:
                continue
            yield ev


def _iter_log_lines(root: Path, since: datetime, until: datetime | None = None):
    """Itera le righe dei log per-istanza (JSONL) nell'intervallo [since, until)."""
    log_dir = root / "logs"
    if not log_dir.is_dir():
        return
    for fp in sorted(log_dir.glob("FAU_*.jsonl")):
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(rec.get("ts", ""))
            if ts is None or ts < since:
                continue
            if until is not None and ts >= until:
                continue
            yield rec


# ---------------------------------------------------------------------------
# Calcolo KPI
# ---------------------------------------------------------------------------

def compute_kpi(root: Path, since: datetime, until: datetime | None = None) -> dict:
    # --- da telemetria: per-task runs / outcome / throughput ---
    per_task = defaultdict(lambda: {"runs": 0, "ok": 0, "fail": 0, "skip": 0, "throughput": 0})
    for ev in _iter_events(root, since, until):
        t = ev.get("task")
        if not t:
            continue
        d = per_task[t]
        d["runs"] += 1
        oc = ev.get("outcome")
        if oc in ("ok", "fail", "skip"):
            d[oc] += 1
        if t in THROUGHPUT_TASK:
            val = (ev.get("output") or {}).get(THROUGHPUT_TASK[t], 0)
            if isinstance(val, (int, float)):
                d["throughput"] += val

    # --- dai log: segnali fix + ERROR + eccezioni ---
    signal_counts = {k: 0 for k in FIX_SIGNALS}
    signal_by_instance = {k: defaultdict(int) for k in FIX_SIGNALS}
    error_count = 0
    exception_count = 0
    first_ts = None
    last_ts = None
    for rec in _iter_log_lines(root, since, until):
        ts = _parse_ts(rec.get("ts", ""))
        if ts:
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts
        msg = rec.get("msg", "") or ""
        lvl = (rec.get("level", "") or "").upper()
        if lvl == "ERROR":
            error_count += 1
        if "Eccezione" in msg or "Traceback" in msg or "esegui_alleanza" in msg:
            if "Eccezione" in msg:
                exception_count += 1
        for k, spec in FIX_SIGNALS.items():
            if spec["pattern"] in msg:
                signal_counts[k] += 1
                signal_by_instance[k][rec.get("instance", "?")] += 1

    span_h = 0.0
    if first_ts and last_ts and last_ts > first_ts:
        span_h = (last_ts - first_ts).total_seconds() / 3600.0

    # normalizzazioni
    kpi_task = {}
    for t, d in sorted(per_task.items()):
        runs = d["runs"] or 1
        kpi_task[t] = {
            "runs": d["runs"],
            "ok": d["ok"],
            "fail": d["fail"],
            "skip": d["skip"],
            "fail_rate_pct": round(100.0 * d["fail"] / runs, 2),
            "throughput_tot": d["throughput"],
            "throughput_per_run": round(d["throughput"] / runs, 3),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_since": since.isoformat(),
        "window_until": until.isoformat() if until else None,
        "span_hours": round(span_h, 2),
        "tasks": kpi_task,
        "fix_signals": {
            k: {
                "count": signal_counts[k],
                "by_instance": dict(signal_by_instance[k]),
                "desc": FIX_SIGNALS[k]["desc"],
            }
            for k in FIX_SIGNALS
        },
        "error_count": error_count,
        "error_per_h": round(error_count / span_h, 2) if span_h else 0.0,
        "exception_count": exception_count,
    }


# ---------------------------------------------------------------------------
# Confronto / verdetto
# ---------------------------------------------------------------------------

def compare(baseline: dict, current: dict) -> list[str]:
    """Ritorna la lista di regressioni sospette (vuota = nessuna regressione)."""
    regressions = []
    b_tasks = baseline.get("tasks", {})
    c_tasks = current.get("tasks", {})

    for t, cur in c_tasks.items():
        base = b_tasks.get(t)
        if not base:
            continue
        # fail_rate peggiorato oltre tolleranza
        d_fr = cur["fail_rate_pct"] - base["fail_rate_pct"]
        if d_fr > TOL_FAIL_RATE_PP:
            regressions.append(
                f"[{t}] fail_rate {base['fail_rate_pct']}% -> {cur['fail_rate_pct']}% "
                f"(+{d_fr:.1f}pp > {TOL_FAIL_RATE_PP}pp)"
            )
        # throughput/run calato oltre tolleranza (solo se la baseline produceva)
        if t in THROUGHPUT_TASK and base["throughput_per_run"] > 0:
            drop_pct = 100.0 * (base["throughput_per_run"] - cur["throughput_per_run"]) / base["throughput_per_run"]
            if drop_pct > TOL_THROUGHPUT_PCT:
                regressions.append(
                    f"[{t}] throughput/run {base['throughput_per_run']} -> {cur['throughput_per_run']} "
                    f"(-{drop_pct:.0f}% > {TOL_THROUGHPUT_PCT}%)"
                )

    # ERROR/ora peggiorato
    d_err = current.get("error_per_h", 0.0) - baseline.get("error_per_h", 0.0)
    if d_err > TOL_ERROR_PER_H:
        regressions.append(
            f"[globale] ERROR/ora {baseline.get('error_per_h')} -> {current.get('error_per_h')} "
            f"(+{d_err:.1f}/h > {TOL_ERROR_PER_H}/h)"
        )
    # eccezioni: qualunque aumento è sospetto
    if current.get("exception_count", 0) > baseline.get("exception_count", 0):
        regressions.append(
            f"[globale] eccezioni {baseline.get('exception_count')} -> {current.get('exception_count')}"
        )
    return regressions


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(kpi: dict, baseline: dict | None = None, baseline_label: str = "baseline") -> None:
    print("=" * 74)
    print(f"VERIFICA FIX REVISIONE 07/2026  —  finestra da {kpi['window_since']}")
    print(f"span log: {kpi['span_hours']}h   generato: {kpi['generated_at']}")
    print("=" * 74)

    print("\n-- SEGNALI FIX (informativi: il path del fix è stato esercitato) --")
    for k, s in kpi["fix_signals"].items():
        inst = ", ".join(f"{i}:{n}" for i, n in sorted(s["by_instance"].items())) or "—"
        print(f"  {k}  count={s['count']:>3}   [{inst}]")
        print(f"       {s['desc']}")

    print("\n-- KPI PER TASK (regressione = fail_rate su / throughput giù) --")
    print(f"  {'task':<20} {'runs':>5} {'ok':>4} {'fail':>4} {'skip':>4} {'fail%':>6} {'thr/run':>8}")
    for t, d in kpi["tasks"].items():
        print(f"  {t:<20} {d['runs']:>5} {d['ok']:>4} {d['fail']:>4} {d['skip']:>4} "
              f"{d['fail_rate_pct']:>6} {d['throughput_per_run']:>8}")

    print(f"\n-- SALUTE GLOBALE --")
    print(f"  ERROR: {kpi['error_count']}  ({kpi['error_per_h']}/ora)   eccezioni: {kpi['exception_count']}")

    if baseline is not None:
        print("\n" + "=" * 74)
        regs = compare(baseline, kpi)
        if not regs:
            print(f"VERDETTO: ✅ nessuna regressione rilevata rispetto a {baseline_label}")
        else:
            print(f"VERDETTO: ⚠️  {len(regs)} REGRESSIONE/I SOSPETTA/E rispetto a {baseline_label}:")
            for r in regs:
                print(f"   - {r}")
        print("=" * 74)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Monitoraggio anti-regressione fix revisione 07/2026")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="root prod (default C:\\doomsday-engine-prod)")
    ap.add_argument("--hours", type=float, default=24.0, help="finestra ore all'indietro (default 24)")
    ap.add_argument("--baseline", action="store_true", help="salva snapshot baseline invece di confrontare")
    ap.add_argument(
        "--dod", action="store_true",
        help="confronto day-over-day: finestra corrente [now-hours,now] vs STESSA fascia oraria "
             "24h fa [now-24h-hours,now-24h] — elimina i falsi positivi da ciclo giornaliero "
             "(es. alleanza/rifornimento meno attivi di notte). Uso consigliato per il Monitor live."
    )
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    if args.dod:
        kpi = compute_kpi(args.root, since, until=now)
        y_since = since - timedelta(hours=24)
        y_until = now - timedelta(hours=24)
        y_kpi = compute_kpi(args.root, y_since, until=y_until)
        print_report(kpi, baseline=y_kpi, baseline_label="ieri stessa fascia oraria")
        return 1 if compare(y_kpi, kpi) else 0

    snap_path = args.root / "data" / SNAPSHOT_NAME

    kpi = compute_kpi(args.root, since)

    if args.baseline:
        snap_path.write_text(json.dumps(kpi, indent=1, ensure_ascii=False), encoding="utf-8")
        print_report(kpi, baseline=None)
        print(f"\n[baseline salvata] {snap_path}")
        return 0

    baseline = None
    if snap_path.is_file():
        try:
            baseline = json.loads(snap_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            baseline = None
    print_report(kpi, baseline=baseline)
    if baseline is None:
        print("\n[nota] nessuna baseline trovata: esegui prima --baseline (pre-restart).")
        return 0
    return 1 if compare(baseline, kpi) else 0


if __name__ == "__main__":
    sys.exit(main())
