# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/stats_reader.py
#
#  Read-only — non scrive nessun file.
#  Legge e aggrega dati di stato/statistiche per la dashboard.
#
#  Fonti:
#    - engine_status.json  : stato live engine + storico eventi
#    - state/FAU_XX.json   : stato persistito per istanza (schedule, metrics,
#                            rifornimento, daily_tasks, boost/vip/arena su prod)
#    - runtime_overrides   : tipologia / abilitata per istanza (via config_manager)
#    - instances.json      : elenco istanze (via config_manager, read-only)
#
#  API pubblica:
#    get_engine_status()           -> EngineStatus
#    get_instance_stats(nome)      -> InstanceStats
#    get_all_stats()               -> list[InstanceStats]
#    get_storico(n=50)             -> list[StoricoEntry]
# ==============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from dashboard.models import (
    EngineStatus, IstanzaStatus, StoricoEntry,
    InstanceStats, TickStats, RaccoltaStats, TipologiaIstanza,
)
from dashboard.services.config_manager import get_overrides, get_instances


# ==============================================================================
# Path costanti — coerenti con main.py (_ROOT/...)
# ==============================================================================
# dashboard/services/stats_reader.py -> parents: [services, dashboard, project root]
_ROOT          = Path(__file__).parent.parent.parent
_ENGINE_STATUS = _ROOT / "engine_status.json"
_STATE_DIR     = _ROOT / "state"
_LOGS_DIR      = _ROOT / "logs"


# ==============================================================================
# Helpers interni
# ==============================================================================

def _load_engine_status() -> EngineStatus:
    """
    Legge engine_status.json e popola IstanzaStatus.nome da chiave dict
    (non presente nel payload raw).
    Failsafe: EngineStatus() default su errore (delegato a EngineStatus.load).
    """
    es = EngineStatus.load(_ENGINE_STATUS)
    for nome, ist in es.istanze.items():
        ist.nome = nome
    return es


def _load_state(nome: str) -> dict:
    """Legge state/FAU_XX.json grezzo. Failsafe: {} su errore."""
    try:
        with open(_STATE_DIR / f"{nome}.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _raccolta_from_state(state: dict) -> RaccoltaStats:
    """
    Estrae RaccoltaStats da state/FAU_XX.json.

    Lo state attuale non ha campi "raccolta_*" strutturati — le info
    disponibili sono in metrics (pomodoro_per_ora, legno_per_ora, ...).
    Restituiamo quello che c'e', il resto a 0. Upgrade path: quando
    tasks/raccolta.py scrivera' campi strutturati in state, aggiornare qui.
    """
    # `metrics` letto per future-proof (al momento non mappato su RaccoltaStats)
    _ = state.get("metrics", {})
    return RaccoltaStats(
        slot_totali        = state.get("raccolta_slot_totali", 0),
        slot_usati         = state.get("raccolta_slot_usati", 0),
        nodi_raccolti      = state.get("raccolta_nodi_ok", 0),
        nodi_falliti       = state.get("raccolta_nodi_fail", 0),
        tipologie_bloccate = state.get("raccolta_tipologie_bloccate", []),
    )


def _tick_from_status_and_state(
    nome: str,
    ist_status: Optional[IstanzaStatus],
    state: dict,
) -> TickStats:
    """
    Costruisce TickStats combinando engine_status e state.

    Fonti:
      - ts_inizio     -> state.ultimo_avvio (None se mai avviato)
      - durata_s      -> ist_status.ultimo_task.durata_s
      - task_eseguiti -> ist_status.task_eseguiti (dict nome->count) filtrato >0
      - task_falliti  -> [ist_status.ultimo_task.nome] se esito == "err"
      - raccolta      -> _raccolta_from_state(state)
    """
    ts_inizio = state.get("ultimo_avvio")
    durata_s: Optional[float] = None

    task_eseguiti: list[str] = []
    task_falliti:  list[str] = []

    if ist_status:
        # task_eseguiti: dict {nome: conteggio} -> lista nomi con count > 0
        te = ist_status.task_eseguiti or {}
        task_eseguiti = [k for k, v in te.items() if isinstance(v, int) and v > 0]

        # task_falliti: dall'ultimo_task se esito == "err"
        ut = ist_status.ultimo_task
        if ut and getattr(ut, "esito", None) == "err":
            nome_task = getattr(ut, "nome", None)
            if nome_task:
                task_falliti = [nome_task]

        # durata_s dall'ultimo_task se disponibile
        if ut:
            durata_s = getattr(ut, "durata_s", None)

    raccolta = _raccolta_from_state(state)

    return TickStats(
        ts_inizio     = ts_inizio,
        durata_s      = durata_s,
        task_eseguiti = task_eseguiti,
        task_falliti  = task_falliti,
        raccolta      = raccolta,
    )


def _tipologia_istanza(nome: str) -> TipologiaIstanza:
    """Legge tipologia da runtime_overrides.json. Default: full."""
    try:
        ov = get_overrides()
        t  = ov.get("istanze", {}).get(nome, {}).get("tipologia", "full")
        return TipologiaIstanza(t)
    except Exception:
        return TipologiaIstanza.full


def _abilitata(nome: str) -> bool:
    """Legge abilitata da runtime_overrides.json. Default: True."""
    try:
        ov = get_overrides()
        return bool(ov.get("istanze", {}).get(nome, {}).get("abilitata", True))
    except Exception:
        return True


# ==============================================================================
# API pubblica
# ==============================================================================

def get_engine_status() -> EngineStatus:
    """Legge engine_status.json. Failsafe: EngineStatus() default."""
    return _load_engine_status()


def get_instance_stats(nome: str) -> InstanceStats:
    """
    Aggrega InstanceStats per una singola istanza.
    Combina: engine_status + state + overrides.
    Failsafe totale: InstanceStats con stato_live='unknown' su errore.
    """
    try:
        es          = _load_engine_status()
        ist_status  = es.istanze.get(nome)
        state       = _load_state(nome)
        stato_live  = ist_status.stato if ist_status else "unknown"
        ultimo_tick = _tick_from_status_and_state(nome, ist_status, state)
        return InstanceStats(
            nome        = nome,
            tipologia   = _tipologia_istanza(nome),
            abilitata   = _abilitata(nome),
            stato_live  = stato_live,
            ultimo_tick = ultimo_tick,
        )
    except Exception:
        return InstanceStats(nome=nome, stato_live="unknown")


def get_all_stats() -> list[InstanceStats]:
    """
    Restituisce InstanceStats per tutte le istanze in instances.json.
    Legge engine_status una sola volta (efficienza).
    Failsafe: [] su errore.
    """
    try:
        es     = _load_engine_status()
        insts  = get_instances()
        result: list[InstanceStats] = []
        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue
            if not nome.startswith("FAU_"):
                continue
            ist_status  = es.istanze.get(nome)
            state       = _load_state(nome)
            stato_live  = ist_status.stato if ist_status else "unknown"
            ultimo_tick = _tick_from_status_and_state(nome, ist_status, state)
            result.append(InstanceStats(
                nome        = nome,
                tipologia   = _tipologia_istanza(nome),
                abilitata   = _abilitata(nome),
                stato_live  = stato_live,
                ultimo_tick = ultimo_tick,
            ))
        return result
    except Exception:
        return []


def get_storico(n: int = 50) -> list[StoricoEntry]:
    """
    Restituisce gli ultimi n eventi dallo storico engine_status.json.
    Failsafe: [] su errore.
    """
    try:
        es = _load_engine_status()
        return es.storico[-n:] if es.storico else []
    except Exception:
        return []
