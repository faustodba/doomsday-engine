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
  /cicli        — ultimi 5 cicli (in corso + 4 completati)
  /ciclo [N]    — dettaglio ciclo #N (ometti N per l'ultimo)
  /stop         — attiva maintenance mode
  /avvia        — disattiva maintenance mode
  /restart_bot_telegram — riavvia il processo Telegram bot (~15s downtime)
  /rif_risorsa  — abilita/disabilita risorsa rifornimento
  /rif_modo     — cambia modalità (mappa/membri/entrambi/nessuno)
  /rif_soglia   — cambia soglia deposito per risorsa
  /rif_provviste — cambia provviste_max
  /rif_reset    — azzera stato giornaliero rifornimento per istanza

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


def _patch_runtime(patch_fn) -> bool:
    """Legge runtime_overrides.json, applica patch_fn(ov: dict) e riscrive atomicamente.

    Ritorna True se OK.
    """
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        try:
            ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}
        except Exception as read_exc:
            _log.warning("[TG-BOT] _patch_runtime: lettura fallita, abort: %s", read_exc)
            return False
        patch_fn(ov)
        tmp = ov_path.with_suffix(ov_path.suffix + ".tmp")
        tmp.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ov_path)
        return True
    except Exception as exc:
        _log.warning("[TG-BOT] _patch_runtime fallito: %s", exc)
        return False


def _set_messaggi_enabled(enabled: bool) -> bool:
    """Scrive telegram.enabled in runtime_overrides.json (DYNAMIC, hot-reload).

    Ritorna True se scrittura OK.
    """
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("notifications", {}).setdefault("telegram", {})["enabled"] = enabled
    return _patch_runtime(patch)


def _set_istanza_abilitata(nome: str, abilitata: bool) -> tuple[bool, str]:
    """Imposta abilitata per l'istanza in runtime_overrides.json.

    Usa il nome canonico da instances.json (case-insensitive input).
    Ritorna (ok, messaggio_errore_o_nome_canonico).
    """
    instances = _read_instances_cfg()
    # mappa UPPERCASE → nome canonico (es. "FAUMORFEUS" → "FauMorfeus")
    nomi_map = {c["nome"].upper(): c["nome"] for c in instances}
    nome_canonico = nomi_map.get(nome.upper())
    if not nome_canonico:
        suggerito = ", ".join(sorted(nomi_map.values()))
        return False, f"istanza '{nome}' non trovata.\nDisponibili: {suggerito}"

    def patch(ov):
        ov.setdefault("istanze", {}).setdefault(nome_canonico, {})["abilitata"] = abilitata

    ok = _patch_runtime(patch)
    return ok, nome_canonico


def _set_task(nome: Optional[str], enabled: bool) -> tuple[bool, dict, dict]:
    """Imposta un task specifico (nome) o tutti (nome=None) in globali.task.

    Ritorna (ok, stato_prima, stato_dopo).
    """
    before: dict = {}
    after:  dict = {}

    def patch(ov):
        task_dict = ov.setdefault("globali", {}).setdefault("task", {})
        before.update(task_dict)
        targets = [nome] if nome else list(task_dict)
        for k in targets:
            if k in task_dict:
                task_dict[k] = enabled
        after.update(task_dict)

    ok = _patch_runtime(patch)
    return ok, before, after


# ─── Rifornimento helpers (config + state) ────────────────────────────────────

# Mappa nome utente → chiave interna config (pomodoro = "campo" storicamente)
_RIF_RISORSA_MAP: dict[str, str] = {
    "pomodoro": "campo",
    "campo":    "campo",
    "legno":    "legno",
    "acciaio":  "acciaio",
    "petrolio": "petrolio",
}
_RIF_RISORSE_VALIDE = ("pomodoro", "legno", "acciaio", "petrolio")


def _set_rif_risorsa(risorsa: str, abilitata: bool) -> tuple[bool, str]:
    """Abilita/disabilita risorsa in globali.rifornimento_comune."""
    nome_int = _RIF_RISORSA_MAP.get(risorsa.lower())
    if not nome_int:
        return False, f"risorsa '{risorsa}' non valida. Usa: {', '.join(_RIF_RISORSE_VALIDE)}"
    campo = f"{nome_int}_abilitato"
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento_comune", {})[campo] = abilitata
    ok = _patch_runtime(patch)
    return ok, campo


def _set_rif_modo(modo: str) -> tuple[bool, str]:
    """Imposta modalità rifornimento (mappa/membri/entrambi/nessuno)."""
    modo = modo.lower()
    _validi = ("mappa", "membri", "entrambi", "nessuno")
    if modo not in _validi:
        return False, f"modo non valido. Usa: {', '.join(_validi)}"
    mappa_on  = modo in ("mappa",  "entrambi")
    membri_on = modo in ("membri", "entrambi")
    def patch(ov):
        rif = ov.setdefault("globali", {}).setdefault("rifornimento", {})
        rif["mappa_abilitata"]  = mappa_on
        rif["membri_abilitati"] = membri_on
    ok = _patch_runtime(patch)
    return ok, f"mappa={'on' if mappa_on else 'off'}  membri={'on' if membri_on else 'off'}"


