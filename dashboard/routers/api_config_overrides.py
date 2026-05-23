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
async def save_globals(request: Request):
    """
    Aggiorna task flags e parametri globali sistema — MERGE INCREMENTALE.

    Bug fix 08/05: pre-fix `ov.globali.sistema = payload.sistema` sovrascriveva
    i 2 campi sistema con i default Pydantic se non inviati. Ora merge raw.

    Hot-reload: attivo al prossimo tick del bot.
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="payload deve essere un oggetto JSON")

    ov = _load_ov()

    # Task flags — merge solo chiavi esplicitamente presenti
    task_payload = raw.get("task") or {}
    task_updated_keys: list[str] = []
    if isinstance(task_payload, dict):
        for k, v in task_payload.items():
            if hasattr(ov.globali.task, k):
                setattr(ov.globali.task, k, bool(v))
                task_updated_keys.append(k)

    # Sistema — merge field-by-field (bug fix tick_sleep/max_parallel sovrascritti)
    sistema_payload = raw.get("sistema") or {}
    if isinstance(sistema_payload, dict):
        cur_sis = ov.globali.sistema
        for field in ("max_parallel", "tick_sleep_min"):
            if field in sistema_payload:
                try:
                    setattr(cur_sis, field, int(sistema_payload[field]))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400,
                                        detail=f"valore non numerico per {field}")

    # 08/05: skip_predictor_* RIMOSSI (regola "no skip istanza"). Eventuali
    # chiavi residue nel payload vengono ignorate silenziosamente.

    _save_ov(ov)
    return {
        "ok": True, "restart_required": False, "sezione": "globals",
        "task_updated": task_updated_keys,
    }


# ==============================================================================
# PUT /api/config/rifornimento — soglie, flag, modalità, coordinate
# ==============================================================================

@router.put("/rifornimento")
async def save_rifornimento(request: Request):
    """
    Aggiorna configurazione rifornimento — MERGE INCREMENTALE.

    Bug fix 08/05: pre-fix `PayloadRifornimento` aveva `default_factory` su
    sub-modelli → invio parziale → Pydantic rifabbricava il modello con default
    Pydantic (es. acciaio_abilitato=False, coord rifugio 687/532) sovrascrivendo
    i valori esistenti nel runtime_overrides.

    Post-fix: parse JSON raw, applica SOLO le chiavi effettivamente presenti.
    Backward compatible: client che inviano payload completo continuano a
    funzionare; client parziali preservano i campi non inviati.
    Hot-reload: attivo al prossimo tick.
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="payload deve essere un oggetto JSON")

    ov = _load_ov()

    # Sub-section "rifornimento_comune" — merge incrementale field-by-field
    rc_payload = raw.get("rifornimento_comune") or {}
    if isinstance(rc_payload, dict):
        cur_rc = ov.globali.rifornimento_comune
        for field in ("dooms_account", "max_spedizioni_ciclo",
                      "soglia_campo_m", "soglia_legno_m",
                      "soglia_petrolio_m", "soglia_acciaio_m",
                      "campo_abilitato", "legno_abilitato",
                      "petrolio_abilitato", "acciaio_abilitato"):
            if field in rc_payload:
                setattr(cur_rc, field, rc_payload[field])
        # Sub-sub: allocazione (anch'essa merge)
        alloc_payload = rc_payload.get("allocazione") or {}
        if isinstance(alloc_payload, dict):
            for field in ("pomodoro", "legno", "petrolio", "acciaio"):
                if field in alloc_payload:
                    setattr(cur_rc.allocazione, field,
                            float(alloc_payload[field]))

    # Sub-section "rifugio" — merge incrementale (preserva coord se non inviate)
    rifugio_payload = raw.get("rifugio") or {}
    if isinstance(rifugio_payload, dict):
        cur_r = ov.globali.rifugio
        for field in ("coord_x", "coord_y"):
            if field in rifugio_payload:
                setattr(cur_r, field, int(rifugio_payload[field]))

    # Modalità mutuamente esclusive: applica SOLO se almeno una è esplicitamente
    # presente nel payload (altrimenti preserva stato esistente)
    has_mappa = "mappa_abilitata" in raw
    has_membri = "membri_abilitati" in raw
    if has_mappa or has_membri:
        m = bool(raw.get("mappa_abilitata", False))
        mb = bool(raw.get("membri_abilitati", False))
        if m:
            ov.globali.rifornimento.mappa_abilitata  = True
            ov.globali.rifornimento.membri_abilitati = False
        elif mb:
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

