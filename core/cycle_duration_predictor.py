"""
core/cycle_duration_predictor.py — Stimatore durata ciclo bot e per-istanza.

WU-CycleDur (04/05/2026) — predice quanto durerà il prossimo ciclo bot
basandosi su statistiche rolling (median ultimi N=20 esecuzioni) di:
  - boot_home_s per istanza
  - task_durations_s per (istanza, task)

INDIPENDENTE dal Skip Predictor: utile da solo per dashboard/planning.
Integrato come `gap_atteso` nel modello "squadre fuori" (Step 4 raffinato).

API:
    predict_istanza_duration(istanza, scheduled_tasks) -> dict
    predict_cycle_duration(istanze_attive, tasks_per_istanza, tick_sleep_s) -> dict
    refresh_stats() -> None

Storage stats: cache in-memory ricomputata da `data/istanza_metrics.jsonl`
con TTL 30min (rapida convergenza dopo nuovi cicli).

Self-improving: ogni nuovo tick si aggiunge ai 20 record rolling → media stabile.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Config rolling stats
# ──────────────────────────────────────────────────────────────────────────────

ROLLING_WINDOW   = 20      # ultimi N record per istanza per stat
CACHE_TTL_S      = 1800    # 30 min: refresh stats lazy on demand
MIN_SAMPLES_HI   = 10      # >=10 samples → confidence "alta"
MIN_SAMPLES_MID  = 3       # >=3 samples → "media"; <3 → "bassa"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers path / cache
# ──────────────────────────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _metrics_path() -> Path:
    return _root() / "data" / "istanza_metrics.jsonl"


_cache_lock = threading.Lock()
_cache: dict = {"computed_at": 0.0, "stats": {}}


# ──────────────────────────────────────────────────────────────────────────────
# Calcolo stats da metrics
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskStats:
    median:    float = 0.0
    p90:       float = 0.0
    n_samples: int   = 0


@dataclass
class IstanzaStats:
    boot_home: TaskStats = field(default_factory=TaskStats)
    tasks:     dict      = field(default_factory=dict)   # task_name -> TaskStats


def _percentile(sorted_vals: list, pct: float) -> float:
    """p-th percentile (linear). pct in [0..100]."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _stats_from_values(values: list[float]) -> TaskStats:
    """Calcola median + p90 da lista valori."""
    if not values:
        return TaskStats()
    vals_clean = [v for v in values if v is not None and v > 0]
    if not vals_clean:
        return TaskStats()
    vals_sorted = sorted(vals_clean)
    return TaskStats(
        median    = float(statistics.median(vals_clean)),
        p90       = float(_percentile(vals_sorted, 90)),
        n_samples = len(vals_clean),
    )


def refresh_stats() -> None:
    """Ricalcola stats da `istanza_metrics.jsonl`. Idempotente, thread-safe."""
    path = _metrics_path()
    if not path.exists():
        with _cache_lock:
            _cache["computed_at"] = time.time()
            _cache["stats"] = {}
        return

    # Per ogni istanza: ultimi ROLLING_WINDOW record (sort desc per ts, prendi N)
    by_inst: dict[str, list[dict]] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                inst = r.get("instance")
                if not inst:
                    continue
                by_inst.setdefault(inst, []).append(r)
    except Exception:
        return

    new_stats: dict[str, IstanzaStats] = {}
    for inst, records in by_inst.items():
        # Sort desc per ts, prendi ultimi ROLLING_WINDOW
        records.sort(key=lambda r: r.get("ts", ""), reverse=True)
        recent = records[:ROLLING_WINDOW]

        boot_vals: list[float] = []
        task_vals: dict[str, list[float]] = {}
        for r in recent:
            bh = r.get("boot_home_s")
            if bh is not None and bh > 0:
                boot_vals.append(float(bh))
            durs = r.get("task_durations_s") or {}
            for tname, sec in durs.items():
                if sec is None or sec <= 0:
                    continue
                task_vals.setdefault(tname, []).append(float(sec))

        ist_stats = IstanzaStats(boot_home=_stats_from_values(boot_vals))
        for tname, vals in task_vals.items():
            ist_stats.tasks[tname] = _stats_from_values(vals)
        new_stats[inst] = ist_stats

    with _cache_lock:
        _cache["computed_at"] = time.time()
        _cache["stats"] = new_stats