def _set_rif_soglia(risorsa: str, valore_m: float) -> tuple[bool, str]:
    """Cambia soglia deposito per risorsa in globali.rifornimento_comune."""
    nome_int = _RIF_RISORSA_MAP.get(risorsa.lower())
    if not nome_int:
        return False, f"risorsa '{risorsa}' non valida. Usa: {', '.join(_RIF_RISORSE_VALIDE)}"
    campo = f"soglia_{nome_int}_m"
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento_comune", {})[campo] = valore_m
    ok = _patch_runtime(patch)
    return ok, campo


def _set_rif_provviste(valore: int) -> tuple[bool, str]:
    """Cambia provviste_max in globali.rifornimento."""
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento", {})["provviste_max"] = valore
    ok = _patch_runtime(patch)
    return ok, f"provviste_max={valore}M"


def _reset_rif_stato(nome_ist: Optional[str]) -> tuple[int, int]:
    """Azzera spedizioni_oggi + provviste_esaurite nello state file.

    nome_ist=None → tutte le istanze (eccetto FauMorfeus).
    Ritorna (n_ok, n_err).
    """
    instances = _read_instances_cfg()
    tutti = [c["nome"] for c in instances if c["nome"] != "FauMorfeus"]
    if nome_ist:
        up = nome_ist.upper()
        if up not in {t.upper() for t in tutti}:
            return 0, 1
        targets = [up]
    else:
        targets = tutti

    today = datetime.now(timezone.utc).date().isoformat()
    n_ok = n_err = 0
    for ist in targets:
        p = _root() / "state" / f"{ist}.json"
        try:
            st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            rif = st.setdefault("rifornimento", {})
            rif["spedizioni_oggi"]    = 0
            rif["provviste_esaurite"] = False
            rif["data_riferimento"]   = today
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
            n_ok += 1
        except Exception as exc:
            _log.warning("[TG-BOT] reset rif stato %s fallito: %s", ist, exc)
            n_err += 1
    return n_ok, n_err


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


def _read_last_metrics(instance: str) -> dict:
    """Ultimo record istanza_metrics.jsonl per l'istanza specificata."""
    p = _root() / "data" / "istanza_metrics.jsonl"
    last: dict = {}
    try:
        if p.exists():
            tag = f'"{instance}"'
            for line in p.read_text(encoding="utf-8").splitlines():
                if tag in line:
                    try:
                        last = json.loads(line)
                    except Exception:
                        pass
    except Exception:
        pass
    return last


def _read_truppe_storico(instance: str) -> list:
    p = _root() / "data" / "storico_truppe.json"
    d = _read_json_safe(p)
    return d.get(instance, [])


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

    # Bot running — controllo processo (primario) + engine_status (info ciclo)
    bot_ok = _check_bot_running()
    es     = _read_engine_status()

    if bot_ok:
        lines.append("🟢 <b>Bot: ATTIVO</b>")
    else:
        lines.append("🔴 <b>Bot: SPENTO</b>")

    # Ciclo corrente da cicli.json
    if bot_ok:
        cicli = _read_cicli()
        if cicli:
            ultimo = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[0]
            n     = ultimo.get("numero", ultimo.get("cycle_n", "?"))
            start = ultimo.get("start_ts", "")
            if start:
                try:
                    dt  = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
                    dur = (now - dt).total_seconds()
                    lines.append(f"Ciclo #{n} in corso da {_fmt_dur(dur)}")
                except Exception:
                    lines.append(f"Ciclo #{n}")

    # Istanze da instances.json (lista completa configurata)
    instances = _read_instances_cfg()
    ov        = _read_runtime_overrides()
    ist_ov    = ov.get("istanze", {})
    n_tot     = len(instances)
    n_ok      = sum(
        1 for cfg in instances
        if ist_ov.get(cfg["nome"], {}).get("abilitata", cfg.get("abilitata", True))
    )
    lines.append(f"Istanze: {n_tot} configurate, {n_ok} abilitate")

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


def _read_instances_cfg() -> list:
    """Legge instances.json (lista completa istanze configurate)."""
    p = _root() / "config" / "instances.json"
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _read_all_last_metrics() -> dict[str, dict]:
    """Ritorna {nome: ultimo_record} da istanza_metrics.jsonl."""
    p = _root() / "data" / "istanza_metrics.jsonl"
    last: dict[str, dict] = {}
    try:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    nome = r.get("instance", "")
                    if nome:
                        last[nome] = r
                except Exception:
                    pass
    except Exception:
        pass
    return last


