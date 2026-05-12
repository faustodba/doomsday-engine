"""
shared/task_scheduling.py — Regole di scheduling centralizzate per task

WU157 (12/05/2026) — single source of truth per gate orari/condizionali.

Pattern: ogni task con vincolo temporale ha una funzione `time_gate_<task>(now=None)`
che ritorna True se il task PUO' girare al momento `now` (UTC).

Sia il bot live (`tasks/<task>.py::should_run()`) sia il predictor
(`core/cycle_duration_predictor.py::_is_task_due()`) chiamano la stessa funzione.
Cambio strategia gate -> 1 sola modifica qui.

Razionale: pre-WU157 ogni gate richiedeva 2 modifiche (live + predictor) con
rischio drift (caso WU145 -> WU156: arena gate UTC<10 e' restato 2 giorni solo
nel live, predictor sovrastimava T_ciclo notturno di 3-5min).

Aggiungere nuovo gate:
  1. Definire `time_gate_<task>(now=None) -> bool` qui
  2. Registrare in `TIME_GATES` dict
  3. `tasks/<task>.py::should_run()` chiama la funzione gate
  4. Predictor introspection automatica via `can_run_by_time_gate()` — no modifica
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional


def _now_utc(now=None):
    """Default `datetime.now(utc)` se `now` non fornito."""
    return now if now is not None else datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
# Time gates — un task per funzione
# ──────────────────────────────────────────────────────────────────────────────

def time_gate_arena(now=None) -> bool:
    """
    WU145: arena gira solo UTC>=10. Posticipa al ciclo dopo 10:00 UTC per
    evitare picco notturno cumulato col reset rifornimento master 00:00 UTC.
    Finestra esecuzione: 10:00-24:00 UTC.

    Trade-off: se bot fermo 00->10 UTC arena ritardata; se bot fermo tutta
    la finestra 10->24 UTC il giorno viene saltato (accettato, finestra
    ampia 14h).
    """
    return _now_utc(now).hour >= 10


def time_gate_main_mission(now=None) -> bool:
    """
    WU91: main_mission gira solo UTC>=20. Massimizza chest milestone
    accumulando AP durante il giorno e raccogliendo a fine giornata.
    Finestra esecuzione: 20:00-24:00 UTC (4h, ~2-3 tick disponibili).

    Reset missioni gioco: 00:00 UTC (le daily si azzerano).
    """
    return _now_utc(now).hour >= 20


# ──────────────────────────────────────────────────────────────────────────────
# Registry — introspection automatica per predictor
# ──────────────────────────────────────────────────────────────────────────────

# Mappa task_name (canonical lower_snake da CLASS_TO_TASK_NAME) -> funzione gate.
# Solo task con vincolo temporale lo registrano qui. Task senza gate (raccolta,
# rifornimento, boost, donazione, truppe, ...) NON appaiono.
TIME_GATES: dict[str, Callable[[Optional[datetime]], bool]] = {
    "arena":         time_gate_arena,
    "main_mission":  time_gate_main_mission,
}


def can_run_by_time_gate(task_name: str, now=None) -> bool:
    """
    True se il task non ha gate orario, o se il gate permette esecuzione ora.
    False solo se task ha gate orario E il momento (`now`) e' fuori finestra.

    Args:
        task_name: nome canonico task (snake_case, es. 'arena', 'main_mission')
        now: datetime UTC opzionale. Default `datetime.now(utc)`.

    Returns:
        bool. Default True (no gate = sempre eseguibile).

    Usato da:
        - tasks/<task>.py::should_run() (live bot, no se vuoi check esplicito
          con messaggio log custom — chiama direttamente time_gate_<task>())
        - core/cycle_duration_predictor.py::_is_task_due() (predictor T_ciclo)
    """
    gate = TIME_GATES.get(task_name)
    if gate is None:
        return True
    try:
        return gate(now)
    except Exception:
        # Failsafe: su errore, lascia che il task giri (conservativo)
        return True
