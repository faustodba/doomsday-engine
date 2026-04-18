# ==============================================================================
#  DOOMSDAY ENGINE V6 — monitor/analyzer.py
#
#  Parsing e analisi log JSONL per MCP server.
#  Tutte le funzioni sono pure (nessuno stato globale).
# ==============================================================================

from __future__ import annotations

import json
import os
import re
from collections import deque
from typing import Any


# ==============================================================================
# Lettura JSONL
# ==============================================================================

def leggi_jsonl_tail(path: str, n: int = 100) -> list[dict]:
    """Legge le ultime n righe di un file JSONL. Ritorna [] se file assente."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=n)
    except Exception:
        return []
    out: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def leggi_jsonl_da(path: str, da_ts: str) -> list[dict]:
    """Legge tutte le righe JSONL con ts >= da_ts (ISO string)."""
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("ts", "")
                if ts and ts >= da_ts:
                    out.append(row)
    except Exception:
        return out
    return out


def leggi_txt_tail(path: str, n: int = 100) -> list[str]:
    """Legge le ultime n righe di un file di testo semplice (bot.log)."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=n)
    except Exception:
        return []
    return [ln.rstrip("\n") for ln in tail]


# ==============================================================================
# Rilevamento anomalie
# ==============================================================================

_PATTERN_ERROR = [
    (r"FALLITO",                      "ERROR"),
    (r"\bfallito\b",                  "ERROR"),
    (r"vai_in_mappa fallito",         "ERROR"),
    (r"troppi fallimenti",            "ERROR"),
    (r"impossibile andare in mappa",  "ERROR"),
    (r"avvia_istanza\(\) fallito",    "ERROR"),
    (r"screenshot None",              "ERROR"),
    (r"timeout battaglia",            "ERROR"),
]
_PATTERN_WARN = [
    (r"NON selezionato",              "WARN"),
    (r"stabilizzazione timeout",      "WARN"),
    (r"HOME instabile",               "WARN"),
    (r"abort sequenza livelli",       "WARN"),
]


def rileva_anomalie(righe: list[dict]) -> list[dict]:
    """
    Scansiona righe JSONL e ritorna solo quelle anomale.
    Ogni anomalia ritorna: {ts, instance, module, msg, severita}
    severita: 'ERROR' | 'WARN'
    """
    out: list[dict] = []
    for row in righe:
        msg = str(row.get("msg", ""))
        if not msg:
            continue
        severita = None
        for pat, sev in _PATTERN_ERROR + _PATTERN_WARN:
            if re.search(pat, msg, re.IGNORECASE):
                severita = sev
                break
        if severita is None:
            continue
        out.append({
            "ts":        row.get("ts", ""),
            "instance":  row.get("instance", ""),
            "module":    row.get("module", ""),
            "msg":       msg,
            "severita":  severita,
        })
    return out


# ==============================================================================
# Analisi raccolta
# ==============================================================================

_RE_INVIATE        = re.compile(r"squadra confermata \((\d+)/\d+\)")
_RE_SLOT_PIENI     = re.compile(r"slot pieni", re.IGNORECASE)
_RE_TIPO_BLOCCATO  = re.compile(r"tipo '(\w+)' bloccato")
_RE_SKIP_NEUTRO    = re.compile(r"skip neutro (\w+) \((\d+)/\d+\)")
_RE_FALLIMENTO     = re.compile(r"fallimenti_cons=(\d+)/")
_RE_TENTATIVO      = re.compile(r"tentativo (\d+)/(\d+)", re.IGNORECASE)
_RE_BLACKLIST_NOD  = re.compile(r"nodo (\d+_\d+) .*blacklist", re.IGNORECASE)
_RE_FUORI          = re.compile(r"nodo (\d+_\d+) FUORI|(\d+_\d+) in blacklist statica fuori")
_RE_LIVELLO_USATO  = re.compile(r"CERCA eseguita per \w+ Lv\.(\d+)")


def analizza_raccolta(righe: list[dict]) -> dict:
    """
    Estrae statistiche raccolta da righe JSONL.
    """
    inviate         = 0
    slot_pieni      = False
    tipi_bloccati:  set[str]     = set()
    skip_neutri:    dict[str, int] = {}
    fallimenti      = 0
    tentativi_ciclo = 0
    nodi_blacklist: set[str]     = set()
    nodi_fuori:     set[str]     = set()
    livelli_usati:  set[int]     = set()

    for row in righe:
        msg = str(row.get("msg", ""))
        if row.get("module") != "task":
            continue

        m = _RE_INVIATE.search(msg)
        if m:
            inviate = max(inviate, int(m.group(1)))

        if _RE_SLOT_PIENI.search(msg):
            slot_pieni = True

        m = _RE_TIPO_BLOCCATO.search(msg)
        if m:
            tipi_bloccati.add(m.group(1))

        m = _RE_SKIP_NEUTRO.search(msg)
        if m:
            skip_neutri[m.group(1)] = int(m.group(2))

        m = _RE_FALLIMENTO.search(msg)
        if m:
            fallimenti = max(fallimenti, int(m.group(1)))

        m = _RE_TENTATIVO.search(msg)
        if m and "completato" in msg.lower():
            tentativi_ciclo = max(tentativi_ciclo, int(m.group(1)))

        m = _RE_BLACKLIST_NOD.search(msg)
        if m:
            nodi_blacklist.add(m.group(1))

        if "FUORI territorio" in msg or "blacklist statica fuori" in msg:
            # estrai eventuale coord X_Y
            coord = re.search(r"(\d{3}_\d{3})", msg)
            if coord:
                nodi_fuori.add(coord.group(1))

        m = _RE_LIVELLO_USATO.search(msg)
        if m:
            livelli_usati.add(int(m.group(1)))

    return {
        "inviate":          inviate,
        "slot_pieni":       slot_pieni,
        "tipi_bloccati":    sorted(tipi_bloccati),
        "skip_neutri":      skip_neutri,
        "fallimenti":       fallimenti,
        "tentativi_ciclo":  tentativi_ciclo,
        "nodi_blacklist":   sorted(nodi_blacklist),
        "nodi_fuori_territorio": sorted(nodi_fuori),
        "livelli_usati":    sorted(livelli_usati),
    }


