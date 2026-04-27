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


def _cicli_path() -> Path:
    return _telemetry_root() / "cicli.json"


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


def detect_anomaly_patterns(events: list) -> dict:
    """
    Step 8 — pattern matcher multi-evento. Identifica sequenze problematiche
    che un singolo evento non rivela.

    Pattern rilevati:
      - adb_cascade               : 3+ abort/adb_unhealthy entro 5min (stessa istanza)
      - rifornimento_skip_chain   : 3+ skip rifornimento consecutivi (stessa istanza)
      - task_timeout_recurring    : 2+ task con duration > 2× p95 (stesso task)
      - home_stab_loop            : 3+ home_stab_timeout entro 30min (stessa istanza)

    Ritorna dict {pattern_name: [{instance|task, count, ts_start, ts_end,
                                   event_ids: [...], severity: low|med|high}]}
    """
    out: dict = {
        "adb_cascade":             [],
        "rifornimento_skip_chain": [],
        "task_timeout_recurring":  [],
        "home_stab_loop":          [],
    }
    if not events:
        return out

    # Group per istanza, ordinati per ts_start
    by_inst: dict = {}
    by_task: dict = {}
    for ev in sorted(events, key=lambda e: e.ts_start):
        by_inst.setdefault(ev.instance, []).append(ev)
        by_task.setdefault(ev.task, []).append(ev)

    # ── Pattern 1: ADB cascade ────────────────────────────────────────────────
    for inst, evs in by_inst.items():
        problematici = [
            e for e in evs
            if ANOM_ADB_UNHEALTHY in e.anomalies or e.outcome == OUTCOME_ABORT
        ]
        # Sliding window 5 min
        i = 0
        while i < len(problematici):
            window_start = problematici[i]
            try:
                t_start = _iso_to_epoch(window_start.ts_start)
            except Exception:
                i += 1
                continue
            j = i
            while j < len(problematici):
                try:
                    t_j = _iso_to_epoch(problematici[j].ts_start)
                except Exception:
                    break
                if t_j - t_start > 300:
                    break
                j += 1
            count = j - i
            if count >= 3:
                window = problematici[i:j]
                out["adb_cascade"].append({
                    "instance":   inst,
                    "count":      count,
                    "ts_start":   window[0].ts_start,
                    "ts_end":     window[-1].ts_end,
                    "event_ids":  [e.event_id for e in window],
                    "severity":   "high" if count >= 5 else "med",
                })
                i = j  # skip overlap, no doppi conteggi
            else:
                i += 1

    # ── Pattern 2: rifornimento_skip_chain ────────────────────────────────────
    for inst, evs in by_inst.items():
        rif_evs = [e for e in evs if e.task == "rifornimento"]
        skip_run = 0
        chain_start: Optional[TaskTelemetry] = None
        chain_events: list = []
        for ev in rif_evs:
            is_skip = (
                ev.outcome == OUTCOME_SKIP
                or (isinstance(ev.output, dict)
                    and ev.output.get("spedizioni", -1) == 0)
            )
            if is_skip:
                if skip_run == 0:
                    chain_start = ev
                    chain_events = [ev]
                else:
                    chain_events.append(ev)
                skip_run += 1
            else:
                if skip_run >= 3 and chain_start:
                    out["rifornimento_skip_chain"].append({
                        "instance":   inst,
                        "count":      skip_run,
                        "ts_start":   chain_start.ts_start,
                        "ts_end":     chain_events[-1].ts_end,
                        "event_ids":  [e.event_id for e in chain_events],
                        "severity":   "med" if skip_run < 5 else "high",
                    })
                skip_run = 0
                chain_start = None
                chain_events = []
        # Catena ancora aperta a fine eventi
        if skip_run >= 3 and chain_start:
            out["rifornimento_skip_chain"].append({
                "instance":   inst,
                "count":      skip_run,
                "ts_start":   chain_start.ts_start,
                "ts_end":     chain_events[-1].ts_end,
                "event_ids":  [e.event_id for e in chain_events],
                "severity":   "med" if skip_run < 5 else "high",
            })

    # ── Pattern 3: task_timeout_recurring ─────────────────────────────────────
    # Threshold basato su mediana × 3 (più robusto di p95 quando outliers
    # contaminano la distribuzione: p95 di [50,50,50,50,50,300,300,300]=300).
    for task_name, evs in by_task.items():
        durs = [e.duration_s for e in evs if e.duration_s > 0]
        if len(durs) < 5:
            continue
        median = _percentile(durs, 50)
        threshold = max(30.0, median * 3.0)  # min 30s, sotto è rumore
        outliers = [e for e in evs if e.duration_s > threshold]
        if len(outliers) >= 2:
            out["task_timeout_recurring"].append({
                "task":           task_name,
                "count":          len(outliers),
                "threshold_s":    round(threshold, 1),
                "median_s":       round(median, 1),
                "max_observed_s": round(max(e.duration_s for e in outliers), 1),
                "event_ids":      [e.event_id for e in outliers[:5]],
                "severity":       "high" if len(outliers) >= 5 else "med",
            })

    # ── Pattern 4: home_stab_loop ─────────────────────────────────────────────
    # Anomaly tag canonico (ora non emesso ma riserva il pattern)
    for inst, evs in by_inst.items():
        loops = [e for e in evs if ANOM_HOME_TIMEOUT in e.anomalies]
        i = 0
        while i < len(loops):
            try:
                t_start = _iso_to_epoch(loops[i].ts_start)
            except Exception:
                i += 1
                continue
            j = i
            while j < len(loops):
                try:
                    t_j = _iso_to_epoch(loops[j].ts_start)
                except Exception:
                    break
                if t_j - t_start > 1800:  # 30 min window
                    break
                j += 1
            count = j - i
            if count >= 3:
                window = loops[i:j]
                out["home_stab_loop"].append({
                    "instance":   inst,
                    "count":      count,
                    "ts_start":   window[0].ts_start,
                    "ts_end":     window[-1].ts_end,
                    "event_ids":  [e.event_id for e in window],
                    "severity":   "med",
                })
                i = j
            else:
                i += 1

    return out


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

    # Step 8 — Pattern detector multi-evento
    rollup["patterns_detected"] = detect_anomaly_patterns(events)

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
# Cicli persistenti (Step bonus — scritti dal bot, no parsing log volatili)
# ==============================================================================

