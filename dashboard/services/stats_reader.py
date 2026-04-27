# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/stats_reader.py
#
#  Read-only — non scrive nessun file.
#  Legge e aggrega dati di stato/statistiche per la dashboard.
#
#  Fonti:
#    - engine_status.json  : stato live engine + storico eventi
#    - state/<nome>.json   : stato persistito per istanza (schedule, metrics,
#                            rifornimento, daily_tasks, boost/vip/arena su prod)
#    - runtime_overrides   : tipologia / abilitata per istanza (via config_manager)
#    - instances.json      : elenco istanze (via config_manager, read-only)
#
#  API pubblica:
#    get_engine_status()           -> EngineStatus
#    get_instance_stats(nome)      -> InstanceStats
#    get_all_stats()               -> list[InstanceStats]
#    get_storico(n=50)             -> list[StoricoEntry]
#    get_risorse_farm()            -> RisorseFarm
#
#  Nota: nessun filtro per nome (es. startswith "FAU_") o per flag `abilitata`.
#  Tutte le istanze presenti in instances.json vengono aggregate. Le eventuali
#  istanze senza state/<nome>.json vengono saltate automaticamente (state vuoto).
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dashboard.models import (
    EngineStatus, IstanzaStatus, StoricoEntry,
    InstanceStats, TickStats, RaccoltaStats, TipologiaIstanza,
)
from dashboard.services.config_manager import get_overrides, get_instances


# ==============================================================================
# Path costanti — coerenti con main.py (_ROOT/...)
# ==============================================================================
_ROOT          = Path(__file__).parent.parent.parent
_PROD_ROOT     = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_ENGINE_STATUS = _PROD_ROOT / "engine_status.json"
_STATE_DIR     = _PROD_ROOT / "state"
_LOGS_DIR      = _PROD_ROOT / "logs"

# Soglia anti-falso-positivo OCR (Issue #16: legno=999M da FAU_10).
# Una singola spedizione reale non supera mai 100M.
_MAX_QTA_SPEDIZIONE = 100_000_000  # 100M

# Risorse gestite — garantisce presenza nel dict anche se non inviate
_RISORSE_STANDARD = ("pomodoro", "legno", "petrolio", "acciaio")


# ==============================================================================
# Modelli aggregati risorse farm
# ==============================================================================

@dataclass
class RifornimentoIstanza:
    """Dati rifornimento di una singola istanza (da state/<nome>.json)."""
    nome:                str
    spedizioni_oggi:     int
    quota_max_per_ciclo: int
    provviste_residue:   int
    provviste_esaurite:  bool
    inviato_oggi:        Dict[str, int] = field(default_factory=dict)


@dataclass
class RisorseFarm:
    """
    Aggregato risorse per tutte le istanze con state persistito.

    Campi:
      - inviato_per_risorsa   : totale inviato oggi per risorsa (somma tutte istanze)
                                Fonte: dettaglio_oggi[*].qta_inviata (non inviato_oggi)
                                Filtro: spedizioni > 100M escluse (falsi positivi OCR)
      - provviste_residue     : somma provviste residue tutte istanze
      - spedizioni_oggi       : somma spedizioni oggi (cumulativo giornaliero)
      - quota_max_per_ciclo   : somma quota_max per-ciclo tutte istanze
                                Nota: NON confrontabile con spedizioni_oggi (cumulativo)
      - istanze_detail        : lista RifornimentoIstanza per dettaglio per-istanza
      - produzione_per_ora    : somma metrics.*_per_ora da tutte le istanze
    """
    inviato_per_risorsa:  Dict[str, int]            = field(default_factory=dict)
    provviste_residue:    int                        = 0
    spedizioni_oggi:      int                        = 0
    quota_max_per_ciclo:  int                        = 0
    istanze_detail:       List[RifornimentoIstanza] = field(default_factory=list)
    produzione_per_ora:   Dict[str, float]           = field(default_factory=dict)


# ==============================================================================
# Helpers interni
# ==============================================================================

def _load_engine_status() -> EngineStatus:
    es = EngineStatus.load(_ENGINE_STATUS)
    for nome, ist in es.istanze.items():
        ist.nome = nome
    return es


