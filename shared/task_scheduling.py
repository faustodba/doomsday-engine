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
# Finestra evento multi-giorno — District Showdown (R-06, revisione 07/2026)
# ──────────────────────────────────────────────────────────────────────────────

# Default finestra evento DS (UTC). DEVONO restare allineati ai default di
# DistrictShowdownConfig (tasks/district_showdown.py:122-125): Ven 00:00 → Lun 00:00.
DS_START_WEEKDAY = 4   # venerdì (Python weekday: 0=lun … 6=dom)
DS_START_HOUR    = 0   # 00:00 UTC
DS_END_WEEKDAY   = 0   # lunedì
DS_END_HOUR      = 0   # 00:00 UTC (con hour=0 il lunedì è di fatto escluso)


def is_in_ds_event_window(
    now=None,
    *,
    ds_start_weekday: int = DS_START_WEEKDAY,
    ds_start_hour:    int = DS_START_HOUR,
    ds_end_weekday:   int = DS_END_WEEKDAY,
    ds_end_hour:      int = DS_END_HOUR,
) -> bool:
    """
    True se l'ora UTC `now` è nella finestra evento District Showdown
    (default Ven 00:00 UTC → Lun 00:00 UTC, 3 giorni esatti).

    UNICA implementazione della logica finestra DS (R-06: prima era duplicata
    tra il task live e il predictor, con rischio drift — il predictor hardcodava
    `lun → sempre fuori` ignorando `ds_end_hour`). Ora:
      - tasks/district_showdown.py::_is_in_event_window   → chiama passando cfg
      - core/cycle_duration_predictor.py::_district_showdown_will_skip → chiama
        negata (skip = fuori finestra)

    L'ordine dei check (end prima di start) replica esattamente il task originale.
    """
    d  = _now_utc(now)
    wd = d.weekday()   # 0=lun … 6=dom
    h  = d.hour
    # Lunedì (fine evento): attivo solo prima di ds_end_hour
    if wd == ds_end_weekday:
        return h < ds_end_hour
    # Venerdì (inizio evento): attivo solo da ds_start_hour in poi
    if wd == ds_start_weekday:
        return h >= ds_start_hour
    # Sabato/Domenica: pieno weekend evento
    if wd in (5, 6):
        return True
    # Mar/Mer/Gio: fuori finestra
    return False


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
