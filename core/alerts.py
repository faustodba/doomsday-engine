"""core/alerts.py — alert real-time email (WU137 fase 2).

Genera notifiche email per eventi anomali del bot, con rate-limit per non
spammare. State persistente in `data/alerts_state.json` (sopravvive restart).

Usage:
    from core.alerts import trigger_alert, check_master_saturo, check_heartbeat_cicli

    # Hook diretto (usato da launcher / task / main):
    trigger_alert(
        event_type="cascade_adb",
        severity="error",
        title="cascade ADB persistente",
        body="FAU_04 ha avuto 4 cascade in 1h",
        instance="FAU_04",
    )

    # Check periodici (chiamati da main loop a fine ciclo):
    check_master_saturo()
    check_heartbeat_cicli()

Rate limit:
    Ogni event_type ha un cooldown configurabile (default per severity).
    Se invocato durante cooldown → no-op silenzioso.

Schema state file `data/alerts_state.json`:
    {
      "<event_type>": {
        "last_sent_iso":  "2026-05-08T15:30:00+00:00",
        "count_total":    int,
        "first_seen_iso": "2026-05-08T14:00:00+00:00",
      },
      ...
    }

Schema config `globali.notifications.alerts_enabled` (bool, default False).
Eventi specifici disattivabili via `globali.notifications.alerts_disabled` list.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


# ─── Cooldown default per event_type (override da config in futuro) ─────────

COOLDOWN_S: dict[str, int] = {
    "cascade_adb":           3600,      # 1×/ora
    "maintenance_long":      4 * 3600,  # 1×/4h
    "master_saturo_long":    2 * 3600,  # 1×/2h
    "bot_unexpected_restart": 900,      # 1×/15min
    "heartbeat_cicli":       1800,      # 1×/30min
    "cache_pulizia_mancante": 4 * 3600, # 1×/4h
    "login_conflict":        1800,      # 1×/30min (WU192-bis)
    "boot_timeout":          3600,      # 1×/ora per istanza (warn) — WU208
    "boot_timeout_crit":     2 * 3600,  # 1×/2h per istanza (escalation critical)
}

DEFAULT_COOLDOWN = 1800   # 30min per event_type non listati


# ─── Storage ────────────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _state_path() -> Path:
    return _root() / "data" / "alerts_state.json"


_state_lock = threading.Lock()


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log.warning("[ALERTS] state illeggibile: %s", exc)
        return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
    except Exception as exc:
        _log.error("[ALERTS] save state fail: %s", exc)


# ─── Helpers tempo ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ─── Config helper ──────────────────────────────────────────────────────────

def _alerts_enabled() -> bool:
    """Master toggle alert real-time. Default False (safety)."""
    try:
        from config.config_loader import load_effective_notifications
        n = load_effective_notifications() or {}
        if not n.get("enabled", False):
            return False
        return bool(n.get("alerts_enabled", False))
    except Exception:
        return False


def _alert_disabled(event_type: str) -> bool:
    """Specifico evento disabilitato via lista `alerts_disabled`.

    Match esatto OPPURE per prefisso col confine `_`: una voce base come
    `cascade_adb` o `boot_timeout` nella lista disabilita anche gli event_type
    per-istanza derivati (`cascade_adb_FAU_04`, `boot_timeout_FAU_04`,
    `boot_timeout_crit_FAU_04`). Il confine `d + "_"` evita match parziali su
    parole diverse. Pre-WU208 il match era solo esatto, quindi il toggle
    dashboard `cascade_adb` non disabilitava davvero i cascade per-istanza.
    """
    try:
        from config.config_loader import load_effective_notifications
        n = load_effective_notifications() or {}
        disabled = n.get("alerts_disabled", []) or []
        for d in disabled:
            if event_type == d or event_type.startswith(f"{d}_"):
                return True
        return False
    except Exception:
        return False


def _recipients() -> list[str]:
    try:
        from config.config_loader import load_effective_notifications
        n = load_effective_notifications() or {}
        recs = n.get("recipients", []) or []
        return [r for r in recs if r]
    except Exception:
        return []


# ─── Core API: trigger_alert ────────────────────────────────────────────────

SEV_ICONS = {
    "info":     "ℹ️",
    "warn":     "⚠️",
    "error":    "❗",
    "critical": "🚨",
}


def trigger_alert(event_type: str,
                  severity: str,
                  title: str,
                  body: str,
                  instance: Optional[str] = None,
                  cooldown_s: Optional[int] = None) -> bool:
    """Invia un alert email rispettando il rate-limit per `event_type`.

    Args:
        event_type: chiave identificativa per rate-limit (es. "cascade_adb").
        severity:   "info" | "warn" | "error" | "critical".
        title:      titolo conciso (sarà prefisso del subject).
        body:       corpo testo descrittivo.
        instance:   nome istanza correlata (opzionale, accodato al body).
        cooldown_s: override cooldown (default: COOLDOWN_S[event_type]).

    Returns:
        True se l'alert è stato accodato in queue email; False se:
          - alerts disabilitati (master toggle o per event_type)
          - cooldown attivo (rate limited)
          - destinatari vuoti
          - errore I/O state file
    """
    if not _alerts_enabled():
        _log.debug("[ALERTS] disabled — skip %s", event_type)
        return False
    if _alert_disabled(event_type):
        _log.debug("[ALERTS] %s disabled by config", event_type)
        return False

    cd = cooldown_s if cooldown_s is not None else COOLDOWN_S.get(
        event_type, DEFAULT_COOLDOWN)

    now = _now()
    with _state_lock:
        state = _load_state()
        ev = state.get(event_type) or {}
        last_sent = _parse_iso(ev.get("last_sent_iso"))
        if last_sent and (now - last_sent).total_seconds() < cd:
            elapsed = int((now - last_sent).total_seconds())
            _log.info("[ALERTS] %s rate-limited (%ds<%ds) — skip",
                      event_type, elapsed, cd)
            # Aggiorna count_total (anche se non inviato)
            ev["count_total"] = int(ev.get("count_total", 0)) + 1
            state[event_type] = ev
            _save_state(state)
            return False

        # Eligible → enqueue
        recs = _recipients()
        if not recs:
            _log.warning("[ALERTS] %s: no recipients in config", event_type)
            return False

        try:
            from core.notifier import enqueue_email
        except Exception as exc:
            _log.error("[ALERTS] notifier import fail: %s", exc)
            return False

        sev_lc = (severity or "info").lower()
        ic = SEV_ICONS.get(sev_lc, "•")
        subj = f"{ic} [Doomsday] {title}"
        if instance:
            subj += f" · {instance}"

        body_full = (
            f"Severity: {sev_lc.upper()}\n"
            f"Event: {event_type}\n"
            f"Time:  {now.isoformat(timespec='seconds')}\n"
            + (f"Instance: {instance}\n" if instance else "")
            + f"\n{body.strip()}\n"
            f"\n— Doomsday alert (auto)\n"
        )

        try:
            enqueue_email(to=recs, subj=subj, body=body_full)
        except Exception as exc:
            _log.error("[ALERTS] enqueue fail: %s", exc)
            return False

        # Aggiorna state (last_sent + counters)
        ev["last_sent_iso"] = now.isoformat()
        ev["count_total"] = int(ev.get("count_total", 0)) + 1
        if not ev.get("first_seen_iso"):
            ev["first_seen_iso"] = now.isoformat()
        state[event_type] = ev
        _save_state(state)

        _log.info("[ALERTS] enqueued %s sev=%s inst=%s",
                  event_type, sev_lc, instance or "-")

        # Forward a Telegram (best-effort, no eccezioni). cascade/DRL hanno
        # formatter dedicati; gli altri eventi (heartbeat_cicli, maintenance,
        # restart) usano notify_alert generico — prima restavano senza canale
        # Telegram (solo email). Il gate telegram.enabled e' dentro _send_notify.
        try:
            from core.telegram_bot import (
                notify_cascade_adb, notify_drl_saturo, notify_alert,
            )
            if event_type == "cascade_adb" and instance:
                notify_cascade_adb(instance, body[:200])
            elif event_type in ("master_saturo_long", "master_saturo"):
                notify_drl_saturo(0.0)
            else:
                notify_alert(title=title, body=body[:300],
                             severity=sev_lc, instance=instance or "")
        except Exception:
            pass

        return True


# ─── Check periodici (chiamati dal main loop) ───────────────────────────────

def check_master_saturo(soglia_s: int = 3600) -> bool:
    """Master `daily_recv_limit==0` da > soglia_s con istanze attive.

    Returns: True se alert inviato (o tentato), False se condizione non vera
             o rate-limited.
    """
    if not _alerts_enabled():
        return False

    try:
        from shared import morfeus_state
        ms = morfeus_state.load() or {}
    except Exception:
        return False

    drl = ms.get("daily_recv_limit", -1)
    if drl is None or int(drl) != 0:
        return False   # non saturo

    # Da quanto è saturo? Usa `ts` come proxy (è l'ultima lettura)
    ts = _parse_iso(ms.get("ts", ""))
    if ts is None:
        return False
    now = _now()
    # FIX: il DRL del gioco si auto-resetta a 00:00 UTC. Se l'ultima lettura
    # OCR è di un giorno UTC diverso dal corrente, il valore=0 è STALE — il
    # gioco lo ha già resettato e il bot non ha ancora ri-letto (es. master
    # disabilitato o ultimo nel ciclo). No alert: aspettiamo prima rilettura.
    if ts.astimezone(timezone.utc).date() != now.astimezone(timezone.utc).date():
        _log.info("[ALERTS] master_saturo: DRL=0 STALE (ts=%s, oggi=%s) — skip",
                  ts.date(), now.date())
        return False
    elapsed_s = (now - ts).total_seconds()
    if elapsed_s < soglia_s:
        return False

    elapsed_min = int(elapsed_s / 60)
    body = (
        f"Master FauMorfeus saturo (Daily Receiving Limit residuo = 0M) "
        f"da {elapsed_min} minuti.\n"
        f"\nUltima lettura OCR: {ms.get('letto_da','?')} @ "
        f"{ms.get('ts','?')[:19]}\n"
        f"\nGli invii rifornimento delle istanze ordinarie sono inutili "
        f"finché il master non scarica le risorse o si ribalta a mezzanotte UTC.\n"
    )
    return trigger_alert(
        event_type="master_saturo_long",
        severity="warn",
        title=f"master saturo da {elapsed_min}min",
        body=body,
    )


def check_heartbeat_cicli(soglia_s: int = 3600) -> bool:
    """Nessun ciclo completato negli ultimi `soglia_s` secondi.

    Legge `data/telemetry/cicli.json` per trovare l'ultimo ciclo terminato.
    """
    if not _alerts_enabled():
        return False

    try:
        # cicli.json ha schema {"cicli": [...]} (NON una lista nuda): riusa il
        # reader canonico di telemetry che estrae la lista correttamente.
        # Import lazy per evitare cicli di import core<->core.
        # Pre-fix: json.loads(...) or [] ritornava il dict {"cicli":...} e
        # `for c in reversed(dict)` iterava le CHIAVI-stringa (isinstance dict
        # False) -> return False sempre -> l'alert non scattava MAI.
        from core.telemetry import load_cicli
        cicli = load_cicli()
    except Exception:
        return False

    # Trova l'ultimo ciclo "chiuso" (con end_ts valorizzato — chiave reale
    # dello schema; il ciclo in corso ha end_ts=None ed e' saltato).
    ultimo_end = None
    for c in reversed(cicli):
        if not isinstance(c, dict):
            continue
        ts_end = c.get("end_ts") or c.get("ts_end") or c.get("end") or ""
        if ts_end:
            ultimo_end = _parse_iso(ts_end)
            break

    if ultimo_end is None:
        return False
    elapsed_s = (_now() - ultimo_end).total_seconds()
    if elapsed_s < soglia_s:
        return False

    elapsed_min = int(elapsed_s / 60)
    body = (
        f"Nessun ciclo bot completato negli ultimi {elapsed_min} minuti.\n"
        f"\nUltimo ciclo terminato: {ultimo_end.isoformat(timespec='seconds')}\n"
        f"\nPossibili cause: bot crashed, deadlock istanza, MuMu offline, "
        f"o cascade ADB persistente. Verificare `bot.log` e dashboard.\n"
    )
    return trigger_alert(
        event_type="heartbeat_cicli",
        severity="critical",
        title=f"heartbeat: {elapsed_min}min senza cicli",
        body=body,
    )


def check_maintenance_long(soglia_s: int = 7200) -> bool:
    """`data/maintenance.flag` attivo da > soglia_s (default 2h).

    L'utente potrebbe averla dimenticata attiva (es. notte 28→29/04).
    """
    if not _alerts_enabled():
        return False

    flag_path = _root() / "data" / "maintenance.flag"
    if not flag_path.exists():
        return False

    try:
        # mtime = istante di attivazione (file scritto da `enable_maintenance`)
        mtime = datetime.fromtimestamp(flag_path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return False

    elapsed_s = (_now() - mtime).total_seconds()
    if elapsed_s < soglia_s:
        return False

    elapsed_min = int(elapsed_s / 60)
    body = (
        f"Modalità manutenzione attiva da {elapsed_min} minuti.\n"
        f"\nFile flag: {flag_path}\n"
        f"Attivata: {mtime.isoformat(timespec='seconds')}\n"
        f"\nIl bot è in pausa: nessun ciclo viene processato. "
        f"Disattivare da dashboard se non più necessaria.\n"
    )
    return trigger_alert(
        event_type="maintenance_long",
        severity="warn",
        title=f"maintenance attiva da {elapsed_min}min",
        body=body,
    )


def _istanze_attese_cache() -> list[str]:
    """Istanze per cui ci si aspetta la marca giornaliera in `cache_state.json`.

    Esclude: disabilitate (`abilitata=False`, runtime ha priorità su static —
    stesso criterio di `monitor/analyzer.py::_carica_istanze_abilitate`) e
    `tipologia=="raccolta_only"` (la pulizia cache è skippata per queste in
    `core/launcher.py`, es. master FauMorfeus — WU112)."""
    root = _root()
    try:
        instances = json.loads((root / "config" / "instances.json")
                                .read_text(encoding="utf-8"))
    except Exception:
        return []
    try:
        ov = json.loads((root / "config" / "runtime_overrides.json")
                         .read_text(encoding="utf-8"))
        ov_istanze = ov.get("istanze", {}) or {}
    except Exception:
        ov_istanze = {}

    risultato = []
    for ist in instances:
        nome = ist.get("nome")
        if not nome:
            continue
        ov_i = ov_istanze.get(nome, {}) or {}
        abilitata = ov_i.get("abilitata")
        if abilitata is None:
            abilitata = ist.get("abilitata", True)
        if not abilitata:
            continue
        tipologia = ov_i.get("tipologia") or ist.get("profilo", "full")
        if tipologia == "raccolta_only":
            continue
        risultato.append(nome)
    return risultato


def check_cache_pulizia_giornaliera(cutoff_hour_utc: int = 12) -> bool:
    """Istanze senza pulizia cache marcata per oggi dopo `cutoff_hour_utc` UTC.

    WU166: `core/settings_helper.py::_marca_cache_pulita` scrive
    `data/cache_state.json[nome] = oggi` SOLO su successo del flow Help→Clear
    cache→CLOSE. Se dopo il cutoff (default mezzogiorno UTC, ben oltre la
    finestra 00:00-02:00 osservata) la marca manca, la pulizia è quasi
    certamente fallita — e senza questo check nessuno se ne accorgerebbe
    (i log della notte sono già ruotati via dal tick successivo).
    """
    if not _alerts_enabled():
        return False

    now = _now()
    if now.hour < cutoff_hour_utc:
        return False

    try:
        state_path = _root() / "data" / "cache_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception:
        return False

    oggi = now.strftime("%Y-%m-%d")
    attese = _istanze_attese_cache()
    if not attese:
        return False
    mancanti = [n for n in attese if state.get(n) != oggi]
    if not mancanti:
        return False

    body = (
        f"Pulizia cache giornaliera non confermata per {len(mancanti)}/{len(attese)} "
        f"istanze dopo le {cutoff_hour_utc:02d}:00 UTC: {', '.join(mancanti)}.\n"
        f"\nVerificare `data/cache_debug/` (ultimo screenshot del tentativo) e "
        f"`data/cache_history.jsonl` (esito/durata per istanza) — probabile "
        f"timeout polling CLOSE o layout pannello Help non riconosciuto.\n"
    )
    return trigger_alert(
        event_type="cache_pulizia_mancante",
        severity="warn",
        title=f"cache non pulita: {len(mancanti)} istanze",
        body=body,
    )


# ─── Hook diretti (chiamati da launcher / task) ─────────────────────────────

# In-memory tracker per "cascade ADB persistente": conta cascade per istanza
# in finestra mobile 1h. Persiste solo finché il bot è vivo (reset su restart).
_cascade_tracker: dict[str, list[datetime]] = {}
_cascade_lock = threading.Lock()
CASCADE_WINDOW_S = 3600       # 1h finestra
CASCADE_THRESHOLD = 3         # >=3 cascade in 1h → alert


def report_cascade_adb(instance: str) -> bool:
    """Hook da `core/launcher.py` quando rileva cascade ADB.

    Tiene contatore in-memory; se istanza supera CASCADE_THRESHOLD in
    CASCADE_WINDOW_S → alert. Rate limit applicato comunque al livello di
    `trigger_alert`.
    """
    if not _alerts_enabled():
        return False
    now = _now()
    with _cascade_lock:
        events = _cascade_tracker.setdefault(instance, [])
        events.append(now)
        # Compatta finestra mobile
        cutoff = now - timedelta(seconds=CASCADE_WINDOW_S)
        events[:] = [t for t in events if t >= cutoff]
        n = len(events)

    if n < CASCADE_THRESHOLD:
        return False

    body = (
        f"L'istanza {instance} ha avuto {n} cascade ADB nell'ultima ora.\n"
        f"\nUltime occorrenze: "
        + ", ".join(t.strftime("%H:%M:%S") for t in events[-5:])
        + "\n\nL'istanza potrebbe richiedere kill manuale o restart MuMu.\n"
    )
    return trigger_alert(
        event_type=f"cascade_adb_{instance}",
        severity="error",
        title=f"cascade ADB · {n} eventi/h",
        body=body,
        instance=instance,
        cooldown_s=COOLDOWN_S["cascade_adb"],
    )


# In-memory tracker per "boot timeout consecutivi" per istanza (WU208). Un boot
# OK (report_boot_ok) azzera lo streak. Persiste finché il bot è vivo (reset su
# restart, come _cascade_tracker). Serve all'escalation warn→critical quando la
# stessa istanza non carica per N cicli di fila (istanza persistentemente
# bloccata, non lentezza occasionale).
_boot_timeout_streak: dict[str, int] = {}
_boot_timeout_lock = threading.Lock()
BOOT_TIMEOUT_ESCALATION = 3     # >=3 timeout consecutivi stessa istanza → critical


def report_boot_ok(instance: str) -> None:
    """Hook da `main.py` quando l'istanza raggiunge la HOME (boot riuscito):
    azzera lo streak di timeout consecutivi. No-op se non c'era streak."""
    with _boot_timeout_lock:
        _boot_timeout_streak.pop(instance, None)