_CICLI_RETENTION = 100  # ultimi N cicli mantenuti su disco
_CICLI_LOCK = threading.Lock()

# WU48 — Numerazione globale crescente. Il counter ciclo del bot riparte da 1
# ad ogni restart, causando duplicati visivi nello storico (3× CICLO 1 stale).
# La numerazione globale (numero_g) cresce monotona attraverso tutti i restart.
# Run ID = timestamp boot del processo (singleton per-process).
_RUN_ID: Optional[str] = None
_RUN_LOCK = threading.Lock()


def _get_run_id() -> str:
    """Singleton run_id per il processo bot corrente. Boot ts UTC."""
    global _RUN_ID
    with _RUN_LOCK:
        if _RUN_ID is None:
            _RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return _RUN_ID


def _next_numero_globale(cicli: List[dict]) -> int:
    """Calcola il prossimo numero ciclo globale (max esistente + 1)."""
    return max((int(c.get("numero", 0)) for c in cicli), default=0) + 1


def _read_cicli_raw() -> List[dict]:
    """Legge cicli.json. Failsafe (file mancante/corrotto → [])."""
    try:
        path = _cicli_path()
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("cicli", []) if isinstance(d, dict) else []
    except Exception:
        return []


def _write_cicli_raw(cicli: List[dict]) -> bool:
    """Atomic write cicli.json. Failsafe."""
    try:
        path = _cicli_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # FIFO retention: tieni gli ultimi N
        tail = cicli[-_CICLI_RETENTION:] if len(cicli) > _CICLI_RETENTION else cicli
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"cicli": tail}, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_cicli() -> List[dict]:
    """
    API pubblica: ritorna lista cicli persistiti, ordinati cronologicamente.

    Schema entry:
      {
        "numero": int,                 # numero ciclo (può ripartire da 1 dopo restart)
        "start_ts": ISO,
        "end_ts": ISO | None,
        "durata_s": int,
        "completato": bool,
        "istanze": {
          nome: {"start_ts": ISO, "end_ts": ISO|None, "durata_s": int, "esito": str}
        }
      }
    """
    return _read_cicli_raw()


