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
    farm_stato,
    istanza_stato_completo,
    task_performance,
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

_ESITO_ICON = {
    "running":  "▶",
    "ok":       "✓",
    "cascade":  "⚡",
    "abort":    "✗",
    "attesa":   "⏳",
}

@mcp.tool()
def ciclo_stato() -> str:
    """Analisi completa dell'ultimo ciclo di tutte le istanze abilitate."""
    stato = stato_ciclo_completo(ROOT)
    righe: list[str] = []

    # Header ciclo
    ts_str = str(stato.get("ciclo_start_ts", ""))[:16].replace("T", " ")
    stato_ciclo = "COMPLETATO" if stato.get("completato") else "IN CORSO"
    righe.append(f"=== CICLO {stato['ciclo_n']} — {stato_ciclo} (avv. {ts_str}) ===")
    righe.append(f"Anomalie totali: {stato['anomalie_totali']}")
    righe.append("")

    for nome, dati in stato["istanze"].items():
        esito        = dati.get("esito", "attesa")
        task_live    = dati.get("task_corrente")
        icon         = _ESITO_ICON.get(esito, "?")
        launcher     = dati.get("launcher") or {}
        raccolta     = dati.get("raccolta") or {}
        tasks        = dati.get("tasks")    or {}
        anomalie     = dati.get("anomalie") or []

        # Riga header istanza con esito e task live
        header = f"--- {nome} [{icon} {esito}]"
        if esito == "running" and task_live:
            header += f" → {task_live}"
        righe.append(header)

        if launcher and launcher.get("home_raggiunto"):
            righe.append(
                f"  launcher: reset={launcher.get('reset_completato')} "
                f"android={launcher.get('android_started_s')}s "
                f"stab={launcher.get('stabilizzazione')} "
                f"instabili={launcher.get('home_instabili')}"
            )
        if tasks:
            tasks_str = ", ".join(f"{k}={v}" for k, v in tasks.items())
            righe.append(f"  tasks: {tasks_str}")
        if raccolta and (raccolta.get("inviate") or raccolta.get("slot_pieni")):
            righe.append(
                f"  raccolta: inviate={raccolta.get('inviate')} "
                f"slot_pieni={raccolta.get('slot_pieni')} "
                f"tipi_bloccati={raccolta.get('tipi_bloccati')} "
                f"tentativi={raccolta.get('tentativi_ciclo')}"
            )
            nodi_b = raccolta.get("nodi_blacklist") or []
            if nodi_b:
                righe.append(f"    blacklist: {nodi_b[:5]}{'…' if len(nodi_b) > 5 else ''}")
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
# Tool 7 — farm_stato
# ==============================================================================

@mcp.tool()
def farm_stato_globale() -> str:
    """Snapshot globale della farm: DRL master, spedizioni, produzione/ora, truppe, storico 3gg."""
    d = farm_stato(ROOT)
    out: list[str] = ["=== FARM — STATO GLOBALE ===", ""]

    # Master DRL
    m = d.get("master", {})
    if m:
        saturo = "🔴 SATURO" if m.get("saturo") else "🟢"
        out.append(f"DRL FauMorfeus: {saturo} {m.get('drl_residuo_m')}M / {m.get('drl_max_m')}M "
                   f"({m.get('drl_pct')}%)  tassa {m.get('tassa_pct')}%  @{m.get('ts','')}")

    # Spedizioni totali
    out.append(f"\nSpedizioni oggi: {d.get('spedizioni_totali', 0)}")
    inv = d.get("inviato_totale_m", {})
    if inv:
        out.append("Inviato totale M: " + "  ".join(f"{k}={v}" for k,v in inv.items()))

    # Produzione/ora farm
    prod = d.get("farm_prod_h_m", {})
    if prod:
        out.append("Prod/ora farm M/h: " + "  ".join(f"{k}={v}" for k,v in prod.items()))

    # Per-istanza
    out.append("\n--- Istanze ---")
    for nome, ist in sorted(d.get("istanze", {}).items()):
        parts = [f"{nome}:"]
        if ist.get("sped_oggi"):
            parts.append(f"sped={ist['sped_oggi']}")
        if ist.get("inviato_m"):
            inv_str = " ".join(f"{k}={v}M" for k,v in ist["inviato_m"].items())
            parts.append(f"inviato=[{inv_str}]")
        if ist.get("prod_h_m"):
            prod_str = " ".join(f"{k}={v}" for k,v in ist["prod_h_m"].items())
            parts.append(f"prod_h={prod_str}")
        if ist.get("boost"):
            parts.append(f"boost={ist['boost']}")
        if ist.get("arena_esaurita"):
            parts.append("arena=✓")
        if ist.get("provviste_m") is not None:
            parts.append(f"provviste={ist['provviste_m']}M")
        out.append("  " + "  ".join(parts))

    # Truppe
    truppe = d.get("truppe", {})
    if truppe:
        out.append("\n--- Truppe (total_squads) ---")
        for nome, sq in sorted(truppe.items()):
            out.append(f"  {nome}: {sq:,}")

    # Storico 3gg
    storico = d.get("storico_3gg", {})
    if storico:
        out.append("\n--- Storico invii (ultimi 3 giorni) ---")
        for data, totali in sorted(storico.items()):
            riga = "  ".join(f"{k}={v}M" for k,v in totali.items())
            out.append(f"  {data}: {riga}")

    return "\n".join(out)