def report_boot_timeout(instance: str,
                        fase: str = "caricamento HOME",
                        timeout_s: Optional[int] = None) -> bool:
    """Hook da `main.py` quando il boot di un'istanza fallisce e il bot la
    salta passando alla successiva (`avvia_istanza` o `attendi_home` falliti).

    Invia alert `warn`; escala a `critical` quando la STESSA istanza va in
    timeout per >= BOOT_TIMEOUT_ESCALATION cicli consecutivi (segnale di istanza
    persistentemente non caricabile — splash infinito, update richiesto,
    reconnect, VM non responsiva — non semplice lentezza occasionale).

    Rate-limit per istanza; l'escalation usa un event_type dedicato
    (`boot_timeout_crit_<istanza>`) così il `critical` non viene soppresso dal
    cooldown del `warn` precedente. Entrambi disattivabili dal toggle dashboard
    `boot_timeout` (match per prefisso in `_alert_disabled`).
    """
    if not _alerts_enabled():
        return False

    with _boot_timeout_lock:
        n = _boot_timeout_streak.get(instance, 0) + 1
        _boot_timeout_streak[instance] = n

    to_txt = f"{timeout_s}s" if timeout_s else "timeout"

    if n >= BOOT_TIMEOUT_ESCALATION:
        body = (
            f"L'istanza {instance} ha fallito il boot ({fase}) per {n} cicli "
            f"CONSECUTIVI — saltata ogni volta.\n"
            f"\nNon è più una lentezza occasionale: il client di gioco o "
            f"l'istanza MuMu è probabilmente bloccato (splash infinito, update "
            f"richiesto, reconnect, o VM non responsiva). Serve un intervento "
            f"manuale: aprire l'istanza {instance} e verificare lo stato del "
            f"gioco.\n"
        )
        return trigger_alert(
            event_type=f"boot_timeout_crit_{instance}",
            severity="critical",
            title=f"boot timeout · {n}× consecutivi",
            body=body,
            instance=instance,
            cooldown_s=COOLDOWN_S["boot_timeout_crit"],
        )

    body = (
        f"L'istanza {instance} non ha raggiunto la HOME entro il timeout "
        f"({fase}, {to_txt}): boot fallito, istanza saltata — il bot è passato "
        f"alla successiva senza retry nel tick.\n"
        f"\nCausa tipica: caricamento gioco lento o bloccato sullo splash. "
        f"Ritenterà al prossimo ciclo. Se ricorre {BOOT_TIMEOUT_ESCALATION}× di "
        f"fila l'alert diventa critical.\n"
    )
    return trigger_alert(
        event_type=f"boot_timeout_{instance}",
        severity="warn",
        title=f"boot timeout ({to_txt})",
        body=body,
        instance=instance,
        cooldown_s=COOLDOWN_S["boot_timeout"],
    )


