# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/config_manager.py
#
#  Unico punto della dashboard che legge e scrive i file di config.
#
#  Responsabilità:
#    Read:  global_config.json, runtime_overrides.json, instances.json
#    Write: runtime_overrides.json (tmp+replace atomico)
#           instances.json         (tmp+replace atomico — solo campi strutturali)
#
#  global_config.json è READ-ONLY dalla dashboard nella nuova architettura:
#    tutti i parametri vengono scritti su runtime_overrides.json che il bot
#    legge ad ogni tick tramite merge_config().
#
#  save_instances_fields() scrive su instances.json solo i campi
#    max_squadre, layout, livello — che non sono presenti in runtime_overrides.
#    Tutti gli altri campi per-istanza (abilitata, truppe, tipologia,
#    fascia_oraria) vengono scritti su runtime_overrides.json.
# ==============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from config.config_loader import (
    load_global,
    save_global,
    load_overrides,
    GlobalConfig,
)
from dashboard.models import RuntimeOverrides


# ==============================================================================
# Path costanti
# ==============================================================================

_ROOT               = Path(__file__).parent.parent.parent
_PROD_ROOT          = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_GLOBAL_CONFIG_PATH = _PROD_ROOT / "config" / "global_config.json"
_OVERRIDES_PATH     = _PROD_ROOT / "config" / "runtime_overrides.json"
_INSTANCES_PATH     = _PROD_ROOT / "config" / "instances.json"


# ==============================================================================
# Read
# ==============================================================================

def get_global_config() -> dict:
    """
    Legge global_config.json normalizzato via GlobalConfig._from_raw.
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
    Failsafe: {} su file assente/corrotto.
    """
    return load_overrides(_OVERRIDES_PATH)


def get_merged_config() -> dict:
    """
    Restituisce la configurazione merged (global_config + runtime_overrides)
    esattamente come la vede il bot ad ogni tick.
    Usato dalla dashboard per mostrare valori reali (Issue #18).

    Nota: raccolta.allocazione nel merged è in formato percentuali 0-100
    (come salvato da `AllocazioneOverride`). Il template UI lavora in
    percentuali senza conversione.
    """
    try:
        from config.config_loader import merge_config
        gcfg = get_global_config()
        ovr  = get_overrides()
        return merge_config(gcfg, ovr)
    except Exception:
        return get_global_config()


def get_instances() -> list[dict]:
    """
    Legge instances.json. Failsafe: [] su errore.
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
# Write — runtime_overrides.json
# ==============================================================================

def save_overrides(data: dict) -> None:
    """
    Valida e salva runtime_overrides.json.

    Validazione:
      1. data deve essere dict
      2. RuntimeOverrides.model_validate(data) deve passare (Pydantic)
      3. Scrittura atomica (tmp + os.replace)

    Solleva:
      ValueError  se data non è dict o non valida
      IOError     su errori di scrittura
    """
    if not isinstance(data, dict):
        raise ValueError("overrides: deve essere un dict")
    try:
        RuntimeOverrides.model_validate(data)
    except Exception as exc:
        raise ValueError(f"runtime_overrides non valido: {exc}") from exc

    tmp = _OVERRIDES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, _OVERRIDES_PATH)


# ==============================================================================
# Write — instances.json (solo campi strutturali)
# ==============================================================================

def save_instances_fields(updates: dict[str, dict]) -> None:
    """
    Aggiorna campi strutturali in instances.json per le istanze specificate.

    Args:
        updates: dict nome_istanza → dict campi da aggiornare.
                 Campi ammessi: max_squadre, layout, livello.
                 Esempio: {"FAU_00": {"max_squadre": 5, "livello": 7}}

    Scrittura atomica (tmp + os.replace).
    Solleva IOError su errori di scrittura.
    """
    # WU50 — raccolta_fuori_territorio è un default statico per-istanza
    allowed_fields = {"max_squadre", "layout", "livello", "raccolta_fuori_territorio"}

    # Filtra solo campi ammessi
    filtered: dict[str, dict] = {}
    for nome, campi in updates.items():
        campi_ok = {k: v for k, v in campi.items() if k in allowed_fields}
        if campi_ok:
            filtered[nome] = campi_ok

    if not filtered:
        return  # nulla da scrivere

    # Carica instances.json corrente
    instances = get_instances()
    if not instances:
        raise IOError(f"instances.json non trovato o vuoto: {_INSTANCES_PATH}")

    # Applica aggiornamenti
    aggiornate = []
    for ist in instances:
        nome = ist.get("nome", "")
        if nome in filtered:
            for campo, valore in filtered[nome].items():
                ist[campo] = valore
            aggiornate.append(nome)

    if not aggiornate:
        return  # nessuna istanza trovata — non è un errore

    # Scrittura atomica
    tmp = _INSTANCES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(instances, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, _INSTANCES_PATH)


# ==============================================================================
# Write — global_config.json (legacy — mantenuto per retrocompatibilità)
# ==============================================================================

def save_global_config(data: dict) -> None:
    """
    Valida e salva global_config.json.
    Mantenuto per retrocompatibilità con api_config_global.py.
    Nella nuova architettura la dashboard scrive su runtime_overrides.json.

    Solleva:
      ValueError  se data non è dict o non passa _from_raw
      IOError     se save_global ritorna False
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
