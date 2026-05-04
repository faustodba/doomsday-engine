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
#          {"tipo": "campo", "livello": 6, "cap_nodo": 1200000,
#           "eta_marcia_s": 95, "ts_invio": "2026-05-01T22:07:15+00:00"}
#          # NOTE: cap_nodo = capacità RESIDUA letta da popup gather (non nominale).
#          #       livello = ground truth da LENTE (CERCA filter), -1 solo se anomalia.
#          #       eta_marcia_s = sola ANDATA (OCR pre-marcia).
#          #       ts_invio = momento partenza marcia (post-_esegui_marcia OK).
#          #       Per predictor: ts_libero ≈ ts_invio + 2*eta + tempo_raccolta.
#          #       Cap nominale derivabile da (tipo, livello) — vedi shared/ocr_helpers.
#        ]
#      },
#      "rifornimento": {                              03/05 — esteso per predictor 5-invii
#        "invii": [
#          {"risorsa": "pomodoro", "qta_netta": 1199999, "eta_residua_s": 90}
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
                            cap_nodo: int, eta_marcia_s: int,
                            ts_invio_iso: str | None = None,
                            load_squadra: int = -1) -> None:
    """Hook raccolta: aggiunge dettaglio invio singolo.

    ts_invio_iso: timestamp ISO UTC del momento in cui la marcia è partita
    (post `_esegui_marcia` OK). Permette al predictor di stimare ts_libero
    empiricamente correlando con `attive_post` dei tick successivi.

    load_squadra: WU116 — carico effettivo della squadra (OCR maschera invio),
    -1 se non disponibile. Permette analisi copertura squadra (load < cap →
    underprovisioned, nodo non chiuso non rigenera al max).
    """
    if ts_invio_iso is None:
        ts_invio_iso = datetime.now(timezone.utc).isoformat()
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        buf.setdefault("raccolta", {"invii": []})["invii"].append({
            "tipo": tipo,
            "livello": int(livello),
            "cap_nodo": int(cap_nodo),
            "load_squadra": int(load_squadra),
            "eta_marcia_s": int(eta_marcia_s),
            "ts_invio": str(ts_invio_iso),
        })


def aggiungi_invio_rifornimento(instance: str, risorsa: str,
                                 qta_netta: int, eta_residua_s: int = 0) -> None:
    """Hook rifornimento: aggiunge dettaglio spedizione singola.

    Permette al predictor di valutare se il ciclo ha raggiunto la soglia
    "5 invii" combinando raccolta.invii + rifornimento.invii.
    """
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        rif = buf.setdefault("rifornimento", {"invii": []})
        rif.setdefault("invii", []).append({
            "risorsa": str(risorsa),
            "qta_netta": int(qta_netta),
            "eta_residua_s": int(eta_residua_s),
        })


def imposta_task_duration(instance: str, task_name: str, secondi: float) -> None:
    """Hook orchestrator: durata di un task del tick."""
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        buf.setdefault("task_durations_s", {})[task_name] = round(float(secondi), 1)


def aggiungi_wait_inter_task(instance: str, wait_s: float) -> None:
    """
    WU122-OptC: traccia il wait tra fine task_i e inizio task_{i+1}.

    Comprende: gate HOME (vai_in_home), save state post-task, should_run
    check del prossimo task, dismiss banners, telemetry overhead. Mancante
    nelle `task_durations_s` che misurano solo `task.run()` interno.

    Accumula somma + count per il tick. predict_istanza_duration usa la
    somma come componente extra di T_s per ridurre la sotto-stima.
    """
    if wait_s <= 0:
        return
    with _lock:
        buf = _BUFFER_PER_INSTANCE.get(instance)
        if buf is None:
            return
        buf["wait_inter_task_s"] = round(float(buf.get("wait_inter_task_s", 0.0))
                                          + float(wait_s), 1)
        buf["wait_inter_task_n"] = int(buf.get("wait_inter_task_n", 0)) + 1


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
    for k in ("boot_home_s", "raccolta", "rifornimento", "task_durations_s",
              "wait_inter_task_s", "wait_inter_task_n"):
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
