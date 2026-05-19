"""core/telegram_bot.py — Telegram bot loop + comandi + notifiche proattive.

Architettura:
  - Thread daemon in background che fa long-polling getUpdates ogni 20s
  - Solo messaggi dal chat_id configurato vengono processati (security gate)
  - Notifiche proattive: chiamate esterne che inviano messaggi al chat_id

Comandi supportati:
  /help         — lista comandi
  /status       — stato ciclo corrente + istanze attive
  /istanze      — dettaglio per istanza (tipologia, task, raccolta)
  /rifornimento — DRL master + spedizioni oggi
  /stop         — attiva maintenance mode
  /avvia        — disattiva maintenance mode

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
from typing import Optional

_log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_POLL_TIMEOUT_S   = 20   # long-polling timeout
_POLL_RETRY_SLEEP = 5    # sleep su errore prima di riprovare
_MAX_MSG_LEN      = 4000 # limite caratteri per messaggio TG

# ─── Stato globale thread ─────────────────────────────────────────────────────

_bot_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event]  = None
_update_offset: int = 0
_running_lock = threading.Lock()


# ─── Path helpers ─────────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _read_json_safe(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ─── Config helpers ───────────────────────────────────────────────────────────

def _tg_config() -> dict:
    """Ritorna config telegram da runtime_overrides (DYNAMIC, hot-reload)."""
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        ov = _read_json_safe(ov_path)
        return ov.get("globali", {}).get("notifications", {}).get("telegram", {})
    except Exception:
        return {}


def _tg_enabled() -> bool:
    """True se le notifiche proattive sono abilitate."""
    return bool(_tg_config().get("enabled", False))


def _set_messaggi_enabled(enabled: bool) -> bool:
    """Scrive telegram.enabled in runtime_overrides.json (DYNAMIC, hot-reload).

    Ritorna True se scrittura OK.
    """
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        try:
            ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}
        except Exception:
            ov = {}
        tg = ov.setdefault("globali", {}).setdefault("notifications", {}).setdefault("telegram", {})
        tg["enabled"] = enabled
        tmp = ov_path.with_suffix(ov_path.suffix + ".tmp")
        tmp.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ov_path)
        return True
    except Exception as exc:
        _log.warning("[TG-BOT] _set_messaggi_enabled fallito: %s", exc)
        return False


def _notify_cycle_every_n() -> int:
    return int(_tg_config().get("notify_cycle_every_n", 5))


def _notify_cascade() -> bool:
    return bool(_tg_config().get("notify_cascade", True))


def _notify_drl() -> bool:
    return bool(_tg_config().get("notify_drl", True))


def _notify_daily_report() -> bool:
    return bool(_tg_config().get("notify_daily_report", True))


# ─── Data readers (per comandi /status /istanze /rifornimento) ────────────────

def _read_engine_status() -> dict:
    """Legge engine_status.json dal ROOT del bot."""
    p = _root() / "engine_status.json"
    return _read_json_safe(p)


def _read_morfeus_state() -> dict:
    p = _root() / "data" / "morfeus_state.json"
    return _read_json_safe(p)


def _read_runtime_overrides() -> dict:
    p = _root() / "config" / "runtime_overrides.json"
    return _read_json_safe(p)


def _read_state(instance: str) -> dict:
    p = _root() / "state" / f"{instance}.json"
    return _read_json_safe(p)


def _read_cicli() -> list:
    p = _root() / "data" / "telemetry" / "cicli.json"
    d = _read_json_safe(p)
    return d.get("cicli", [])


def _maintenance_info() -> Optional[dict]:
    try:
        from core.maintenance import get_maintenance_info
        return get_maintenance_info()
    except Exception:
        return None


def _fmt_dur(s: float) -> str:
    """Formatta durata in min o h/min."""
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


# ─── Formatters comandi ───────────────────────────────────────────────────────

def _build_status() -> str:
    """Risposta al comando /status."""
    lines: list[str] = ["<b>Stato Doomsday Engine</b>"]

    # Stato messaggi proattivi (on/off)
    msg_on = _tg_enabled()
    lines.append(f"Messaggi: {'🔔 ON' if msg_on else '🔕 OFF'} "
                 f"({'usa /stop_messaggi per disabilitare' if msg_on else 'usa /start_messaggi per abilitare'})")

    # Maintenance mode
    maint = _maintenance_info()
    if maint and maint.get("active"):
        lines.append("⏸ <b>MAINTENANCE MODE</b> attivo")
        lines.append(f"  Motivo: {maint.get('motivo', '—')}")

    # Engine status — rileva se bot è fermo (stale > 10 min)
    es = _read_engine_status()
    _BOT_STALE_S = 600  # 10 minuti senza aggiornamento = bot fermo
    if not es:
        lines.append("🔴 <b>Bot: SPENTO</b> (engine_status.json assente)")
    else:
        ts_raw = es.get("ts_update", "")
        ago_s: int = 0
        ts_str = "—"
        if ts_raw:
            try:
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                ago_s = int((datetime.now(timezone.utc) - dt).total_seconds())
                ts_str = _fmt_dur(ago_s)
            except Exception:
                pass

        if ago_s > _BOT_STALE_S:
            lines.append(f"🔴 <b>Bot: SPENTO</b> (ultimo aggiornamento {ts_str} fa)")
        else:
            lines.append(f"🟢 <b>Bot: ATTIVO</b> (aggiornato {ts_str} fa)")

        # Ciclo corrente (solo se bot attivo)
        if ago_s <= _BOT_STALE_S:
            cicli = _read_cicli()
            if cicli:
                ultimo = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[0]
                n = ultimo.get("cycle_n", "?")
                start = ultimo.get("start_ts", "")
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        dur = (datetime.now(timezone.utc) - dt).total_seconds()
                        lines.append(f"Ciclo #{n} in corso da {_fmt_dur(dur)}")
                    except Exception:
                        lines.append(f"Ciclo #{n}")

        # Istanze (sempre mostrate — dati su disco persistono)
        istanze_st = es.get("istanze", {})
        n_tot = len(istanze_st)
        n_ok = sum(1 for v in istanze_st.values() if v.get("abilitata", True))
        lines.append(f"Istanze: {n_tot} totali, {n_ok} abilitate")

    # Dashboard
    dash_ok = _check_dashboard_running()
    lines.append("🟢 Dashboard: ATTIVA" if dash_ok else "🔴 Dashboard: non avviata")

    # DRL master
    morf = _read_morfeus_state()
    drl = morf.get("daily_recv_limit", -1)
    drl_max = morf.get("daily_recv_limit_max", -1)
    if drl >= 0:
        drl_pct = int((drl / drl_max * 100)) if drl_max > 0 else 0
        icon = "🔴" if drl == 0 else ("🟡" if drl_pct < 20 else "🟢")
        lines.append(f"DRL master: {icon} {drl/1e6:.0f}M / {drl_max/1e6:.0f}M ({drl_pct}%)")

    # Suggerimento avvio rapido se qualcosa è spento
    if not _check_bot_running() or not dash_ok:
        lines.append("")
        lines.append("Usa /avvia_tutto per avviare i servizi spenti")

    return "\n".join(lines)


def _build_istanze() -> str:
    """Risposta al comando /istanze."""
    es = _read_engine_status()
    ov = _read_runtime_overrides()
    istanze_ov = ov.get("istanze", {})

    if not es:
        return "⚠ engine_status.json non disponibile (bot fermo?)"

    ist_status = es.get("istanze", {})
    lines: list[str] = ["<b>Istanze</b>"]

    for nome in sorted(ist_status.keys()):
        ist_ov = istanze_ov.get(nome, {})
        abilitata = ist_ov.get("abilitata", True)
        tipologia = ist_ov.get("tipologia", "full")
        max_sq = ist_ov.get("max_squadre", "?")

        st = ist_status.get(nome, {})
        outcome = st.get("last_outcome", "—")
        raccolta_invii = st.get("raccolta_last_invii", "?")

        icon = "✅" if abilitata else "❌"
        icon_out = {"ok": "✓", "cascade": "⚡", "abort": "✗"}.get(outcome, "—")

        lines.append(
            f"{icon} <b>{nome}</b> [{tipologia}] sq={max_sq}"
            f"  {icon_out} invii={raccolta_invii}"
        )

    return "\n".join(lines)


def _build_rifornimento() -> str:
    """Risposta al comando /rifornimento."""
    lines: list[str] = ["<b>Rifornimento</b>"]

    # DRL master
    morf = _read_morfeus_state()
    drl = morf.get("daily_recv_limit", -1)
    drl_max = morf.get("daily_recv_limit_max", -1)
    ts_drl = morf.get("ts_ultima_lettura", "")
    if drl >= 0:
        drl_pct = int((drl / drl_max * 100)) if drl_max > 0 else 0
        icon = "🔴" if drl == 0 else ("🟡" if drl_pct < 20 else "🟢")
        ts_str = ""
        if ts_drl:
            try:
                dt = datetime.fromisoformat(ts_drl.replace("Z", "+00:00"))
                ago = int((datetime.now(timezone.utc) - dt).total_seconds())
                ts_str = f" ({_fmt_dur(ago)} fa)"
            except Exception:
                pass
        lines.append(f"DRL FauMorfeus: {icon} {drl/1e6:.0f}M / {drl_max/1e6:.0f}M ({drl_pct}%){ts_str}")
    else:
        lines.append("DRL FauMorfeus: non disponibile")

    # Spedizioni per istanza (oggi)
    ov = _read_runtime_overrides()
    istanze_ov = ov.get("istanze", {})
    tot_sped = 0
    righe_ist: list[str] = []
    for nome in sorted(istanze_ov.keys()):
        if nome == "FauMorfeus":
            continue
        st = _read_state(nome)
        rif = st.get("rifornimento", {})
        sped_oggi = rif.get("spedizioni_oggi", 0)
        tot_sped += sped_oggi
        if sped_oggi > 0:
            # Calcola netto totale oggi
            det = rif.get("dettaglio_oggi", {})
            netto_tot = sum(v.get("qta_inviata", 0) for v in det.values()) / 1e6
            righe_ist.append(f"  {nome}: {sped_oggi} sped, {netto_tot:.1f}M netti")

    lines.append(f"Spedizioni totali oggi: {tot_sped}")
    if righe_ist:
        lines.extend(righe_ist[:10])  # max 10 istanze mostrate
    elif tot_sped == 0:
        lines.append("  (nessuna spedizione ancora oggi)")

    return "\n".join(lines)


# ─── Command dispatcher ───────────────────────────────────────────────────────

def _handle_command(text: str, chat_id: str) -> str:
    """Processa un comando e ritorna la risposta da inviare."""
    cmd = text.split()[0].lower().rstrip("@")

    if cmd == "/help":
        msg_icon = "🔔" if _tg_enabled() else "🔕"
        bot_icon  = "🟢" if _check_bot_running()       else "🔴"
        dash_icon = "🟢" if _check_dashboard_running() else "🔴"
        return (
            "<b>Comandi disponibili</b>\n"
            "\n"
            "<b>Informazioni</b>\n"
            "/status — stato completo (bot, dashboard, ciclo, DRL)\n"
            "/istanze — dettaglio per istanza (tipologia, invii)\n"
            "/rifornimento — DRL master FauMorfeus + spedizioni oggi\n"
            "\n"
            f"<b>Avvio sistema</b> (bot {bot_icon}  dashboard {dash_icon})\n"
            "/avvia_bot — avvia il bot (run_prod.bat)\n"
            "/avvia_dashboard — avvia la dashboard (uvicorn)\n"
            "/avvia_tutto — avvia bot + dashboard\n"
            "\n"
            "<b>Bot management</b>\n"
            "/stop — attiva maintenance mode (bot in pausa)\n"
            "/avvia — disattiva maintenance mode (bot riprende)\n"
            "\n"
            f"<b>Notifiche proattive</b> (ora: {msg_icon})\n"
            "/stop_messaggi — disabilita notifiche automatiche\n"
            "/start_messaggi — abilita notifiche automatiche\n"
            "\n"
            "/help — questo messaggio"
        )

    if cmd == "/status":
        try:
            return _build_status()
        except Exception as exc:
            return f"⚠ Errore /status: {exc}"

    if cmd == "/istanze":
        try:
            return _build_istanze()
        except Exception as exc:
            return f"⚠ Errore /istanze: {exc}"

    if cmd == "/rifornimento":
        try:
            return _build_rifornimento()
        except Exception as exc:
            return f"⚠ Errore /rifornimento: {exc}"

    if cmd == "/stop":
        try:
            from core.maintenance import enable_maintenance
            enable_maintenance(motivo="Telegram /stop", set_da="telegram")
            return "⏸ Maintenance mode attivato. Bot in pausa tra un'istanza e la successiva."
        except Exception as exc:
            return f"⚠ Errore /stop: {exc}"

    if cmd == "/avvia":
        try:
            from core.maintenance import disable_maintenance
            disable_maintenance()
            return "▶ Maintenance mode disattivato. Bot riprende."
        except Exception as exc:
            return f"⚠ Errore /avvia: {exc}"

    if cmd == "/stop_messaggi":
        if not _tg_enabled():
            return "🔕 Notifiche già disabilitate. Usa /start_messaggi per riattivarle."
        ok = _set_messaggi_enabled(False)
        if ok:
            return "🔕 Notifiche proattive disabilitate.\nUsa /start_messaggi per riattivarle."
        return "⚠ Errore durante la disabilitazione. Controlla i log."

    if cmd == "/start_messaggi":
        if _tg_enabled():
            return "🔔 Notifiche già abilitate. Usa /stop_messaggi per disabilitarle."
        ok = _set_messaggi_enabled(True)
        if ok:
            return "🔔 Notifiche proattive abilitate.\nRiceverai: ciclo completato, cascade ADB, DRL saturo, daily report."
        return "⚠ Errore durante l'abilitazione. Controlla i log."

    if cmd == "/avvia_bot":
        if _check_bot_running():
            return "🟢 Bot già in esecuzione. Usa /status per i dettagli."
        ok, msg = _launch_bat(_BAT_BOT, "Bot")
        if ok:
            return f"▶ Bot avviato — {msg}\nFinestra console aperta sul server.\nUsa /status tra 60s per verificare."
        return f"⚠ Avvio bot fallito: {msg}"

    if cmd == "/avvia_dashboard":
        if _check_dashboard_running():
            return "🟢 Dashboard già in esecuzione su http://localhost:8765"
        ok, msg = _launch_bat(_BAT_DASHBOARD, "Dashboard")
        if ok:
            return f"▶ Dashboard avviata — {msg}\nDisponibile su http://localhost:8765"
        return f"⚠ Avvio dashboard fallito: {msg}"

    if cmd == "/avvia_tutto":
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

    return f"Comando non riconosciuto: <code>{cmd}</code>\nUsa /help per la lista comandi."


# ─── Polling loop ─────────────────────────────────────────────────────────────

def _polling_loop(stop: threading.Event) -> None:
    """Loop polling principale.

    Nota: i comandi sono sempre attivi indipendentemente da `telegram.enabled`.
    Il flag `enabled` controlla SOLO le notifiche proattive (in _send_notify).
    Il polling gira se il token è configurato, anche con messaggi OFF.
    """
    global _update_offset

    from shared.telegram_client import get_updates, send_message, load_chat_id, has_token

    _log.info("[TG-BOT] polling loop avviato")
    authorized_chat = load_chat_id()

    while not stop.is_set():
        # Senza token non possiamo fare niente — attendi che l'utente lo configuri
        if not has_token():
            time.sleep(15)
            authorized_chat = load_chat_id()
            continue

        try:
            updates = get_updates(offset=_update_offset, timeout_s=_POLL_TIMEOUT_S)
        except Exception as exc:
            _log.warning("[TG-BOT] get_updates errore: %s", exc)
            time.sleep(_POLL_RETRY_SLEEP)
            continue

        # aggiorna chat_id in caso sia cambiato a caldo
        authorized_chat = load_chat_id()

        for upd in updates:
            _update_offset = upd.get("update_id", _update_offset) + 1
            msg = upd.get("message")
            if not msg:
                continue
            chat = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()

            # Security gate: solo chat_id configurato
            if not authorized_chat:
                _log.warning("[TG-BOT] chat_id non configurato — messaggio ignorato da %s", chat)
                continue
            if chat != authorized_chat:
                _log.warning("[TG-BOT] messaggio da chat non autorizzato: %s", chat)
                continue

            if not text.startswith("/"):
                continue  # ignora messaggi non-comando

            _log.info("[TG-BOT] comando da %s: %s", chat, text[:80])
            try:
                reply = _handle_command(text, chat)
            except Exception as exc:
                reply = f"⚠ Errore interno: {exc}"
            send_message(chat, reply[:_MAX_MSG_LEN])

    _log.info("[TG-BOT] polling loop terminato")


# ─── Lifecycle ────────────────────────────────────────────────────────────────

def start() -> bool:
    """Avvia il bot thread in background. Idempotente.

    Returns: True se avviato ora, False se già running.
    """
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
    """Segnala stop al bot thread. Non bloccante se timeout."""
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
    """Invia notifica ciclo completato ogni N cicli (config notify_cycle_every_n).

    Returns: True se il messaggio è stato inviato.
    """
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
    """Notifica cascade ADB su un'istanza."""
    if not _notify_cascade():
        return False
    text = f"⚡ <b>Cascade ADB</b> — {instance}"
    if details:
        text += f"\n{details[:200]}"
    return _send_notify(text)


