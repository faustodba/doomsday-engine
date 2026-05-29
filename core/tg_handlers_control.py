"""core/tg_handlers_control.py — Handler comandi di controllo sistema.

Comandi: /pausa /riprendi /avvia_ora /restart_bot
         /avvia_bot /avvia_dashboard /avvia_tutto /restart_telegram
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from core.tg_utils import _check_bot_running, _check_dashboard_running, _root

_log = logging.getLogger(__name__)

# ─── Bat launchers ────────────────────────────────────────────────────────────

_ROOT_PROD    = _root()   # usa _root() per rispettare DOOMSDAY_ROOT env var
_BAT_BOT      = _ROOT_PROD / "start.bat"
_BAT_DASHBOARD = _ROOT_PROD / "run_dashboard_prod.bat"


def _launch_bat(bat_path: Path, label: str) -> tuple[bool, str]:
    """Lancia un bat file in una nuova finestra console indipendente."""
    import subprocess
    if not bat_path.exists():
        return False, f"{bat_path.name} non trovato in {bat_path.parent}"
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=str(bat_path.parent),
            close_fds=True,
        )
        return True, f"console aperta ('{label}')"
    except Exception as exc:
        return False, str(exc)


def _schedule_self_restart(delay_s: int = 5) -> None:
    """Spegne il processo bot Telegram dopo delay_s secondi (exit 100)."""
    def _do():
        time.sleep(delay_s)
        _log.info("[TG-BOT] restart programmato — os._exit(100)")
        os._exit(100)
    t = threading.Thread(target=_do, daemon=True, name="tg-self-restart")
    t.start()


# ─── Handler functions (signature: text -> str) ───────────────────────────────

def cmd_pausa(text: str) -> str:
    try:
        from core.maintenance import enable_maintenance
        enable_maintenance(motivo="Telegram /pausa", set_da="telegram")
        return "⏸ Maintenance mode attivato. Bot in pausa tra un'istanza e la successiva."
    except Exception as exc:
        return f"⚠ Errore /pausa: {exc}"


def cmd_riprendi(text: str) -> str:
    try:
        from core.maintenance import disable_maintenance
        disable_maintenance()
        return "▶ Maintenance mode disattivato. Bot riprende."
    except Exception as exc:
        return f"⚠ Errore /riprendi: {exc}"


def cmd_avvia_ora(text: str) -> str:
    if not _check_bot_running():
        return "🔴 Bot non in esecuzione. Usa /avvia_bot per avviarlo prima."
    flag = _root() / "data" / "wake_now.flag"
    try:
        flag.touch()
        return "▶ Segnale inviato — il bot salterà il sleep e avvierà il prossimo ciclo subito."
    except Exception as exc:
        return f"⚠ Errore /avvia_ora: {exc}"


def cmd_restart_bot(text: str) -> str:
    if not _check_bot_running():
        return "🔴 Bot non in esecuzione. Usa /avvia_bot per avviarlo."
    try:
        from core.restart_scheduler import request_restart, is_restart_requested
        if is_restart_requested():
            return "🔄 Restart già in coda. Usa /status per monitorare."
        ok = request_restart(reason="telegram")
        if ok:
            return (
                "🔄 <b>Restart bot richiesto.</b>\n"
                "Il bot uscirà a fine ciclo (exit code 100) e start.bat "
                "lo riavvierà automaticamente.\nUsa /status per monitorare."
            )
        return "⚠ Scrittura flag restart fallita. Controlla i log."
    except Exception as exc:
        return f"⚠ Errore /restart_bot: {exc}"


def cmd_avvia_bot(text: str) -> str:
    if _check_bot_running():
        return "🟢 Bot già in esecuzione. Usa /status per i dettagli."
    ok, msg = _launch_bat(_BAT_BOT, "Bot")
    if ok:
        return f"▶ Bot avviato — {msg}\nFinestra console aperta sul server.\nUsa /status tra 60s per verificare."
    return f"⚠ Avvio bot fallito: {msg}"


def cmd_avvia_dashboard(text: str) -> str:
    if _check_dashboard_running():
        return "🟢 Dashboard già in esecuzione su http://localhost:8765"
    ok, msg = _launch_bat(_BAT_DASHBOARD, "Dashboard")
    if ok:
        return f"▶ Dashboard avviata — {msg}\nDisponibile su http://localhost:8765"
    return f"⚠ Avvio dashboard fallito: {msg}"


def cmd_avvia_tutto(text: str) -> str:
    lines: list[str] = ["<b>Avvio sistema</b>"]
    bot_era_ok  = _check_bot_running()
    dash_era_ok = _check_dashboard_running()

    if bot_era_ok and dash_era_ok:
        return "🟢 Bot e Dashboard già in esecuzione. Usa /status per i dettagli."

    if not bot_era_ok:
        ok, msg = _launch_bat(_BAT_BOT, "Bot")
        lines.append(f"{'▶' if ok else '⚠'} Bot: {msg if ok else 'avvio fallito — ' + msg}")
    else:
        lines.append("🟢 Bot: già attivo")

    if not dash_era_ok:
        ok, msg = _launch_bat(_BAT_DASHBOARD, "Dashboard")
        lines.append(f"{'▶' if ok else '⚠'} Dashboard: {msg if ok else 'avvio fallito — ' + msg}")
    else:
        lines.append("🟢 Dashboard: già attiva")

    lines.append("\nUsa /status tra 60s per verificare i servizi.")
    return "\n".join(lines)


def cmd_restart_telegram(text: str) -> str:
    _schedule_self_restart(delay_s=5)
    return (
        "🔄 <b>Riavvio SERVIZIO TELEGRAM in 5s…</b>\n"
        "Il processo Telegram esce → <code>run_telegram_prod.bat</code> lo "
        "riavvia automaticamente dopo 10s.\n"
        "Downtime totale: ~15s. Il bot di gioco NON viene toccato."
    )
