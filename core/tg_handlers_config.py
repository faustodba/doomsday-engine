"""core/tg_handlers_config.py — Handler comandi di configurazione.

Comandi: /stop_messaggi /start_messaggi
         /disabilita /abilita (istanza)
         /task /disabilita_task /abilita_task
         /rif_risorsa /rif_modo /rif_soglia /rif_provviste /rif_reset
"""

from __future__ import annotations

import logging

from core.tg_utils import (
    _read_runtime_overrides,
    _reset_rif_stato,
    _set_istanza_abilitata,
    _set_messaggi_enabled,
    _set_rif_modo,
    _set_rif_provviste,
    _set_rif_risorsa,
    _set_rif_soglia,
    _set_task,
    _tg_enabled,
)

_log = logging.getLogger(__name__)


# ─── Handler functions (signature: text -> str) ───────────────────────────────

def cmd_stop_messaggi(text: str) -> str:
    if not _tg_enabled():
        return "🔕 Notifiche già disabilitate. Usa /start_messaggi per riattivarle."
    ok = _set_messaggi_enabled(False)
    if ok:
        return "🔕 Notifiche proattive disabilitate.\nUsa /start_messaggi per riattivarle."
    return "⚠ Errore durante la disabilitazione. Controlla i log."


def cmd_start_messaggi(text: str) -> str:
    if _tg_enabled():
        return "🔔 Notifiche già abilitate. Usa /stop_messaggi per disabilitarle."
    ok = _set_messaggi_enabled(True)
    if ok:
        return "🔔 Notifiche proattive abilitate.\nRiceverai: ciclo completato, cascade ADB, DRL saturo, daily report."
    return "⚠ Errore durante l'abilitazione. Controlla i log."


def cmd_disabilita(text: str) -> str:
    return _cmd_toggle_istanza(text, abilitata=False)

def cmd_abilita(text: str) -> str:
    return _cmd_toggle_istanza(text, abilitata=True)

def _cmd_toggle_istanza(text: str, abilitata: bool) -> str:
    cmd   = text.split()[0]
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


def cmd_task(text: str) -> str:
    ov        = _read_runtime_overrides()
    task_dict = ov.get("globali", {}).get("task", {})
    if not task_dict:
        return "⚠ Nessun task configurato in runtime_overrides.json"
    lines = ["📋 <b>Task globali</b>", ""]
    for nome_t, stato in sorted(task_dict.items()):
        icona = "🟢" if stato else "🔴"
        lines.append(f"{icona} {nome_t}")
    lines += ["", "Usa /disabilita_task &lt;nome&gt; o /abilita_task &lt;nome&gt;"]
    return "\n".join(lines)


def cmd_disabilita_task(text: str) -> str:
    return _cmd_toggle_task(text, abilitata=False)

def cmd_abilita_task(text: str) -> str:
    return _cmd_toggle_task(text, abilitata=True)

def _cmd_toggle_task(text: str, abilitata: bool) -> str:
    cmd   = text.split()[0]
    parts = text.split()
    if len(parts) < 2:
        return (
            f"⚠ Uso: {cmd} &lt;nome_task&gt;  (es. {cmd} arena)\n"
            "Usa /task per vedere la lista dei task e il loro stato."
        )
    nome_task = parts[1].lower()
    ov_now    = _read_runtime_overrides()
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


def cmd_rif_risorsa(text: str) -> str:
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


def cmd_rif_modo(text: str) -> str:
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


def cmd_rif_soglia(text: str) -> str:
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


def cmd_rif_provviste(text: str) -> str:
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


def cmd_rif_reset(text: str) -> str:
    parts    = text.split()
    nome_ist = parts[1] if len(parts) > 1 else None
    n_ok, n_err = _reset_rif_stato(nome_ist)
    if n_ok == 0 and n_err > 0:
        target = nome_ist or "tutte le istanze"
        return f"⚠ Reset fallito per <b>{target}</b>. Controlla i log."
    target_str = f"<b>{nome_ist.upper()}</b>" if nome_ist else f"<b>{n_ok} istanze</b>"
    err_str    = f"  ({n_err} errori)" if n_err else ""
    return (
        f"✅ Stato rifornimento azzerato per {target_str}{err_str}.\n"
        "spedizioni_oggi=0 · provviste_esaurite=False\n"
        "⚠ Effetto al prossimo tick dell'istanza (non retroattivo se tick in corso)."
    )
