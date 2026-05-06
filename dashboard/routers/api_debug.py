"""
dashboard/routers/api_debug.py — endpoint per gestione debug screenshot per-task.

WU115 (04/05) — sistema debug indipendente con hot-reload via dashboard.
Vedi shared/debug_buffer.py per architettura completa.

Endpoints:
  GET   /api/debug-tasks                           — status corrente di tutti i task
  PATCH /api/debug-tasks/{task_name}/{action}      — enable/disable singolo task
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from shared.debug_buffer import (
    get_all_debug_status,
    is_debug_enabled,
    set_debug_enabled,
)


router = APIRouter(prefix="/api", tags=["debug"])


# Lista task noti — popolata in base a quelli che usano DebugBuffer.
# Estendere quando si aggiunge il pattern a un nuovo task.
_KNOWN_TASKS: list[str] = [
    "arena",
    "arena_mercato",
    "store",
    "vip",
    "messaggi",
    "boost",
    "alleanza",
    "donazione",
    "radar",
    "radar_census",
    "truppe",
    "zaino",
    "main_mission",
    "raccolta",
    "raccolta_fast",       # 06/05 — variante fast (WU57), opt-in via tipologia istanza
    "raccolta_chiusura",
    "rifornimento",
    "district_showdown",
]


@router.get("/debug-tasks")
def get_debug_tasks() -> dict:
    """
    Ritorna lo stato corrente debug per tutti i task noti.

    Schema risposta:
        {
            "known_tasks": ["arena", "arena_mercato", "store", ...],
            "status": {"arena": false, "arena_mercato": false, ...},
            "active_count": 0
        }
    """
    raw_status = get_all_debug_status()
    # Costruisci status completo: tutti i known_tasks, default False se non in config
    status: dict[str, bool] = {}
    for task in _KNOWN_TASKS:
        status[task] = bool(raw_status.get(task, False))
    # Aggiungi eventuali task in config NON presenti in known_tasks (per visibilità)
    for task, val in raw_status.items():
        if task not in status:
            status[task] = bool(val)
    active = sum(1 for v in status.values() if v)
    return {
        "known_tasks":  _KNOWN_TASKS,
        "status":       status,
        "active_count": active,
    }


@router.patch("/debug-tasks/{task_name}/{action}")
def patch_debug_task(task_name: str, action: str) -> dict:
    """
    Enable/disable debug screenshot per singolo task.

    Args:
        task_name: nome del task (es. "arena", "store", ...)
        action:    "enable" | "disable"

    Effetto:
      - Modifica `runtime_overrides.json::globali.debug_tasks.{task_name}`
      - Invalida cache shared/debug_buffer (refresh immediato)
      - I prossimi run del task useranno il nuovo flag

    NB: per task in esecuzione corrente, il DebugBuffer è già stato
    instanziato con il flag al momento della creazione → non cambia
    a runtime per quel run specifico. Cambio attivo dal run successivo.
    """
    action_l = action.lower()
    if action_l not in ("enable", "disable"):
        raise HTTPException(
            status_code=400,
            detail=f"Azione '{action}' non valida. Usa 'enable' o 'disable'.",
        )
    if not task_name:
        raise HTTPException(status_code=400, detail="task_name vuoto")

    enabled = (action_l == "enable")
    ok = set_debug_enabled(task_name, enabled)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Scrittura runtime_overrides.json fallita per task '{task_name}'",
        )
    return {
        "ok":      True,
        "task":    task_name,
        "enabled": enabled,
        "active":  is_debug_enabled(task_name),
    }