def _load_state(nome: str) -> dict:
    try:
        with open(_STATE_DIR / f"{nome}.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _raccolta_from_state(state: dict) -> RaccoltaStats:
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
    ts_inizio = state.get("ultimo_avvio")
    durata_s: Optional[float] = None
    task_eseguiti: list[str] = []
    task_falliti:  list[str] = []

    if ist_status:
        te = ist_status.task_eseguiti or {}
        task_eseguiti = [k for k, v in te.items() if isinstance(v, int) and v > 0]
        ut = ist_status.ultimo_task
        if ut and getattr(ut, "esito", None) == "err":
            nome_task = getattr(ut, "nome", None)
            if nome_task:
                task_falliti = [nome_task]
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
    try:
        ov = get_overrides()
        t  = ov.get("istanze", {}).get(nome, {}).get("tipologia", "full")
        return TipologiaIstanza(t)
    except Exception:
        return TipologiaIstanza.full


def _abilitata(nome: str) -> bool:
    try:
        ov = get_overrides()
        return bool(ov.get("istanze", {}).get(nome, {}).get("abilitata", True))
    except Exception:
        return True


# ==============================================================================
# API pubblica
# ==============================================================================

def get_engine_status() -> EngineStatus:
    return _load_engine_status()


def get_instance_stats(nome: str) -> InstanceStats:
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
    Ritorna InstanceStats per TUTTE le istanze in instances.json.
    Nessun filtro per nome o per flag abilitata — la dashboard decide
    eventualmente come visualizzare gli stati inattivi.
    """
    try:
        es     = _load_engine_status()
        insts  = get_instances()
        result: list[InstanceStats] = []
        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
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
    try:
        es = _load_engine_status()
        return es.storico[-n:] if es.storico else []
    except Exception:
        return []


def get_produzione_istanze() -> list[dict]:
    """
    Auto-WU14 step3: ritorna dati produzione per ogni istanza.

    Auto-WU18 (27/04): arricchito con stato live, task corrente, errori,
    quota rifornimento (per card unificata).

    Per ogni istanza presente in instances.json, legge state/<nome>.json
    e estrae produzione_corrente + ultima sessione chiusa dal storico,
    arricchito con dati live da engine_status.json.

    Schema output:
    [{
      "nome": str,
      "abilitata": bool,
      "stato": "online" | "idle" | "error" | "unknown",
      "task_corrente": str | None,
      "errori_live": int,
      "quota_max": int,            # rifornimento.quota_max
      "spedizioni_oggi": int,      # rifornimento.spedizioni_oggi
      "quota_esaurita": bool,      # spedizioni_oggi >= quota_max
      "corrente": {...} | None,
      "precedente": {...} | None,
      "n_storico_24h": int,
    }, ...]
    """
    try:
        insts = get_instances()
        engine = get_engine_status()
        result: list[dict] = []
        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue
            state = _load_state(nome)
            corrente = state.get("produzione_corrente")
            storico  = state.get("produzione_storico", []) or []
            precedente = storico[-1] if storico else None

            # Live state from engine_status
            ist_status = engine.istanze.get(nome) if engine else None
            stato = (ist_status.stato if ist_status else None) or "unknown"
            task_corrente = ist_status.task_corrente if ist_status else None
            errori_live = ist_status.errori if ist_status else 0
            # auto-WU19: ultimo task (per assorbire la card top inst-grid)
            ut = ist_status.ultimo_task if ist_status else None
            ultimo_task_nome  = (ut.nome if ut else None) or None
            ultimo_task_ts    = (ut.ts if ut else None) or None
            ultimo_task_msg   = ((ut.msg or "") if ut else "")[:50]
            ultimo_task_esito = (ut.esito if ut else None) or None

            # Quota rifornimento
            rif = state.get("rifornimento", {})
            quota_max       = int(rif.get("quota_max", 0) or 0)
            spedizioni_oggi = int(rif.get("spedizioni_oggi", 0) or 0)
            quota_esaurita  = quota_max > 0 and spedizioni_oggi >= quota_max

            result.append({
                "nome":              nome,
                "abilitata":         _abilitata(nome),
                "stato":             stato,
                "task_corrente":     task_corrente,
                "errori_live":       errori_live,
                "ultimo_task_nome":  ultimo_task_nome,
                "ultimo_task_ts":    ultimo_task_ts,
                "ultimo_task_msg":   ultimo_task_msg,
                "ultimo_task_esito": ultimo_task_esito,
                "quota_max":         quota_max,
                "spedizioni_oggi":   spedizioni_oggi,
                "quota_esaurita":    quota_esaurita,
                "corrente":          corrente,
                "precedente":        precedente,
                "n_storico_24h":     len(storico),
            })
        return result
    except Exception:
        return []


def get_risorse_farm() -> RisorseFarm:
    """
    Aggrega dati risorse da tutti gli state/<nome>.json presenti.
    Nessun filtro per nome o per flag abilitata — tutte le istanze con
    state persistito contribuiscono ai totali.

    Fonte inviato: dettaglio_oggi[*].qta_inviata (NON inviato_oggi).
    Motivo: inviato_oggi può contenere falsi positivi OCR (Issue #16, legno=999M).
    dettaglio_oggi contiene i valori scritti dal bot al momento dell'invio reale.
    Sanity check aggiuntivo: qta_inviata > 100M viene scartata.

    Somma per tutte le istanze:
      - dettaglio_oggi[*].qta_inviata  → inviato_per_risorsa (filtrato)
      - rifornimento.provviste_residue  → provviste_residue (totale)
      - rifornimento.spedizioni_oggi    → spedizioni_oggi (cumulativo giornaliero)
      - rifornimento.quota_max          → quota_max_per_ciclo (per-ciclo)
      - metrics.*_per_ora               → produzione_per_ora (somma istanze)

    Failsafe: RisorseFarm() vuoto su errore.
    """
    try:
        insts = get_instances()

        # Inizializza tutte le risorse a 0 — garantisce presenza nel dict
        inviato:     Dict[str, int]   = {r: 0 for r in _RISORSE_STANDARD}
        provviste:   int              = 0
        sped_oggi:   int              = 0
        quota_ciclo: int              = 0
        prod_ora:    Dict[str, float] = {r: 0.0 for r in _RISORSE_STANDARD}
        detail:      List[RifornimentoIstanza] = []

        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue

            state = _load_state(nome)
            if not state:
                continue

            rif = state.get("rifornimento", {})

            # --- Inviato oggi — fonte: dettaglio_oggi (valori reali bot) ---
            # dettaglio_oggi è scritto dal bot al momento dell'invio effettivo,
            # non da OCR — elimina alla radice Issue #16.
            # Sanity check residuo: scarta comunque qta > 100M.
            inviato_ist: Dict[str, int] = {r: 0 for r in _RISORSE_STANDARD}
            for entry in rif.get("dettaglio_oggi", []):
                risorsa = entry.get("risorsa", "")
                qta     = int(entry.get("qta_inviata", 0))
                if risorsa not in _RISORSE_STANDARD:
                    continue
                if qta > _MAX_QTA_SPEDIZIONE:
                    continue  # falso positivo OCR — scarta
                inviato_ist[risorsa] += qta

            for risorsa, qta in inviato_ist.items():
                inviato[risorsa] += qta

            # --- Provviste e spedizioni ---
            prov        = int(rif.get("provviste_residue", 0))
            provviste   += prov
            sped_oggi   += int(rif.get("spedizioni_oggi", 0))
            quota_ciclo += int(rif.get("quota_max", 0))

            detail.append(RifornimentoIstanza(
                nome                = nome,
                spedizioni_oggi     = int(rif.get("spedizioni_oggi", 0)),
                quota_max_per_ciclo = int(rif.get("quota_max", 0)),
                provviste_residue   = prov,
                provviste_esaurite  = bool(rif.get("provviste_esaurite", False)),
                inviato_oggi        = inviato_ist,
            ))

            # --- Metrics (produzione/ora) ---
            m = state.get("metrics", {})
            for r in _RISORSE_STANDARD:
                prod_ora[r] = round(prod_ora[r] + float(m.get(f"{r}_per_ora", 0.0)), 2)

        return RisorseFarm(
            inviato_per_risorsa = inviato,
            provviste_residue   = provviste,
            spedizioni_oggi     = sped_oggi,
            quota_max_per_ciclo = quota_ciclo,
            istanze_detail      = detail,
            produzione_per_ora  = prod_ora,
        )

    except Exception:
        return RisorseFarm()