# ==============================================================================
# POST /api/config/reset — ripristina runtime da static (regola 08/05)
# ==============================================================================

@router.post("/reset")
def reset_runtime_overrides() -> dict:
    """Cancella `runtime_overrides.json` e lo ricrea da static (`global_config.json`
    + `instances.json`).

    Equivalente a "reset configurazione runtime": tutti i valori dinamici
    correnti vengono persi e sostituiti dai valori static voluti dall'utente
    (set in `/ui/config/global`).

    Effetto: runtime_overrides.json sovrascritto. Bot legge nuovi valori al
    prossimo tick istanza (hot-reload).

    Vedi memoria `architecture_config_static_dynamic.md`.
    """
    try:
        from config.config_loader import bootstrap_runtime_from_static_if_missing
        ok = bootstrap_runtime_from_static_if_missing(force=True)
        if not ok:
            raise HTTPException(status_code=500, detail="bootstrap fallito")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")

    return {
        "ok": True,
        "msg": "runtime_overrides.json ricreato da static",
        "restart_required": False,
    }


@router.post("/promote")
def promote_runtime_to_static_endpoint() -> dict:
    """Promuove `runtime_overrides.json` → `global_config.json` + `instances.json`.

    Inverso del `/reset`: la configurazione runtime corrente (modifiche
    real-time fatte da HOME/card istanza) diventa il nuovo baseline statico.

    Preserva i campi del file static non gestiti dal runtime (mumu, _note,
    qta_*). Effetto: global_config.json + instances.json sovrascritti.

    Bot: nessun impatto immediato (legge dynamic). Si applica al prossimo
    bootstrap (file dynamic mancante) o reset esplicito.
    """
    try:
        from config.config_loader import promote_runtime_to_static
        result = promote_runtime_to_static()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")

    if result.get("error") and not (result.get("global_updated") and result.get("instances_updated")):
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "ok": True,
        "msg": "runtime promosso a static (global_config.json + instances.json)",
        "global_updated":    result.get("global_updated", False),
        "instances_updated": result.get("instances_updated", False),
        "warning": result.get("error"),  # non-fatal warning se uno dei due solo OK
    }


@router.put("/zaino")
async def save_zaino(request: Request):
    """
    Aggiorna configurazione zaino — MERGE INCREMENTALE (bug fix 08/05).
    Pre-fix `payload.zaino` aveva default_factory → invio parziale rifabbricava
    il modello sovrascrivendo flag risorsa/soglie ai default Pydantic.
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="payload deve essere un oggetto JSON")

    # Supporta sia wrapper "zaino" sia flat
    z_payload = raw.get("zaino") if isinstance(raw.get("zaino"), dict) else raw

    ov = _load_ov()
    cur_z = ov.globali.zaino
    for field in ("modalita", "usa_pomodoro", "usa_legno",
                  "usa_petrolio", "usa_acciaio",
                  "soglia_pomodoro_m", "soglia_legno_m",
                  "soglia_petrolio_m", "soglia_acciaio_m"):
        if field in z_payload:
            setattr(cur_z, field, z_payload[field])

    _save_ov(ov)
    return {"ok": True, "restart_required": False, "sezione": "zaino"}


# ==============================================================================
# PUT /api/config/allocazione — percentuali raccolta
# ==============================================================================

@router.put("/allocazione")
async def save_allocazione(request: Request):
    """
    Aggiorna percentuali allocazione raccolta — MERGE INCREMENTALE.

    Bug fix 08/05: pre-fix il payload aveva `default_factory=AllocazioneOverride`
    con default uniforme 25/25/25/25. Invio parziale (es. solo `pomodoro=35`)
    rifabbricava modello con default → altre risorse a 25.

    Post-fix: applica SOLO i field presenti nel JSON raw.
    Hot-reload: attivo al prossimo tick.
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="payload deve essere un oggetto JSON")

    ov = _load_ov()

    # Supporta sia payload con wrapper "allocazione" sia flat
    alloc_payload = raw.get("allocazione") if isinstance(raw.get("allocazione"), dict) else raw

    cur_alloc = ov.globali.raccolta.allocazione
    for field in ("pomodoro", "legno", "petrolio", "acciaio"):
        if field in alloc_payload:
            try:
                setattr(cur_alloc, field, float(alloc_payload[field]))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400,
                                    detail=f"valore non numerico per {field}")

    _save_ov(ov)

    totale = sum([cur_alloc.pomodoro, cur_alloc.legno,
                  cur_alloc.petrolio, cur_alloc.acciaio])
    return {
        "ok": True,
        "restart_required": False,
        "sezione": "allocazione",
        "totale_pct": round(totale, 1),
        "warn": None if abs(totale - 100.0) <= 0.5 else f"Totale {totale:.1f}% ≠ 100% — il bot normalizzerà",
    }


