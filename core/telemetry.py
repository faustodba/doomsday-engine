# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/telemetry.py                    Issue #53 — Step 1
#
#  Telemetria task standardizzata: schema + storage 3-tier (events/rollup/live).
#
#  RESPONSABILITÀ
#    • Definire schema TaskTelemetry (un evento = un task eseguito)
#    • Persistere eventi append-only in events_YYYY-MM-DD.jsonl (retention 30gg)
#    • Esporre helper per generare event_id, ts ISO, anomaly tagging
#    • Garantire scrittura atomica e thread-safe (più istanze → un solo writer)
#
#  STORAGE LAYOUT
#    data/telemetry/
#    ├── events/events_YYYY-MM-DD.jsonl   (1 riga = 1 TaskTelemetry, retention 30gg)
#    ├── rollup/rollup_YYYY-MM-DD.json    (Step 4 — daily aggregate, retention 365gg)
#    └── live.json                         (Step 5 — rolling 24h, refresh 60s)
#
#  COESISTENZA
#    Questo modulo è isolato: importarlo NON cambia il comportamento del bot.
#    Step 2 aggiungerà l'hook `record(event)` chiamato dall'orchestrator.
#
#  USO TIPICO (Step 2 — wrapper)
#      ev = TaskTelemetry.start(task="raccolta", instance="FAU_00", cycle=14)
#      ...                                       # esecuzione task
#      ev.finish(success=True, msg="4 squadre", outcome="ok",
#                output={"squadre_inviate": 4})
#      record(ev)
# ==============================================================================

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


# ==============================================================================
# Path resolver (coerente con main.py / orchestrator)
# ==============================================================================

def _telemetry_root() -> Path:
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "telemetry"


def _events_dir() -> Path:
    return _telemetry_root() / "events"


def _rollup_dir() -> Path:
    return _telemetry_root() / "rollup"


def _live_path() -> Path:
    return _telemetry_root() / "live.json"


# ==============================================================================
# Outcome canonici
# ==============================================================================

OUTCOME_OK     = "ok"
OUTCOME_SKIP   = "skip"
OUTCOME_FAIL   = "fail"
OUTCOME_ABORT  = "abort"
OUTCOME_NO_OP  = "no_op"

_VALID_OUTCOMES = {OUTCOME_OK, OUTCOME_SKIP, OUTCOME_FAIL, OUTCOME_ABORT, OUTCOME_NO_OP}


# ==============================================================================
# Anomaly tags canonici (estendibile)
# ==============================================================================

ANOM_ADB_UNHEALTHY     = "adb_unhealthy"
ANOM_ADB_CASCADE       = "adb_cascade"
ANOM_HOME_TIMEOUT      = "home_stab_timeout"
ANOM_OCR_FAIL          = "ocr_fail"
ANOM_TEMPLATE_NOT_FOUND = "template_not_found"
ANOM_BANNER_UNMATCHED   = "banner_unmatched"
ANOM_FOREGROUND_RECOV   = "foreground_recovery"
ANOM_RETRY              = "retry"


# ==============================================================================
# Schema TaskTelemetry
# ==============================================================================