# ==============================================================================
# Tool 8 — istanza_stato
# ==============================================================================

@mcp.tool()
def istanza_stato(nome: str) -> str:
    """Stato completo di una singola istanza: rifornimento, boost, arena, produzione, metriche, storico task.

    Args:
        nome: nome istanza (es. FAU_00, FAU_09, FauMorfeus)
    """
    d = istanza_stato_completo(ROOT, nome)
    out: list[str] = [f"=== {nome} — STATO COMPLETO ===", ""]

    # Live
    live = d.get("live", {})
    if live.get("stato"):
        stato_str = f"▶ IN ESECUZIONE ({live['task_corrente']})" if live.get("task_corrente") else live["stato"]
        out.append(f"Stato: {stato_str}")

    # Ultimo tick
    ult = d.get("ultimo_tick", {})
    if ult:
        out.append(f"\nUltimo tick ({ult.get('ts','')}):")
        out.append(f"  outcome={ult.get('outcome')}  boot={ult.get('boot_home_s')}s  "
                   f"tick={ult.get('tick_total_s')}s")
        out.append(f"  raccolta: {ult.get('marce')} marce  slot {ult.get('slot')}")
        top3 = ult.get("task_top3_s", {})
        if top3:
            top3_str = "  ".join(f"{k}={v:.0f}s" for k,v in top3.items())
            out.append(f"  task più lenti: {top3_str}")

    # Rifornimento
    rif = d.get("rifornimento", {})
    if rif:
        out.append(f"\nRifornimento:")
        out.append(f"  spedizioni_oggi={rif.get('spedizioni_oggi')}  "
                   f"tassa={rif.get('tassa_pct')}%  ultima={rif.get('ultima_sped','')}")
        if rif.get("inviato_m"):
            inv_str = "  ".join(f"{k}={v}M" for k,v in rif["inviato_m"].items())
            out.append(f"  inviato oggi: {inv_str}")
        if rif.get("provviste_m") is not None:
            out.append(f"  provviste residue: {rif['provviste_m']}M")

    # Boost
    if d.get("boost"):
        out.append(f"\nBoost: {d['boost']}")

    # Arena
    arn = d.get("arena", {})
    if arn:
        esaurite_str = "✓ esaurite" if arn.get("esaurite") else "⏳ disponibili"
        out.append(f"\nArena: {esaurite_str}  (data={arn.get('data_rif','')})")

    # Produzione/ora
    if d.get("prod_h"):
        prod_str = "  ".join(f"{k}={v}" for k,v in d["prod_h"].items())
        out.append(f"\nProd/ora: {prod_str}")

    # Truppe
    if d.get("truppe"):
        delta_str = f"  Δ{d['truppe_delta']:+,}" if d.get("truppe_delta") else ""
        out.append(f"\nTruppe: {d['truppe']:,}{delta_str}")

    # Storico task recenti
    if d.get("storico_task"):
        out.append("\nStorico task recenti:")
        for t in d["storico_task"]:
            out.append(f"  {t}")

    if "state_error" in d:
        out.append(f"\n⚠ state file error: {d['state_error']}")

    return "\n".join(out)


# ==============================================================================
# Tool 9 — task_performance
# ==============================================================================

@mcp.tool()
def performance_task() -> str:
    """Performance dei task nell'engine_status.storico: count, ok%, durata media, errori recenti."""
    perf = task_performance(ROOT)
    if not perf:
        return "Nessun dato in engine_status.storico"
    out = ["=== PERFORMANCE TASK ===", ""]
    out.append(f"{'Task':<20} {'Count':>5} {'OK%':>5} {'Dur.avg':>8}  Ultimi fail")
    out.append("-" * 70)
    for task, d in sorted(perf.items(), key=lambda x: -x[1]["count"]):
        ok_pct  = d["ok_pct"]
        ok_icon = "🟢" if ok_pct == 100 else ("🟡" if ok_pct >= 80 else "🔴")
        fails   = " | ".join(d["fails"][:2]) if d["fails"] else ""
        out.append(
            f"{task:<20} {d['count']:>5} {ok_icon}{ok_pct:>3}% {d['dur_avg_s']:>7.1f}s  {fails}"
        )
    return "\n".join(out)


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