def notify_drl_saturo(residuo_m: float = 0.0) -> bool:
    """Notifica DRL master saturo o quasi."""
    if not _notify_drl():
        return False
    text = f"🔴 <b>DRL FauMorfeus saturo</b> — residuo {residuo_m:.0f}M\nRifornimento bloccato fino a reset (00:00 UTC)"
    return _send_notify(text)


def notify_daily_report(report_text: str) -> bool:
    """Forward del daily report via Telegram (versione abbreviata)."""
    if not _notify_daily_report():
        return False
    # Limita a max_len — il report completo è via email
    header = "📊 <b>Daily Report</b>\n"
    available = _MAX_MSG_LEN - len(header)
    body = report_text[:available]
    return _send_notify(header + body)


# ─── System info helpers ─────────────────────────────────────────────────────

def _get_uptime_s() -> int:
    """Uptime sistema in secondi. Windows: GetTickCount64. Fallback: -1."""
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetTickCount64()) // 1000
    except Exception:
        return -1


def _check_dashboard_running() -> bool:
    """True se uvicorn risponde su localhost:8765."""
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8765/", timeout=2)
        return True
    except Exception:
        return False


def _check_bot_running() -> bool:
    """True se engine_status.json aggiornato negli ultimi 10 minuti."""
    es = _read_engine_status()
    if not es:
        return False
    ts_raw = es.get("ts_update", "")
    if not ts_raw:
        return False
    try:
        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < 600
    except Exception:
        return False


