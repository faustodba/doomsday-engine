# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/config_manager.py
#
#  Unico punto della dashboard che scrive su disco i file di config.
#
#  Responsabilita':
#    - Read:  global_config.json, runtime_overrides.json, instances.json
#    - Write: global_config.json (via save_global del bot)
#             runtime_overrides.json (tmp+replace atomico)
#
#  instances.json e' READ-ONLY (la dashboard non lo modifica — richiede
#  restart del bot, gestito a livello UI).
#
#  Validazione prima della scrittura:
#    - global_config.json  : GlobalConfig._from_raw(data) dry-run
#    - runtime_overrides   : RuntimeOverrides.model_validate(data) Pydantic
#
#  Nessuna logica duplicata — riusa save_global/load_global/load_overrides
#  gia' testati in config.config_loader.
# ==============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# Import dal bot — non duplicare logica gia' esistente
from config.config_loader import (
    load_global,
    save_global,
    load_overrides,
    GlobalConfig,
)
from dashboard.models import RuntimeOverrides


# ==============================================================================
# Path costanti — coerenti con main.py (_ROOT/config/*)
# ==============================================================================
# dashboard/services/config_manager.py -> parents: [services, dashboard, project root]
_ROOT               = Path(__file__).parent.parent.parent
_GLOBAL_CONFIG_PATH = _ROOT / "config" / "global_config.json"
_OVERRIDES_PATH     = _ROOT / "config" / "runtime_overrides.json"
_INSTANCES_PATH     = _ROOT / "config" / "instances.json"


# ==============================================================================
# Read
# ==============================================================================

def get_global_config() -> dict:
    """
    Legge global_config.json e restituisce il dict raw (per la dashboard).
    Usa GlobalConfig.to_dict() per garantire struttura coerente con lo schema
    atteso dal bot (se il file su disco manca sezioni, i default vengono
    normalizzati attraverso _from_raw -> to_dict).
    Failsafe: {} su errore.
    """
    try:
        gcfg = load_global(_GLOBAL_CONFIG_PATH)
        return gcfg.to_dict()
    except Exception:
        return {}


def get_overrides() -> dict:
    """
    Legge runtime_overrides.json grezzo.
    Failsafe: {} su file assente/corrotto (delegato a load_overrides).
    """
    return load_overrides(_OVERRIDES_PATH)


def get_instances() -> list[dict]:
    """
    Legge instances.json. Read-only — la dashboard non scrive questo file
    (richiederebbe restart del bot per prendere effetto).
    Failsafe: [] su errore.
    """
    try:
        with open(_INSTANCES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_instance(nome: str) -> Optional[dict]:
    """Restituisce la voce di instances.json per nome, o None se assente."""
    return next(
        (i for i in get_instances() if i.get("nome") == nome),
        None,
    )


# ==============================================================================
# Write
# ==============================================================================

def save_global_config(data: dict) -> None:
    """
    Valida e salva global_config.json.

    Validazione (in ordine):
      1. data deve essere dict non vuoto
      2. GlobalConfig._from_raw(data) deve passare (dry-run di parsabilita')
      3. Scrittura atomica via save_global() del bot (tmp+replace interno)

    La firma di save_global e' (gcfg: GlobalConfig, path=...) -> bool: il
    dict viene prima convertito in GlobalConfig via _from_raw, poi passato.

    Solleva:
      ValueError  se data non e' un dict o non passa _from_raw
      IOError     se save_global ritorna False (scrittura fallita)
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("global_config: deve essere un dict non vuoto")
    try:
        gcfg_obj = GlobalConfig._from_raw(data)
    except Exception as exc:
        raise ValueError(f"global_config non valido: {exc}") from exc
    ok = save_global(gcfg_obj, path=_GLOBAL_CONFIG_PATH)
    if not ok:
        raise IOError(f"save_global: scrittura fallita su {_GLOBAL_CONFIG_PATH}")


def save_overrides(data: dict) -> None:
    """
    Valida e salva runtime_overrides.json.

    Validazione:
      1. data deve essere dict
      2. RuntimeOverrides.model_validate(data) deve passare (Pydantic)
      3. Scrittura atomica (tmp + os.replace)

    Solleva:
      ValueError  se data non e' dict o non valida il modello Pydantic
      IOError     su errori di scrittura (propagato)
    """
    if not isinstance(data, dict):
        raise ValueError("overrides: deve essere un dict")
    try:
        RuntimeOverrides.model_validate(data)
    except Exception as exc:
        raise ValueError(f"runtime_overrides non valido: {exc}") from exc
    # Scrittura atomica
    tmp = _OVERRIDES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, _OVERRIDES_PATH)