@dataclass
class TaskTelemetry:
    """
    Un evento = un'esecuzione di un task in un tick.

    Campi obbligatori in scrittura:
      event_id, ts_start, ts_end, duration_s, task, instance, cycle,
      success, outcome, msg, output, anomalies, retry_count

    Costruzione tipica via TaskTelemetry.start(...) + .finish(...).
    """
    event_id:     str           = ""
    ts_start:     str           = ""    # ISO8601 UTC
    ts_end:       str           = ""    # ISO8601 UTC
    duration_s:   float         = 0.0
    task:         str           = ""
    instance:     str           = ""
    cycle:        int           = 0
    success:      bool          = False
    outcome:      str           = OUTCOME_NO_OP
    msg:          str           = ""
    output:       dict          = field(default_factory=dict)
    anomalies:    list          = field(default_factory=list)
    retry_count:  int           = 0

    # ── factory ────────────────────────────────────────────────────────────────
    @classmethod
    def start(cls, *, task: str, instance: str, cycle: int = 0) -> "TaskTelemetry":
        return cls(
            event_id  = _short_uuid(),
            ts_start  = _iso_now(),
            task      = task,
            instance  = instance,
            cycle     = int(cycle),
        )

    # ── chiusura evento ────────────────────────────────────────────────────────
    def finish(
        self,
        *,
        success:     bool,
        outcome:     str            = "",
        msg:         str            = "",
        output:      Optional[dict] = None,
        anomalies:   Optional[list] = None,
        retry_count: int            = 0,
    ) -> "TaskTelemetry":
        self.ts_end = _iso_now()
        try:
            self.duration_s = round(
                _iso_to_epoch(self.ts_end) - _iso_to_epoch(self.ts_start), 3
            )
        except Exception:
            self.duration_s = 0.0
        self.success     = bool(success)
        self.outcome     = outcome if outcome in _VALID_OUTCOMES else (
            OUTCOME_OK if success else OUTCOME_FAIL
        )
        self.msg         = (msg or "")[:200]
        self.output      = dict(output or {})
        # Merge anomalies — preserve quelle aggiunte via add_anomaly() prima di finish()
        if anomalies:
            for tag in anomalies:
                if tag and tag not in self.anomalies:
                    self.anomalies.append(tag)
        self.retry_count = int(retry_count)
        return self

    def add_anomaly(self, tag: str) -> None:
        if tag and tag not in self.anomalies:
            self.anomalies.append(tag)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)


# ==============================================================================
# Helpers
# ==============================================================================