# ─── Process launcher ─────────────────────────────────────────────────────────

_ROOT_PROD = Path("C:/doomsday-engine-prod")
_BAT_BOT        = _ROOT_PROD / "run_prod.bat"
_BAT_DASHBOARD  = _ROOT_PROD / "run_dashboard_prod.bat"


def _launch_bat(bat_path: Path, label: str) -> tuple[bool, str]:
    """Lancia un bat file in una nuova finestra console indipendente.

    Usa 'cmd /c start' per garantire che il .bat sia eseguito correttamente
    anche quando Python non ha shell=True (Task Scheduler, processo standalone).
    """
    import subprocess
    if not bat_path.exists():
        return False, f"{bat_path.name} non trovato in {bat_path.parent}"
    try:
        # cmd /c start apre una nuova finestra console indipendente.
        # Il titolo è il label (primo argomento di start con virgolette).
        proc = subprocess.Popen(
            ["cmd", "/c", "start", f'"{label}"', str(bat_path)],
            close_fds=True,
        )
        proc.wait(timeout=2)  # cmd /c start ritorna subito (non aspetta il bat)
        return True, f"console aperta ('{label}')"
    except subprocess.TimeoutExpired:
        return True, f"console aperta ('{label}')"
    except Exception as exc:
        return False, str(exc)


