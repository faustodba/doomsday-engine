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
    """Legge instances.json + runtime_overrides e ritorna le istanze abilitate.

    La chiave `abilitata` in runtime_overrides ha priorità su instances.json.
    """
    path = os.path.join(root, "config", "instances.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ["FAU_00", "FAU_01", "FAU_02"]

    # Override runtime: runtime_overrides.json::istanze.{nome}.abilitata
    ov_istanze: dict = {}
    ov_path = os.path.join(root, "config", "runtime_overrides.json")
    try:
        with open(ov_path, "r", encoding="utf-8") as f:
            ov = json.load(f)
        ov_istanze = ov.get("istanze", {})
    except Exception:
        pass

    result = []
    for ist in data:
        nome = ist.get("nome")
        if not nome:
            continue
        if nome in ov_istanze and "abilitata" in ov_istanze[nome]:
            abilitata = ov_istanze[nome]["abilitata"]
        else:
            abilitata = ist.get("abilitata", True)
        if abilitata:
            result.append(nome)
    return result


def stato_ciclo_completo(root: str) -> dict:
    """
    Stato del ciclo corrente basato su sorgenti affidabili:
      - data/telemetry/cicli.json  → numero ciclo + timestamp per-istanza
      - engine_status.json         → istanza live + task_corrente
      - logs/FAU_XX.jsonl          → filtrati da start_ts istanza (solo ciclo corrente)
    """
    # ── 1. Ciclo corrente da cicli.json ────────────────────────────────────────
    ciclo_n        = 0
    ciclo_start_ts = ""
    ciclo_completo = False
    ist_ciclo: dict[str, dict] = {}   # {nome: {start_ts, end_ts, esito}}

    cicli_path = os.path.join(root, "data", "telemetry", "cicli.json")
    try:
        with open(cicli_path, "r", encoding="utf-8") as f:
            cicli_data = json.load(f)
        cicli_list = sorted(
            cicli_data.get("cicli", []),
            key=lambda c: c.get("start_ts", ""),
            reverse=True,
        )
        if cicli_list:
            c = cicli_list[0]
            ciclo_n        = c.get("numero", 0)
            ciclo_start_ts = c.get("start_ts", "")
            ciclo_completo = c.get("completato", False)
            ist_ciclo      = c.get("istanze", {})
    except Exception:
        pass

    # ── 2. Stato live da engine_status.json ────────────────────────────────────
    engine_ist: dict[str, dict] = {}
    es_path = os.path.join(root, "engine_status.json")
    try:
        with open(es_path, "r", encoding="utf-8") as f:
            es = json.load(f)
        engine_ist = es.get("istanze", {})
    except Exception:
        pass

    # ── 3. Lista istanze abilitate (instances.json + runtime_overrides) ────────
    istanze = _carica_istanze_abilitate(root)

    # ── 4. Analisi per-istanza ─────────────────────────────────────────────────
    ris_istanze: dict[str, dict] = {}
    anomalie_totali = 0

    for nome in istanze:
        ist_info   = ist_ciclo.get(nome, {})
        ist_start  = ist_info.get("start_ts", ciclo_start_ts)
        ist_esito  = ist_info.get("esito", "attesa")   # running/ok/cascade/abort/attesa

        # Task corrente dal live engine_status
        live       = engine_ist.get(nome, {})
        task_live  = live.get("task_corrente")

        # Log filtrati: solo righe successive all'avvio dell'istanza nel ciclo
        jpath = os.path.join(root, "logs", f"{nome}.jsonl")
        if ist_start:
            righe = leggi_jsonl_da(jpath, da_ts=ist_start)
        else:
            righe = leggi_jsonl_tail(jpath, n=300)

        if not righe:
            ris_istanze[nome] = {
                "esito":        ist_esito,
                "task_corrente": task_live,
                "launcher":     {},
                "tasks":        {},
                "raccolta":     {},
                "anomalie":     [],
            }
            continue

        anomalie = rileva_anomalie(righe)
        ris_istanze[nome] = {
            "esito":         ist_esito,
            "task_corrente": task_live,
            "launcher":      analizza_launcher(righe),
            "tasks":         _parse_tasks(righe),
            "raccolta":      analizza_raccolta(righe),
            "anomalie":      anomalie[-20:],
        }
        anomalie_totali += len(anomalie)

    return {
        "ciclo_n":         ciclo_n,
        "ciclo_start_ts":  ciclo_start_ts,
        "completato":      ciclo_completo,
        "istanze":         ris_istanze,
        "anomalie_totali": anomalie_totali,
    }


# ==============================================================================
# Farm stato globale
# ==============================================================================

def farm_stato(root: str) -> dict:
    """
    Snapshot globale della farm:
      - DRL master (FauMorfeus) da morfeus_state.json
      - Spedizioni totali oggi + per-istanza da state/FAU_XX.json
      - Produzione/ora aggregata da metrics per-istanza
      - Truppe per istanza da storico_truppe.json
      - Storico invii ultimi 3 giorni da storico_farm.json
    """
    result: dict = {}

    # ── DRL master ────────────────────────────────────────────────────────────
    morf_path = os.path.join(root, "data", "morfeus_state.json")
    try:
        with open(morf_path, encoding="utf-8") as f:
            m = json.load(f)
        drl     = m.get("daily_recv_limit", -1)
        drl_max = m.get("daily_recv_limit_max", 0)
        drl_pct = round(drl / drl_max * 100, 1) if drl_max > 0 else 0
        result["master"] = {
            "drl_residuo_m":   round(drl / 1e6, 1),
            "drl_max_m":       round(drl_max / 1e6, 1),
            "drl_pct":         drl_pct,
            "tassa_pct":       round(m.get("tassa_pct", 0) * 100, 1),
            "ts":              str(m.get("ts", ""))[:16],
            "saturo":          drl == 0,
        }
    except Exception:
        result["master"] = {}

    # ── Istanze: rifornimento + produzione/ora + boost + arena ────────────────
    state_dir = os.path.join(root, "state")
    istanze_stato: dict[str, dict] = {}
    tot_sped = 0
    tot_inviato_m: dict[str, float] = {}
    farm_prod: dict[str, float] = {}

    for fn in sorted(os.listdir(state_dir)):
        if not fn.endswith(".json") or fn.startswith("."):
            continue
        nome = fn[:-5]
        if nome == "FauMorfeus":
            continue
        try:
            with open(os.path.join(state_dir, fn), encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            continue

        rif  = st.get("rifornimento", {})
        met  = st.get("metrics", {})
        bst  = st.get("boost", {})
        arn  = st.get("arena", {})

        sped = rif.get("spedizioni_oggi", 0)
        tot_sped += sped

        # inviato per risorsa oggi
        inv = rif.get("inviato_oggi", {})
        for res, val in inv.items():
            tot_inviato_m[res] = tot_inviato_m.get(res, 0) + val / 1e6

        # prod/ora
        prod_h = {}
        for res in ("pomodoro", "legno", "acciaio", "petrolio"):
            val = met.get(f"{res}_per_ora", 0)
            if val and abs(val) > 100:
                prod_h[res] = round(val / 1e6, 3)
                farm_prod[res] = farm_prod.get(res, 0) + val

        # boost scadenza
        bst_info = None
        if bst.get("tipo"):
            from datetime import datetime, timezone
            scad = bst.get("scadenza", "")
            try:
                dt_scad = datetime.fromisoformat(scad.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                residuo_m = int((dt_scad - now).total_seconds() / 60)
                bst_info = f"{bst['tipo']} residuo {residuo_m}m" if residuo_m > 0 else f"{bst['tipo']} scaduto"
            except Exception:
                bst_info = bst.get("tipo")

        istanze_stato[nome] = {
            "sped_oggi":     sped,
            "inviato_m":     {k: round(v / 1e6, 1) for k, v in inv.items() if v > 0},
            "prod_h_m":      prod_h,
            "boost":         bst_info,
            "arena_esaurita": arn.get("esaurite", False),
            "provviste_m":   round(rif.get("provviste_residue", -1) / 1e6, 1)
                             if rif.get("provviste_residue", -1) >= 0 else None,
        }

    result["spedizioni_totali"] = tot_sped
    result["inviato_totale_m"]  = {k: round(v, 1) for k, v in tot_inviato_m.items()}
    result["farm_prod_h_m"]     = {k: round(v / 1e6, 3) for k, v in farm_prod.items()}
    result["istanze"]           = istanze_stato

    # ── Truppe ────────────────────────────────────────────────────────────────
    tt_path = os.path.join(root, "data", "storico_truppe.json")
    truppe: dict[str, int] = {}
    try:
        with open(tt_path, encoding="utf-8") as f:
            tt = json.load(f)
        for nome, records in tt.items():
            if records:
                truppe[nome] = records[-1].get("total_squads", 0)
    except Exception:
        pass
    result["truppe"] = truppe

    # ── Storico farm ultimi 3 giorni ──────────────────────────────────────────
    sf_path = os.path.join(root, "data", "storico_farm.json")
    storico: dict = {}
    try:
        with open(sf_path, encoding="utf-8") as f:
            sf = json.load(f)
        for data in sorted(sf.keys())[-3:]:
            giorno = sf[data]
            totale_m: dict[str, float] = {}
            for _, val in giorno.items():
                if isinstance(val, dict):
                    for res, qty in val.items():
                        if isinstance(qty, (int, float)):
                            totale_m[res] = totale_m.get(res, 0) + qty / 1e6
            storico[data] = {k: round(v, 1) for k, v in totale_m.items()}
    except Exception:
        pass
    result["storico_3gg"] = storico

    return result


# ==============================================================================
# Stato completo singola istanza
# ==============================================================================

def istanza_stato_completo(root: str, nome: str) -> dict:
    """
    Stato completo di una singola istanza:
      - state/FAU_XX.json: rifornimento, boost, arena, metrics, produzione
      - istanza_metrics.jsonl: ultimo record (boot, tick, raccolta, durate task)
      - engine_status.json: task_corrente, storico task recenti
      - storico_truppe.json: delta truppe
    """
    result: dict = {"nome": nome}

    # ── State file ────────────────────────────────────────────────────────────
    st_path = os.path.join(root, "state", f"{nome}.json")
    try:
        with open(st_path, encoding="utf-8") as f:
            st = json.load(f)

        rif = st.get("rifornimento", {})
        result["rifornimento"] = {
            "spedizioni_oggi": rif.get("spedizioni_oggi", 0),
            "provviste_m":     round(rif.get("provviste_residue", -1) / 1e6, 1)
                               if rif.get("provviste_residue", -1) >= 0 else None,
            "tassa_pct":       round(rif.get("tassa_pct_avg", 0) * 100, 1),
            "inviato_m":       {k: round(v / 1e6, 1) for k, v in rif.get("inviato_oggi", {}).items() if v > 0},
            "ultima_sped":     str(rif.get("ultima_spedizione", ""))[:16],
        }

        bst = st.get("boost", {})
        if bst.get("tipo"):
            from datetime import datetime, timezone
            scad = bst.get("scadenza", "")
            try:
                dt_scad = datetime.fromisoformat(scad.replace("Z", "+00:00"))
                residuo_m = int((dt_scad - datetime.now(timezone.utc)).total_seconds() / 60)
                result["boost"] = f"{bst['tipo']} — residuo {max(0, residuo_m)}m"
            except Exception:
                result["boost"] = bst.get("tipo", "?")

        result["arena"] = {
            "esaurite":       st.get("arena", {}).get("esaurite", False),
            "data_rif":       st.get("arena", {}).get("data_riferimento", ""),
        }

        met = st.get("metrics", {})
        prod_h = {}
        for res in ("pomodoro", "legno", "acciaio", "petrolio"):
            val = met.get(f"{res}_per_ora", 0)
            if val and abs(val) > 1000:
                prod_h[res] = f"{val/1e3:.0f}K/h"
        result["prod_h"] = prod_h

        pc = st.get("produzione_corrente", {})
        result["tick_corrente"] = {
            "ts_inizio":    str(pc.get("ts_inizio", ""))[:16],
            "tasks_count":  len(pc.get("tasks_count", {})),
            "zaino_delta_m": {k: round(v/1e6, 1) for k, v in pc.get("zaino_delta", {}).items() if v},
        }
    except Exception as exc:
        result["state_error"] = str(exc)

    # ── Istanza metrics (ultimo record) ───────────────────────────────────────
    met_path = os.path.join(root, "data", "istanza_metrics.jsonl")
    last_met: dict = {}
    try:
        with open(met_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("instance") == nome:
                        last_met = r
                except Exception:
                    pass
    except Exception:
        pass

    if last_met:
        racc = last_met.get("raccolta", {})
        result["ultimo_tick"] = {
            "ts":            str(last_met.get("ts", ""))[:16],
            "outcome":       last_met.get("outcome", ""),
            "boot_home_s":   last_met.get("boot_home_s", 0),
            "tick_total_s":  last_met.get("tick_total_s", 0),
            "marce":         len(racc.get("invii", [])),
            "slot":          f"{racc.get('attive_pre','?')}→{racc.get('attive_post','?')}/{racc.get('totali','?')}",
            "task_top3_s":   dict(sorted(
                last_met.get("task_durations_s", {}).items(),
                key=lambda x: -x[1])[:3]
            ),
        }

    # ── Engine status — task corrente + storico ───────────────────────────────
    es_path = os.path.join(root, "engine_status.json")
    try:
        with open(es_path, encoding="utf-8") as f:
            es = json.load(f)
        live = es.get("istanze", {}).get(nome, {})
        result["live"] = {
            "stato":        live.get("stato"),
            "task_corrente": live.get("task_corrente"),
        }
        storico_task = [
            s for s in es.get("storico", [])
            if s.get("istanza") == nome
        ][-8:]
        if storico_task:
            result["storico_task"] = [
                f"{s['task']}={s['esito']} {s.get('durata_s',0):.0f}s"
                + (f" ({s['msg'][:40]})" if s.get("msg") else "")
                for s in storico_task
            ]
    except Exception:
        pass

    # ── Truppe ────────────────────────────────────────────────────────────────
    tt_path = os.path.join(root, "data", "storico_truppe.json")
    try:
        with open(tt_path, encoding="utf-8") as f:
            tt = json.load(f)
        records = tt.get(nome, [])
        if records:
            last2 = records[-2:]
            result["truppe"] = last2[-1].get("total_squads", 0)
            if len(last2) == 2:
                result["truppe_delta"] = last2[-1].get("total_squads", 0) - last2[0].get("total_squads", 0)
    except Exception:
        pass

    return result


# ==============================================================================
# Performance task (da engine_status.storico)
# ==============================================================================

def task_performance(root: str) -> dict:
    """
    Performance ultimi task eseguiti da engine_status.storico.
    Raggruppa per task: count, durata media, tasso ok, ultimi messaggi anomali.
    """
    es_path = os.path.join(root, "engine_status.json")
    try:
        with open(es_path, encoding="utf-8") as f:
            es = json.load(f)
    except Exception:
        return {}

    storico = es.get("storico", [])
    from collections import defaultdict
    perf: dict[str, dict] = defaultdict(lambda: {"count": 0, "ok": 0, "fail": 0, "durate": [], "msgs": []})

    for s in storico:
        task = s.get("task", "?")
        esito = s.get("esito", "?")
        dur = s.get("durata_s", 0)
        msg = s.get("msg", "")
        perf[task]["count"] += 1
        if esito == "ok":
            perf[task]["ok"] += 1
        else:
            perf[task]["fail"] += 1
            if msg:
                perf[task]["msgs"].append(f"{s.get('istanza','?')}: {msg[:50]}")
        if dur:
            perf[task]["durate"].append(dur)

    result = {}
    for task, d in sorted(perf.items()):
        durate = d["durate"]
        result[task] = {
            "count":    d["count"],
            "ok_pct":   round(d["ok"] / d["count"] * 100) if d["count"] else 0,
            "dur_avg_s": round(sum(durate) / len(durate), 1) if durate else 0,
            "fails":    d["msgs"][-3:],
        }
    return result
