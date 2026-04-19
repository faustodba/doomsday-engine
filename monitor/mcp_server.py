# ==============================================================================
#  DOOMSDAY ENGINE V6 — monitor/mcp_server.py
#
#  MCP server (FastMCP, stdio) per il monitoring di Doomsday Engine V6.
#  Espone tool per analisi log, anomalie, stato ciclo.
# ==============================================================================

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

# Aggiungi la cartella padre al path per permettere "from monitor.analyzer ..."
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from mcp.server.fastmcp import FastMCP

from monitor.analyzer import (
    leggi_jsonl_tail,
    leggi_jsonl_da,
    leggi_txt_tail,
    rileva_anomalie,
    analizza_raccolta,
    analizza_launcher,
    stato_ciclo_completo,
)


_AUTO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT    = os.environ.get("DOOMSDAY_ROOT", _AUTO_ROOT)
ISTANZE = os.environ.get("DOOMSDAY_ISTANZE", "FAU_00,FAU_01,FAU_02").split(",")

mcp = FastMCP("doomsday-monitor")


# ==============================================================================
# Helpers
# ==============================================================================

def _path_log(nome: str) -> str:
    """Risolve il path del log JSONL (o bot.log) di una istanza."""
    if nome == "bot":
        return os.path.join(ROOT, "bot.log")
    return os.path.join(ROOT, "logs", f"{nome}.jsonl")


def _fmt_row(row: dict) -> str:
    """Formatta una riga JSONL in testo leggibile."""
    ts   = str(row.get("ts", "?"))[:19].replace("T", " ")
    lvl  = str(row.get("level", "?"))[:5]
    inst = str(row.get("instance", "?"))
    mod  = str(row.get("module", "?"))
    msg  = str(row.get("msg", ""))
    return f"[{ts}] {lvl} {inst}/{mod}: {msg}"


def _fmt_anomalia(a: dict) -> str:
    ts   = str(a.get("ts", "?"))[:19].replace("T", " ")
    sev  = a.get("severita", "?")
    inst = a.get("instance", "?")
    msg  = a.get("msg", "")
    return f"[{ts}] {sev:5} {inst}: {msg}"


# ==============================================================================
# Tool 1 — ciclo_stato
# ==============================================================================

@mcp.tool()
def ciclo_stato() -> str:
    """Analisi completa dell'ultimo ciclo di tutte le istanze abilitate."""
    stato = stato_ciclo_completo(ROOT)
    righe: list[str] = []
    righe.append(f"=== CICLO {stato['ciclo_n']} ===")
    righe.append(f"Anomalie totali: {stato['anomalie_totali']}")
    righe.append("")
    for nome, dati in stato["istanze"].items():
        righe.append(f"--- {nome} ---")
        launcher = dati.get("launcher") or {}
        raccolta = dati.get("raccolta") or {}
        tasks    = dati.get("tasks")    or {}
        anomalie = dati.get("anomalie") or []

        if launcher:
            righe.append(
                f"  launcher: reset={launcher.get('reset_completato')} "
                f"android={launcher.get('android_started_s')}s "
                f"home={launcher.get('home_raggiunto')} "
                f"stab={launcher.get('stabilizzazione')} "
                f"instabili={launcher.get('home_instabili')}"
            )
        if tasks:
            tasks_str = ", ".join(f"{k}={v}" for k, v in tasks.items())
            righe.append(f"  tasks: {tasks_str}")
        if raccolta:
            righe.append(
                f"  raccolta: inviate={raccolta.get('inviate')} "
                f"slot_pieni={raccolta.get('slot_pieni')} "
                f"tipi_bloccati={raccolta.get('tipi_bloccati')} "
                f"tentativi={raccolta.get('tentativi_ciclo')}"
            )
            skip_n = raccolta.get("skip_neutri") or {}
            if skip_n:
                righe.append(f"    skip_neutri: {skip_n}")
            nodi_b = raccolta.get("nodi_blacklist") or []
            if nodi_b:
                righe.append(f"    blacklist: {nodi_b[:5]}{'…' if len(nodi_b) > 5 else ''}")
            nodi_f = raccolta.get("nodi_fuori_territorio") or []
            if nodi_f:
                righe.append(f"    fuori_territorio: {nodi_f[:5]}{'…' if len(nodi_f) > 5 else ''}")
            livelli = raccolta.get("livelli_usati") or []
            if livelli:
                righe.append(f"    livelli_usati: {livelli}")
        if anomalie:
            righe.append(f"  anomalie ({len(anomalie)}):")
            for a in anomalie[-5:]:
                righe.append(f"    {_fmt_anomalia(a)}")
        righe.append("")
    return "\n".join(righe)


# ==============================================================================
# Tool 2 — istanza_anomalie
# ==============================================================================