# ─── Notifica di avvio sistema ────────────────────────────────────────────────

def _send_system_alert(text: str) -> bool:
    """Invia messaggio di sistema (sempre, ignora il flag enabled)."""
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
    """Invia notifica di avvio al boot. Chiamata dopo 8s per dare tempo alla rete."""
    uptime = _get_uptime_s()
    bot_ok  = _check_bot_running()
    dash_ok = _check_dashboard_running()

    # Determina contesto avvio
    if 0 < uptime < 300:
        ctx = f"⚡ <b>Riavvio PC rilevato</b> (uptime {_fmt_dur(uptime)})"
    else:
        ctx = f"▶ Telegram bot avviato"
        if uptime > 0:
            ctx += f" (uptime PC {_fmt_dur(uptime)})"

    bot_line  = "🟢 Bot: ATTIVO"      if bot_ok  else "🔴 Bot: non avviato"
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


# ─── Entry point standalone ────────────────────────────────────────────────────

if __name__ == "__main__":
    """Avvio come processo standalone indipendente.

    Usato da run_telegram_prod.bat (auto-restart loop).
    Logging su stdout + logs/telegram_service.log.
    Blocca fino a SIGINT/SIGTERM.
    """
    import signal
    import sys

    # Setup logging su stdout + file
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

    _svc_stop = threading.Event()

    def _on_signal(sig, frame):
        _log.info("Segnale %s ricevuto — stop", sig)
        _svc_stop.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    start()

    # Notifica di avvio in background dopo 8s (attende inizializzazione rete)
    def _delayed_startup_notify():
        time.sleep(8)
        _log.info("[TG-BOT] invio notifica startup...")
        _notify_startup()

    threading.Thread(target=_delayed_startup_notify, daemon=True,
                     name="TgStartupNotify").start()

    _svc_stop.wait()   # blocca fino a SIGINT / SIGTERM
    stop(timeout_s=5)
    _log.info("=== Telegram bot service terminato ===")