def record_cicle_start(numero_locale: int) -> None:
    """
    Apri nuovo ciclo. Chiamato da main.py al log 'MAIN CICLO N'.

    `numero_locale` è il counter del bot (riparte da 1 ad ogni restart).
    Persistiamo `numero` GLOBALE crescente (max esistente + 1) per evitare
    duplicati visivi nello storico cicli (WU48).
    """
    try:
        with _CICLI_LOCK:
            cicli = _read_cicli_raw()

            # WU48 — auto-close cicli stale dello stesso run/precedenti.
            # Se ci sono cicli IN CORSO mai chiusi (restart bot mid-ciclo),
            # marcali come 'aborted' invece di lasciarli IN CORSO perpetui.
            for c in cicli:
                if not c.get("completato") and not c.get("aborted"):
                    c["aborted"]    = True
                    c["completato"] = True  # rimuove dal pool "in corso"
                    if not c.get("end_ts"):
                        c["end_ts"] = _iso_now()

            cicli.append({
                "numero":     _next_numero_globale(cicli),
                "run_id":     _get_run_id(),
                "run_local":  int(numero_locale),
                "start_ts":   _iso_now(),
                "end_ts":     None,
                "durata_s":   0,
                "completato": False,
                "istanze":    {},
            })
            _write_cicli_raw(cicli)
    except Exception:
        pass


def _find_current_cicle(cicli: List[dict]) -> Optional[dict]:
    """Trova ciclo attivo del run corrente (l'ultimo aperto, run_id matching)."""
    run_id = _get_run_id()
    for c in reversed(cicli):
        if c.get("run_id") == run_id and not c.get("completato"):
            return c
    return None


def record_cicle_end(numero_locale: int = -1) -> None:
    """
    Chiudi ciclo corrente. Chiamato a 'MAIN Ciclo N completato'.
    Match su run_id corrente (non sul numero, che ora è globale).
    """
    try:
        with _CICLI_LOCK:
            cicli = _read_cicli_raw()
            if not cicli:
                return
            current = _find_current_cicle(cicli)
            if not current:
                return
            current["end_ts"]     = _iso_now()
            current["completato"] = True
            try:
                current["durata_s"] = max(0, int(
                    _iso_to_epoch(current["end_ts"]) -
                    _iso_to_epoch(current["start_ts"])
                ))
            except Exception:
                current["durata_s"] = 0
            _write_cicli_raw(cicli)
    except Exception:
        pass


def record_istanza_tick_start(istanza: str) -> None:
    """Registra inizio tick istanza nel ciclo del run corrente."""
    try:
        with _CICLI_LOCK:
            cicli = _read_cicli_raw()
            current = _find_current_cicle(cicli)
            if not current:
                return
            istanze = current.setdefault("istanze", {})
            if istanza not in istanze:
                istanze[istanza] = {
                    "start_ts": _iso_now(),
                    "end_ts":   None,
                    "durata_s": 0,
                    "esito":    "running",
                }
                _write_cicli_raw(cicli)
    except Exception:
        pass


def record_istanza_tick_end(istanza: str, esito: str = "ok") -> None:
    """Registra fine tick istanza nel ciclo del run corrente."""
    try:
        with _CICLI_LOCK:
            cicli = _read_cicli_raw()
            current = _find_current_cicle(cicli)
            if not current:
                return
            info = (current.get("istanze") or {}).get(istanza)
            if not info or info.get("end_ts"):
                return
            info["end_ts"] = _iso_now()
            info["esito"]  = esito
            try:
                info["durata_s"] = max(0, int(
                    _iso_to_epoch(info["end_ts"]) -
                    _iso_to_epoch(info["start_ts"])
                ))
            except Exception:
                info["durata_s"] = 0
            _write_cicli_raw(cicli)
    except Exception:
        pass


