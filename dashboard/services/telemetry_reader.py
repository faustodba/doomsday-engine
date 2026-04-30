# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/telemetry_reader.py
#
#  Aggrega dati telemetria da fonti già esistenti (no nuova instrumentation):
#    - logs/FAU_*.jsonl     → KPI task (esec, ok%, durate) + health pattern
#    - engine_status.json   → ciclo corrente + storico ultimi tick
#    - data/storico_farm.json → trend 7gg
#
#  API:
#    get_task_kpi_24h() -> List[TaskKpi]
#    get_health_24h()   -> List[HealthIssue]
#    get_ciclo_status() -> CicloStatus
#    get_trend_7gg()    -> List[TrendSeries]
#
#  Cache: 30s TTL — il log scan 24h è costoso (~12 file × MB).
# ==============================================================================

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ==============================================================================
# Path
# ==============================================================================

_ROOT       = Path(__file__).parent.parent.parent
_PROD_ROOT  = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_LOGS_DIR   = _PROD_ROOT / "logs"
_BOT_LOG    = _PROD_ROOT / "bot.log"
_STATUS     = _PROD_ROOT / "engine_status.json"
_STORICO    = _PROD_ROOT / "data" / "storico_farm.json"


# ==============================================================================
# Modelli
# ==============================================================================

@dataclass
class TaskKpi:
    nome:       str
    esec_24h:   int
    ok_pct:     int                  # 0-100
    avg_dur_s:  float
    last_ts:    str                  # "HH:MM"
    last_err:   str                  # "—" se nessun errore recente


@dataclass
class HealthIssue:
    kind:    str          # "ok" | "warn" | "err"
    label:   str
    value:   str
    note:    str


@dataclass
class IstanzaCiclo:
    nome:    str
    esito:   str          # "ok" | "abort" | "live" | "wait"
    durata:  str          # "12.4m" o "—"
    tasks:   str
    badge:   str          # "ADB" | "DEF" | "▸" | ""


@dataclass
class CicloStatus:
    numero:           int
    in_corso_da_s:    int
    media_durata_s:   int
    eta_fine_s:       int
    completate:       int
    totale:           int
    prossima:         str
    istanze:          List[IstanzaCiclo] = field(default_factory=list)


@dataclass
class TaskDurationStats:
    """
    WU49 — Statistiche durata task con filtro outlier IQR (Tukey fences).

    Consistenza basata su CV (coefficient of variation = std/mean):
      - high: cv < 0.3   (deviazione standard < 30% della media)
      - med:  cv 0.3-0.7
      - low:  cv > 0.7   (alta varianza → tempi inconsistenti)
      - n/a:  count < 5  (campione troppo piccolo per statistica)
    """
    task:           str
    count:          int          # esecuzioni considerate (post-filtro)
    count_total:    int          # esecuzioni totali (pre-filtro)
    excluded:       int          # outlier rimossi
    min_s:          float
    median_s:       float
    mean_s:         float
    p95_s:          float
    max_s:          float
    std_s:          float
    cv:             float        # coefficient of variation = std/mean
    consistenza:    str          # "high" | "med" | "low" | "n/a"


@dataclass
class CicloStorico:
    """Singolo ciclo completato con durata e istanze processate."""
    numero:        int          # globale crescente (WU48)
    start_hhmm:    str          # "14:46"
    end_hhmm:      str          # "18:06" o "—" se in corso
    durata_s:      int          # durata totale in secondi
    n_istanze:     int          # numero istanze processate
    completato:    bool
    aborted:       bool = False # WU48 — ciclo interrotto (restart bot mid-ciclo)
    run_local:     int  = 0     # numero locale del bot (debug)
    start_date:    str  = ""    # "29/04" — data di inizio ciclo (UTC)


@dataclass
class TrendSeries:
    label:     str
    sparkline: str        # "▂▃▄▆▇█▇▆"
    current:   str
    delta:     str


# ==============================================================================
# Cache TTL
# ==============================================================================