@mcp.tool()
def istanza_anomalie(nome: str, n_righe: int = 200) -> str:
    """Anomalie rilevate nelle ultime n_righe del log di una istanza.

    Args:
        nome: FAU_00 | FAU_01 | FAU_02
        n_righe: numero di righe da analizzare (default 200)
    """
    if nome not in ISTANZE and nome != "bot":
        return f"Istanza sconosciuta: {nome}. Valide: {ISTANZE} o 'bot'"
    path = _path_log(nome)
    righe = leggi_jsonl_tail(path, n=n_righe)
    if not righe:
        return f"Nessuna riga JSONL trovata in {path}"
    anomalie = rileva_anomalie(righe)
    if not anomalie:
        return f"{nome}: nessuna anomalia rilevata nelle ultime {n_righe} righe"
    out = [f"=== {nome} — {len(anomalie)} anomalie in {n_righe} righe ==="]
    for a in anomalie:
        out.append(_fmt_anomalia(a))
    return "\n".join(out)


# ==============================================================================
# Tool 3 — istanza_raccolta
# ==============================================================================

@mcp.tool()
def istanza_raccolta(nome: str) -> str:
    """Statistiche raccolta dell'ultimo tick di una istanza.

    Args:
        nome: FAU_00 | FAU_01 | FAU_02
    """
    if nome not in ISTANZE:
        return f"Istanza sconosciuta: {nome}. Valide: {ISTANZE}"
    path = _path_log(nome)
    righe = leggi_jsonl_tail(path, n=500)
    if not righe:
        return f"Nessuna riga per {nome}"
    stat = analizza_raccolta(righe)
    out = [f"=== {nome} — Raccolta ultimo tick ==="]
    out.append(f"Inviate:             {stat['inviate']}")
    out.append(f"Slot pieni:          {stat['slot_pieni']}")
    out.append(f"Tentativi ciclo:     {stat['tentativi_ciclo']}")
    out.append(f"Fallimenti_cons max: {stat['fallimenti']}")
    out.append(f"Tipi bloccati:       {stat['tipi_bloccati']}")
    out.append(f"Skip neutri:         {stat['skip_neutri']}")
    out.append(f"Livelli usati:       {stat['livelli_usati']}")
    if stat["nodi_blacklist"]:
        out.append(f"Nodi blacklist ({len(stat['nodi_blacklist'])}): "
                   f"{stat['nodi_blacklist'][:10]}")
    if stat["nodi_fuori_territorio"]:
        out.append(f"Nodi fuori territorio ({len(stat['nodi_fuori_territorio'])}): "
                   f"{stat['nodi_fuori_territorio'][:10]}")
    return "\n".join(out)


# ==============================================================================
# Tool 4 — istanza_launcher
# ==============================================================================

@mcp.tool()
def istanza_launcher(nome: str) -> str:
    """Stato launcher dell'ultimo avvio di una istanza.

    Args:
        nome: FAU_00 | FAU_01 | FAU_02
    """
    if nome not in ISTANZE:
        return f"Istanza sconosciuta: {nome}. Valide: {ISTANZE}"
    path = _path_log(nome)
    righe = leggi_jsonl_tail(path, n=300)
    if not righe:
        return f"Nessuna riga per {nome}"
    stat = analizza_launcher(righe)
    out = [f"=== {nome} — Launcher ultimo avvio ==="]
    out.append(f"Reset completato:    {stat['reset_completato']}")
    out.append(f"Android started:     {stat['android_started_s']}s")
    out.append(f"HOME raggiunta:      {stat['home_raggiunto']}")
    out.append(f"Stabilizzazione:     {stat['stabilizzazione']}")
    out.append(f"HOME instabili:      {stat['home_instabili']}")
    return "\n".join(out)


# ==============================================================================
# Tool 5 — log_tail
# ==============================================================================

@mcp.tool()
def log_tail(nome: str, n: int = 50) -> str:
    """Ultime n righe del log di una istanza, formato leggibile.

    Args:
        nome: FAU_00 | FAU_01 | FAU_02 | bot (per bot.log)
        n: numero di righe (default 50)
    """
    path = _path_log(nome)
    if not os.path.exists(path):
        return f"File non trovato: {path}"
    if nome == "bot":
        righe = leggi_txt_tail(path, n=n)
        return "\n".join(righe) if righe else "(log vuoto)"
    righe = leggi_jsonl_tail(path, n=n)
    if not righe:
        return "(log vuoto)"
    return "\n".join(_fmt_row(r) for r in righe)


# ==============================================================================
# Tool 6 — anomalie_live
# ==============================================================================

@mcp.tool()
def anomalie_live() -> str:
    """Anomalie degli ultimi 10 minuti da tutte le istanze abilitate."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    totale: list[dict] = []
    for nome in ISTANZE:
        path = _path_log(nome)
        righe = leggi_jsonl_da(path, cutoff)
        if not righe:
            continue
        anomalie = rileva_anomalie(righe)
        for a in anomalie:
            a = dict(a)
            a["instance"] = a.get("instance") or nome
            totale.append(a)
    if not totale:
        return f"Nessuna anomalia negli ultimi 10 minuti (cutoff={cutoff})"
    totale.sort(key=lambda x: x.get("ts", ""))
    out = [f"=== Anomalie ultimi 10 minuti — {len(totale)} totali ==="]
    for a in totale:
        out.append(_fmt_anomalia(a))
    return "\n".join(out)


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