def backfill_cicli_from_botlog(paths: List[Path]) -> int:
    """
    Backfill one-shot da bot.log per popolare cicli.json con dati storici.
    Idempotente: dedup su (numero, start_ts).

    Pattern bot.log:
      [HH:MM:SS] MAIN CICLO N — [...]
      [HH:MM:SS] FAU_XX [LAUNCHER] [FAU_XX] reset pre-ciclo ...
      [HH:MM:SS] MAIN --- Istanza FAU_XX completata ---
      [HH:MM:SS] MAIN Ciclo N completato — sleep ...

    Args:
        paths: lista bot.log da scandire (es. [bot.log.bak, bot.log])
    Returns:
        Numero cicli aggiunti.
    """
    import re as _re
    re_cycle_start = _re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+MAIN CICLO (\d+)")
    re_cycle_end   = _re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+MAIN Ciclo (\d+) completato")
    re_ist_start   = _re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+(\S+)\s+\[LAUNCHER\]\s+\[\S+\]\s+reset pre-ciclo")
    re_ist_end     = _re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+MAIN --- Istanza (\S+) completata ---")

    today_iso = datetime.now().date().isoformat()
    def _hhmm_to_iso(hhmm: str) -> str:
        return f"{today_iso}T{hhmm}"

    parsed: List[dict] = []
    current: Optional[dict] = None
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.startswith("["):
                        continue
                    m = re_cycle_start.match(line)
                    if m:
                        current = {
                            "numero":     int(m.group(2)),
                            "start_ts":   _hhmm_to_iso(m.group(1)),
                            "end_ts":     None,
                            "durata_s":   0,
                            "completato": False,
                            "istanze":    {},
                        }
                        parsed.append(current)
                        continue
                    m = re_cycle_end.match(line)
                    if m and current and current["numero"] == int(m.group(2)):
                        ts = _hhmm_to_iso(m.group(1))
                        current["end_ts"]     = ts
                        current["completato"] = True
                        try:
                            current["durata_s"] = max(0, int(
                                _iso_to_epoch(ts) - _iso_to_epoch(current["start_ts"])
                            ))
                        except Exception:
                            current["durata_s"] = 0
                        continue
                    if not current:
                        continue
                    m = re_ist_start.match(line)
                    if m:
                        nome = m.group(2)
                        if nome not in current["istanze"]:
                            current["istanze"][nome] = {
                                "start_ts": _hhmm_to_iso(m.group(1)),
                                "end_ts":   None,
                                "durata_s": 0,
                                "esito":    "running",
                            }
                        continue
                    m = re_ist_end.match(line)
                    if m:
                        nome = m.group(2)
                        info = current["istanze"].get(nome)
                        if info and not info["end_ts"]:
                            ts = _hhmm_to_iso(m.group(1))
                            info["end_ts"] = ts
                            info["esito"]  = "ok"
                            try:
                                info["durata_s"] = max(0, int(
                                    _iso_to_epoch(ts) - _iso_to_epoch(info["start_ts"])
                                ))
                            except Exception:
                                info["durata_s"] = 0
        except Exception:
            continue

    # WU48 — Numerazione globale crescente al merge.
    # Il backfill estrae `run_local` (numero locale del bot per restart),
    # poi riassegna `numero` globale crescente al merge in cicli.json.
    with _CICLI_LOCK:
        existing = _read_cicli_raw()
        # Chiave di dedup: start_ts (univoco temporalmente)
        existing_starts = {c.get("start_ts") for c in existing}
        added_entries = []
        for p in parsed:
            if p["start_ts"] in existing_starts:
                continue
            # Sposta numero (locale del bot) in run_local
            p["run_local"] = p.pop("numero", 0)
            p["run_id"]    = "backfill"  # marker per cicli da bot.log
            added_entries.append(p)
            existing_starts.add(p["start_ts"])

        if not added_entries:
            return 0

        # Merge + sort per start_ts + rinumera GLOBALE crescente
        existing.extend(added_entries)
        existing.sort(key=lambda x: x.get("start_ts", ""))
        for i, c in enumerate(existing, start=1):
            c["numero"] = i
        _write_cicli_raw(existing)
        return len(added_entries)


def renumber_cicli_globally() -> int:
    """
    Manutenzione: rinumera tutti i cicli in cicli.json con numerazione
    globale crescente per start_ts. Utile dopo migration legacy.

    Returns:
        Numero totale cicli rinumerati.
    """
    try:
        with _CICLI_LOCK:
            cicli = _read_cicli_raw()
            if not cicli:
                return 0
            cicli.sort(key=lambda x: x.get("start_ts", ""))
            for i, c in enumerate(cicli, start=1):
                # Preserva il numero locale se non già fatto
                if "run_local" not in c:
                    c["run_local"] = c.get("numero", 0)
                c["numero"] = i
            _write_cicli_raw(cicli)
            return len(cicli)
    except Exception:
        return 0


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
