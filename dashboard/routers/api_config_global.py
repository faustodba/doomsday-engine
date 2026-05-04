# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_config_global.py
#
#  Endpoint per global_config.json.
#  Prefix: /api/config
#
#  Modifiche a global_config.json richiedono restart del bot (banner in UI).
# ==============================================================================

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from dashboard.services.config_manager import (
    _GLOBAL_CONFIG_PATH, get_global_config, save_global_config,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _save_global_raw(data: dict) -> None:
    """Scrive global_config.json senza round-trip via GlobalConfig dataclass.
    Preserva campi che non sono nel dataclass (rifugio, rifornimento unificato,
    auto_learn_banner, raccolta_ocr_debug, soglia_allocazione, ecc.).
    Scrittura atomica (tmp + replace)."""
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="payload deve essere dict non vuoto")
    path = Path(_GLOBAL_CONFIG_PATH)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


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


@router.patch("/global")
def patch_global(data: dict):
    """
    Merge incrementale su global_config.json — sovrascrive solo le chiavi
    top-level presenti nel body, il resto del file resta invariato.

    Scrive dict raw (no round-trip via GlobalConfig dataclass), così
    preserva campi nuovi non ancora nel dataclass (rifugio, rifornimento
    unificato, auto_learn_banner, raccolta_ocr_debug, soglia_allocazione).
    """
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="payload deve essere dict non vuoto")
    # Read current raw JSON (preserva tutti i campi)
    try:
        with open(_GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"global_config.json non leggibile: {exc}")
    if not isinstance(current, dict):
        current = {}
    # Merge top-level (per dict nested, update superficiale; altro overwrite)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            current[k].update(v)
        else:
            current[k] = v
    try:
        _save_global_raw(current)
        return {"ok": True, "restart_required": True, "sezioni_aggiornate": list(data.keys())}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
