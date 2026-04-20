# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_config_overrides.py
#
#  Endpoint per runtime_overrides.json.
#  Prefix: /api/config
#
#  Hot-reload: modifiche attive al prossimo turno istanza (no restart).
# ==============================================================================

from fastapi import APIRouter, HTTPException

from dashboard.models import RuntimeOverrides, IstanzaOverride
from dashboard.services.config_manager import get_overrides, save_overrides

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/overrides", response_model=RuntimeOverrides)
def read_overrides():
    """
    Legge runtime_overrides.json.
    Hot-reload: modifiche attive al prossimo turno istanza (senza restart).
    """
    raw = get_overrides()
    return RuntimeOverrides.model_validate(raw) if raw else RuntimeOverrides()


@router.put("/overrides", response_model=dict)
def write_overrides(data: RuntimeOverrides):
    """
    Sovrascrive runtime_overrides.json.
    Pydantic valida in ingresso. 422 automatico su payload invalido.
    Hot-reload: nessun restart richiesto.
    """
    try:
        save_overrides(data.model_dump())
        return {"ok": True, "restart_required": False}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/overrides/task/{task_name}")
def toggle_task(task_name: str, abilitato: bool):
    """
    Toggle singolo task flag senza sovrascrivere tutto il file.
    Utile per la UI: switch on/off rapido da overview.
    """
    valid_tasks = {
        "alleanza", "messaggi", "vip", "radar", "radar_census",
        "rifornimento", "rifornimento_mappa", "zaino",
        "arena", "arena_mercato", "boost", "store",
    }
    if task_name not in valid_tasks:
        raise HTTPException(status_code=404,
                            detail=f"Task '{task_name}' non riconosciuto")
    raw = get_overrides()
    ov  = RuntimeOverrides.model_validate(raw) if raw else RuntimeOverrides()
    setattr(ov.globali.task, task_name, abilitato)
    try:
        save_overrides(ov.model_dump())
        return {"ok": True, "task": task_name, "abilitato": abilitato}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/overrides/istanze/{nome}")
def patch_istanza(nome: str, data: dict):
    """
    Aggiorna i campi override di una singola istanza.
    Merge con i valori esistenti (non sovrascrive tutto).
    Campi accettati: abilitata, truppe, tipologia, fascia_oraria.
    """
    raw = get_overrides()
    ov  = RuntimeOverrides.model_validate(raw) if raw else RuntimeOverrides()
    current      = ov.istanze.get(nome, IstanzaOverride())
    current_dict = current.model_dump()
    # Merge: solo i campi presenti in data sovrascrivono
    allowed = {"abilitata", "truppe", "tipologia", "fascia_oraria"}
    for k, v in data.items():
        if k in allowed:
            current_dict[k] = v
    ov.istanze[nome] = IstanzaOverride.model_validate(current_dict)
    try:
        save_overrides(ov.model_dump())
        return {"ok": True, "istanza": nome, "aggiornato": current_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
