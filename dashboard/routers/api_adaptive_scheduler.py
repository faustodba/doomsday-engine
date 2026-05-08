"""
dashboard/routers/api_adaptive_scheduler.py — endpoint Adaptive Scheduler.

Endpoints:
  GET   /api/adaptive-scheduler         — status completo (flag, soglie, live, reasons)
  PATCH /api/adaptive-scheduler         — modifica flag + soglie

Schema config:
    globali.adaptive_scheduler_enabled       bool
    globali.adaptive_scheduler_shadow_only   bool
    globali.adaptive_scheduler_thresholds.{drl_residuo_pct, pct_istanze_sat, spedizioni_oggi}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["adaptive-scheduler"])


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _runtime_overrides_path() -> Path:
    return _root() / "config" / "runtime_overrides.json"


def _read_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json_atomic(p: Path, data: dict) -> bool:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


@router.get("/adaptive-scheduler")
def get_adaptive_scheduler() -> dict:
    """Status corrente: flag + soglie + valori live + scheduler.active."""
    try:
        from core.adaptive_scheduler import get_status
        return get_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


@router.get("/adaptive-scheduler/preview")
def preview_adaptive_scheduler() -> dict:
    """Simulazione live dell'ordine pianificato dal scheduler.

    Calcola greedy l'ordine attuale per le istanze abilitate (master in fondo)
    + carica eventuale ordine persisted in `data/scheduler_planned_order.json`.

    Returns:
        {
          "now_iso":         str,
          "ordine_live":     [ {ist, score, slot_liberi_atteso, slot_liberi_now,
                                 totali, attive_now, rientro_atteso,
                                 t_avvio_min, anzianita_tick_min,
                                 elapsed_min, t_residue_min, data_completa,
                                 is_master}, ... ],
          "ordine_persisted": dict | None,   # ordine ciclo corrente (se in volo)
          "active":          bool,
          "shadow_only":     bool,
          "enabled":         bool,
          "reasons":         list[str],
        }
    """
    try:
        from core.adaptive_scheduler import (
            get_status, ordina_istanze_adaptive, load_planned_order,
        )
        from dashboard.services.config_manager import get_instances
        from dashboard.services.config_manager import get_overrides

        status = get_status()
        all_ist = get_instances() or []
        ov_ist = ((get_overrides() or {}).get("istanze") or {})

        # Filtro: solo istanze abilitate (override > static)
        nomi: list[str] = []
        for i in all_ist:
            nome = i.get("nome", "")
            if not nome:
                continue
            ov = ov_ist.get(nome) or {}
            on = ov.get("abilitata", i.get("abilitata", True))
            if on:
                nomi.append(nome)

        from datetime import datetime, timezone
        ordine_live = ordina_istanze_adaptive(nomi)
        persisted = load_planned_order()

        return {
            "now_iso":          datetime.now(timezone.utc).isoformat(),
            "ordine_live":      ordine_live,
            "ordine_persisted": persisted,
            "active":           status.get("active", False),
            "shadow_only":      status.get("shadow_only", False),
            "enabled":          status.get("enabled", False),
            "reasons":          status.get("reasons", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


class AdaptiveSchedulerPatch(BaseModel):
    enabled:                    Optional[bool] = None
    shadow_only:                Optional[bool] = None
    threshold_drl_residuo_m:    Optional[int]  = None
    threshold_pct_istanze_sat:  Optional[int]  = None
    threshold_spedizioni_oggi:  Optional[int]  = None


def _global_config_path() -> Path:
    return _root() / "config" / "global_config.json"


@router.patch("/adaptive-scheduler")
def patch_adaptive_scheduler(payload: AdaptiveSchedulerPatch) -> dict:
    """Merge superficiale dei field non-None su `global_config.json` (STATIC).

    08/05: regola architetturale "config modifica solo static". Questa card è
    in `/ui/config/global` → scrive su global_config.json. Le modifiche diventano
    attive al prossimo bootstrap o reset (banner UI lo specifica).
    """
    gc_path = _global_config_path()
    gc = _read_json(gc_path)
    changed: dict = {}

    if payload.enabled is not None:
        gc["adaptive_scheduler_enabled"] = bool(payload.enabled)
        changed["enabled"] = bool(payload.enabled)
    if payload.shadow_only is not None:
        gc["adaptive_scheduler_shadow_only"] = bool(payload.shadow_only)
        changed["shadow_only"] = bool(payload.shadow_only)

    # Thresholds (validati). 08/05: drl_residuo_m sostituisce drl_residuo_pct.
    # Cleanup automatico: se la chiave legacy è ancora presente, rimossa.
    th = gc.setdefault("adaptive_scheduler_thresholds", {})
    if payload.threshold_drl_residuo_m is not None:
        v = int(payload.threshold_drl_residuo_m)
        if not (0 <= v <= 10000):
            raise HTTPException(status_code=400,
                                detail="drl_residuo_m fuori 0-10000 (M)")
        th["drl_residuo_m"] = v
        changed["drl_residuo_m"] = v
        if "drl_residuo_pct" in th:
            del th["drl_residuo_pct"]
    if payload.threshold_pct_istanze_sat is not None:
        v = int(payload.threshold_pct_istanze_sat)
        if not (0 <= v <= 100):
            raise HTTPException(status_code=400, detail="pct_istanze_sat fuori 0-100")
        th["pct_istanze_sat"] = v
        changed["pct_istanze_sat"] = v
    if payload.threshold_spedizioni_oggi is not None:
        v = int(payload.threshold_spedizioni_oggi)
        if v < 0:
            raise HTTPException(status_code=400, detail="spedizioni_oggi < 0")
        th["spedizioni_oggi"] = v
        changed["spedizioni_oggi"] = v

    if not changed:
        return {"ok": True, "changed": {}, "msg": "nessuna modifica"}

    if not _write_json_atomic(gc_path, gc):
        raise HTTPException(status_code=500,
                            detail="scrittura global_config.json fallita")

    return {"ok": True, "changed": changed,
            "target": "static", "applies_after": "bootstrap_or_reset"}
