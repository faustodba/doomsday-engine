# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/restart_scheduler.py
# ==============================================================================
#
#  Restart scheduler: decide se il bot deve uscire (con exit code 100) per
#  permettere a run_prod.bat di riavviarlo automaticamente. Il check avviene
#  SOLO post-chiusura ciclo completo (mai mid-tick) per garantire state
#  coerente e nessuna squadra interrotta.
#
#  TRIGGER (in OR, primo che scatta vince):
#    1. File flag `data/restart_requested.flag` — set da dashboard endpoint
#       `/api/restart-bot`. Cancellato al boot del nuovo bot.
#    2. Schedule cron-like — config `globali.restart_schedule_hh_mm` (es. "03:00").
#       Scatta se l'ora corrente UTC corrisponde all'orario configurato e non
#       e' gia' scattato in questa giornata.
#    3. Cicli max — config `globali.restart_after_cicli` (es. 200). Scatta dopo
#       N cicli completi dal boot. Anti memory-leak / refresh ADB.
#
#  EXIT CODE: 100 → run_prod.bat lo cattura e riavvia. Altri exit code (0
#  normale, 1 errore) NON triggernano restart automatico.
#
#  STATE: data/restart_state.json — contatore cicli + ultimo ts schedule
#         scattato (per evitare doppio-scatto stesso giorno).
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


EXIT_CODE_RESTART = 100


def _root() -> Path:
    """Risolve la root del progetto (DOOMSDAY_ROOT env o cwd)."""
    return Path(os.environ.get("DOOMSDAY_ROOT", os.getcwd()))


def _flag_path() -> Path:
    return _root() / "data" / "restart_requested.flag"


def _state_path() -> Path:
    return _root() / "data" / "restart_state.json"


# ──────────────────────────────────────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    """Carica state restart (best-effort, ritorna dict vuoto su errore)."""
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    """Salva state restart (atomic write)."""
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def init_boot() -> None:
    """
    Init al boot del bot. Cancella eventuali flag pendenti dal restart
    precedente e azzera il contatore cicli.
    """
    flag = _flag_path()
    if flag.exists():
        try:
            flag.unlink()
        except Exception:
            pass
    state = _load_state()
    state["boot_ts"] = datetime.now(timezone.utc).isoformat()
    state["cicli_da_boot"] = 0
    _save_state(state)


def mark_cycle_completed(ciclo_numero: int) -> None:
    """Incrementa contatore cicli post-boot. Chiamato a fine ciclo."""
    state = _load_state()
    state["cicli_da_boot"] = int(state.get("cicli_da_boot", 0)) + 1
    state["ultimo_ciclo_numero"] = int(ciclo_numero)
    state["ultimo_ciclo_ts"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


def request_restart(reason: str = "manual") -> bool:
    """
    Richiesta esterna di restart (es. da dashboard). Crea file flag che
    `should_restart_now()` rilevera' al prossimo check.
    Ritorna True se la flag e' stata creata.
    """
    try:
        flag = _flag_path()
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(json.dumps({
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def is_restart_requested() -> bool:
    """True se file flag presente (richiesta restart pendente)."""
    return _flag_path().exists()


# ──────────────────────────────────────────────────────────────────────────────
# Decision logic
# ──────────────────────────────────────────────────────────────────────────────

def _read_config() -> dict:
    """Legge config restart da runtime_overrides.json::globali."""
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        if not ov_path.exists():
            return {}
        ov = json.loads(ov_path.read_text(encoding="utf-8"))
        return ov.get("globali", {}) or {}
    except Exception:
        return {}


def _check_schedule_trigger(globali: dict) -> Optional[str]:
    """
    Controlla trigger schedule (`restart_schedule_hh_mm` formato "HH:MM" UTC).
    Scatta se ora corrente >= ora schedule e non gia' scattato oggi.
    Ritorna reason string se scattato, None altrimenti.
    """
    sched = globali.get("restart_schedule_hh_mm")
    if not sched or not isinstance(sched, str):
        return None
    try:
        hh, mm = sched.split(":")
        hh = int(hh); mm = int(mm)
    except Exception:
        return None

    now = datetime.now(timezone.utc)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < target:
        return None

    # Evita doppio-scatto stesso giorno
    state = _load_state()
    last_sched_iso = state.get("ultimo_schedule_ts")
    if last_sched_iso:
        try:
            last_sched_dt = datetime.fromisoformat(last_sched_iso)
            if last_sched_dt.date() == now.date() and last_sched_dt >= target:
                return None
        except Exception:
            pass

    # Scatta + persisti
    state["ultimo_schedule_ts"] = now.isoformat()
    _save_state(state)
    return f"schedule_{sched}_UTC"


def _check_cicli_max_trigger(globali: dict) -> Optional[str]:
    """
    Controlla trigger cicli max (`restart_after_cicli`).
    Scatta se cicli_da_boot >= soglia.
    """
    soglia = globali.get("restart_after_cicli")
    if not soglia or not isinstance(soglia, int) or soglia <= 0:
        return None
    state = _load_state()
    cicli = int(state.get("cicli_da_boot", 0))
    if cicli >= soglia:
        return f"cicli_max_{cicli}>={soglia}"
    return None


def should_restart_now() -> tuple[bool, str]:
    """
    Valuta tutti i trigger e ritorna (True, reason) se uno scatta.
    Chiamato dal main loop a fine ciclo, post `chiudi_tick` ultima istanza.

    Ordine priorita':
      1. File flag (richiesta esterna esplicita)
      2. Schedule cron-like
      3. Cicli max

    Returns:
        (True, reason) → bot deve uscire con exit code 100
        (False, "")    → continua loop normale
    """
    # 1. File flag esterno
    if is_restart_requested():
        try:
            flag_data = json.loads(_flag_path().read_text(encoding="utf-8"))
            reason = flag_data.get("reason", "manual")
        except Exception:
            reason = "manual"
        return True, f"flag:{reason}"

    globali = _read_config()

    # 2. Schedule cron-like
    sched_reason = _check_schedule_trigger(globali)
    if sched_reason:
        return True, sched_reason

    # 3. Cicli max
    cicli_reason = _check_cicli_max_trigger(globali)
    if cicli_reason:
        return True, cicli_reason

    return False, ""