def _get_stats() -> dict[str, IstanzaStats]:
    """Stats con auto-refresh se cache stale."""
    with _cache_lock:
        age = time.time() - _cache["computed_at"]
    if age > CACHE_TTL_S or not _cache["stats"]:
        refresh_stats()
    with _cache_lock:
        return dict(_cache["stats"])


# ──────────────────────────────────────────────────────────────────────────────
# API: previsione duration
# ──────────────────────────────────────────────────────────────────────────────

def predict_istanza_duration(
    istanza: str,
    scheduled_tasks: list[str],
) -> dict:
    """
    Stima durata tick istanza in secondi.

    Args:
        istanza: nome (es. "FAU_00")
        scheduled_tasks: lista task che verranno schedulati nel ciclo
                         (es. ["boost", "rifornimento", "raccolta"]).
                         Se [], usa "tutti i task con stat" come fallback.

    Returns:
        {
            "istanza": str,
            "T_s": float,                  # secondi totali
            "boot_home_s": float,
            "tasks": {task: T_s},
            "confidence": "alta" | "media" | "bassa",
            "missing_stats": [task list]   # task senza dati storici
        }
    """
    stats = _get_stats().get(istanza)
    if stats is None:
        # Nessun dato per istanza: fallback statici 600s totali
        return {
            "istanza":     istanza,
            "T_s":         600.0,
            "boot_home_s": 90.0,
            "tasks":       {t: 60.0 for t in scheduled_tasks},
            "confidence":  "bassa",
            "missing_stats": list(scheduled_tasks),
        }

    boot_s = stats.boot_home.median if stats.boot_home.n_samples > 0 else 90.0

    if not scheduled_tasks:
        scheduled_tasks = list(stats.tasks.keys())

    tasks_breakdown = {}
    missing = []
    n_with_stats = 0
    for tname in scheduled_tasks:
        ts = stats.tasks.get(tname)
        if ts is None or ts.n_samples == 0:
            tasks_breakdown[tname] = 60.0   # fallback statico
            missing.append(tname)
        else:
            tasks_breakdown[tname] = ts.median
            n_with_stats += 1

    total = boot_s + sum(tasks_breakdown.values())

    # Confidence
    avg_samples = (
        stats.boot_home.n_samples
        + sum(stats.tasks.get(t, TaskStats()).n_samples for t in scheduled_tasks)
    ) / max(1, len(scheduled_tasks) + 1)
    if avg_samples >= MIN_SAMPLES_HI:
        conf = "alta"
    elif avg_samples >= MIN_SAMPLES_MID:
        conf = "media"
    else:
        conf = "bassa"

    return {
        "istanza":       istanza,
        "T_s":           round(total, 1),
        "boot_home_s":   round(boot_s, 1),
        "tasks":         {k: round(v, 1) for k, v in tasks_breakdown.items()},
        "confidence":    conf,
        "missing_stats": missing,
    }


