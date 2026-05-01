# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/istanza_metrics.py
#
#  Persistenza metriche per-istanza per-ciclo: dataset analitico per stime
#  durata boot, tempi task, comportamento raccolta, predittore skip futuro.
#
#  Storage: data/istanza_metrics.jsonl (append-only)
#  Schema record:
#    {
#      "ts":          "2026-05-01T18:00:00+00:00",  ISO UTC fine ciclo istanza
#      "instance":    "FAU_07",
#      "cycle_id":    123,                            numero ciclo globale
#      "boot_home_s": 142.3,                          durata avvio -> HOME (None se cascade)
#      "tick_total_s": 487.2,                         durata totale tick (avvio -> chiusura)
#      "raccolta": {
#        "attive_pre":   0,                           slot occupati pre-tick
#        "attive_post":  4,                           slot occupati post-tick
#        "totali":       4,                           max squadre istanza
#        "invii": [                                   dettaglio per squadra inviata
#          {"tipo": "campo", "livello": 6, "cap_nodo": 1200000, "eta_marcia_s": 95}
#        ]
#      },
#      "task_durations_s": {                          per ogni task eseguito nel tick
#        "raccolta": 95.3, "donazione": 21.5, ...
#      },
#      "outcome": "ok" | "cascade" | "abort"
#    }
#
#  Best-effort: errori I/O silenziati per non rompere il bot.
# ==============================================================================

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_BUFFER_PER_INSTANCE: dict[str, dict[str, Any]] = {}


def _root_dir() -> Path:
    root = os.environ.get("DOOMSDAY_ROOT")
    if root:
        return Path(root)
    return Path(os.getcwd())


def _file_path() -> Path:
    p = _root_dir() / "data" / "istanza_metrics.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------
# Buffer building API — usata dai vari hook nel codice
# ------------------------------------------------------------------

def inizia_tick(instance: str, cycle_id: int = 0) -> None:
    """Inizializza buffer per il tick corrente di un'istanza."""
    with _lock:
        _BUFFER_PER_INSTANCE[instance] = {
            "instance": instance,
            "cycle_id": int(cycle_id),
            "ts_avvio": datetime.now(timezone.utc).isoformat(),
            "raccolta": {"invii": []},
            "task_durations_s": {},
        }


def imposta_boot_home(instance: str, secondi: float) -> None:
    """Hook launcher: dopo HOME raggiunto."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is not None:
            buf["boot_home_s"] = round(float(secondi), 1)


def imposta_raccolta_slot(instance: str, attive_pre: int = -1,
                          attive_post: int = -1, totali: int = -1) -> None:
    """Hook raccolta: imposta contatori slot pre/post tick."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        rac = buf.setdefault("raccolta", {"invii": []})
        if attive_pre >= 0:
            rac["attive_pre"] = int(attive_pre)
        if attive_post >= 0:
            rac["attive_post"] = int(attive_post)
        if totali >= 0:
            rac["totali"] = int(totali)


def aggiungi_invio_raccolta(instance: str, tipo: str, livello: int,
                            cap_nodo: int, eta_marcia_s: int) -> None:
    """Hook raccolta: aggiunge dettaglio invio singolo."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        buf.setdefault("raccolta", {"invii": []})["invii"].append({
            "tipo": tipo,
            "livello": int(livello),
            "cap_nodo": int(cap_nodo),
            "eta_marcia_s": int(eta_marcia_s),
        })


def imposta_task_duration(instance: str, task_name: str, secondi: float) -> None:
    """Hook orchestrator: durata di un task del tick."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        buf.setdefault("task_durations_s", {})[task_name] = round(float(secondi), 1)


def chiudi_tick(instance: str, outcome: str = "ok",
                tick_total_s: float | None = None) -> None:
    """Hook main: flush record su disco a fine tick istanza."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.pop(instance, None)
    if buf is None:
        return
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "instance": buf.get("instance", instance),
        "cycle_id": buf.get("cycle_id", 0),
        "outcome": str(outcome),
    }
    for k in ("boot_home_s", "raccolta", "task_durations_s"):
        if k in buf:
            record[k] = buf[k]
    if tick_total_s is not None:
        record["tick_total_s"] = round(float(tick_total_s), 1)
    try:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _lock:
            with _file_path().open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass  # silent fail