def _short_uuid() -> str:
    """8 char hex stabilmente unico per evento — collisioni trascurabili."""
    return uuid.uuid4().hex[:8]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _iso_to_epoch(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def _today_utc_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ==============================================================================
# Writer events_YYYY-MM-DD.jsonl — append append-only thread-safe
# ==============================================================================

_WRITE_LOCK = threading.Lock()
_RETENTION_DAYS_EVENTS = 30


def record(event: TaskTelemetry) -> bool:
    """
    Append atomico di un TaskTelemetry alla jsonl del giorno corrente.
    Thread-safe (lock di processo). Failsafe: ritorna False senza alzare
    eccezioni — la telemetria non deve mai bloccare il bot.
    """
    try:
        events_dir = _events_dir()
        events_dir.mkdir(parents=True, exist_ok=True)
        path = events_dir / f"events_{_today_utc_str()}.jsonl"
        line = event.to_json_line() + "\n"
        with _WRITE_LOCK:
            # 'a' append text + buffering=1 → flush a ogni newline
            with open(path, "a", encoding="utf-8", buffering=1) as f:
                f.write(line)
        return True
    except Exception:
        # Telemetria silenziosa: non vogliamo che un disco pieno o un permesso
        # negato faccia fallire un task in produzione.
        return False


# ==============================================================================
# Retention sweep — chiamato manualmente (Step 4 lo collegherà al rollup daily)
# ==============================================================================

def cleanup_old_events(retention_days: int = _RETENTION_DAYS_EVENTS) -> int:
    """Rimuove events_*.jsonl più vecchi di N giorni. Ritorna numero file rimossi."""
    try:
        events_dir = _events_dir()
        if not events_dir.exists():
            return 0
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=retention_days)
        removed = 0
        for fp in events_dir.glob("events_*.jsonl"):
            stem = fp.stem.replace("events_", "")
            try:
                d = datetime.strptime(stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < cutoff:
                try:
                    fp.unlink()
                    removed += 1
                except Exception:
                    pass
        return removed
    except Exception:
        return 0


# ==============================================================================
# Reader low-level (utile per Step 6 / test)
# ==============================================================================

def iter_events(date_str: Optional[str] = None):
    """
    Yield TaskTelemetry letti da events_YYYY-MM-DD.jsonl.
    date_str=None → giorno corrente UTC.
    Saltiamo righe corrotte (no raise).
    """
    date_str = date_str or _today_utc_str()
    path = _events_dir() / f"events_{date_str}.jsonl"
    if not path.exists():
        return
    try:
        with open(path, "rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    yield TaskTelemetry(**d)
                except Exception:
                    continue
    except Exception:
        return


def iter_events_range(days: int = 1):
    """
    Yield TaskTelemetry degli ultimi `days` giorni (UTC), dal più vecchio al più recente.
    """
    today = datetime.now(timezone.utc).date()
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        yield from iter_events(d.isoformat())


# ==============================================================================
# Rollup engine (Step 4) — aggregazione giornaliera deterministica
# ==============================================================================

_RETENTION_DAYS_ROLLUP = 365


def _percentile(values: list, pct: float) -> float:
    """Percentile semplice (no numpy). pct in [0..100]. Vuoto → 0.0."""
    if not values:
        return 0.0
    sv = sorted(values)
    if pct <= 0:
        return float(sv[0])
    if pct >= 100:
        return float(sv[-1])
    k = (len(sv) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    frac = k - lo
    return float(sv[lo] * (1 - frac) + sv[hi] * frac)


def _aggregate_outputs(events_for_task: list) -> dict:
    """
    Aggrega TaskTelemetry.output di tutti gli eventi di un task.
    Regole:
      - bool=True  → counter "<key>_true"
      - bool=False → counter "<key>_false"
      - int/float  → somma "<key>_sum" + max "<key>_max"
      - str        → counter "<key>__<value>" (categorico)
      - list       → ignorato
    Failsafe: errori per-key non interrompono l'aggregazione.
    """
    agg: dict = {}
    for ev in events_for_task:
        out = ev.output or {}
        for k, v in out.items():
            try:
                # bool prima di int (bool è subclass di int)
                if isinstance(v, bool):
                    sub = "true" if v else "false"
                    key = f"{k}_{sub}"
                    agg[key] = int(agg.get(key, 0)) + 1
                elif isinstance(v, (int, float)):
                    agg[f"{k}_sum"] = agg.get(f"{k}_sum", 0) + v
                    agg[f"{k}_max"] = max(agg.get(f"{k}_max", v), v)
                elif isinstance(v, str) and v:
                    key = f"{k}__{v[:30]}"
                    agg[key] = int(agg.get(key, 0)) + 1
                # list/dict/None → skip
            except Exception:
                continue
    return agg


def compute_rollup(date_str: Optional[str] = None) -> dict:
    """
    Calcola il rollup giornaliero leggendo events_<date>.jsonl.

    Schema:
      {
        "date":             "YYYY-MM-DD",
        "computed_at":      "ISO ts",
        "totals":           {events, ok, skip, fail, abort, no_op},
        "per_task":         {task: {exec, ok, ok_pct, durations, anomalies, output_aggregates}},
        "per_instance":     {ist: {exec, tasks_breakdown, anomalies_total}},
        "anomalies_global": {tag: count}
      }
    """
    date_str = date_str or _today_utc_str()
    events = list(iter_events(date_str))
    rollup = _build_rollup_from_events(events)
    rollup["date"]        = date_str
    rollup["computed_at"] = _iso_now()
    return rollup


def save_rollup(rollup: dict, date_str: Optional[str] = None) -> bool:
    """Atomic write rollup_<date>.json. Failsafe."""
    try:
        date_str = date_str or rollup.get("date") or _today_utc_str()
        rollup_dir = _rollup_dir()
        rollup_dir.mkdir(parents=True, exist_ok=True)
        path = rollup_dir / f"rollup_{date_str}.json"
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rollup, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_rollup(date_str: Optional[str] = None) -> Optional[dict]:
    """Legge rollup_<date>.json. None se mancante o corrotto."""
    try:
        date_str = date_str or _today_utc_str()
        path = _rollup_dir() / f"rollup_{date_str}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def compute_and_save_rollup(date_str: Optional[str] = None) -> Optional[dict]:
    """Convenience: calcola + salva. Ritorna rollup o None se fallito."""
    r = compute_rollup(date_str)
    if save_rollup(r, date_str):
        return r
    return None


def cleanup_old_rollups(retention_days: int = _RETENTION_DAYS_ROLLUP) -> int:
    """Rimuove rollup_*.json più vecchi di N giorni. Ritorna numero file rimossi."""
    try:
        rollup_dir = _rollup_dir()
        if not rollup_dir.exists():
            return 0
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=retention_days)
        removed = 0
        for fp in rollup_dir.glob("rollup_*.json"):
            stem = fp.stem.replace("rollup_", "")
            try:
                d = datetime.strptime(stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < cutoff:
                try:
                    fp.unlink()
                    removed += 1
                except Exception:
                    pass
        return removed
    except Exception:
        return 0


# ==============================================================================
# Live writer (Step 5) — rolling 24h, refresh periodico
# ==============================================================================

_LIVE_REFRESH_DEFAULT_S = 60


def compute_live_24h(now: Optional[datetime] = None) -> dict:
    """
    Aggrega TaskTelemetry degli ultimi 24h (sliding window).
    Legge events di oggi + ieri (UTC) e filtra per ts >= now - 24h.

    Schema identico al rollup ma con campi window_start/window_end al posto di date.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    cutoff_iso = cutoff.isoformat()

    today_str     = now.date().isoformat()
    yesterday_str = (now.date() - timedelta(days=1)).isoformat()

    # Carica eventi da ieri + oggi, filtra per ts >= cutoff
    events = []
    for d_str in (yesterday_str, today_str):
        for ev in iter_events(d_str):
            if ev.ts_start >= cutoff_iso:
                events.append(ev)

    # Riusa _build_rollup_from_events (refactor minimale)
    rollup = _build_rollup_from_events(events)
    rollup.pop("date", None)
    rollup["window_start"] = cutoff_iso
    rollup["window_end"]   = now.isoformat()
    rollup["computed_at"]  = now.isoformat()
    return rollup


def _build_rollup_from_events(events: list) -> dict:
    """
    Logica core di aggregazione condivisa tra compute_rollup() e
    compute_live_24h(). Ritorna dict con totals/per_task/per_instance/anomalies.
    """
    rollup = {
        "totals":           {"events": 0, "ok": 0, "skip": 0, "fail": 0, "abort": 0, "no_op": 0},
        "per_task":         {},
        "per_instance":     {},
        "anomalies_global": {},
    }
    if not events:
        return rollup

    by_task: dict = {}
    by_inst: dict = {}
    for ev in events:
        by_task.setdefault(ev.task, []).append(ev)
        by_inst.setdefault(ev.instance, []).append(ev)
        rollup["totals"]["events"] += 1
        oc = ev.outcome if ev.outcome in rollup["totals"] else "no_op"
        rollup["totals"][oc] = rollup["totals"].get(oc, 0) + 1
        for tag in (ev.anomalies or []):
            rollup["anomalies_global"][tag] = rollup["anomalies_global"].get(tag, 0) + 1

    for task_name, evs in by_task.items():
        outc = {"ok": 0, "skip": 0, "fail": 0, "abort": 0, "no_op": 0}
        durs = []
        anom: dict = {}
        last_ts = ""
        last_err = ""
        for ev in evs:
            outc[ev.outcome] = outc.get(ev.outcome, 0) + 1
            if ev.duration_s > 0:
                durs.append(ev.duration_s)
            for tag in (ev.anomalies or []):
                anom[tag] = anom.get(tag, 0) + 1
            if ev.ts_end and ev.ts_end > last_ts:
                last_ts = ev.ts_end
            if ev.outcome in ("fail", "abort") and ev.msg:
                last_err = ev.msg[:80]
        exec_n = len(evs)
        ok_n = outc["ok"] + outc["skip"]
        rollup["per_task"][task_name] = {
            "exec":             exec_n,
            "ok":               outc["ok"],
            "skip":             outc["skip"],
            "fail":             outc["fail"],
            "abort":            outc["abort"],
            "no_op":            outc["no_op"],
            "ok_pct":           round(100.0 * ok_n / exec_n, 1) if exec_n else 0.0,
            "duration_avg_s":   round(sum(durs) / len(durs), 3) if durs else 0.0,
            "duration_p50":     round(_percentile(durs, 50), 3),
            "duration_p95":     round(_percentile(durs, 95), 3),
            "duration_max_s":   round(max(durs), 3) if durs else 0.0,
            "anomalies":        anom,
            "output_aggregates": _aggregate_outputs(evs),
            "last_ts":          last_ts,
            "last_err":         last_err or "—",
        }

    for ist_name, evs in by_inst.items():
        outc = {"ok": 0, "skip": 0, "fail": 0, "abort": 0, "no_op": 0}
        breakdown: dict = {}
        anom_total = 0
        for ev in evs:
            outc[ev.outcome] = outc.get(ev.outcome, 0) + 1
            breakdown[ev.task] = breakdown.get(ev.task, 0) + 1
            anom_total += len(ev.anomalies or [])
        rollup["per_instance"][ist_name] = {
            "exec":            len(evs),
            "ok":              outc["ok"],
            "skip":            outc["skip"],
            "fail":            outc["fail"],
            "abort":           outc["abort"],
            "no_op":           outc["no_op"],
            "tasks_breakdown": breakdown,
            "anomalies_total": anom_total,
        }

    return rollup


def save_live(live: dict) -> bool:
    """Atomic write data/telemetry/live.json. Failsafe."""
    try:
        path = _live_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(live, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_live() -> Optional[dict]:
    """Legge data/telemetry/live.json. None se mancante o corrotto."""
    try:
        path = _live_path()
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def compute_and_save_live() -> Optional[dict]:
    """Convenience: calcola + salva live.json. Ritorna dict o None se fallito."""
    live = compute_live_24h()
    if save_live(live):
        return live
    return None


def backfill_from_logs(
    logs_dir: Path,
    since_iso: Optional[str] = None,
    until_iso: Optional[str] = None,
) -> dict:
    """
    Step 7 — backfill retroattivo eventi telemetry dai logs/FAU_*.jsonl.

    Estrae coppie "Orchestrator: avvio task 'X'" + "...completato/fallito"
    e genera TaskTelemetry storici, scritti in events_<date>.jsonl.

    Idempotente: dedup su (ts_start, task, instance) — re-eseguibile senza
    duplicati. Output: dict con statistiche {generated, deduped, files_scanned}.

    Limiti inerenti (i log non contengono):
      - output strutturato (Step 3 attivo solo da bot restart in poi) → output={}
      - cycle preciso → cycle=0
      - retry_count → 0
      - anomalies inferite da pattern: ADB UNHEALTHY, eccezione

    Args:
        logs_dir: directory con FAU_*.jsonl e FauMorfeus.jsonl
        since_iso: limite inferiore (escluso prima); None = nessun limite
        until_iso: limite superiore (escluso dopo); None = nessun limite

    Returns:
        Statistiche operazione.
    """
    import re as _re
    re_start = _re.compile(r"Orchestrator: avvio task '([^']+)'")
    re_done  = _re.compile(
        r"Orchestrator: task '([^']+)' (?:completato|fallito) -- "
        r"success=(True|False)(?: msg='([^']*)')?"
    )
    re_adb_abort = _re.compile(
        r"Orchestrator: task '([^']+)' ADB UNHEALTHY"
    )
    re_exc = _re.compile(
        r"Orchestrator: task '([^']+)' -- eccezione: (.+)"
    )

    stats = {
        "files_scanned":  0,
        "events_parsed":  0,
        "events_written": 0,
        "deduped":        0,
        "errors":         0,
    }

    # Step A: pre-carica fingerprint eventi esistenti per dedup
    existing_fp: set = set()
    events_dir = _events_dir()
    events_dir.mkdir(parents=True, exist_ok=True)
    for fp in events_dir.glob("events_*.jsonl"):
        try:
            with open(fp, "rb") as f:
                for raw in f:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        existing_fp.add((d.get("ts_start", ""), d.get("task", ""),
                                         d.get("instance", "")))
                    except Exception:
                        continue
        except Exception:
            stats["errors"] += 1

    # Step B: scansiona logs
    if not logs_dir.exists():
        return stats

    # Pending starts per (instance, task) — ts_start in attesa di end
    # Usiamo solo ULTIMO start: V6 sequenziale, no overlap
    pending: dict = {}

    def _maybe_in_range(ts: str) -> bool:
        if since_iso and ts < since_iso:
            return False
        if until_iso and ts > until_iso:
            return False
        return True

    def _emit(ev: TaskTelemetry):
        fp = (ev.ts_start, ev.task, ev.instance)
        if fp in existing_fp:
            stats["deduped"] += 1
            return
        if not _maybe_in_range(ev.ts_start):
            return
        # Append direttamente al file events_<date>.jsonl
        try:
            date_str = ev.ts_start[:10]  # YYYY-MM-DD
            path = events_dir / f"events_{date_str}.jsonl"
            with _WRITE_LOCK:
                with open(path, "a", encoding="utf-8", buffering=1) as f:
                    f.write(ev.to_json_line() + "\n")
            existing_fp.add(fp)
            stats["events_written"] += 1
        except Exception:
            stats["errors"] += 1

    for fp in sorted(logs_dir.glob("*.jsonl")):
        if fp.name.endswith(".bak.jsonl"):
            continue
        stats["files_scanned"] += 1
        try:
            with open(fp, "rb") as f:
                for raw in f:
                    try:
                        d = json.loads(raw.decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    ts = d.get("ts", "")
                    ist = d.get("instance", "")
                    msg = d.get("msg", "")
                    if not (ts and ist and msg):
                        continue

                    # Match start
                    m = re_start.match(msg)
                    if m:
                        task = m.group(1)
                        pending[(ist, task)] = ts
                        continue

                    # Match completion (normal)
                    m = re_done.match(msg)
                    if m:
                        task    = m.group(1)
                        success = m.group(2) == "True"
                        body    = m.group(3) or ""
                        ts_start = pending.pop((ist, task), None)
                        if not ts_start:
                            continue  # orphan end → skip
                        stats["events_parsed"] += 1
                        # Outcome heuristic
                        if success:
                            # 'skipped' non differenziato nei log — consideriamo ok
                            # eccezione: msg contains 'skip' o 'disabilitato'
                            outc = OUTCOME_SKIP if (
                                "skip" in body.lower() or "disabilitato" in body.lower()
                                or "nessuna" in body.lower()
                            ) else OUTCOME_OK
                        else:
                            outc = OUTCOME_FAIL
                        ev = TaskTelemetry.start(task=task, instance=ist, cycle=0)
                        ev.ts_start = ts_start
                        ev.ts_end   = ts
                        try:
                            ev.duration_s = round(
                                _iso_to_epoch(ts) - _iso_to_epoch(ts_start), 3
                            )
                        except Exception:
                            ev.duration_s = 0.0
                        ev.success = success
                        ev.outcome = outc
                        ev.msg     = body[:200]
                        if "eccezione" in body.lower():
                            ev.anomalies.append("retry")
                        _emit(ev)
                        continue

                    # Match ADB abort (no end-event, special path in orchestrator)
                    m = re_adb_abort.match(msg)
                    if m:
                        task = m.group(1)
                        ts_start = pending.pop((ist, task), None)
                        if not ts_start:
                            continue
                        stats["events_parsed"] += 1
                        ev = TaskTelemetry.start(task=task, instance=ist, cycle=0)
                        ev.ts_start = ts_start
                        ev.ts_end   = ts
                        try:
                            ev.duration_s = round(
                                _iso_to_epoch(ts) - _iso_to_epoch(ts_start), 3
                            )
                        except Exception:
                            ev.duration_s = 0.0
                        ev.success = False
                        ev.outcome = OUTCOME_ABORT
                        ev.msg     = "ADB UNHEALTHY (backfill)"
                        ev.anomalies.append(ANOM_ADB_UNHEALTHY)
                        _emit(ev)
                        continue

                    # Match generic exception
                    m = re_exc.match(msg)
                    if m:
                        task = m.group(1)
                        exc_msg = m.group(2)
                        ts_start = pending.pop((ist, task), None)
                        if not ts_start:
                            continue
                        stats["events_parsed"] += 1
                        ev = TaskTelemetry.start(task=task, instance=ist, cycle=0)
                        ev.ts_start = ts_start
                        ev.ts_end   = ts
                        try:
                            ev.duration_s = round(
                                _iso_to_epoch(ts) - _iso_to_epoch(ts_start), 3
                            )
                        except Exception:
                            ev.duration_s = 0.0
                        ev.success = False
                        ev.outcome = OUTCOME_FAIL
                        ev.msg     = f"eccezione: {exc_msg}"[:200]
                        _emit(ev)
        except Exception:
            stats["errors"] += 1

    return stats


def live_writer_loop(stop_event: "threading.Event",
                     refresh_s: int = _LIVE_REFRESH_DEFAULT_S) -> None:
    """
    Loop daemon per aggiornare live.json ogni `refresh_s` secondi.
    Hookable da main.py:
        threading.Thread(target=live_writer_loop,
                         args=(stop_event, 60),
                         name="LiveTelemetry", daemon=True).start()

    Failsafe: ogni iterazione cattura eccezioni — loop non termina mai
    spontaneamente (solo via stop_event).
    """
    # Una passata immediata all'avvio così la dashboard non aspetta refresh_s
    try:
        compute_and_save_live()
    except Exception:
        pass
    while not stop_event.wait(refresh_s):
        try:
            compute_and_save_live()
        except Exception:
            pass


# ==============================================================================
# Self-test (eseguibile diretto)
# ==============================================================================

if __name__ == "__main__":
    # Prova rapida: scrive 3 eventi e li rilegge
    import tempfile

    tmp = tempfile.mkdtemp(prefix="tel_test_")
    os.environ["DOOMSDAY_ROOT"] = tmp
    print(f"[SELFTEST] root={tmp}")

    e1 = TaskTelemetry.start(task="raccolta", instance="FAU_00", cycle=1)
    time.sleep(0.05)
    e1.finish(success=True, outcome=OUTCOME_OK, msg="4 squadre",
              output={"squadre_inviate": 4})

    e2 = TaskTelemetry.start(task="rifornimento", instance="FAU_01", cycle=1)
    time.sleep(0.02)
    e2.add_anomaly(ANOM_OCR_FAIL)
    e2.finish(success=True, outcome=OUTCOME_OK, msg="2 spediz.",
              output={"qta_inviata": 1_500_000, "tassa_pct": 0.23})

    e3 = TaskTelemetry.start(task="arena", instance="FAU_02", cycle=1)
    e3.add_anomaly(ANOM_ADB_UNHEALTHY)
    e3.finish(success=False, outcome=OUTCOME_ABORT, msg="ADB cascade",
              retry_count=2)

    for ev in (e1, e2, e3):
        ok = record(ev)
        print(f"  record {ev.task:<15} {ev.outcome:<6} dur={ev.duration_s:.3f}s ok={ok}")

    print("[SELFTEST] readback:")
    for ev in iter_events():
        print(f"  {ev.task:<15} {ev.instance} dur={ev.duration_s:.3f}s "
              f"outcome={ev.outcome} anom={ev.anomalies}")
    print("[SELFTEST] done.")
