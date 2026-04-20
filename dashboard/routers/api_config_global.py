# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_config_global.py
#
#  Endpoint per global_config.json.
#  Prefix: /api/config
#
#  Modifiche a global_config.json richiedono restart del bot (banner in UI).
# ==============================================================================

from fastapi import APIRouter, HTTPException

from dashboard.services.config_manager import get_global_config, save_global_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/global")
def read_global():
    """
    Legge global_config.json normalizzato.
    Read-only per la dashboard in questa versione.
    Modifiche a global_config richiedono restart bot — banner in UI.
    """
    return get_global_config()


@router.put("/global")
def write_global(data: dict):
    """
    Sovrascrive global_config.json.
    Valida via GlobalConfig._from_raw prima di scrivere.
    422 su validazione fallita, 500 su errore I/O.
    """
    try:
        save_global_config(data)
        return {"ok": True, "restart_required": True}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))