def _parse_dt(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _build_istanze() -> str:
    """Risposta al comando /istanze.

    Header: ciclo #N | avv. HH:MM | modalità adaptive | stato bot
    Per istanza: durata esecuzione (tick_total_s) invece del tempo trascorso.
    Ordine: sequenza di esecuzione nel ciclo (ascending per ultima ts metrics).
    Funziona anche con bot spento.
    """
    instances   = _read_instances_cfg()
    ov          = _read_runtime_overrides()
    es          = _read_engine_status()
    all_metrics = _read_all_last_metrics()

    if not instances:
        return "⚠ instances.json non disponibile"

    ist_ov     = ov.get("istanze", {})
    ist_status = es.get("istanze", {}) if es else {}
    now        = datetime.now(timezone.utc)

    # Modalità adaptive scheduler
    glob_ov  = ov.get("globali", {})
    adapt_on = bool(glob_ov.get("adaptive_scheduler_enabled", False))
    shadow   = bool(glob_ov.get("adaptive_scheduler_shadow_only", True))
    if adapt_on and not shadow:
        mode_str = "🎯 Adaptive LIVE"
    elif adapt_on and shadow:
        mode_str = "👁 Adaptive SHADOW"
    else:
        mode_str = "📋 Sequenza fissa"

    # Ciclo corrente: numero + orario avvio locale
    ciclo_n: object = "?"
    ciclo_start: Optional[datetime] = None
    ciclo_avv_str = ""
    cicli = _read_cicli()
    if cicli:
        ultimo_ciclo = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[0]
        ciclo_n     = ultimo_ciclo.get("numero", ultimo_ciclo.get("cycle_n", "?"))
        ciclo_start = _parse_dt(ultimo_ciclo.get("start_ts", ""))
        if ciclo_start:
            ciclo_avv_str = ciclo_start.astimezone().strftime("%H:%M")

    # Istanza live
    live_nome = next(
        (nome for nome, st in ist_status.items() if st.get("stato") == "running"),
        None,
    )

    # Ordina per timestamp ultima esecuzione (ascending = ordine nel ciclo)
    def _sort_key(cfg: dict) -> str:
        nome = cfg.get("nome", "")
        return all_metrics.get(nome, {}).get("ts", "1970-01-01T00:00:00")

    ordered = sorted(instances, key=_sort_key)

    # Header
    bot_on  = _check_bot_running()
    bot_str = "🟢 bot attivo" if bot_on else "🔴 bot spento"
    avv_part = f" | avv. {ciclo_avv_str}" if ciclo_avv_str else ""
    lines: list[str] = [
        f"<b>Istanze</b> — ciclo #{ciclo_n}{avv_part} | {mode_str} | {bot_str}",
        "",
    ]

    for idx, cfg in enumerate(ordered, 1):
        nome      = cfg.get("nome", "")
        ov_i      = ist_ov.get(nome, {})
        abilitata = ov_i.get("abilitata", cfg.get("abilitata", True))
        tipologia = ov_i.get("tipologia", cfg.get("profilo", "full"))
        tip_short = {"raccolta_fast": "fast", "raccolta_only": "solo-racc"}.get(tipologia, tipologia)
        on_icon   = "🟢" if abilitata else "🔴"

        # Metriche ultima esecuzione
        mx        = all_metrics.get(nome, {})
        mx_ts     = _parse_dt(mx.get("ts", "")) if mx else None
        mx_out    = mx.get("outcome", "") if mx else ""
        mx_dur_s  = mx.get("tick_total_s", 0) if mx else 0
        out_icon  = {"ok": "✓", "cascade": "⚡", "abort": "✗"}.get(mx_out, "—")
        dur_str   = _fmt_dur(int(mx_dur_s)) if mx_dur_s and mx_dur_s > 0 else "?"

        # Stato riga
        st = ist_status.get(nome, {})
        if nome == live_nome:
            task_c    = st.get("task_corrente")
            stato_str = "<b>▶ LIVE</b>" + (f" ({task_c})" if task_c else "")
        elif bot_on and ciclo_start and mx_ts and mx_ts >= ciclo_start:
            stato_str = f"{out_icon} {dur_str}"
        elif bot_on:
            stato_str = "⏳ attesa"
        else:
            # Bot spento: mostra outcome + durata ultima esecuzione nota
            stato_str = f"{out_icon} {dur_str}"

        lines.append(f"{idx:2}. {on_icon} <b>{nome}</b> [{tip_short}]  {stato_str}")

    return "\n".join(lines)


def _build_ciclo_detail(numero: Optional[int]) -> str:
    """Risposta a /ciclo [N] — dettaglio singolo ciclo.

    Se numero=None mostra il ciclo più recente.
    """
    cicli = _read_cicli()
    if not cicli:
        return "Nessun ciclo disponibile in data/telemetry/cicli.json"

    if numero is None:
        c = sorted(cicli, key=lambda x: x.get("start_ts", ""), reverse=True)[0]
    else:
        matches = [x for x in cicli if x.get("numero") == numero]
        if not matches:
            nums = sorted({x.get("numero") for x in cicli if x.get("numero")}, reverse=True)
            recenti = ", ".join(f"#{n}" for n in nums[:8])
            return f"⚠ Ciclo #{numero} non trovato.\nDisponibili (recenti): {recenti}"
        c = matches[0]

    n          = c.get("numero", "?")
    completato = c.get("completato", False)
    start_ts   = c.get("start_ts", "")
    end_ts     = c.get("end_ts", "")
    durata_s   = c.get("durata_s", 0)
    istanze    = c.get("istanze", {})
    now        = datetime.now(timezone.utc)

    # Header
    if not completato:
        dt_start = _parse_dt(start_ts)
        elapsed = _fmt_dur((now - dt_start).total_seconds()) if dt_start else "?"
        avv_str = dt_start.astimezone().strftime("%d/%m %H:%M") if dt_start else "?"
        n_done  = sum(1 for v in istanze.values() if v.get("end_ts"))
        n_tot   = len(istanze)
        header  = f"🔄 <b>Ciclo #{n}</b>  —  in corso da {elapsed}\n{avv_str} → in corso  |  {n_done}/{n_tot}"
    else:
        dt_start = _parse_dt(start_ts)
        dt_end   = _parse_dt(end_ts)
        avv_str  = dt_start.astimezone().strftime("%d/%m %H:%M") if dt_start else "?"
        fine_str = dt_end.astimezone().strftime("%H:%M") if dt_end else "?"
        dur_str  = _fmt_dur(durata_s) if durata_s else "?"
        n_ok     = sum(1 for v in istanze.values() if v.get("esito") == "ok")
        n_tot    = len(istanze)
        esiti_extra = ""
        n_cas = sum(1 for v in istanze.values() if v.get("esito") == "cascade")
        n_ab  = sum(1 for v in istanze.values() if v.get("esito") == "abort")
        if n_cas: esiti_extra += f"  ⚡{n_cas}"
        if n_ab:  esiti_extra += f"  ✂{n_ab}"
        stato_icon = "✅" if n_ok == n_tot else ("⚠" if n_ok > 0 else "❌")
        header = (
            f"{stato_icon} <b>Ciclo #{n}</b>  —  {dur_str}\n"
            f"{avv_str} → {fine_str}  |  {n_ok}/{n_tot} ok{esiti_extra}"
        )

    # Tabella istanze
    _ESITO_ICON = {"ok": "✅", "cascade": "⚡", "abort": "✂", "running": "▶"}
    rows: list[tuple[str, int, str]] = []  # (nome, durata_s, esito)
    for nome, v in istanze.items():
        d_s  = v.get("durata_s", 0)
        esit = v.get("esito", "?")
        # calcola elapsed per istanza in-progress
        if esit == "running" and v.get("start_ts"):
            dt_i = _parse_dt(v["start_ts"])
            d_s  = int((now - dt_i).total_seconds()) if dt_i else 0
        rows.append((nome, d_s, esit))

    lines: list[str] = [header, "", "<code>Istanza       durata</code>"]
    for nome, d_s, esit in rows:
        icona = _ESITO_ICON.get(esit, "?")
        dur   = _fmt_dur(d_s) if d_s else "—"
        if esit == "running":
            dur += " ▶"
        lines.append(f"<code>{nome:<12} {dur:>6}</code>  {icona}")

    # Footer min/max solo su cicli con durata valida e almeno 2 istanze
    durate = [(nome, d_s) for nome, d_s, esit in rows if d_s > 0 and esit != "running"]
    if len(durate) >= 2:
        mn = min(durate, key=lambda x: x[1])
        mx = max(durate, key=lambda x: x[1])
        lines.append("")
        lines.append(f"min: {mn[0]} {_fmt_dur(mn[1])}  |  max: {mx[0]} {_fmt_dur(mx[1])}")

    return "\n".join(lines)


def _build_cicli() -> str:
    """Risposta al comando /cicli — ultimi 5 cicli (4 completati + 1 in corso)."""
    cicli = _read_cicli()
    if not cicli:
        return "Nessun ciclo disponibile in data/telemetry/cicli.json"

    # Ordina per start_ts desc, prendi i 5 più recenti
    sorted_cicli = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[:5]

    lines: list[str] = ["<b>Ultimi cicli</b>"]

    for c in sorted_cicli:
        n          = c.get("numero", "?")
        completato = c.get("completato", False)
        start_ts   = c.get("start_ts", "")
        durata_s   = c.get("durata_s", 0)
        istanze    = c.get("istanze", {})

        # Orario avvio locale
        avv_str = ""
        if start_ts:
            dt = _parse_dt(start_ts)
            if dt:
                avv_str = dt.astimezone().strftime("%d/%m %H:%M")

        if not completato:
            # Ciclo in corso
            now = datetime.now(timezone.utc)
            dur_str = ""
            if start_ts:
                dt = _parse_dt(start_ts)
                if dt:
                    dur_str = f" — in corso da {_fmt_dur((now - dt).total_seconds())}"

            n_done    = sum(1 for v in istanze.values() if v.get("esito") not in ("running", None) and v.get("end_ts"))
            n_tot     = len(istanze)
            running   = next((k for k, v in istanze.items() if v.get("esito") == "running"), None)
            run_str   = f"  ▶ {running}" if running else ""

            lines.append(f"\n🔄 <b>Ciclo #{n}</b>{dur_str}  [{n_done}/{n_tot}]{run_str}")
            if avv_str:
                lines.append(f"   avv. {avv_str}")
        else:
            # Ciclo completato
            n_ok      = sum(1 for v in istanze.values() if v.get("esito") == "ok")
            n_cascade = sum(1 for v in istanze.values() if v.get("esito") == "cascade")
            n_abort   = sum(1 for v in istanze.values() if v.get("esito") == "abort")
            n_tot     = len(istanze)

            esiti_str = f"{n_ok}/{n_tot} ok"
            if n_cascade:
                esiti_str += f"  ⚡{n_cascade} cascade"
            if n_abort:
                esiti_str += f"  ✂{n_abort} abort"

            dur_str = _fmt_dur(durata_s) if durata_s else "?"
            lines.append(f"\n✅ <b>Ciclo #{n}</b> — {dur_str}  {esiti_str}")
            if avv_str:
                lines.append(f"   avv. {avv_str}")

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
        lines.extend(righe_ist[:10])
    elif tot_sped == 0:
        lines.append("  (nessuna spedizione ancora oggi)")

    # Config attuale (hot-reload da runtime_overrides)
    lines.append("")
    lines.append("<b>Config attuale</b>")
    rc  = ov.get("globali", {}).get("rifornimento_comune", {})
    rif = ov.get("globali", {}).get("rifornimento", {})
    # Modalità
    mappa_on  = rif.get("mappa_abilitata",  False)
    membri_on = rif.get("membri_abilitati", False)
    if mappa_on and membri_on:
        modo_str = "entrambi"
    elif mappa_on:
        modo_str = "mappa"
    elif membri_on:
        modo_str = "membri"
    else:
        modo_str = "⚠ nessuna"
    lines.append(f"Modalità: {modo_str}")
    # Risorse
    ris_labels = [
        ("pomodoro", rc.get("campo_abilitato",    True)),
        ("legno",    rc.get("legno_abilitato",    True)),
        ("acciaio",  rc.get("acciaio_abilitato",  True)),
        ("petrolio", rc.get("petrolio_abilitato", True)),
    ]
    ris_str = "  ".join(f"{'🟢' if on else '🔴'}{r}" for r, on in ris_labels)
    lines.append(f"Risorse: {ris_str}")
    # Soglie deposito
    soglie = [
        ("pom", rc.get("soglia_campo_m",    5.0)),
        ("leg", rc.get("soglia_legno_m",    5.0)),
        ("acc", rc.get("soglia_acciaio_m",  3.5)),
        ("pet", rc.get("soglia_petrolio_m", 2.5)),
    ]
    s_str = "  ".join(f"{k}={v:.1f}M" for k, v in soglie)
    lines.append(f"Soglie: {s_str}")
    # Provviste max
    prov_max = rif.get("provviste_max", 100)
    lines.append(f"Provviste max: {prov_max}M")

    return "\n".join(lines)


def _build_istanza_detail(nome: str) -> str:
    """Risposta al comando /istanza XXX — card dettaglio singola istanza."""
    # Config
    instances = _read_instances_cfg()
    cfg_map      = {c["nome"]: c for c in instances}
    cfg_map_low  = {k.lower(): k for k in cfg_map}
    nome_resolved = cfg_map_low.get(nome.lower())
    if not nome_resolved:
        available = ", ".join(sorted(cfg_map.keys()))
        return f"⚠ Istanza <code>{nome}</code> non trovata.\nDisponibili: {available}"
    nome = nome_resolved

    cfg = cfg_map[nome]
    ov  = _read_runtime_overrides()
    ov_i = ov.get("istanze", {}).get(nome, {})

    abilitata = ov_i.get("abilitata", cfg.get("abilitata", True))
    tipologia = ov_i.get("tipologia", cfg.get("profilo", "full"))
    max_sq    = ov_i.get("max_squadre", cfg.get("max_squadre", "?"))
    livello   = ov_i.get("livello", cfg.get("livello", "?"))

    on_icon   = "🟢" if abilitata else "🔴"
    tip_short = {"raccolta_fast": "fast", "raccolta_only": "solo-racc"}.get(tipologia, tipologia)

    lines: list[str] = [
        f"{on_icon} <b>{nome}</b> [{tip_short}]  sq={max_sq}  lv={livello}"
    ]

    # Stato live da engine_status
    es       = _read_engine_status()
    ist_live = (es.get("istanze", {}) if es else {}).get(nome, {})
    stato    = ist_live.get("stato", "")
    task_c   = ist_live.get("task_corrente")
    if stato == "running":
        lines.append("▶ <b>LIVE</b>" + (f" — {task_c}" if task_c else ""))

    # Ultimo ciclo da istanza_metrics
    mx = _read_last_metrics(nome)
    if mx:
        outcome   = mx.get("outcome", "")
        boot_s    = mx.get("boot_home_s", 0)
        tick_s    = mx.get("tick_total_s", 0)
        out_icon  = {"ok": "✓", "cascade": "⚡", "abort": "✗"}.get(outcome, "—")
        lines.append(
            f"\n🔄 <b>Ultimo ciclo</b>: {out_icon} {outcome}"
            + (f"  durata {_fmt_dur(tick_s)}" if tick_s else "")
            + (f"  boot {_fmt_dur(boot_s)}" if boot_s else "")
        )

        # Raccolta
        racc = mx.get("raccolta", {})
        invii_list = racc.get("invii", [])
        n_invii   = len(invii_list)
        att_pre   = racc.get("attive_pre", "?")
        att_post  = racc.get("attive_post", "?")
        tot       = racc.get("totali", "?")
        if n_invii or att_pre != "?":
            tipi = {}
            for inv in invii_list:
                t = inv.get("tipo", "?")
                tipi[t] = tipi.get(t, 0) + 1
            tipi_str = " ".join(f"{v}×{k}" for k, v in tipi.items()) if tipi else "0 marce"
            lines.append(
                f"\n📦 <b>Raccolta</b>: {n_invii} marce  [{tipi_str}]"
                f"\n   slot: {att_pre}→{att_post}/{tot}"
            )

        # Task durations
        td = mx.get("task_durations_s", {})
        if td:
            sorted_td = sorted(td.items(), key=lambda x: -x[1])[:6]
            td_str = "  ".join(f"{k} {_fmt_dur(v)}" for k, v in sorted_td)
            lines.append(f"\n⏱ <b>Task</b>: {td_str}")

    # Rifornimento da state
    st  = _read_state(nome)
    rif = st.get("rifornimento", {})
    sped = rif.get("spedizioni_oggi", 0)
    if sped or nome != "FauMorfeus":
        inv_oggi = rif.get("inviato_oggi", {})
        _RES = [("pomodoro","🍅"),("legno","🪵"),("acciaio","⚙"),("petrolio","🛢")]
        tot_m = sum(inv_oggi.values()) / 1e6 if inv_oggi else 0
        res_str = "  ".join(
            f"{icon}{v/1e6:.1f}M" for r, icon in _RES
            if (v := inv_oggi.get(r, 0)) > 0
        ) if inv_oggi else "—"
        prov = rif.get("provviste_residue", -1)
        prov_str = f"  provviste {prov/1e6:.1f}M" if prov >= 0 else ""
        lines.append(
            f"\n🚚 <b>Rifornimento</b>: {sped} sped  {tot_m:.1f}M netti{prov_str}"
            + (f"\n   {res_str}" if res_str != "—" else "")
        )

    # Arena
    arena = st.get("arena", {})
    if arena:
        esaurite = arena.get("esaurite", False)
        lines.append(f"\n🏟 <b>Arena</b>: {'✓ esaurita' if esaurite else '⏳ disponibile'}")

    # Truppe
    tr_list = _read_truppe_storico(nome)
    if tr_list:
        last_tr = tr_list[-1]
        squads  = last_tr.get("total_squads", 0)
        delta   = 0
        if len(tr_list) >= 2:
            delta = squads - tr_list[-2].get("total_squads", squads)
        delta_str = f"  Δ{delta:+,}" if delta else ""
        lines.append(f"\n🪖 <b>Truppe</b>: {squads:,}{delta_str}")

    # Produzione/ora da metrics state
    met = st.get("metrics", {})
    _RES_KEYS = [("pomodoro","🍅"),("legno","🪵"),("acciaio","⚙"),("petrolio","🛢")]
    prod_parts = []
    for r, icon in _RES_KEYS:
        val = met.get(f"{r}_per_ora", 0)
        if val and abs(val) > 100:
            sign = "+" if val > 0 else ""
            prod_parts.append(f"{icon}{sign}{val/1e3:.0f}K/h")
    if prod_parts:
        lines.append(f"\n📈 <b>Prod/h</b>: {' '.join(prod_parts)}")

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
            "/istanze — lista istanze ON/OFF con istanza live\n"
            "/istanza FAU_03 — card dettaglio singola istanza\n"
            "/rifornimento — DRL master FauMorfeus + spedizioni oggi\n"
            "/cicli — ultimi 5 cicli (in corso + 4 completati)\n"
            "/ciclo 184 — dettaglio ciclo #184 (ometti N per l'ultimo)\n"
            "\n"
            f"<b>Avvio sistema</b> (bot {bot_icon}  dashboard {dash_icon})\n"
            "/avvia_bot — avvia il bot (run_prod.bat)\n"
            "/avvia_dashboard — avvia la dashboard (uvicorn)\n"
            "/avvia_tutto — avvia bot + dashboard\n"
            "\n"
            "<b>Bot management</b>\n"
            "/stop — attiva maintenance mode (bot in pausa)\n"
            "/avvia — disattiva maintenance mode (bot riprende)\n"
            "/restart_bot_telegram — riavvia questo bot Telegram (~15s downtime)\n"
            "\n"
            "<b>Istanze</b>\n"
            "/disabilita FAU_03 — disabilita istanza (hot-reload)\n"
            "/abilita FAU_03 — abilita istanza (hot-reload)\n"
            "\n"
            "<b>Task globali</b>\n"
            "/task — stato ON/OFF di ogni task\n"
            "/disabilita_task arena — disabilita task singolo\n"
            "/abilita_task arena — abilita task singolo\n"
            "\n"
            "<b>Rifornimento</b>\n"
            "/rifornimento — DRL + spedizioni oggi + config\n"
            "/rif_risorsa acciaio off — abilita/disabilita risorsa\n"
            "/rif_modo mappa — modalità: mappa|membri|entrambi|nessuno\n"
            "/rif_soglia acciaio 3.5 — soglia deposito (M)\n"
            "/rif_provviste 80 — provviste_max (M)\n"
            "/rif_reset FAU_03 — azzera stato giornaliero istanza\n"
            "/rif_reset — azzera stato giornaliero tutte le istanze\n"
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

    if cmd == "/cicli":
        try:
            return _build_cicli()
        except Exception as exc:
            return f"⚠ Errore /cicli: {exc}"

    if cmd == "/ciclo":
        parts = text.split()
        numero = None
        if len(parts) > 1:
            raw = parts[1].lstrip("#")
            try:
                numero = int(raw)
            except ValueError:
                return "⚠ Uso: /ciclo [N]  Es: /ciclo 184  oppure /ciclo per il più recente"
        try:
            return _build_ciclo_detail(numero)
        except Exception as exc:
            return f"⚠ Errore /ciclo: {exc}"

    if cmd == "/istanza":
        parts = text.split()
        if len(parts) < 2:
            return "⚠ Uso: /istanza NOME  (es. /istanza FAU_03)"
        nome = parts[1].upper()
        try:
            return _build_istanza_detail(nome)
        except Exception as exc:
            return f"⚠ Errore /istanza: {exc}"

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

    if cmd in ("/disabilita", "/abilita"):
        abilitata = (cmd == "/abilita")
        parts = text.split()
        if len(parts) < 2:
            return f"⚠ Uso: {cmd} NOME_ISTANZA  (es. {cmd} FAU_03)"
        nome = parts[1]
        ok, msg = _set_istanza_abilitata(nome, abilitata)
        if not ok:
            return f"⚠ {msg}"
        icona = "🟢" if abilitata else "🔴"
        stato = "abilitata" if abilitata else "disabilitata"
        return f"{icona} Istanza <b>{msg}</b> {stato}.\nEffetto al prossimo tick del bot."

    if cmd == "/task":
        ov = _read_runtime_overrides()
        task_dict = ov.get("globali", {}).get("task", {})
        if not task_dict:
            return "⚠ Nessun task configurato in runtime_overrides.json"
        lines = ["📋 <b>Task globali</b>", ""]
        for nome_t, stato in sorted(task_dict.items()):
            icona = "🟢" if stato else "🔴"
            lines.append(f"{icona} {nome_t}")
        lines += ["", "Usa /disabilita_task &lt;nome&gt; o /abilita_task &lt;nome&gt;"]
        return "\n".join(lines)

    if cmd in ("/disabilita_task", "/abilita_task"):
        abilitata = (cmd == "/abilita_task")
        parts = text.split()
        if len(parts) < 2:
            return (
                f"⚠ Uso: {cmd} &lt;nome_task&gt;  (es. {cmd} arena)\n"
                "Usa /task per vedere la lista dei task e il loro stato."
            )
        nome_task = parts[1].lower()
        ov_now = _read_runtime_overrides()
        task_dict = ov_now.get("globali", {}).get("task", {})
        if nome_task not in task_dict:
            validi = ", ".join(sorted(task_dict))
            return f"⚠ Task '<b>{nome_task}</b>' non trovato.\nTask disponibili: {validi}"
        if task_dict[nome_task] == abilitata:
            stato_str = "già abilitato" if abilitata else "già disabilitato"
            return f"ℹ️ Task <b>{nome_task}</b> {stato_str}."
        ok, _, _ = _set_task(nome_task, abilitata)
        if not ok:
            return "⚠ Errore scrittura runtime_overrides.json"
        icona = "🟢" if abilitata else "🔴"
        stato = "abilitato" if abilitata else "disabilitato"
        return f"{icona} Task <b>{nome_task}</b> {stato}.\nEffetto al prossimo tick del bot."

    # ── Rifornimento — comandi di modifica ───────────────────────────────────

    if cmd == "/rif_risorsa":
        parts = text.split()
        if len(parts) < 3:
            return (
                "⚠ Uso: /rif_risorsa &lt;risorsa&gt; on|off\n"
                "Risorse: pomodoro, legno, acciaio, petrolio\n"
                "Es: /rif_risorsa acciaio off"
            )
        risorsa, stato_s = parts[1].lower(), parts[2].lower()
        if stato_s not in ("on", "off"):
            return "⚠ Stato non valido. Usa: on oppure off"
        abilitata = stato_s == "on"
        ok, msg = _set_rif_risorsa(risorsa, abilitata)
        if not ok:
            return f"⚠ {msg}"
        icona = "🟢" if abilitata else "🔴"
        return (
            f"{icona} Risorsa <b>{risorsa}</b> {'abilitata' if abilitata else 'disabilitata'}.\n"
            f"Effetto al prossimo tick. Usa /rifornimento per verificare."
        )

    if cmd == "/rif_modo":
        parts = text.split()
        if len(parts) < 2:
            return (
                "⚠ Uso: /rif_modo &lt;mappa|membri|entrambi|nessuno&gt;\n"
                "Es: /rif_modo mappa"
            )
        ok, msg = _set_rif_modo(parts[1])
        if not ok:
            return f"⚠ {msg}"
        return f"✅ Modalità impostata: <b>{msg}</b>\nEffetto al prossimo tick."

    if cmd == "/rif_soglia":
        parts = text.split()
        if len(parts) < 3:
            return (
                "⚠ Uso: /rif_soglia &lt;risorsa&gt; &lt;M&gt;\n"
                "Risorse: pomodoro, legno, acciaio, petrolio\n"
                "Es: /rif_soglia acciaio 3.5"
            )
        risorsa = parts[1].lower()
        try:
            valore_m = float(parts[2].replace(",", "."))
        except ValueError:
            return "⚠ Valore non valido. Usa un numero in milioni (es. 3.5)"
        if valore_m < 0 or valore_m > 500:
            return "⚠ Valore fuori range (0–500 M)"
        ok, campo = _set_rif_soglia(risorsa, valore_m)
        if not ok:
            return f"⚠ {campo}"
        return f"✅ Soglia <b>{risorsa}</b> impostata a <b>{valore_m:.1f}M</b>.\nEffetto al prossimo tick."

    if cmd == "/rif_provviste":
        parts = text.split()
        if len(parts) < 2:
            return "⚠ Uso: /rif_provviste &lt;M&gt;  Es: /rif_provviste 80"
        try:
            valore = int(float(parts[1]))
        except ValueError:
            return "⚠ Valore non valido. Usa un numero intero in milioni."
        if valore < 1 or valore > 9999:
            return "⚠ Valore fuori range (1–9999 M)"
        ok, msg = _set_rif_provviste(valore)
        if not ok:
            return "⚠ Errore scrittura runtime_overrides.json"
        return f"✅ {msg}\nEffetto al prossimo tick. Usa /rifornimento per verificare."

    if cmd == "/rif_reset":
        parts = text.split()
        nome_ist = parts[1] if len(parts) > 1 else None
        n_ok, n_err = _reset_rif_stato(nome_ist)
        if n_ok == 0 and n_err > 0:
            target = nome_ist or "tutte le istanze"
            return f"⚠ Reset fallito per <b>{target}</b>. Controlla i log."
        target_str = f"<b>{nome_ist.upper()}</b>" if nome_ist else f"<b>{n_ok} istanze</b>"
        err_str = f"  ({n_err} errori)" if n_err else ""
        return (
            f"✅ Stato rifornimento azzerato per {target_str}{err_str}.\n"
            "spedizioni_oggi=0 · provviste_esaurite=False\n"
            "⚠ Effetto al prossimo tick dell'istanza (non retroattivo se tick in corso)."
        )

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

    if cmd == "/restart_bot_telegram":
        _schedule_self_restart(delay_s=5)
        return (
            "🔄 <b>Riavvio bot in 5s…</b>\n"
            "Il processo esce con codice 100 → <code>run_prod.bat</code> riparte "
            "automaticamente dopo 5s.\n"
            "Downtime totale: ~10-15s."
        )

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
    """True se il processo main.py Python è in esecuzione.

    Metodo primario: interroga Win32_Process via PowerShell per trovare
    python.exe con 'main.py' nella command line.
    Fallback: freschezza engine_status.json (< 10 min).
    """
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
             "| Where-Object { $_.CommandLine -like '*main.py*' "
             "  -and $_.CommandLine -notlike '*-m uvicorn*' } "
             "| Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=8,
        )
        count = r.stdout.strip()
        if count.isdigit() and int(count) > 0:
            return True
    except Exception:
        pass
    # Fallback: engine_status.json freschezza
    es = _read_engine_status()
    if not es:
        return False
    ts_raw = es.get("ts_update") or es.get("ts", "")
    if not ts_raw:
        return False
    try:
        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt).total_seconds() < 600
    except Exception:
        return False


