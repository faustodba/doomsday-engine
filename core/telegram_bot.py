"""core/telegram_bot.py — Telegram bot: polling loop, lifecycle, notifiche proattive.

Architettura (moduli):
  telegram_bot.py          — questo file: polling loop, dispatch, lifecycle, notifiche
  tg_utils.py              — path helpers, config, readers, formatters, check processo
  tg_handlers_monitoring.py — comandi di sola lettura (status/istanze/cicli/produzione/rif)
  tg_handlers_control.py  — comandi di controllo sistema (pausa/restart/avvia)
  tg_handlers_config.py   — comandi di configurazione (task/istanze/rif_*/messaggi)

Comandi supportati:
  /help         — lista comandi
  /status       — stato ciclo corrente + istanze attive
  /istanze      — dettaglio per istanza (tipologia, task, raccolta)
  /istanza XXX  — card dettaglio singola istanza
  /produzione   — produzione 24h per istanza
  /rifornimento — DRL master + spedizioni oggi
  /cicli        — ultimi 5 cicli (in corso + 4 completati)
  /ciclo [N]    — dettaglio ciclo #N (ometti N per il più recente)
  /pausa        — attiva maintenance mode
  /riprendi     — disattiva maintenance mode
  /avvia_ora    — salta sleep inter-ciclo, avvia ciclo subito
  /restart_bot  — richiede restart bot al fine ciclo (via flag, riavvio programmato)
  /restart_telegram — riavvia il processo Telegram bot (~15s downtime)
  /avvia_bot    — avvia il bot (start.bat)
  /avvia_dashboard — avvia la dashboard
  /avvia_tutto  — avvia bot + dashboard
  /disabilita FAU_03 — disabilita istanza
  /abilita FAU_03    — abilita istanza
  /task                    — stato ON/OFF di ogni task
  /disabilita_task arena   — disabilita task
  /abilita_task arena      — abilita task
  /rif_risorsa  — abilita/disabilita risorsa rifornimento
  /rif_modo     — cambia modalità (mappa/membri/entrambi/nessuno)
  /rif_soglia   — cambia soglia deposito per risorsa
  /rif_provviste — cambia provviste_max
  /rif_reset    — azzera stato giornaliero rifornimento per istanza
  /stop_messaggi  — disabilita notifiche proattive
  /start_messaggi — abilita notifiche proattive
  /claude <domanda> — AI advisor via Claude Code CLI (abbonamento)
  /haiku  <domanda> — AI advisor via Claude Haiku API (pay-per-use)

Config (runtime_overrides.json::globali.notifications.telegram):
  {
    "enabled":              bool   (master toggle, default False)
    "notify_cycle_every_n": int    (notifica ogni N cicli completati, default 5)
    "notify_cascade":       bool   (notifica cascade ADB, default True)
    "notify_drl":           bool   (notifica DRL saturato, default True)
    "notify_daily_report":  bool   (forward daily report, default True)
  }

Token e chat_id: in data/secrets.json via shared.telegram_client.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_POLL_TIMEOUT_S   = 20   # long-polling timeout
_POLL_RETRY_SLEEP = 5    # sleep su errore prima di riprovare
_MAX_MSG_LEN      = 4000 # limite caratteri per messaggio TG

# ─── Stato globale thread ─────────────────────────────────────────────────────

_bot_thread:    Optional[threading.Thread] = None
_stop_event:    Optional[threading.Event]  = None
_update_offset: int = 0
_running_lock = threading.Lock()

# ─── Stato alert bot silenzioso ───────────────────────────────────────────────

_last_bot_ok:       bool  = True
_last_bot_check_ts: float = 0.0
_last_bot_alert_ts: float = 0.0
_bot_fail_streak:   int   = 0
_BOT_SILENT_CHECK_S   = 120
_BOT_SILENT_COOLDOWN_S = 900
_BOT_FAIL_THRESHOLD   = 3

# ─── Stato alert raccolta bassa ───────────────────────────────────────────────

_raccolta_alert_cicli: set[int] = set()

# ─── ForceReply tracking (AI commands senza argomenti) ───────────────────────
# {message_id: "/claude" | "/haiku"} — reply attese dall'utente
_force_reply_pending: dict[int, str] = {}

# ─── Instance lock ────────────────────────────────────────────────────────────

_PID_FILE: Optional[Path] = None


# ─── Imports handler modules ─────────────────────────────────────────────────

from core.tg_utils import (
    _check_bot_running, _check_dashboard_running,
    _fmt_dur, _get_uptime_s, _notify_cascade, _notify_cycle_every_n,
    _notify_daily_report_flag, _notify_drl, _root,
    _tg_enabled,
)
from core.tg_handlers_monitoring import (
    cmd_cicli, cmd_ciclo, cmd_depositi, cmd_istanza, cmd_istanze,
    cmd_produzione, cmd_rifornimento, cmd_status,
)
from core.tg_handlers_control import (
    _BAT_BOT, _BAT_DASHBOARD,
    _schedule_self_restart,
    cmd_avvia_bot, cmd_avvia_dashboard, cmd_avvia_tutto,
    cmd_avvia_ora, cmd_pausa, cmd_restart_bot, cmd_restart_telegram,
    cmd_riprendi,
)
from core.tg_handlers_config import (
    cmd_abilita, cmd_abilita_task,
    cmd_disabilita, cmd_disabilita_task,
    cmd_rif_modo, cmd_rif_provviste, cmd_rif_reset,
    cmd_rif_risorsa, cmd_rif_soglia,
    cmd_start_messaggi, cmd_stop_messaggi, cmd_task,
)
from core.tg_handlers_ai import cmd_claude, cmd_haiku, cmd_credit


# ─── /help handler ────────────────────────────────────────────────────────────

def _cmd_help(text: str) -> str:
    msg_icon  = "🔔" if _tg_enabled()               else "🔕"
    bot_icon  = "🟢" if _check_bot_running()         else "🔴"
    dash_icon = "🟢" if _check_dashboard_running()   else "🔴"
    return (
        "<b>Comandi disponibili</b>\n"
        "\n"
        "<b>Informazioni</b> (sola lettura)\n"
        "/status — stato completo (bot, dashboard, ciclo, DRL)\n"
        "/istanze — lista istanze ON/OFF con istanza live\n"
        "/istanza FAU_03 — card dettaglio singola istanza\n"
        "/produzione — produzione 24h per istanza\n"
        "/rifornimento — DRL + spedizioni oggi + config\n"
        "/depositi — risorse deposito di tutte le farm\n"
        "/cicli — ultimi 5 cicli (in corso + 4 completati)\n"
        "/ciclo 184 — dettaglio ciclo #184 (ometti per l'ultimo)\n"
        "\n"
        f"<b>Avvio sistema</b> (bot {bot_icon}  dashboard {dash_icon})\n"
        "/avvia_bot       → <code>start.bat</code> (kill orfani + MuMu + ADB + resume)\n"
        "/avvia_dashboard → <code>run_dashboard_prod.bat</code>\n"
        "/avvia_tutto     → <code>start.bat</code> + <code>run_dashboard_prod.bat</code>\n"
        "\n"
        "<b>Bot management</b>\n"
        "/pausa           → <code>data/maintenance.flag</code> (pausa tra istanze)\n"
        "/riprendi        → rimuove <code>data/maintenance.flag</code>\n"
        "/avvia_ora       → <code>data/wake_now.flag</code> (salta sleep inter-ciclo)\n"
        "/restart_bot     → <code>data/restart_requested.flag</code> → exit 100 a fine ciclo → <code>start.bat :loop</code> (riavvio programmato)\n"
        "/restart_telegram → exit 100 → <code>run_telegram_prod.bat :loop</code> (~15s)\n"
        "\n"
        "<b>Istanze</b> → <code>runtime_overrides.json</code> (hot-reload)\n"
        "/disabilita FAU_03 — disabilita istanza\n"
        "/abilita FAU_03    — abilita istanza\n"
        "\n"
        "<b>Task globali</b> → <code>runtime_overrides.json</code> (hot-reload)\n"
        "/task                    — stato ON/OFF di ogni task\n"
        "/disabilita_task arena   — disabilita task\n"
        "/abilita_task arena      — abilita task\n"
        "\n"
        "<b>Rifornimento</b>\n"
        "/rif_risorsa acciaio off  → <code>runtime_overrides.json</code>\n"
        "/rif_modo mappa           → <code>runtime_overrides.json</code>\n"
        "/rif_soglia acciaio 3.5   → <code>runtime_overrides.json</code>\n"
        "/rif_provviste 80         → <code>runtime_overrides.json</code>\n"
        "/rif_reset FAU_03         → <code>state/FAU_03.json</code> (azzera giornaliero)\n"
        "/rif_reset                → <code>state/*.json</code> (azzera tutte)\n"
        "\n"
        f"<b>Notifiche proattive</b> (ora: {msg_icon}) → <code>runtime_overrides.json</code>\n"
        "/stop_messaggi  — disabilita notifiche automatiche\n"
        "/start_messaggi — abilita notifiche automatiche\n"
        "\n"
        "<b>AI Advisor</b> (contesto farm live)\n"
        "/claude &lt;domanda&gt; — Claude Code CLI (abbonamento, gratuito)\n"
        "/haiku  &lt;domanda&gt; — Claude Haiku API (pay-per-use, ~$0.002/query)\n"
        "/credit             — utilizzo API: costo oggi, totale, storico 7gg\n"
        "\n"
        "/help — questo messaggio"
    )


# ─── Command dispatch ─────────────────────────────────────────────────────────

_DISPATCH: dict[str, Callable[[str], str]] = {
    "/help":              _cmd_help,
    # Monitoraggio
    "/status":            cmd_status,
    "/istanze":           cmd_istanze,
    "/istanza":           cmd_istanza,
    "/produzione":        cmd_produzione,
    "/rifornimento":      cmd_rifornimento,
    "/depositi":          cmd_depositi,
    "/cicli":             cmd_cicli,
    "/ciclo":             cmd_ciclo,
    # Controllo
    "/pausa":             cmd_pausa,
    "/riprendi":          cmd_riprendi,
    "/avvia_ora":         cmd_avvia_ora,
    "/restart_bot":       cmd_restart_bot,
    "/avvia_bot":         cmd_avvia_bot,
    "/avvia_dashboard":   cmd_avvia_dashboard,
    "/avvia_tutto":       cmd_avvia_tutto,
    "/restart_telegram":  cmd_restart_telegram,
    "/restart_bot_telegram": cmd_restart_telegram,
    # Config
    "/stop_messaggi":     cmd_stop_messaggi,
    "/start_messaggi":    cmd_start_messaggi,
    "/disabilita":        cmd_disabilita,
    "/abilita":           cmd_abilita,
    "/task":              cmd_task,
    "/disabilita_task":   cmd_disabilita_task,
    "/abilita_task":      cmd_abilita_task,
    "/rif_risorsa":       cmd_rif_risorsa,
    "/rif_modo":          cmd_rif_modo,
    "/rif_soglia":        cmd_rif_soglia,
    "/rif_provviste":     cmd_rif_provviste,
    "/rif_reset":         cmd_rif_reset,
    # AI advisor
    "/claude":            cmd_claude,
    "/haiku":             cmd_haiku,
    "/credit":            cmd_credit,
}


def _handle_command(text: str, chat_id: str) -> str:
    cmd     = text.split()[0].lower().rstrip("@")
    handler = _DISPATCH.get(cmd)
    if handler:
        return handler(text)
    return f"Comando non riconosciuto: <code>{cmd}</code>\nUsa /help per la lista comandi."


# ─── Polling loop ─────────────────────────────────────────────────────────────

def _polling_loop(stop: threading.Event) -> None:
    """Loop polling principale.

    I comandi sono sempre attivi indipendentemente da telegram.enabled.
    Il flag enabled controlla SOLO le notifiche proattive (_send_notify).
    """
    global _update_offset, _last_bot_ok, _last_bot_check_ts, _last_bot_alert_ts, _bot_fail_streak

    from shared.telegram_client import get_updates, send_message, load_chat_id, has_token

    _log.info("[TG-BOT] polling loop avviato")
    authorized_chat = load_chat_id()

    # Delay primo check bot silenzioso: aspetta almeno 1 ciclo (~120s) dal boot
    _last_bot_check_ts = time.time()

    while not stop.is_set():
        if not has_token():
            time.sleep(15)
            authorized_chat = load_chat_id()
            continue

        _t_poll = time.time()
        try:
            updates = get_updates(offset=_update_offset, timeout_s=_POLL_TIMEOUT_S)
        except Exception as exc:
            _log.warning("[TG-BOT] get_updates errore: %s", exc)
            time.sleep(_POLL_RETRY_SLEEP)
            continue

        # Risposta vuota in <5s = errore swallowed (es. 409) — backoff
        if not updates and (time.time() - _t_poll) < 5:
            time.sleep(_POLL_RETRY_SLEEP)
            continue

        authorized_chat = load_chat_id()

        for upd in updates:
            _update_offset = upd.get("update_id", _update_offset) + 1
            msg  = upd.get("message")
            if not msg:
                continue
            chat = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()

            if not authorized_chat:
                _log.warning("[TG-BOT] chat_id non configurato — messaggio ignorato da %s", chat)
                continue
            if chat != authorized_chat:
                _log.warning("[TG-BOT] messaggio da chat non autorizzato: %s", chat)
                continue

            # ── ForceReply: risposta a un comando AI senza argomenti ──────────
            reply_to = msg.get("reply_to_message", {})
            reply_to_id = reply_to.get("message_id") if reply_to else None
            if reply_to_id and reply_to_id in _force_reply_pending and not text.startswith("/"):
                cmd_origin = _force_reply_pending.pop(reply_to_id)
                _log.info("[TG-BOT] ForceReply per %s: %s", cmd_origin, text[:60])
                try:
                    reply = _handle_command(f"{cmd_origin} {text}", chat)
                except Exception as exc:
                    reply = f"⚠ Errore interno: {exc}"
                send_message(chat, reply[:_MAX_MSG_LEN])
                continue

            if not text.startswith("/"):
                continue

            _log.info("[TG-BOT] comando da %s: %s", chat, text[:80])
            try:
                reply = _handle_command(text, chat)
            except Exception as exc:
                reply = f"⚠ Errore interno: {exc}"
            # Per ForceReply: se il reply è un prompt (messaggio_id != None),
            # salvarlo nel tracking prima di inviarlo
            if isinstance(reply, tuple):
                # (testo, force_reply_cmd) — formato speciale da cmd_claude/cmd_haiku
                reply_text, force_cmd = reply
                from shared.telegram_client import send_force_reply
                msg_id = send_force_reply(chat, reply_text)
                if msg_id:
                    _force_reply_pending[msg_id] = force_cmd
            else:
                send_message(chat, reply[:_MAX_MSG_LEN])

        # ── Check bot silenzioso (ogni _BOT_SILENT_CHECK_S secondi) ──────────
        try:
            _now = time.time()
            if _now - _last_bot_check_ts >= _BOT_SILENT_CHECK_S:
                _last_bot_check_ts = _now
                _bot_now = _check_bot_running()
                if _bot_now:
                    _bot_fail_streak = 0
                    _last_bot_ok     = True
                else:
                    _bot_fail_streak += 1
                    if _last_bot_ok and _bot_fail_streak >= _BOT_FAIL_THRESHOLD:
                        if _now - _last_bot_alert_ts >= _BOT_SILENT_COOLDOWN_S:
                            _last_bot_alert_ts = _now
                            _last_bot_ok       = False
                            _send_system_alert(
                                "🔴 <b>Bot fermato inaspettatamente</b>\n\n"
                                "L'engine non risulta più in esecuzione.\n"
                                "Usa /avvia_bot per riavviarlo o /status per dettagli."
                            )
        except Exception:
            pass

    _log.info("[TG-BOT] polling loop terminato")


# ─── Lifecycle ────────────────────────────────────────────────────────────────

def start() -> bool:
    global _bot_thread, _stop_event
    with _running_lock:
        if _bot_thread and _bot_thread.is_alive():
            return False
        _stop_event = threading.Event()
        _bot_thread = threading.Thread(
            target=_polling_loop,
            args=(_stop_event,),
            name="TelegramBot",
            daemon=True,
        )
        _bot_thread.start()
        _log.info("[TG-BOT] avviato")
        return True


def stop(timeout_s: float = 3.0) -> None:
    global _stop_event
    if _stop_event:
        _stop_event.set()
    if _bot_thread:
        _bot_thread.join(timeout=timeout_s)
    _log.info("[TG-BOT] fermato")


def is_running() -> bool:
    return bool(_bot_thread and _bot_thread.is_alive())


# ─── Notifiche proattive ──────────────────────────────────────────────────────

def _send_notify(text: str) -> bool:
    """Invia notifica al chat_id configurato. No-op se TG non abilitato."""
    if not _tg_enabled():
        return False
    try:
        from shared.telegram_client import send_message, load_chat_id
        chat_id = load_chat_id()
        if not chat_id:
            _log.warning("[TG-BOT] notify: chat_id non configurato")
            return False
        return send_message(chat_id, text[:_MAX_MSG_LEN])
    except Exception as exc:
        _log.warning("[TG-BOT] notify fallita: %s", exc)
        return False


def notify_cycle_complete(ciclo_n: int,
                          n_istanze: int,
                          tot_marce: int,
                          tot_sped: int,
                          durata_s: float) -> bool:
    every_n = _notify_cycle_every_n()
    if every_n <= 0 or (ciclo_n % every_n) != 0:
        return False
    text = (
        f"♻ <b>Ciclo #{ciclo_n} completato</b>\n"
        f"Istanze: {n_istanze}  |  Marce: {tot_marce}  |  Spedizioni: {tot_sped}\n"
        f"Durata: {_fmt_dur(durata_s)}"
    )
    return _send_notify(text)


def notify_cascade_adb(instance: str, details: str = "") -> bool:
    if not _notify_cascade():
        return False
    text = f"⚡ <b>Cascade ADB</b> — {instance}"
    if details:
        text += f"\n{details[:200]}"
    return _send_notify(text)


def notify_drl_saturo(residuo_m: float = 0.0) -> bool:
    if not _notify_drl():
        return False
    text = f"🔴 <b>DRL FauMorfeus saturo</b> — residuo {residuo_m:.0f}M\nRifornimento bloccato fino a reset (00:00 UTC)"
    return _send_notify(text)


def notify_daily_report(report_text: str) -> bool:
    if not _notify_daily_report_flag():
        return False
    header    = "📊 <b>Daily Report</b>\n"
    available = _MAX_MSG_LEN - len(header)
    body      = report_text[:available]
    return _send_notify(header + body)


def notify_alert(title: str, body: str = "", severity: str = "warn",
                 instance: str = "") -> bool:
    """Notifica Telegram generica per alert real-time senza formatter dedicato
    (heartbeat_cicli, maintenance_lunga, restart_inatteso). Prima questi eventi
    non avevano canale Telegram in trigger_alert. Gated da telegram.enabled
    via _send_notify."""
    icon = {"info": "ℹ️", "warn": "⚠️", "error": "❗", "critical": "🚨"}.get(
        (severity or "warn").lower(), "•")
    text = f"{icon} <b>{title}</b>"
    if instance:
        text += f" — {instance}"
    if body:
        text += f"\n{body}"
    return _send_notify(text)


def notify_raccolta_bassa(ciclo_n: int) -> bool:
    """Alert se >=3 istanze hanno slot liberi ma 0 marce. Deduplicato per ciclo."""
    global _raccolta_alert_cicli
    if ciclo_n in _raccolta_alert_cicli:
        return False

    p = _root() / "data" / "istanza_metrics.jsonl"
    if not p.exists():
        return False

    last: dict[str, dict] = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r    = json.loads(line)
                nome = r.get("instance", "")
                if nome and nome != "FauMorfeus":
                    last[nome] = r
            except Exception:
                pass
    except Exception:
        return False

    problemi: list[str] = []
    for nome, r in last.items():
        racc    = r.get("raccolta", {})
        attive  = racc.get("attive_pre", -1)
        totali  = racc.get("totali", -1)
        n_invii = len(racc.get("invii", []))
        if attive >= 0 and totali > 0 and attive < totali and n_invii == 0:
            problemi.append(nome)

    if len(problemi) < 3:
        return False

    _raccolta_alert_cicli.add(ciclo_n)
    if len(_raccolta_alert_cicli) > 10:
        _raccolta_alert_cicli = set(sorted(_raccolta_alert_cicli)[-10:])

    nomi_str = ", ".join(sorted(problemi))
    text = (
        f"⚠ <b>Raccolta bassa — ciclo #{ciclo_n}</b>\n\n"
        f"{len(problemi)} istanze con slot liberi ma 0 marce:\n"
        f"<code>{nomi_str}</code>\n\n"
        "Possibili cause: blacklist satura, territorio esaurito, task bloccato."
    )
    return _send_notify(text)


# ─── System alert (sempre, ignora enabled) ───────────────────────────────────

def _send_system_alert(text: str) -> bool:
    try:
        from shared.telegram_client import send_message, load_chat_id
        chat_id = load_chat_id()
        if not chat_id:
            return False
        return send_message(chat_id, text[:_MAX_MSG_LEN])
    except Exception as exc:
        _log.warning("[TG-BOT] system alert fallita: %s", exc)
        return False


def _notify_startup() -> None:
    uptime  = _get_uptime_s()
    bot_ok  = _check_bot_running()
    dash_ok = _check_dashboard_running()

    if 0 < uptime < 300:
        ctx = f"⚡ <b>Riavvio PC rilevato</b> (uptime {_fmt_dur(uptime)})"
    else:
        ctx = f"▶ Telegram bot avviato"
        if uptime > 0:
            ctx += f" (uptime PC {_fmt_dur(uptime)})"

    bot_line  = "🟢 Bot: ATTIVO"       if bot_ok  else "🔴 Bot: non avviato"
    dash_line = "🟢 Dashboard: ATTIVA" if dash_ok else "🔴 Dashboard: non avviata"

    azioni: list[str] = []
    if not bot_ok and not dash_ok:
        azioni = ["/avvia_tutto — avvia bot + dashboard"]
    else:
        if not bot_ok:
            azioni.append("/avvia_bot — avvia il bot")
        if not dash_ok:
            azioni.append("/avvia_dashboard — avvia la dashboard")

    lines = [ctx, "", bot_line, dash_line]
    if azioni:
        lines.append("")
        lines.append("<b>Avvio rapido:</b>")
        lines.extend(azioni)

    _send_system_alert("\n".join(lines))


# ─── Instance lock (evita doppio polling → errore 409) ───────────────────────

def _acquire_lock() -> bool:
    global _PID_FILE
    import subprocess
    pid_path = _root() / "data" / "telegram_bot.pid"
    my_pid   = os.getpid()

    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text(encoding="utf-8").strip())
            if old_pid != my_pid:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     f"(Get-Process -Id {old_pid} -ErrorAction SilentlyContinue) -ne $null"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.stdout.strip() == "True":
                    _log.warning("[TG-BOT] Altra istanza in esecuzione (PID %d) — uscita per evitare 409.", old_pid)
                    return False
                _log.info("[TG-BOT] PID file stale (PID %d) — sovrascrittura.", old_pid)
        except Exception:
            pass

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(my_pid), encoding="utf-8")
    _PID_FILE = pid_path
    return True


def _release_lock() -> None:
    if _PID_FILE and _PID_FILE.exists():
        try:
            _PID_FILE.unlink()
        except Exception:
            pass


# ─── Entry point standalone ────────────────────────────────────────────────────

if __name__ == "__main__":
    import signal
    import sys

    _logs_dir = _root() / "logs"
    _logs_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _logs_dir / "telegram_service.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(_log_file), encoding="utf-8"),
        ],
    )

    _log.info("=== Telegram bot service avviato (standalone, root=%s) ===", _root())

    if not _acquire_lock():
        _log.error("[TG-BOT] Uscita: istanza già in esecuzione.")
        sys.exit(1)

    _svc_stop = threading.Event()

    def _on_signal(sig, frame):
        _log.info("Segnale %s ricevuto — stop", sig)
        _svc_stop.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    start()

    def _delayed_startup_notify():
        time.sleep(8)
        _log.info("[TG-BOT] invio notifica startup...")
        _notify_startup()

    threading.Thread(target=_delayed_startup_notify, daemon=True,
                     name="TgStartupNotify").start()

    _svc_stop.wait()
    stop(timeout_s=5)
    _release_lock()
    _log.info("=== Telegram bot service terminato ===")