_CACHE_TTL_S = 30
_cache: Dict[str, Tuple[float, object]] = {}

def _cached(key: str, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL_S:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


# ==============================================================================
# Helpers parsing log JSONL
# ==============================================================================

_RE_DUR = re.compile(r"durata_s=([\d.]+)|in (\d+(?:\.\d+)?)s")
_TASK_NAMES = (
    "boost", "rifornimento", "raccolta", "donazione",
    "districtshowdown", "arena", "zaino", "vip", "alleanza",
    "raccolta_chiusura", "store",
)


def _iter_logs(since_iso: str):
    """
    Yield (ts_iso, instance, msg) per ogni evento JSONL con ts >= since_iso.
    Filtra a una scansione singola — chi chiama applica i filtri.
    """
    if not _LOGS_DIR.exists():
        return
    for fp in sorted(_LOGS_DIR.glob("*.jsonl")):
        if fp.name.endswith(".bak.jsonl"):
            continue
        try:
            with open(fp, "rb") as f:
                # ottimizzazione: leggi a blocchi dalla fine se file grande
                for raw in f:
                    line = raw.decode("utf-8", errors="replace")
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = d.get("ts", "")
                    if ts < since_iso:
                        continue
                    yield ts, d.get("instance", ""), d.get("msg", "")
        except Exception:
            continue


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_minus_h(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _hhmm_from_iso(ts: str) -> str:
    if not ts:
        return ""
    return ts[11:16]


# ==============================================================================
# 1. KPI per task (24h)
# ==============================================================================

def get_task_kpi_24h() -> List[TaskKpi]:
    return _cached("task_kpi_24h", _compute_task_kpi_24h_dual)


def _compute_task_kpi_24h_dual() -> List[TaskKpi]:
    """
    WU42 — fonte primaria: data/telemetry/live.json (precomputato dal
    LiveTelemetry thread, schema TaskTelemetry). Fallback al log scan
    legacy (WU37) se telemetry non è ancora attiva o live.json vuoto.
    """
    try:
        from core.telemetry import load_live
        live = load_live()
    except Exception:
        live = None

    if live and live.get("per_task"):
        return _kpi_from_live(live)
    # Fallback log scan
    return _compute_task_kpi_24h()


def _kpi_from_live(live: dict) -> List[TaskKpi]:
    out: List[TaskKpi] = []
    for task_name, t in live.get("per_task", {}).items():
        last_ts = t.get("last_ts", "") or ""
        # converti "2026-04-27T13:25:14.123+00:00" → "13:25"
        last_short = last_ts[11:16] if len(last_ts) >= 16 else ""
        out.append(TaskKpi(
            nome      = task_name,
            esec_24h  = int(t.get("exec", 0)),
            ok_pct    = round(float(t.get("ok_pct", 0))),
            avg_dur_s = float(t.get("duration_avg_s", 0.0)),
            last_ts   = last_short,
            last_err  = t.get("last_err", "—") or "—",
        ))
    out.sort(key=lambda t: t.esec_24h, reverse=True)
    return out


def _compute_task_kpi_24h() -> List[TaskKpi]:
    """
    Scansiona logs/FAU_*.jsonl ultime 24h cercando coppie:
      "Orchestrator: avvio task 'X'"     → ts_start
      "Orchestrator: task 'X' completato -- success=True/False msg='...'"  → ts_end + esito + msg

    Per ogni task aggrega: count, ok%, avg_durata, last_ts, last_err.
    """
    since = _iso_minus_h(24)

    # Per istanza: stack di start in attesa di end
    pending: Dict[Tuple[str, str], str] = {}   # (instance, task) -> ts_start
    stats: Dict[str, dict] = {
        t: {"esec": 0, "ok": 0, "dur": [], "last_ts": "", "last_err": "—"}
        for t in _TASK_NAMES
    }

    re_start = re.compile(r"Orchestrator: avvio task '([^']+)'")
    re_done  = re.compile(
        r"Orchestrator: task '([^']+)' (?:completato|fallito) -- success=(True|False)(?: msg='([^']*)')?"
    )

    for ts, ist, msg in _iter_logs(since):
        m = re_start.match(msg)
        if m:
            pending[(ist, m.group(1))] = ts
            continue
        m = re_done.match(msg)
        if m:
            task = m.group(1)
            ok   = m.group(2) == "True"
            err  = m.group(3) or ""
            ts_start = pending.pop((ist, task), None)
            if task not in stats:
                stats[task] = {"esec": 0, "ok": 0, "dur": [], "last_ts": "", "last_err": "—"}
            stats[task]["esec"] += 1
            if ok:
                stats[task]["ok"] += 1
            else:
                # accumula ultimo err non-ok (cumulativo per ultimo)
                stats[task]["last_err"] = (err or "fallito")[:40]
            if ts_start:
                try:
                    dur = (
                        datetime.fromisoformat(ts).timestamp()
                        - datetime.fromisoformat(ts_start).timestamp()
                    )
                    if 0 < dur < 1800:  # safety: max 30 min
                        stats[task]["dur"].append(dur)
                except Exception:
                    pass
            stats[task]["last_ts"] = _hhmm_from_iso(ts)

    out: List[TaskKpi] = []
    for nome, s in stats.items():
        if s["esec"] == 0:
            continue
        avg = sum(s["dur"]) / len(s["dur"]) if s["dur"] else 0.0
        out.append(TaskKpi(
            nome      = nome,
            esec_24h  = s["esec"],
            ok_pct    = round(100 * s["ok"] / s["esec"]),
            avg_dur_s = avg,
            last_ts   = s["last_ts"],
            last_err  = s["last_err"],
        ))
    out.sort(key=lambda t: t.esec_24h, reverse=True)
    return out


# ==============================================================================
# 2. Health 24h — pattern matching su logs
# ==============================================================================

# Pattern (label, regex, kind, source)
# source: "jsonl" (logs/FAU_*.jsonl) | "botlog" (bot.log) | "any"
_HEALTH_PATTERNS = [
    ("Stab HOME timeout",       r"stabilizzazione timeout — procedo comunque", "warn", "botlog"),
    ("HOME instabile reset",    r"HOME instabile \(Screen\.UNKNOWN\)",         "warn", "botlog"),
    ("ADB cascade abort",       r"ADB UNHEALTHY|cosmetico — failure",          "warn", "any"),
    ("ARENA recovery cascade",  r"ARENA-PIN screenshot fallito",               "warn", "any"),
    ("Banner unmatched (tap X)", r"_unmatched_tap_x.*: [1-9]",                 "warn", "botlog"),
    ("Boot foreground recov",   r"NON in foreground|monkey preventivo",        "warn", "botlog"),
    ("Spedizione invio (VAI)",  r"Rifornimento: tap VAI",                      "ok",   "jsonl"),
    ("Tick completato",         r"task '[^']+' completato -- success=True",    "ok",   "jsonl"),
]


def get_health_24h() -> List[HealthIssue]:
    return _cached("health_24h", _compute_health_24h_dual)


def _compute_health_24h_dual() -> List[HealthIssue]:
    """
    WU42+44 — sorgenti multiple:
      - data/telemetry/live.json: anomalies_global, totals, patterns_detected (Step 8)
      - bot.log: pattern launcher (HOME timeout, banner unmatched, foreground)
    Fallback completo al log scan legacy se telemetry non disponibile.
    """
    try:
        from core.telemetry import load_live
        live = load_live()
    except Exception:
        live = None

    out: List[HealthIssue] = []

    # 0. Pattern detector (Step 8) — pattern multi-evento ad alta priorità
    if live and live.get("patterns_detected"):
        patterns = live["patterns_detected"]

        # ADB cascade
        for cas in patterns.get("adb_cascade", [])[:3]:
            sev = "err" if cas.get("severity") == "high" else "warn"
            out.append(HealthIssue(
                kind=sev, label=f"⛓ ADB cascade {cas['instance']}",
                value=f"{cas['count']} eventi",
                note=f"finestra {cas['ts_start'][11:16]}–{cas['ts_end'][11:16]}",
            ))

        # Rifornimento skip chain
        for chain in patterns.get("rifornimento_skip_chain", [])[:3]:
            out.append(HealthIssue(
                kind="warn",
                label=f"⛓ rifornimento skip chain {chain['instance']}",
                value=f"{chain['count']} skip consecutivi",
                note=f"finestra {chain['ts_start'][11:16]}–{chain['ts_end'][11:16]}",
            ))

        # Task timeout recurring
        for rec in patterns.get("task_timeout_recurring", [])[:3]:
            out.append(HealthIssue(
                kind="warn",
                label=f"⏱ {rec['task']} timeout ricorrente",
                value=f"{rec['count']} outlier",
                note=f"max {rec['max_observed_s']:.0f}s vs mediana {rec.get('median_s', 0):.0f}s",
            ))

        # Home stab loop
        for loop in patterns.get("home_stab_loop", [])[:3]:
            out.append(HealthIssue(
                kind="warn",
                label=f"🔁 home stab loop {loop['instance']}",
                value=f"{loop['count']} timeout",
                note=f"finestra {loop['ts_start'][11:16]}–{loop['ts_end'][11:16]}",
            ))

    # 1. Anomalie da telemetry (se disponibile)
    if live and live.get("anomalies_global"):
        anom = live["anomalies_global"]
        # Mappa tag canonici → label leggibile
        tag_labels = {
            "adb_unhealthy":     "ADB cascade abort",
            "adb_cascade":       "ADB cascade",
            "home_stab_timeout": "Stab HOME timeout",
            "ocr_fail":          "OCR fail",
            "template_not_found": "Template non trovato",
            "banner_unmatched":  "Banner unmatched (telemetry)",
            "foreground_recovery": "Boot foreground recov (telemetry)",
            "retry":             "Retry task",
        }
        for tag, count in sorted(anom.items(), key=lambda x: -x[1]):
            label = tag_labels.get(tag, tag)
            out.append(HealthIssue(
                kind="warn", label=label,
                value=f"{count} occorrenze",
                note=f"telemetry · tag={tag}",
            ))
        # OK pill: spedizioni totali
        totals = live.get("totals", {})
        ok_count = totals.get("ok", 0) + totals.get("skip", 0)
        fail_count = totals.get("fail", 0) + totals.get("abort", 0)
        if ok_count + fail_count > 0:
            pct = round(100 * ok_count / (ok_count + fail_count))
            out.append(HealthIssue(
                kind="ok" if pct >= 90 else "warn",
                label="Tick success rate",
                value=f"{ok_count}/{ok_count + fail_count} ({pct}%)",
                note="ok+skip vs fail+abort",
            ))

    # 2. Pattern bot.log non catturati da telemetry
    botlog_patterns = [
        ("Stab HOME timeout (launcher)",     r"stabilizzazione timeout — procedo comunque"),
        ("HOME instabile reset (launcher)",  r"HOME instabile \(Screen\.UNKNOWN\)"),
        ("Banner unmatched (launcher)",      r"_unmatched_tap_x.*: [1-9]"),
        ("Boot foreground recov (launcher)", r"NON in foreground|monkey preventivo"),
    ]
    counters: Dict[str, Dict[str, int]] = {p[0]: {} for p in botlog_patterns}
    compiled = [(lbl, re.compile(pat)) for lbl, pat in botlog_patterns]

    since = _iso_minus_h(24)
    for ts, ist, msg in _iter_botlog(since):
        for lbl, rgx in compiled:
            if rgx.search(msg):
                counters[lbl][ist] = counters[lbl].get(ist, 0) + 1
                break

    for lbl, _pat in botlog_patterns:
        ist_counters = counters[lbl]
        total = sum(ist_counters.values())
        if total == 0:
            continue
        top = sorted(ist_counters.items(), key=lambda x: -x[1])[:3]
        out.append(HealthIssue(
            kind="warn", label=lbl,
            value=f"{total} occorrenze",
            note=", ".join(f"{ist} ×{c}" for ist, c in top),
        ))

    # 3. Fallback completo se nessuna sorgente ha dati
    if not out:
        return _compute_health_24h()

    return out


def _iter_botlog(since_iso: str):
    """Yield (ts_iso, instance, msg) per ogni riga di bot.log con ts approx >= since_iso.
    bot.log format: '[HH:MM:SS] FAU_NN [MODULE] [...] msg'
    Nota: bot.log ha solo HH:MM:SS — assumiamo "oggi" e filtriamo by hour cutoff.
    """
    if not _BOT_LOG.exists():
        return
    # Cutoff sull'ora (24h indietro)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cutoff_local = datetime.now() - timedelta(hours=24)
    today_str = datetime.now().date().isoformat()
    re_line = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s+(\S+)\s+(.+)$")
    try:
        with open(_BOT_LOG, "rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").rstrip()
                m = re_line.match(line)
                if not m:
                    continue
                hh, mm, ss, ist, msg = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
                # ricostruisci ts pseudo-ISO usando data odierna (approssimazione)
                ts = f"{today_str}T{hh}:{mm}:{ss}"
                yield ts, ist, msg
    except Exception:
        return


def _compute_health_24h() -> List[HealthIssue]:
    since = _iso_minus_h(24)
    counters: Dict[str, Dict[str, int]] = {p[0]: {} for p in _HEALTH_PATTERNS}
    compiled = [(lbl, re.compile(pat), kind, src) for lbl, pat, kind, src in _HEALTH_PATTERNS]

    # Scan jsonl
    for ts, ist, msg in _iter_logs(since):
        for lbl, rgx, _k, src in compiled:
            if src in ("jsonl", "any") and rgx.search(msg):
                counters[lbl][ist] = counters[lbl].get(ist, 0) + 1
                break

    # Scan bot.log
    for ts, ist, msg in _iter_botlog(since):
        for lbl, rgx, _k, src in compiled:
            if src in ("botlog", "any") and rgx.search(msg):
                counters[lbl][ist] = counters[lbl].get(ist, 0) + 1
                break

    out: List[HealthIssue] = []
    for lbl, _pat, kind, _src in _HEALTH_PATTERNS:
        ist_counters = counters[lbl]
        total = sum(ist_counters.values())
        if total == 0 and kind == "warn":
            continue
        top = sorted(ist_counters.items(), key=lambda x: -x[1])[:3]
        if kind == "warn":
            note = ", ".join(f"{ist} ×{c}" for ist, c in top)
            value = f"{total} occorrenze"
        else:
            value = f"{total}" if total > 0 else "0"
            note = ""
        out.append(HealthIssue(kind=kind, label=lbl, value=value, note=note))
    return out


# ==============================================================================
# 3. Ciclo corrente
# ==============================================================================

def _load_cicli_persistent() -> List[dict]:
    """
    Legge cicli da data/telemetry/cicli.json (file persistente scritto dal bot).
    Auto-backfill da bot.log al primo accesso se file non esiste o vuoto.

    Returns:
        Lista cicli ordinati cronologicamente. Vuoto se nessuna fonte.
    """
    try:
        from core.telemetry import load_cicli, backfill_cicli_from_botlog
        cicli = load_cicli()
        if not cicli:
            # Auto-backfill one-shot: leggiamo bot.log per popolare il file
            bak = _BOT_LOG.parent / "bot.log.bak"
            paths = [p for p in (bak, _BOT_LOG) if p.exists()]
            if paths:
                backfill_cicli_from_botlog(paths)
                cicli = load_cicli()
        return cicli or []
    except Exception:
        return []


def get_ciclo_status() -> CicloStatus:
    return _cached("ciclo_status", _compute_ciclo_status)


def _ts_to_local_hhmm(ts: str) -> str:
    """WU72 (30/04) — converte timestamp ISO UTC in HH:MM ora locale."""
    if not ts:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts).astimezone().strftime("%H:%M")
    except Exception:
        # Fallback al raw UTC se parse fallisce
        return ts[11:16] if len(ts) >= 16 else "—"


def _ts_to_local_date(ts: str) -> str:
    """WU72 (30/04) — converte timestamp ISO UTC in DD/MM ora locale.
    Necessario a cavallo di mezzanotte UTC (es. 22:58 UTC del 29/04
    = 00:58 locale del 30/04 → mostra '30/04' non '29/04')."""
    if not ts:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts).astimezone().strftime("%d/%m")
    except Exception:
        return f"{ts[8:10]}/{ts[5:7]}" if len(ts) >= 10 else "—"