def report_bot_unexpected_restart(reason: str = "unknown") -> bool:
    """Hook da `main.py::main()` al boot se rileva restart non pianificato.

    Heuristica: se `engine_status.json` ha `ts` recente (< 5min) e file
    presente all'avvio bot → restart unexpected (no exit pulito intermedio).
    """
    if not _alerts_enabled():
        return False
    body = (
        f"Bot restartato senza exit pulito.\n"
        f"\nReason: {reason}\n"
        f"\nVerificare bot.log per stack trace o crash. Possibili cause: "
        f"OOM, signal SIGKILL, errore non gestito in main loop.\n"
    )
    return trigger_alert(
        event_type="bot_unexpected_restart",
        severity="critical",
        title="bot restart unexpected",
        body=body,
    )


# ─── Stato per dashboard ────────────────────────────────────────────────────

def get_state_summary() -> dict:
    """Per dashboard: stato corrente di tutti gli event_type tracciati."""
    state = _load_state()
    out: dict = {}
    now = _now()
    for ev_type, ev in (state or {}).items():
        last = _parse_iso(ev.get("last_sent_iso"))
        cd = COOLDOWN_S.get(ev_type, DEFAULT_COOLDOWN)
        cooldown_left = 0
        if last:
            elapsed = (now - last).total_seconds()
            cooldown_left = max(0, int(cd - elapsed))
        out[ev_type] = {
            "last_sent_iso":  ev.get("last_sent_iso"),
            "count_total":    int(ev.get("count_total", 0)),
            "first_seen_iso": ev.get("first_seen_iso"),
            "cooldown_s":     cd,
            "cooldown_left_s": cooldown_left,
        }
    return out


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Test alerts module.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("master-saturo")
    sub.add_parser("heartbeat")
    sub.add_parser("maintenance")
    p_t = sub.add_parser("trigger", help="Test arbitrary alert")
    p_t.add_argument("--type", default="test")
    p_t.add_argument("--sev", default="info")
    p_t.add_argument("--title", default="test alert")
    p_t.add_argument("--body", default="this is a test")
    sub.add_parser("state")

    args = p.parse_args()
    if args.cmd == "master-saturo":
        print("sent=", check_master_saturo())
    elif args.cmd == "heartbeat":
        print("sent=", check_heartbeat_cicli())
    elif args.cmd == "maintenance":
        print("sent=", check_maintenance_long())
    elif args.cmd == "trigger":
        print("sent=", trigger_alert(
            args.type, args.sev, args.title, args.body))
    elif args.cmd == "state":
        print(json.dumps(get_state_summary(), indent=2))