# ==============================================================================
# PUT /api/truppe-globali — default caserme globale (DYNAMIC, hot-reload)
# ==============================================================================

@router.put("/truppe-globali")
async def save_truppe_globali(request: Request):
    """Aggiorna caserme di default in `runtime_overrides.json::globali.truppe.caserme`.

    09/05: la pagina /ui/advanced opera su DYNAMIC (come gli altri controlli
    real-time della home), non su STATIC. Effetto al prossimo tick istanza.

    Payload atteso: `{caserme: {infantry: bool, rider: bool, ranged: bool, engine: bool}}`
    Tutti i campi opzionali — merge incrementale solo sulle chiavi inviate.
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="payload deve essere un oggetto JSON")

    cas_payload = raw.get("caserme")
    if not isinstance(cas_payload, dict):
        raise HTTPException(status_code=400, detail="caserme dict richiesto")

    ov = _load_ov()
    cur = ov.globali.truppe.caserme
    changed: list[str] = []
    for k in ("infantry", "rider", "ranged", "engine"):
        if k in cas_payload:
            setattr(cur, k, bool(cas_payload[k]))
            changed.append(k)
    _save_ov(ov)
    return {"ok": True, "restart_required": False, "sezione": "truppe-globali",
            "changed": changed}


# ==============================================================================
# PUT /api/truppe-istanze — override per-istanza caserme (DYNAMIC, hot-reload)
# ==============================================================================

@router.put("/truppe-istanze")
async def save_truppe_istanze(request: Request):
    """Aggiorna `runtime_overrides.json::istanze.<nome>.truppe_override.caserme`
    per ogni istanza listata. Hot-reload al prossimo tick.

    Payload: `{istanze: {<nome>: {truppe_override: {caserme: {...}} | None}}}`
    None = elimina override (eredita default globale).
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON non valido: {e}")
    ist_payload = (raw.get("istanze") or {})
    if not isinstance(ist_payload, dict):
        raise HTTPException(status_code=400, detail="istanze dict richiesto")

    ov = _load_ov()
    raw_ovr = get_overrides() or {}
    ist_raw = raw_ovr.setdefault("istanze", {})

    n_changed = 0
    for nome, body in ist_payload.items():
        if not isinstance(body, dict):
            continue
        cur = ist_raw.setdefault(nome, {})
        if not isinstance(cur, dict):
            cur = {}
            ist_raw[nome] = cur
        if "truppe_override" in body:
            tov = body["truppe_override"]
            if tov is None:
                cur["truppe_override"] = None
            elif isinstance(tov, dict):
                cas = (tov.get("caserme") or {})
                if isinstance(cas, dict):
                    cur["truppe_override"] = {
                        "caserme": {
                            k: bool(cas[k]) for k in ("infantry","rider","ranged","engine") if k in cas
                        }
                    }
            n_changed += 1

    # Save raw (preserva altri campi istanza)
    save_overrides(raw_ovr)
    return {"ok": True, "restart_required": False, "sezione": "truppe-istanze",
            "n_changed": n_changed}


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

    06/05: il payload non include `truppe_override` (gestito da endpoint
    /istanze/truppe dedicato). Per non cancellarlo, leggi prima i valori
    esistenti e fai merge campo-per-campo.

    Hot-reload: attivo al prossimo avvio istanza.
    """
    # 08/05 — REGOLA ARCHITETTURALE:
    # CONFIG (`/ui/config/global`) modifica SOLO i parametri iniziali (static).
    # I parametri runtime NON vengono toccati: i due piani entrano in match solo
    # in bootstrap (primo avvio senza runtime_overrides.json) o reset esplicito.
    # Questo garantisce che modifiche al "default voluto" non sovrascrivano lo
    # stato corrente del bot.
    # Vedi memoria `architecture_config_static_dynamic.md`.
    instances_updates: dict[str, dict] = {}
    for nome, ist_ov in payload.istanze.items():
        upd: dict = {}
        upd["abilitata"] = bool(ist_ov.abilitata)
        upd["truppe"] = int(ist_ov.truppe or 0)
        # tipologia (Enum) → profilo (str). `.value` evita "TipologiaIstanza.full"
        tip = ist_ov.tipologia
        upd["profilo"] = tip.value if hasattr(tip, "value") else str(tip)
        upd["raccolta_fuori_territorio"] = bool(ist_ov.raccolta_fuori_territorio)
        upd["master"] = bool(ist_ov.master)
        if ist_ov.fascia_oraria is not None:
            upd["fascia_oraria"] = ist_ov.fascia_oraria
        if ist_ov.max_squadre is not None:
            upd["max_squadre"] = ist_ov.max_squadre
        if ist_ov.livello is not None:
            upd["livello"] = ist_ov.livello
        instances_updates[nome] = upd

    # Invalida cache instance_meta (master flag potrebbe essere cambiato)
    try:
        from shared.instance_meta import invalidate_cache
        invalidate_cache()
    except Exception:
        pass

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
# PUT /api/config/istanze/truppe — override truppe per-istanza (06/05)
# ==============================================================================

@router.put("/istanze/truppe")
async def save_istanze_truppe(request: Request):
    """
    Aggiorna l'override truppe per istanza (campo `truppe_override`).

    08/05: secondo regola architetturale, questo endpoint è chiamato dalla
    sezione CONFIG `/ui/config/global` → scrive SOLO su `instances.json`
    (static). Il bot legge dynamic (runtime_overrides) durante l'esecuzione,
    quindi le modifiche diventano attive al prossimo bootstrap o reset.

    Payload atteso:
      { "istanze": {
            "FAU_00": { "truppe_override": { "caserme": {...} } | null },
            "FAU_01": { "truppe_override": null },   // reset → eredita globale
            ...
        } }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body invalido")
    payload_istanze = (body or {}).get("istanze") or {}
    if not isinstance(payload_istanze, dict):
        raise HTTPException(400, "campo 'istanze' deve essere dict")

    # Costruisci updates per save_instances_fields (scrive su instances.json)
    instances_updates: dict[str, dict] = {}
    aggiornate: list[str] = []
    for nome, patch in payload_istanze.items():
        if not isinstance(patch, dict):
            continue
        new_to = patch.get("truppe_override")
        if new_to is None:
            # Reset: rimuovi truppe_override → segnaliamo None (save lo gestirà)
            instances_updates[nome] = {"truppe_override": None}
        else:
            from dashboard.models import TruppeIstanzaOverride
            try:
                validated = TruppeIstanzaOverride.model_validate(new_to).model_dump()
            except Exception as exc:
                raise HTTPException(400, f"truppe_override invalido per {nome}: {exc}")
            instances_updates[nome] = {"truppe_override": validated}
        aggiornate.append(nome)

    if instances_updates:
        try:
            save_instances_fields(instances_updates)
        except Exception as e:
            raise HTTPException(500, f"scrittura instances.json fallita: {e}")

    return {
        "ok": True,
        "sezione": "istanze.truppe_override (static)",
        "aggiornate": aggiornate,
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
    Aggiorna i campi override di una singola istanza (HOME real-time).
    Merge con i valori esistenti (non sovrascrive tutto).

    08/05 fix: NON tocca `instances.json` (file statico). Le modifiche
    real-time dalla HOME vivono SOLO in `runtime_overrides.json`. Per
    modificare i default statici (instances.json) usare la sezione
    config tramite `PUT /api/config/istanze`.
    """
    ov = _load_ov()
    current      = ov.istanze.get(nome, IstanzaOverride())
    current_dict = current.model_dump()

    # 08/05: rimosso 'layout' (deprecato WU22)
    allowed = {"abilitata", "truppe", "tipologia", "fascia_oraria",
               "max_squadre", "livello", "raccolta_fuori_territorio"}
    for k, v in data.items():
        if k in allowed:
            current_dict[k] = v

    ov.istanze[nome] = IstanzaOverride.model_validate(current_dict)
    _save_ov(ov)

    return {"ok": True, "istanza": nome, "aggiornato": current_dict}
