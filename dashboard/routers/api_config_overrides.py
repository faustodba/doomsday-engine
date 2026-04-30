# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_config_overrides.py
#
#  Endpoint hot-reload per runtime_overrides.json.
#  Prefix: /api/config
#
#  Modifiche attive al PROSSIMO avvio istanza — nessun restart richiesto.
#
#  Endpoint per sezione:
#    GET  /api/config/overrides            — legge tutto runtime_overrides.json
#    PUT  /api/config/globals              — task flags + sistema (max_parallel, tick_sleep)
#    PUT  /api/config/rifornimento         — soglie, flag risorsa, modalità, coordinate
#    PUT  /api/config/zaino               — modalità e soglie zaino
#    PUT  /api/config/allocazione         — percentuali allocazione raccolta
#    PUT  /api/config/istanze             — override per-istanza (scritto anche su instances.json)
#
#    PATCH /api/config/overrides/task/{task_name}     — toggle singolo task
#    PATCH /api/config/overrides/istanze/{nome}       — patch singola istanza
# ==============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from dashboard.models import (
    RuntimeOverrides,
    IstanzaOverride,
    PayloadGlobals,
    PayloadRifornimento,
    PayloadZaino,
    PayloadAllocazione,
    PayloadIstanze,
)
from dashboard.services.config_manager import (
    get_overrides,
    save_overrides,
    save_instances_fields,
)

router = APIRouter(prefix="/api/config", tags=["config"])

# Path instances.json — coerente con config_manager._ROOT
_ROOT           = Path(__file__).parent.parent.parent
_INSTANCES_PATH = _ROOT / "config" / "instances.json"


# ==============================================================================
# Helper — carica overrides correnti
# ==============================================================================

def _load_ov() -> RuntimeOverrides:
    raw = get_overrides()
    return RuntimeOverrides.model_validate(raw) if raw else RuntimeOverrides()


