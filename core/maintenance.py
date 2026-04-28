# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/maintenance.py                            WU51
#
#  Modalità manutenzione/aggiornamento del bot.
#
#  Pattern: file flag su disco. Quando il file esiste, il bot pausa tra
#  un'istanza e la successiva (mai interrompe tick in corso). Polling 5s
#  per riprendere automaticamente quando file rimosso.
#
#  STORAGE
#    data/maintenance.flag  — file JSON con metadata
#    Schema: {
#      "active":     true,
#      "ts_attivato": "2026-04-27T22:30:00+00:00",
#      "motivo":      "aggiornamento WU51",
#      "set_da":      "dashboard"
#    }
#
#  USO BOT (main.py loop):
#    while not stop_event.is_set():
#        ...inizio ciclo...
#        for ist in istanze_ciclo:
#            wait_if_maintenance(stop_event, log_fn)  # blocca se attivo
#            ...processa istanza...
#
#  USO DASHBOARD:
#    enable_maintenance(motivo="aggiornamento", set_da="dashboard")
#    disable_maintenance()
#    info = get_maintenance_info()  # → dict | None
# ==============================================================================

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


def _flag_path() -> Path:
    """Risolve il path del file flag — coerente con orchestrator."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "maintenance.flag"


def is_maintenance_active() -> bool:
    """True se il file flag esiste."""
    try:
        return _flag_path().exists()
    except Exception:
        return False


def get_maintenance_info() -> Optional[dict]:
    """
    Ritorna il contenuto del file flag se attivo, None altrimenti.
    Failsafe: file corrotto → ritorna comunque {} per indicare attivo.
    """
    try:
        path = _flag_path()
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}  # file presente ma corrotto: meglio considerare attivo
    except Exception:
        return None


def enable_maintenance(
    motivo: str = "",
    set_da: str = "manual",
    auto_resume_ts: Optional[str] = None,
) -> bool:
    """
    Attiva la modalità manutenzione. Scrive data/maintenance.flag.

    Args:
        motivo: descrizione (es. "aggiornamento WU51")
        set_da: chi ha attivato ("dashboard", "manual", "cli", ecc.)
        auto_resume_ts: ISO timestamp UTC opzionale per auto-resume (WU54).
                        Quando supera now() il flag viene rimosso automatic.

    Returns:
        True se scritto, False su errore.
    """
    try:
        path = _flag_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active":      True,
            "ts_attivato": datetime.now(timezone.utc).isoformat(),
            "motivo":      str(motivo or "").strip()[:200],
            "set_da":      str(set_da or "manual")[:50],
        }
        if auto_resume_ts:
            payload["auto_resume_ts"] = str(auto_resume_ts)
        tmp = path.with_suffix(".flag.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def enable_maintenance_with_auto_resume(
    eta_seconds: int,
    motivo: str = "",
    set_da: str = "auto",
) -> bool:
    """
    WU54 — Attiva maintenance con auto-resume dopo `eta_seconds`.
    Usata da launcher quando rileva popup MAINTENANCE gioco.

    Calcola auto_resume_ts = now + eta_seconds e lo persiste nel flag.
    `wait_if_maintenance` controllerà questo ts e rimuoverà flag automatic.
    """
    from datetime import timedelta
    eta_s = max(60, int(eta_seconds))  # min 1 min sanity
    resume_ts = (datetime.now(timezone.utc) + timedelta(seconds=eta_s)).isoformat()
    return enable_maintenance(
        motivo=motivo,
        set_da=set_da,
        auto_resume_ts=resume_ts,
    )


def disable_maintenance() -> bool:
    """Disattiva la modalità manutenzione (rimuove il file flag)."""
    try:
        path = _flag_path()
        if path.exists():
            path.unlink()
        return True
    except Exception:
        return False


def _check_auto_resume(info: dict) -> bool:
    """
    WU54 — Auto-resume: se `auto_resume_ts` è settato e superato → rimuove
    flag automaticamente. Returns True se ha rimosso il flag.
    """
    ar_ts = info.get("auto_resume_ts")
    if not ar_ts:
        return False
    try:
        resume_dt = datetime.fromisoformat(ar_ts)
        if datetime.now(timezone.utc) >= resume_dt:
            disable_maintenance()
            return True
    except Exception:
        pass
    return False


def wait_if_maintenance(
    stop_event,
    log_fn: Optional[Callable[[str], None]] = None,
    poll_s: int = 5,
) -> bool:
    """
    Blocca finché modalità manutenzione è attiva (polling `poll_s`).
    Rispetta stop_event: se settato durante l'attesa, esce subito.

    WU54 — Se il flag ha `auto_resume_ts`, viene rimosso automaticamente
    quando il timestamp è superato (utile per maintenance gioco con countdown).

    Returns:
        True se il bot deve fermarsi (stop_event), False per proseguire.
    """
    if not is_maintenance_active():
        return False

    info = get_maintenance_info() or {}
    motivo  = info.get("motivo", "")
    set_da  = info.get("set_da", "?")
    auto_rs = info.get("auto_resume_ts", "")

    # Check auto-resume PRIMA di entrare in pausa (potrebbe essere già scaduto)
    if _check_auto_resume(info):
        if log_fn:
            log_fn(f"[MAINT] flag scaduto (auto_resume_ts={auto_rs[:19]}) → rimosso, riprendo")
        return False

    if log_fn:
        ar_lbl = f" auto_resume={auto_rs[:19]}" if auto_rs else ""
        log_fn(f"[MAINT] modalità manutenzione attiva (set_da={set_da}, motivo={motivo!r}){ar_lbl} — pausa")

    waited_s = 0
    while is_maintenance_active():
        if stop_event and stop_event.is_set():
            if log_fn:
                log_fn(f"[MAINT] stop_event ricevuto durante manutenzione → uscita")
            return True

        # WU54 — check auto-resume periodicamente
        info = get_maintenance_info() or {}
        if _check_auto_resume(info):
            if log_fn:
                log_fn(f"[MAINT] auto-resume scaduto dopo {waited_s}s — riprendo")
            return False

        time.sleep(poll_s)
        waited_s += poll_s
        if waited_s % 60 == 0 and log_fn:
            ar_lbl = f" (auto_resume={auto_rs[:19]})" if auto_rs else ""
            log_fn(f"[MAINT] ancora in pausa ({waited_s}s){ar_lbl}")

    if log_fn:
        log_fn(f"[MAINT] modalità manutenzione disattivata dopo {waited_s}s — riprendo")
    return False