def predict_cycle_duration(
    istanze_attive: list[str],
    tasks_per_istanza: Optional[dict[str, list[str]]] = None,
    tick_sleep_s: float = 300.0,
) -> dict:
    """
    Stima durata ciclo bot completo.

    Args:
        istanze_attive: lista nomi istanze che parteciperanno al ciclo
        tasks_per_istanza: opzionale, dict {istanza: [task,...]}.
                           Se None, ogni istanza usa "tutti i task con stat".
        tick_sleep_s: secondi sleep dopo ciclo.

    Returns:
        {
            "T_ciclo_s": float,
            "T_ciclo_min": float,
            "per_istanza": {istanza: {T_s, tasks, ...}},
            "tick_sleep_s": float,
            "confidence": str,        # min confidence delle istanze
            "n_istanze": int,
        }
    """
    tpi = tasks_per_istanza or {}
    breakdown = {}
    total_s = 0.0
    confidences = []
    for inst in istanze_attive:
        scheduled = tpi.get(inst, [])
        pred = predict_istanza_duration(inst, scheduled)
        breakdown[inst] = pred
        total_s += pred["T_s"]
        confidences.append(pred["confidence"])

    total_with_sleep = total_s + tick_sleep_s

    # Min confidence (peggiore)
    rank = {"alta": 0, "media": 1, "bassa": 2}
    worst = max(confidences, key=lambda c: rank.get(c, 2)) if confidences else "bassa"

    return {
        "T_ciclo_s":    round(total_with_sleep, 1),
        "T_ciclo_min":  round(total_with_sleep / 60, 1),
        "per_istanza":  breakdown,
        "tick_sleep_s": tick_sleep_s,
        "confidence":   worst,
        "n_istanze":    len(istanze_attive),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Schedule-aware: legge state.schedule per dedurre quali task girano nel ciclo
# ──────────────────────────────────────────────────────────────────────────────

# Mapping task_setup.class → task_name (snake_case usato in task_durations_s)
CLASS_TO_TASK_NAME = {
    "BoostTask": "boost", "RifornimentoTask": "rifornimento",
    "RaccoltaTask": "raccolta", "RaccoltaChiusuraTask": "raccolta_chiusura",
    "RaccoltaFastTask": "raccolta_fast",
    "DonazioneTask": "donazione", "AlleanzaTask": "alleanza",
    "MessaggiTask": "messaggi", "VipTask": "vip",
    "ArenaTask": "arena", "ArenaMercatoTask": "arena_mercato",
    "StoreTask": "store", "ZainoTask": "zaino",
    "TruppeTask": "truppe", "DistrictShowdownTask": "district_showdown",
    "RadarTask": "radar", "RadarCensusTask": "radar_census",
    "MainMissionTask": "main_mission",
}


def _load_schedule_state(istanza: str) -> dict:
    """Legge state[istanza].schedule (dict task_name -> ISO last_run_ts)."""
    path = _root() / "state" / f"{istanza}.json"
    if not path.exists():
        return {}
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
        return s.get("schedule", {}) or {}
    except Exception:
        return {}


def _boost_will_skip(istanza: str, tick_sleep_s: float) -> bool:
    """
    True se al prossimo tick BoostTask gira come NOOP rapido (boost ancora attivo).

    Coerente con BoostState.is_attivo (core/state.py): boost attivo se
    `scadenza > now + ANTICIPO (5min)`. Aggiungiamo `tick_sleep_s` perché
    valutiamo il PROSSIMO tick, non quello attuale.

    Returns False (= task girerà) se:
      - state file mancante
      - boost.disponibile=False (nessun boost trovato → riprova sempre)
      - boost.scadenza None (mai attivato)
      - scadenza <= now + tick_sleep + buffer (boost in scadenza al prossimo tick)
    """
    try:
        path = _root() / "state" / f"{istanza}.json"
        if not path.exists():
            return False
        s = json.loads(path.read_text(encoding="utf-8"))
        boost = s.get("boost") or {}
        if not boost.get("disponibile", True):
            return False
        scad_iso = boost.get("scadenza")
        if not scad_iso:
            return False
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        scad = _dt.fromisoformat(scad_iso)
        now  = _dt.now(_tz.utc)
        BOOST_ANTICIPO_S = 300.0   # coerente con _BOOST_ANTICIPO_S in core/state.py
        return scad > now + _td(seconds=tick_sleep_s + BOOST_ANTICIPO_S)
    except Exception:
        return False


def _rifornimento_will_skip(istanza: str) -> bool:
    """
    True se RifornimentoTask gira come NOOP (no-send).

    Condizioni (in OR):
      - Master saturo: morfeus_state.daily_recv_limit == 0
      - Provviste istanza esaurite (guard giornaliero persistente)
      - Quota istanza esaurita: spedizioni_oggi >= quota_max
    """
    try:
        # Master saturo: blocca tutte le istanze ordinarie
        morfeus_path = _root() / "data" / "morfeus_state.json"
        if morfeus_path.exists():
            ms = json.loads(morfeus_path.read_text(encoding="utf-8"))
            drl = ms.get("daily_recv_limit", -1)
            if drl == 0:
                return True
        # Per-istanza: provviste esaurite o quota raggiunta
        path = _root() / "state" / f"{istanza}.json"
        if not path.exists():
            return False
        s = json.loads(path.read_text(encoding="utf-8"))
        rif = s.get("rifornimento") or {}
        if rif.get("provviste_esaurite", False):
            return True
        if int(rif.get("spedizioni_oggi", 0)) >= int(rif.get("quota_max", 5)):
            return True
        return False
    except Exception:
        return False


def _task_will_be_noop(task_name: str,
                       istanza: Optional[str],
                       tick_sleep_s: float) -> bool:
    """
    Guard di stato per task con `interval_hours == 0` (always-due) ma che
    in pratica girano come NOOP frequentemente. Estensibile a zaino,
    donazione, arena, truppe, ecc. nei prossimi step.
    """
    if not istanza:
        return False
    if task_name == "boost":
        return _boost_will_skip(istanza, tick_sleep_s)
    if task_name == "rifornimento":
        return _rifornimento_will_skip(istanza)
    return False


def _is_task_due(task_name: str,
                 task_setup_entry: dict,
                 last_run_iso: Optional[str],
                 now_utc,
                 istanza: Optional[str] = None,
                 tick_sleep_s: float = 300.0) -> bool:
    """
    True se il task girerà al prossimo tick di questa istanza.

    Logica:
      - schedule == "always" / interval_hours == 0 → sempre, MA con guard di
        stato `_task_will_be_noop` per boost/rifornimento (e futuri)
      - last_run None → primo run, gira
      - elapsed >= interval_hours → gira
      - main_mission edge: hour gate UTC ≥ 20 (WU91)

    Args:
        istanza, tick_sleep_s: opzionali. Se forniti, abilitano i guard di
        stato per task con interval=0 (boost active / rifornimento bloccato).
    """
    schedule    = task_setup_entry.get("schedule", "periodic")
    interval_h  = float(task_setup_entry.get("interval_hours", 0) or 0)

    if schedule == "always" or interval_h == 0:
        # Guard di stato: alcuni task always-due saranno NOOP per stato interno
        if _task_will_be_noop(task_name, istanza, tick_sleep_s):
            return False
        return True

    if last_run_iso is None:
        # Mai eseguito → girerà al prossimo tick
        return True

    try:
        from datetime import datetime as _dt
        last_dt  = _dt.fromisoformat(last_run_iso)
        elapsed_h = (now_utc - last_dt).total_seconds() / 3600.0
    except Exception:
        return True   # parse fail: conservativo, conta il task

    if elapsed_h < interval_h:
        return False

    # Edge case main_mission: gate UTC >= 20 (WU91)
    if task_name == "main_mission" and now_utc.hour < 20:
        return False

    return True


# ──────────────────────────────────────────────────────────────────────────────
# Helper opzionale: stima da config + storia + schedule (no input esplicito)
# ──────────────────────────────────────────────────────────────────────────────

def predict_cycle_from_config(strict_schedule: bool = True) -> dict:
    """
    Stima ciclo usando config attuale + schedule per task.

    Args:
        strict_schedule: se True (default), filtra task per ogni istanza in base
            a `state[istanza].schedule[task]` + `interval_hours`. Se False, conta
            tutti i task abilitati per ogni istanza (vecchio comportamento, sovrastima).

    Workflow:
      1. Legge istanze abilitate da `instances.json` + `runtime_overrides.json`
      2. Legge task globali abilitati da `globali.task` flags
      3. Per ogni (istanza × task), valuta `_is_task_due` con last_run da state
      4. Predict per istanza usando solo task dovuti a girare
      5. Somma + tick_sleep = T_ciclo

    Utile per dashboard/CLI senza dover passare input.
    """
    from datetime import datetime as _dt, timezone as _tz
    now_utc = _dt.now(_tz.utc)

    root = _root()
    try:
        with (root / "config" / "instances.json").open(encoding="utf-8") as f:
            insts = json.load(f)
    except Exception:
        return {"error": "instances.json non leggibile"}

    try:
        with (root / "config" / "runtime_overrides.json").open(encoding="utf-8") as f:
            ov = json.load(f)
    except Exception:
        ov = {}

    # Istanze abilitate (override > base)
    abilitate = []
    ist_ov_all = ov.get("istanze", {}) or {}
    for i in insts:
        nome = i.get("nome")
        if not nome:
            continue
        ab = ist_ov_all.get(nome, {}).get("abilitata",
             i.get("abilitata", True))
        if ab:
            abilitate.append(nome)

    # Task abilitati globalmente
    task_flags = (ov.get("globali", {}).get("task") or {})

    try:
        with (root / "config" / "task_setup.json").open(encoding="utf-8") as f:
            task_setup = json.load(f)
    except Exception:
        task_setup = []

    # Build mapping task_name → task_setup_entry per lookup veloce
    task_setup_by_name: dict[str, dict] = {}
    for t in task_setup:
        tn = CLASS_TO_TASK_NAME.get(t.get("class", ""))
        if tn:
            task_setup_by_name[tn] = t

    # Lista task globalmente disponibili (flag abilitato)
    task_globali = [
        tn for tn in task_setup_by_name.keys()
        if task_flags.get(tn, False)
    ]
    # raccolta sempre on (override flag, vedi WU102)
    if "raccolta" not in task_globali and task_flags.get("raccolta", True):
        task_globali.insert(0, "raccolta")

    # tick_sleep va calcolato PRIMA del filtro (serve a _is_task_due per guard boost)
    sis = ov.get("globali", {}).get("sistema", {}) or {}
    tick_sleep_min = sis.get("tick_sleep_min", 5)
    tick_sleep_s = float(tick_sleep_min) * 60

    # Per ogni istanza, filtra task dovuti a girare al prossimo tick
    tpi: dict[str, list[str]] = {}
    schedule_debug: dict[str, dict] = {}
    for inst in abilitate:
        # Tipologia istanza per filtro raccolta_only / raccolta_fast
        ist_o = ist_ov_all.get(inst, {})
        tipologia = ist_o.get("tipologia") or next(
            (i.get("profilo") for i in insts if i.get("nome") == inst), "full"
        )

        if str(tipologia) == "raccolta_only":
            # Solo raccolta + raccolta_chiusura per istanze master/raccolta_only
            tasks_consid = [t for t in ("raccolta", "raccolta_chiusura")
                            if t in task_globali]
        elif str(tipologia) == "raccolta_fast":
            # RaccoltaTask sostituita da RaccoltaFastTask runtime
            tasks_consid = []
            for t in task_globali:
                if t == "raccolta":
                    tasks_consid.append("raccolta_fast")
                else:
                    tasks_consid.append(t)
        else:  # full
            tasks_consid = list(task_globali)

        if not strict_schedule:
            tpi[inst] = tasks_consid
            continue

        # Strict: filtra per schedule
        sch_state = _load_schedule_state(inst)
        due_tasks: list[str] = []
        skipped:   list[str] = []
        for tn in tasks_consid:
            entry = task_setup_by_name.get(tn)
            if entry is None:
                # Task senza entry in task_setup (raccolta_fast non c'è) → conserva
                due_tasks.append(tn)
                continue
            last_run = sch_state.get(tn)
            if _is_task_due(tn, entry, last_run, now_utc,
                            istanza=inst, tick_sleep_s=tick_sleep_s):
                due_tasks.append(tn)
            else:
                skipped.append(tn)
        tpi[inst] = due_tasks
        schedule_debug[inst] = {"due": due_tasks, "skipped": skipped}

    res = predict_cycle_duration(abilitate, tpi, tick_sleep_s=tick_sleep_s)
    res["schedule_debug"] = schedule_debug
    res["strict_schedule"] = strict_schedule
    return res