def _save_ov(ov: RuntimeOverrides) -> None:
    """Salva RuntimeOverrides su disco. Propaga IOError."""
    try:
        save_overrides(ov.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore scrittura overrides: {e}")


# ==============================================================================
# GET /api/config/overrides — lettura completa
# ==============================================================================

@router.get("/overrides", response_model=RuntimeOverrides)
def read_overrides():
    """
    Legge runtime_overrides.json completo.
    Usato dalla dashboard per popolare tutti i form al caricamento.
    """
    return _load_ov()


# ==============================================================================
# PUT /api/config/globals — task flags + parametri sistema
# ==============================================================================

@router.put("/globals")
def save_globals(payload: PayloadGlobals):
    """
    Aggiorna task flags e parametri globali sistema.
    Merge incrementale: solo i campi esplicitamente presenti nel payload
    vengono aggiornati (exclude_unset). I campi task non inviati mantengono
    lo stato precedente.

    Bug storico: payload task={} faceva Pydantic costruire TaskFlags() con
    default — sovrascrivendo rifornimento/radar_census a False (default
    Pydantic) ogni volta che l'utente salvava "sistema".

    Hot-reload: attivo al prossimo tick del bot.
    """
    ov = _load_ov()

    # Merge incrementale task — solo campi esplicitamente presenti
    task_updates = payload.task.model_dump(exclude_unset=True)
    for k, v in task_updates.items():
        setattr(ov.globali.task, k, v)

    # Sistema sempre sovrascritto (solo 2 campi, poco rischio di miss)
    ov.globali.sistema = payload.sistema

    _save_ov(ov)
    return {
        "ok": True, "restart_required": False, "sezione": "globals",
        "task_updated": list(task_updates.keys()),
    }


# ==============================================================================
# PUT /api/config/rifornimento — soglie, flag, modalità, coordinate
# ==============================================================================

@router.put("/rifornimento")
def save_rifornimento(payload: PayloadRifornimento):
    """
    Aggiorna configurazione rifornimento completa:
      - rifornimento_comune: account, max spedizioni, soglie per risorsa, flag per risorsa
      - rifugio: coordinate X/Y mappa
      - modalità: mappa_abilitata / membri_abilitati (mutuamente esclusivi)

    Hot-reload: attivo al prossimo tick.
    """
    ov = _load_ov()
    ov.globali.rifornimento_comune = payload.rifornimento_comune
    ov.globali.rifugio             = payload.rifugio

    # Modalità mutuamente esclusiva: se mappa ON → membri OFF e viceversa
    if payload.mappa_abilitata:
        ov.globali.rifornimento.mappa_abilitata  = True
        ov.globali.rifornimento.membri_abilitati = False
    elif payload.membri_abilitati:
        ov.globali.rifornimento.mappa_abilitata  = False
        ov.globali.rifornimento.membri_abilitati = True
    else:
        ov.globali.rifornimento.mappa_abilitata  = False
        ov.globali.rifornimento.membri_abilitati = False

    _save_ov(ov)
    return {"ok": True, "restart_required": False, "sezione": "rifornimento"}


# ==============================================================================
# PUT /api/config/zaino — modalità e soglie
# ==============================================================================

@router.put("/zaino")
def save_zaino(payload: PayloadZaino):
    """
    Aggiorna configurazione zaino:
      - modalita: "bag" | "svuota" (mutuamente esclusive)
      - usa_*: flag per risorsa
      - soglia_*_m: soglia deposito per risorsa

    Hot-reload: attivo al prossimo tick.
    """
    ov = _load_ov()
    ov.globali.zaino = payload.zaino
    _save_ov(ov)
    return {"ok": True, "restart_required": False, "sezione": "zaino"}


# ==============================================================================
# PUT /api/config/allocazione — percentuali raccolta
# ==============================================================================

@router.put("/allocazione")
def save_allocazione(payload: PayloadAllocazione):
    """
    Aggiorna percentuali allocazione raccolta.
    Somma consigliata = 100%. Il bot normalizza internamente.
    Le percentuali vengono convertite in frazioni (0.0-1.0) prima della scrittura.

    Hot-reload: attivo al prossimo tick.
    """
    ov = _load_ov()
    ov.globali.raccolta.allocazione = payload.allocazione

    # Scrivi frazioni nel raccolta del merged che il bot legge via raccolta.allocazione
    frazioni = payload.allocazione.to_frazioni()
    ov.globali.raccolta.allocazione.pomodoro = payload.allocazione.pomodoro
    ov.globali.raccolta.allocazione.legno    = payload.allocazione.legno
    ov.globali.raccolta.allocazione.petrolio = payload.allocazione.petrolio
    ov.globali.raccolta.allocazione.acciaio  = payload.allocazione.acciaio

    _save_ov(ov)

    totale = sum([
        payload.allocazione.pomodoro,
        payload.allocazione.legno,
        payload.allocazione.petrolio,
        payload.allocazione.acciaio,
    ])
    return {
        "ok": True,
        "restart_required": False,
        "sezione": "allocazione",
        "totale_pct": round(totale, 1),
        "frazioni": frazioni,
        "warn": None if abs(totale - 100.0) <= 0.5 else f"Totale {totale:.1f}% ≠ 100% — il bot normalizzerà",
    }


# ==============================================================================
# PUT /api/config/istanze — override per-istanza
# ==============================================================================

@router.put("/istanze")
def save_istanze(payload: PayloadIstanze):
    """
    Aggiorna override per tutte le istanze.

    Scrittura su DUE file:
      1. runtime_overrides.json.istanze → abilitata, truppe, tipologia, fascia_oraria
      2. instances.json                 → max_squadre, layout, livello
         (solo se presenti nel payload, via save_instances_fields)

    Hot-reload: attivo al prossimo avvio istanza.
    """
    ov = _load_ov()
    ov.istanze = payload.istanze
    _save_ov(ov)

    # Estrai campi da scrivere su instances.json (max_squadre, layout, livello,
    # raccolta_fuori_territorio — WU50 default statico per istanza)
    instances_updates: dict[str, dict] = {}
    for nome, ist_ov in payload.istanze.items():
        upd = {}
        if ist_ov.max_squadre is not None:
            upd["max_squadre"] = ist_ov.max_squadre
        if ist_ov.layout is not None:
            upd["layout"] = ist_ov.layout
        if ist_ov.livello is not None:
            upd["livello"] = ist_ov.livello
        # WU50 — flag fuori territorio sempre persistito in instances.json
        # (è un default statico per-istanza, configurabile da dashboard)
        upd["raccolta_fuori_territorio"] = bool(ist_ov.raccolta_fuori_territorio)
        instances_updates[nome] = upd

    errors: list[str] = []
    if instances_updates:
        try:
            save_instances_fields(instances_updates)
        except Exception as e:
            # Non blocca — overrides salvati, solo instances.json non aggiornato
            errors.append(f"instances.json non aggiornato: {e}")

    return {
        "ok": True,
        "restart_required": False,
        "sezione": "istanze",
        "aggiornate": list(payload.istanze.keys()),
        "instances_json_updated": not bool(errors),
        "warnings": errors,
    }


# ==============================================================================
# PATCH /api/config/overrides/task/{task_name} — toggle singolo task
# ==============================================================================

@router.patch("/overrides/task/{task_name}")
async def toggle_task(task_name: str, request: Request):
    """Toggle singolo task flag — accetta JSON body o form data da HTMX."""
    # Legge il body UNA SOLA VOLTA in base al content-type.
    # HTMX senza json-enc manda application/x-www-form-urlencoded;
    # con json-enc manda application/json.
    content_type = request.headers.get("content-type", "").lower()
    abilitato_raw = "true"
    try:
        if "json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                abilitato_raw = body.get("abilitato", "true")
        else:
            form = await request.form()
            abilitato_raw = form.get("abilitato", "true")
    except Exception:
        # Fallback: prova a leggere query string
        abilitato_raw = request.query_params.get("abilitato", "true")

    abilitato = str(abilitato_raw).lower() not in ("false", "0", "no")

    valid_tasks = {
        "alleanza", "messaggi", "vip", "radar", "radar_census",
        "rifornimento", "donazione", "zaino",
        "arena", "arena_mercato", "district_showdown", "boost", "truppe", "store",
    }
    if task_name not in valid_tasks:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_name}' non riconosciuto. Validi: {sorted(valid_tasks)}",
        )
    ov = _load_ov()
    setattr(ov.globali.task, task_name, abilitato)
    _save_ov(ov)
    return {"ok": True, "task": task_name, "abilitato": abilitato}