def get_storico_cicli(n: int = 20) -> List[CicloStorico]:
    """
    Ritorna ultimi N cicli completati o in corso (più recenti prima).
    Source: data/telemetry/cicli.json (file persistente).

    WU72 (30/04 notte): start_hhmm/end_hhmm/start_date convertiti in ora
    locale del server (era UTC raw, causando disallineamento di 2h con
    le card istanza che mostrano locale, e date sbagliate a cavallo di
    mezzanotte UTC).
    """
    cycles = _load_cicli_persistent()
    out: List[CicloStorico] = []
    for c in cycles[-n:]:
        ts_start = c.get("start_ts") or ""
        ts_end   = c.get("end_ts")   or ""
        out.append(CicloStorico(
            numero      = c["numero"],
            start_hhmm  = _ts_to_local_hhmm(ts_start),
            end_hhmm    = _ts_to_local_hhmm(ts_end),
            start_date  = _ts_to_local_date(ts_start),
            durata_s    = int(c.get("durata_s", 0)),
            n_istanze   = len(c.get("istanze", {})),
            completato  = bool(c.get("completato", False)),
            aborted     = bool(c.get("aborted",    False)),
            run_local   = int(c.get("run_local",   0)),
        ))
    return list(reversed(out))


def _compute_ciclo_status() -> CicloStatus:
    # Source: data/telemetry/cicli.json (persistente, scritto dal bot)
    cycles = _load_cicli_persistent()
    current = cycles[-1] if cycles else None
    completati = [c for c in cycles if c.get("completato")]

    # engine_status per stato live istanze
    try:
        with open(_STATUS, encoding="utf-8") as f:
            es = json.load(f)
    except Exception:
        es = {}
    istanze_dict = es.get("istanze", {})

    # Numero ciclo + durata in corso
    if current:
        numero = int(current["numero"])
        try:
            in_corso_da_s = max(0, int(
                (datetime.now() - datetime.fromisoformat(current["start_ts"])).total_seconds()
            ))
        except Exception:
            in_corso_da_s = 0
    else:
        numero = 0
        in_corso_da_s = 0

    # Media durata: ultimi 5 cicli completati (esclude quello corrente se ancora aperto)
    if completati:
        ultimi = completati[-5:]
        media_dur = int(sum(c["durata_s"] for c in ultimi) / len(ultimi))
    else:
        media_dur = 150 * 60  # fallback 150 min

    # Costruzione tabella istanze del ciclo corrente
    prossima = "—"
    completate = 0
    rows: List[IstanzaCiclo] = []
    cur_istanze = (current or {}).get("istanze", {}) if current else {}
    totale = len(istanze_dict) or len(cur_istanze)

    for nome in sorted(istanze_dict.keys() | cur_istanze.keys()):
        ist = istanze_dict.get(nome, {})
        stato = ist.get("stato", "?")
        ut = ist.get("ultimo_task") or {}
        nome_t = ut.get("nome", "?")
        esito_t = ut.get("esito", "?")
        msg = (ut.get("msg") or "")[:30]

        # Durata: priorità a parser bot.log (più affidabile dell'ultimo task)
        info = cur_istanze.get(nome)
        if info and info.get("end_ts"):
            dur_s = int(info["durata_s"])
            durata = f"{dur_s/60:.1f}m"
        elif info and not info.get("end_ts") and stato == "running":
            try:
                dur_s = max(0, int(
                    (datetime.now() - datetime.fromisoformat(info["start_ts"])).total_seconds()
                ))
                durata = f"{dur_s/60:.1f}m"
            except Exception:
                durata = "in corso"
        else:
            durata = "—"

        if stato == "running":
            riga_esito = "live"
            tasks = f"task={nome_t}"
            badge = "▸"
            prossima = nome
        elif info and info.get("end_ts"):
            # istanza già completata in questo ciclo
            if "ADB" in msg.upper() or "abort" in msg.lower():
                riga_esito = "abort"
                tasks = "ADB cascade abort"
                badge = "ADB"
            else:
                riga_esito = "ok"
                completate += 1
                tasks = msg or nome_t or "—"
                badge = ""
        else:
            riga_esito = "wait"
            tasks = "in coda"
            badge = ""

        rows.append(IstanzaCiclo(
            nome=nome, esito=riga_esito, durata=durata,
            tasks=tasks, badge=badge,
        ))

    # ETA fine: residue × media-istanza basata su completate effettive
    media_istanza_s = (media_dur // max(totale, 1)) if totale else 0
    eta_s = max(0, (totale - completate) * media_istanza_s)

    return CicloStatus(
        numero=numero,
        in_corso_da_s=in_corso_da_s,
        media_durata_s=media_dur,
        eta_fine_s=eta_s,
        completate=completate,
        totale=totale,
        prossima=prossima,
        istanze=rows,
    )


# ==============================================================================
# 4. Trend 7gg da storico_farm.json
# ==============================================================================

_SPARK = "▁▂▃▄▅▆▇█"


def _sparkline(values: List[float]) -> str:
    if not values:
        return ""
    mn, mx = min(values), max(values)
    if mx == mn:
        return _SPARK[3] * len(values)
    span = mx - mn
    return "".join(_SPARK[min(7, int((v - mn) / span * 7))] for v in values)


# ==============================================================================
# WU49 — Report tempi medi task (consistenti, escluso district_showdown)
# ==============================================================================

# Task da escludere dal report (eventi sporadici, troppo variabili, o speciali)
_TASK_EXCLUSI_DURATIONS = {
    "districtshowdown",
    "district_showdown",
    "radar_census",  # spesso fallisce per templates mancanti
}

# Sample size minimo per considerare una statistica significativa
_MIN_SAMPLE_DURATIONS = 5


def get_task_durations_report(days: int = 7) -> List[TaskDurationStats]:
    """
    WU49 — Report tempi medi task con filtro outlier IQR.

    Legge eventi telemetria ultimi `days` giorni, raggruppa per task,
    filtra outlier statistici (Tukey fences IQR×1.5), calcola statistiche.

    Esclude `districtshowdown` (durate inconsistenti per natura evento).
    Solo task con count_total >= 5 per ridurre rumore (sample size).

    Returns:
        Lista TaskDurationStats ordinata per count desc.
    """
    return _cached(f"task_durations_{days}", lambda: _compute_task_durations(days))


def _compute_task_durations(days: int) -> List[TaskDurationStats]:
    try:
        from core.telemetry import iter_events_range, _percentile
    except Exception:
        return []

    # Aggrega durations per task
    by_task: Dict[str, List[float]] = {}
    for ev in iter_events_range(days):
        task = (ev.task or "").lower()
        if task in _TASK_EXCLUSI_DURATIONS:
            continue
        if ev.outcome not in ("ok", "skip"):
            continue
        d = float(ev.duration_s or 0.0)
        if d <= 0.5:  # filtra task quasi-istantanei (skip/disabled)
            continue
        if d > 1800:  # filtra hung (>30 min)
            continue
        by_task.setdefault(ev.task, []).append(d)

    out: List[TaskDurationStats] = []
    for task, durs in by_task.items():
        count_total = len(durs)
        if count_total < _MIN_SAMPLE_DURATIONS:
            continue

        # Filtro outlier IQR (Tukey fences ×1.5)
        sd = sorted(durs)
        n  = len(sd)
        q1 = sd[n // 4]
        q3 = sd[3 * n // 4]
        iqr = q3 - q1
        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr
        clean = [v for v in durs if lo <= v <= hi]
        excluded = count_total - len(clean)

        if not clean:
            clean = durs  # fallback se filtro IQR ha tolto tutto

        # Statistiche
        n2 = len(clean)
        mean = sum(clean) / n2
        var = sum((v - mean) ** 2 for v in clean) / n2 if n2 > 0 else 0.0
        std = var ** 0.5
        cv  = (std / mean) if mean > 0 else 0.0

        # Consistenza basata su CV (coefficient of variation)
        if n2 < _MIN_SAMPLE_DURATIONS:
            consistenza = "n/a"
        elif cv < 0.3:
            consistenza = "high"
        elif cv < 0.7:
            consistenza = "med"
        else:
            consistenza = "low"

        out.append(TaskDurationStats(
            task         = task,
            count        = n2,
            count_total  = count_total,
            excluded     = excluded,
            min_s        = min(clean),
            median_s     = _percentile(clean, 50),
            mean_s       = mean,
            p95_s        = _percentile(clean, 95),
            max_s        = max(clean),
            std_s        = std,
            cv           = cv,
            consistenza  = consistenza,
        ))

    out.sort(key=lambda t: -t.count)
    return out


def get_trend_7gg() -> List[TrendSeries]:
    return _cached("trend_7gg", _compute_trend_7gg)


def _compute_trend_7gg() -> List[TrendSeries]:
    try:
        with open(_STORICO, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []

    # ultimi 7 giorni (sorted ascending)
    days = sorted(d.keys())[-7:]
    if not days:
        return []

    spediz_per_day = []
    inviato_per_day = []
    provviste_per_day = []
    for day in days:
        ist_data = d[day]
        sped = sum(int(v.get("spedizioni", 0) or 0) for v in ist_data.values())
        inv = sum(
            int(v.get("pomodoro", 0) or 0) + int(v.get("legno", 0) or 0)
            + int(v.get("acciaio", 0) or 0) + int(v.get("petrolio", 0) or 0)
            for v in ist_data.values()
        )
        prov = sum(int(v.get("provviste_residue", 0) or 0) for v in ist_data.values())
        spediz_per_day.append(sped)
        inviato_per_day.append(inv)
        provviste_per_day.append(prov)

    def _delta(vals: List[float]) -> str:
        if len(vals) < 2:
            return "—"
        prev = sum(vals[:-1]) / max(1, len(vals) - 1)
        cur = vals[-1]
        if prev == 0:
            return "—"
        pct = (cur - prev) / prev * 100
        if abs(pct) < 5:
            return "stable"
        sign = "↑" if pct > 0 else "↓"
        return f"{sign}{abs(pct):.0f}% vs avg"

    def _fmt_m(v):
        if v >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v/1_000:.0f}K"
        return f"{v:.0f}"

    return [
        TrendSeries("Spedizioni/gg", _sparkline(spediz_per_day),
                    str(spediz_per_day[-1]), _delta(spediz_per_day)),
        TrendSeries("Inviato/gg",    _sparkline(inviato_per_day),
                    _fmt_m(inviato_per_day[-1]), _delta(inviato_per_day)),
        TrendSeries("Provviste eod", _sparkline(provviste_per_day),
                    _fmt_m(provviste_per_day[-1]), _delta(provviste_per_day)),
    ]