# ==============================================================================
# Analisi launcher
# ==============================================================================

_RE_ANDROID_STARTED = re.compile(r"Android started dopo (\d+)s")
_RE_HOME_STABILE    = re.compile(r"HOME stabile (\d+)/3")
_RE_HOME_RAGGIUNTA  = re.compile(r"HOME raggiunto|HOME stabilizzata — pronti")
_RE_RESET_COMPL     = re.compile(r"reset completato")
_RE_HOME_INSTABILE  = re.compile(r"HOME instabile")
_RE_STAB_TIMEOUT    = re.compile(r"stabilizzazione timeout")


def analizza_launcher(righe: list[dict]) -> dict:
    """
    Estrae statistiche launcher dalle righe JSONL di un'istanza.
    """
    reset_completato   = False
    android_started_s  = -1
    home_raggiunto     = False
    stabilizzazione    = "N/D"
    home_instabili     = 0
    ultimo_stable_n    = 0

    for row in righe:
        msg = str(row.get("msg", ""))

        if _RE_RESET_COMPL.search(msg):
            reset_completato = True

        m = _RE_ANDROID_STARTED.search(msg)
        if m:
            android_started_s = int(m.group(1))

        m = _RE_HOME_STABILE.search(msg)
        if m:
            ultimo_stable_n = int(m.group(1))

        if _RE_HOME_INSTABILE.search(msg):
            home_instabili += 1

        if _RE_STAB_TIMEOUT.search(msg):
            stabilizzazione = "timeout"

        if "HOME stabilizzata — pronti" in msg:
            stabilizzazione = "3/3"

        if _RE_HOME_RAGGIUNTA.search(msg):
            home_raggiunto = True

    # Se nessuna convergenza e nessun timeout, usa l'ultimo stable_count
    if stabilizzazione == "N/D" and ultimo_stable_n > 0:
        stabilizzazione = f"{ultimo_stable_n}/3"

    return {
        "reset_completato":  reset_completato,
        "android_started_s": android_started_s,
        "home_raggiunto":    home_raggiunto,
        "stabilizzazione":   stabilizzazione,
        "home_instabili":    home_instabili,
    }


# ==============================================================================
# Stato ciclo completo (multi-istanza)
# ==============================================================================

_RE_CICLO_N      = re.compile(r"CICLO (\d+)")
_RE_TASK_DOVUTI  = re.compile(r"Tick -- (\d+) task dovuti su (\d+)")
_RE_TASK_COMPL   = re.compile(r"task '(\w+)' completato -- success=(True|False)")


def _parse_tasks(righe: list[dict]) -> dict:
    """Estrae stato task eseguiti."""
    esito: dict[str, str] = {}
    for row in righe:
        msg = str(row.get("msg", ""))
        m = _RE_TASK_COMPL.search(msg)
        if m:
            esito[m.group(1)] = "OK" if m.group(2) == "True" else "FAIL"
    return esito


def _carica_istanze_abilitate(root: str) -> list[str]:
    """Legge instances.json e ritorna le istanze abilitate."""
    path = os.path.join(root, "config", "instances.json")
    if not os.path.exists(path):
        return ["FAU_00", "FAU_01", "FAU_02"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [i.get("nome") for i in data if i.get("abilitata", False)]
    except Exception:
        return ["FAU_00", "FAU_01", "FAU_02"]


def stato_ciclo_completo(root: str) -> dict:
    """
    Legge i JSONL di tutte le istanze abilitate e bot.log.
    Ritorna summary completo ultimo ciclo.
    """
    istanze = _carica_istanze_abilitate(root)

    # Parse bot.log per ciclo corrente
    bot_log_path = os.path.join(root, "bot.log")
    righe_bot = leggi_txt_tail(bot_log_path, n=500)
    ciclo_n = 0
    for line in reversed(righe_bot):
        m = _RE_CICLO_N.search(line)
        if m:
            ciclo_n = int(m.group(1))
            break

    ris_istanze: dict[str, dict] = {}
    anomalie_totali = 0

    for nome in istanze:
        jpath = os.path.join(root, "logs", f"{nome}.jsonl")
        righe = leggi_jsonl_tail(jpath, n=500)
        if not righe:
            ris_istanze[nome] = {
                "launcher": {},
                "tasks":    {},
                "raccolta": {},
                "anomalie": [],
            }
            continue
        anomalie = rileva_anomalie(righe)
        ris_istanze[nome] = {
            "launcher": analizza_launcher(righe),
            "tasks":    _parse_tasks(righe),
            "raccolta": analizza_raccolta(righe),
            "anomalie": anomalie[-20:],  # ultime 20 anomalie
        }
        anomalie_totali += len(anomalie)

    return {
        "ciclo_n":         ciclo_n,
        "istanze":         ris_istanze,
        "anomalie_totali": anomalie_totali,
    }