# ==============================================================================
# PATCH /api/config/rifornimento-mode/{sub} — switch modalità rifornimento
# ==============================================================================

@router.patch("/rifornimento-mode/{sub}")
def set_rifornimento_mode(sub: str):
    """
    Switch modalità rifornimento: mappa | membri (mutuamente esclusive).
    Usato dai sub-pill "task-flags-v2" per cambio rapido senza passare dal
    salvataggio completo via PUT /rifornimento.
    """
    if sub not in ("mappa", "membri"):
        raise HTTPException(
            status_code=404,
            detail=f"Sub '{sub}' non riconosciuto. Validi: mappa, membri",
        )
    ov = _load_ov()
    ov.globali.rifornimento.mappa_abilitata  = (sub == "mappa")
    ov.globali.rifornimento.membri_abilitati = (sub == "membri")
    _save_ov(ov)
    return {"ok": True, "sezione": "rifornimento-mode", "active": sub}


# ==============================================================================
# PATCH /api/config/zaino-mode/{sub} — switch modalità zaino
# ==============================================================================

@router.patch("/zaino-mode/{sub}")
def set_zaino_mode(sub: str):
    """
    Switch modalità zaino: bag | svuota (mutuamente esclusive).
    Usato dai sub-pill "task-flags-v2".
    """
    if sub not in ("bag", "svuota"):
        raise HTTPException(
            status_code=404,
            detail=f"Sub '{sub}' non riconosciuto. Validi: bag, svuota",
        )
    ov = _load_ov()
    ov.globali.zaino.modalita = sub
    _save_ov(ov)
    return {"ok": True, "sezione": "zaino-mode", "active": sub}


# ==============================================================================
# PATCH /api/config/overrides/istanze/{nome} — patch singola istanza
# ==============================================================================

@router.patch("/overrides/istanze/{nome}")
def patch_istanza(nome: str, data: dict):
    """
    Aggiorna i campi override di una singola istanza.
    Merge con i valori esistenti (non sovrascrive tutto).
    """
    ov = _load_ov()
    current      = ov.istanze.get(nome, IstanzaOverride())
    current_dict = current.model_dump()

    allowed = {"abilitata", "truppe", "tipologia", "fascia_oraria",
               "max_squadre", "layout", "livello"}
    for k, v in data.items():
        if k in allowed:
            current_dict[k] = v

    ov.istanze[nome] = IstanzaOverride.model_validate(current_dict)
    _save_ov(ov)

    # Aggiorna instances.json se presenti campi strutturali
    instances_upd = {k: current_dict[k] for k in ("max_squadre", "layout", "livello")
                     if current_dict.get(k) is not None}
    if instances_upd:
        try:
            save_instances_fields({nome: instances_upd})
        except Exception:
            pass  # non bloccante

    return {"ok": True, "istanza": nome, "aggiornato": current_dict}
