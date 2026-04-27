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