# ─── Process launcher ─────────────────────────────────────────────────────────

_ROOT_PROD = Path("C:/doomsday-engine-prod")
_BAT_BOT        = _ROOT_PROD / "run_prod.bat"
_BAT_DASHBOARD  = _ROOT_PROD / "run_dashboard_prod.bat"


def _schedule_self_restart(delay_s: int = 5) -> None:
    """Spegne il processo bot Telegram dopo delay_s secondi.

    Il bat run_telegram_prod.bat rileva l'uscita e riavvia automaticamente
    il Python dopo 10s (loop :loop con timeout /t 10). Downtime totale ~15s.
    Usa os._exit (hard exit) per evitare hang su thread join del polling loop.
    """
    def _do():
        time.sleep(delay_s)
        _log.info("[TG-BOT] restart programmato — os._exit(100)")
        os._exit(100)  # 100 = codice atteso da run_prod.bat :run_loop per auto-restart
    t = threading.Thread(target=_do, daemon=True, name="tg-self-restart")
    t.start()


def _launch_bat(bat_path: Path, label: str) -> tuple[bool, str]:
    """Lancia un bat file in una nuova finestra console indipendente.

    Usa CREATE_NEW_CONSOLE invece di 'cmd /c start' perché la forma list[]
    di subprocess causa double-escaping delle virgolette nel titolo, portando
    cmd.exe a misparsare gli argomenti e ignorare silenziosamente il bat.
    """
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


# ─── Instance lock (evita doppio polling → errore 409) ───────────────────────

_PID_FILE: Optional[Path] = None


def _acquire_lock() -> bool:
    """Scrive data/telegram_bot.pid. Ritorna False se un'altra istanza è attiva."""
    global _PID_FILE
    pid_path = _root() / "data" / "telegram_bot.pid"
    my_pid   = os.getpid()

    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text(encoding="utf-8").strip())
            if old_pid != my_pid:
                import subprocess
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

    # Lock istanza singola — previene doppio polling (errore 409)
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

    # Notifica di avvio in background dopo 8s (attende inizializzazione rete)
    def _delayed_startup_notify():
        time.sleep(8)
        _log.info("[TG-BOT] invio notifica startup...")
        _notify_startup()

    threading.Thread(target=_delayed_startup_notify, daemon=True,
                     name="TgStartupNotify").start()

    _svc_stop.wait()   # blocca fino a SIGINT / SIGTERM
    stop(timeout_s=5)
    _release_lock()
    _log.info("=== Telegram bot service terminato ===")
