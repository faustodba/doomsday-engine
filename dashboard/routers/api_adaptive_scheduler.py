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


class AdaptiveSchedulerPatch(BaseModel):
    enabled:                    Optional[bool] = None
    shadow_only:                Optional[bool] = None
    threshold_drl_residuo_pct:  Optional[int]  = None
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

    # Thresholds (validati)
    th = gc.setdefault("adaptive_scheduler_thresholds", {})
    if payload.threshold_drl_residuo_pct is not None:
        v = int(payload.threshold_drl_residuo_pct)
        if not (0 <= v <= 100):
            raise HTTPException(status_code=400, detail="drl_residuo_pct fuori 0-100")
        th["drl_residuo_pct"] = v
        changed["drl_residuo_pct"] = v
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
