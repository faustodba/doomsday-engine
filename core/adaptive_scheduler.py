"""core/adaptive_scheduler.py — scheduler adattivo ordine istanze nel ciclo.

08/05/2026 — sostituisce il pattern "skip statico" del predictor.
Razionale: invece di skippare un'istanza con slot pieni (perdita lavoro),
riordina l'ordine di avvio nel ciclo per privilegiare quelle con più slot
liberi attesi al momento del loro turno. Le istanze con score basso
slittano in coda — l'attesa naturale durante il giro fa rientrare squadre
e libera slot.

LOGICA:
  1. Pre-ciclo: check `should_activate_scheduler()` (4 precondizioni in OR).
     Se NESSUNA vera → ordine fisso come oggi.
  2. Se attivo: greedy adattivo:
     a. Per ogni istanza calcola `slot_liberi_atteso(t_avvio_previsto)`
     b. Sceglie quella col score più alto come prossima
     c. Aggiorna t_avvio_previsto cumulando T_predicted dell'istanza scelta
     d. Ripete finché tutte assegnate
  3. Master FauMorfeus sempre fissa in fondo (fuori ranking).
  4. **Mai skip definitivo**: tutte le istanze processate.
  5. Persistence: salva ordine pianificato in `data/scheduler_planned_order.json`.
     Su restart bot, se file esiste e fresh → resume da sequenza memorizzata.

API:
    from core.adaptive_scheduler import (
        should_activate_scheduler, ordina_istanze_adaptive,
        save_planned_order, load_planned_order, clear_planned_order,
    )

    active, reasons = should_activate_scheduler()
    if active:
        ordine = ordina_istanze_adaptive(istanze_ciclo)
        save_planned_order(ordine)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# ─── Path helpers ──────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


_PLANNED_ORDER_PATH = lambda: _root() / "data" / "scheduler_planned_order.json"

# Soglie precondizioni — DEFAULT, sovrascrivibili da
# `globali.adaptive_scheduler_thresholds.{drl_residuo_m, pct_istanze_sat, spedizioni_oggi}`.
# 08/05: `drl_residuo_m` (M residui assoluti) sostituisce `drl_residuo_pct`
# (% relative al max). Il bot legge il residuo OCR direttamente in unità,
# soglia parametrica più diretta. Default 50 M.
DEFAULT_SOGLIE = {
    "drl_residuo_m":    50,
    "pct_istanze_sat":  50,
    "spedizioni_oggi":  100,
}

# Persistence freshness — se file > N min, ignoralo (assumiamo restart vecchio)
PLANNED_ORDER_TTL_MIN = 240   # 4 ore


def _get_soglie() -> dict:
    """Legge soglie precondizioni da config; fallback a DEFAULT_SOGLIE.

    08/05: backward compat per chiave legacy `drl_residuo_pct` se presente
    nei file (interpretata come % di 600M → convertita a M assoluti).
    """
    try:
        from config.config_loader import load_global
        gc = load_global()
        cfg = getattr(gc, "adaptive_scheduler_thresholds", None) or {}
        out = dict(DEFAULT_SOGLIE)
        for k in DEFAULT_SOGLIE:
            if k in cfg:
                try:
                    out[k] = int(cfg[k])
                except (TypeError, ValueError):
                    pass
        # Migrazione legacy: drl_residuo_pct (%) → drl_residuo_m (M)
        if "drl_residuo_m" not in cfg and "drl_residuo_pct" in cfg:
            try:
                pct = int(cfg["drl_residuo_pct"])
                out["drl_residuo_m"] = max(0, int(pct * 6))  # 30% × 6 = 180M
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return dict(DEFAULT_SOGLIE)


# ─── Precondizioni attivazione ─────────────────────────────────────────────

def _master_drl_residuo_m() -> float:
    """Residuo Daily Receiving Limit master in **milioni** (M).

    Returns:
        Valore in M (= residuo / 1_000_000), oppure -1 se mai letto.
        0 = master saturo. Esempio: residuo 280_000_000 → 280.0
    """
    try:
        ms_path = _root() / "data" / "morfeus_state.json"
        if not ms_path.exists():
            return -1.0
        ms = json.loads(ms_path.read_text(encoding="utf-8"))
        residuo = ms.get("daily_recv_limit", -1)
        if residuo is None or int(residuo) < 0:
            return -1.0
        return float(int(residuo)) / 1_000_000.0
    except Exception as exc:
        _log.warning("[ADAPT-SCHED] DRL residuo (M) error: %s", exc)
        return -1.0


def _master_drl_residuo_pct() -> float:
    """% residuo del Daily Receiving Limit master.

    `daily_recv_limit` letto da OCR = RESIDUO assoluto corrente (decresce
    nella giornata, reset 00:00 UTC). 0 = master saturo.

    `daily_recv_limit_max` = massimo monotone osservato nel giorno UTC
    corrente (= stima del limite totale giornaliero). 08/05 patch.

    Pre-08/05 questa funzione interpretava erroneamente `daily_recv_limit`
    come limite totale e sottraeva inviato_oggi da `storico_farm.json`,
    causando "N/A" (-1) quando il master era saturo (limit=0).

    Returns: 0..100, oppure -1 se mai letto.
    """
    try:
        ms_path = _root() / "data" / "morfeus_state.json"
        if not ms_path.exists():
            return -1.0
        ms = json.loads(ms_path.read_text(encoding="utf-8"))
        residuo = ms.get("daily_recv_limit", -1)
        if residuo is None or int(residuo) < 0:
            return -1.0   # mai letto (no OCR ancora)
        residuo = float(residuo)
        # 0 esplicito → saturo
        if residuo == 0:
            return 0.0
        # Stima limite giornaliero: max monotone osservato (preferito) >
        # config statica > default 600M (~stima VIP medio).
        max_lim = 0
        ms_max = ms.get("daily_recv_limit_max")
        if ms_max and int(ms_max) > 0:
            max_lim = int(ms_max)
        if max_lim <= 0:
            try:
                gc_path = _root() / "config" / "global_config.json"
                if gc_path.exists():
                    gc = json.loads(gc_path.read_text(encoding="utf-8"))
                    cfg_max = (gc.get("rifornimento_comune") or {}).get(
                        "daily_recv_limit_max", 0)
                    if cfg_max and int(cfg_max) > 0:
                        max_lim = int(cfg_max)
            except Exception:
                pass
        if max_lim <= 0:
            max_lim = 600_000_000   # fallback prudente
        # Clamp 0..100 (max_lim può essere stato sottostimato se l'OCR ha
        # registrato solo il residuo basso del giorno)
        max_lim = max(max_lim, int(residuo))
        return min(100.0, (residuo / max_lim) * 100.0)
    except Exception as exc:
        _log.warning("[ADAPT-SCHED] DRL residuo error: %s", exc)
        return -1.0


def _rifornimento_abilitato() -> bool:
    """Rifornimento abilitato globalmente (task flag)?

    True = abilitato. False = OFF da dashboard (= precondizione scheduler vera).
    """
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        if ov_path.exists():
            ov = json.loads(ov_path.read_text(encoding="utf-8"))
            tf = (ov.get("globali") or {}).get("task") or {}
            if "rifornimento" in tf:
                return bool(tf["rifornimento"])
        # Fallback global_config
        gc_path = _root() / "config" / "global_config.json"
        if gc_path.exists():
            gc = json.loads(gc_path.read_text(encoding="utf-8"))
            tf = gc.get("task") or {}
            return bool(tf.get("rifornimento", True))
    except Exception:
        pass
    return True


def _percentuale_istanze_sature() -> float:
    """% istanze ordinarie con `provviste_esaurite=True` nel state."""
    try:
        from shared.instance_meta import is_master_instance
        state_dir = _root() / "state"
        if not state_dir.exists():
            return 0.0
        oggi_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        n_total = 0
        n_sat = 0
        for f in state_dir.glob("*.json"):
            ist = f.stem
            if is_master_instance(ist):
                continue
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            n_total += 1
            rif = s.get("rifornimento") or {}
            esaurite = bool(rif.get("provviste_esaurite", False))
            data_rif = rif.get("data_riferimento", "")
            # Considera saturo solo se flag fresh (oggi UTC), altrimenti
            # è stantio dal giorno precedente
            if esaurite and data_rif == oggi_utc:
                n_sat += 1
        return (n_sat / n_total * 100.0) if n_total else 0.0
    except Exception:
        return 0.0


def _spedizioni_oggi_totali() -> int:
    """Numero spedizioni cumulative di TUTTE le istanze ordinarie oggi UTC."""
    try:
        from shared.instance_meta import is_master_instance
        farm_path = _root() / "data" / "storico_farm.json"
        if not farm_path.exists():
            return 0
        farm = json.loads(farm_path.read_text(encoding="utf-8"))
        oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day = farm.get(oggi) or {}
        n = 0
        for ist, vals in day.items():
            if is_master_instance(ist):
                continue
            if isinstance(vals, dict):
                n += int(vals.get("spedizioni") or 0)
        return n
    except Exception:
        return 0


def _flags_status() -> tuple[bool, bool]:
    """Legge `adaptive_scheduler_enabled` + `_shadow_only` da config.

    Returns: (enabled, shadow_only). Default (False, True) — sicuro.
    """
    try:
        from config.config_loader import load_global
        gc = load_global()
        return (bool(getattr(gc, "adaptive_scheduler_enabled", False)),
                bool(getattr(gc, "adaptive_scheduler_shadow_only", True)))
    except Exception:
        return (False, True)


def should_activate_scheduler() -> tuple[bool, list[str]]:
    """Master gate + 4 precondizioni in OR. Ritorna (active, reasons).

    `active=True` SOLO se:
      - flag `adaptive_scheduler_enabled=True` da config (master toggle)
      - AND ≥1 delle 4 precondizioni è vera

    Reasons elenca quali condizioni sono vere (per log + telemetria).
    Se shadow_only=True, l'attivazione è solo per LOG (caller deve verificare).
    """
    enabled, _shadow = _flags_status()
    if not enabled:
        return (False, ["flag_disabled"])

    soglie = _get_soglie()
    reasons: list[str] = []
    drl_m = _master_drl_residuo_m()
    # Precondizione: residuo master BASSO (= master quasi saturo) → riordino
    # ha senso perché le istanze sature crescono e gli slot vanno ottimizzati.
    # Soglia="≤ N M": scheduler attivo quando residuo <= N. Default 50 M.
    if drl_m >= 0 and drl_m <= soglie["drl_residuo_m"]:
        reasons.append(f"master_residuo={drl_m:.0f}M<={soglie['drl_residuo_m']}M")
    if not _rifornimento_abilitato():
        reasons.append("rifornimento_OFF")
    pct_sat = _percentuale_istanze_sature()
    if pct_sat >= soglie["pct_istanze_sat"]:
        reasons.append(f"istanze_sature={pct_sat:.0f}%>={soglie['pct_istanze_sat']}%")
    sped = _spedizioni_oggi_totali()
    if sped > soglie["spedizioni_oggi"]:
        reasons.append(f"sped_oggi={sped}>{soglie['spedizioni_oggi']}")
    return (len(reasons) > 0, reasons)


def get_status() -> dict:
    """Status completo per dashboard: flag + soglie + valori live + reasons."""
    enabled, shadow = _flags_status()
    soglie = _get_soglie()
    drl_m = _master_drl_residuo_m()
    rif_on = _rifornimento_abilitato()
    pct_sat = _percentuale_istanze_sature()
    sped = _spedizioni_oggi_totali()
    active, reasons = should_activate_scheduler()
    return {
        "enabled":      enabled,
        "shadow_only":  shadow,
        "active":       active,
        "reasons":      reasons,
        "thresholds":   soglie,
        "live": {
            "drl_residuo_m":    round(drl_m, 1) if drl_m >= 0 else None,
            "rifornimento_on":  rif_on,
            "pct_istanze_sat":  round(pct_sat, 1),
            "spedizioni_oggi":  sped,
        },
    }


def is_shadow_mode() -> bool:
    """True se shadow_only attivo (calcola ordine ma NON applica al ciclo)."""
    _enabled, shadow = _flags_status()
    return shadow


# ─── Calcolo slot liberi attesi ────────────────────────────────────────────

def compute_slot_liberi_atteso(istanza: str,
                                 t_offset_min: float = 0.0) -> dict:
    """Stima slot liberi attesi al momento `now + t_offset_min`.

    Usa modello T_marcia da `core.skip_predictor._calc_t_marcia_min` per ogni
    invio nell'ultimo record con invii reali. Una squadra rientra in tempo
    se `T_marcia_residuo[i] <= t_offset_min`.

    Returns dict:
        {
          "ist": str,
          "totali": int,
          "attive_now": int,            # slot occupati ora
          "rientro_atteso": int,         # squadre che rientrano entro offset
          "slot_liberi_atteso": int,     # totali - (attive_now - rientro)
          "slot_liberi_now": int,        # totali - attive_now
          "score": float,                # = slot_liberi_atteso (per ordinamento)
          "elapsed_min": float,
          "t_residue_min": list[float],
          "anzianita_tick_min": float,   # tempo dall'ultimo tick (tie-breaker)
          "data_completa": bool,         # False se metrics incompleti
        }
    """
    try:
        from core.skip_predictor import _calc_t_marcia_min, load_metrics_history
    except Exception as exc:
        _log.warning("[ADAPT-SCHED] import error: %s", exc)
        return _empty_score(istanza)

    history = load_metrics_history(istanza, last_n=10)
    if not history:
        return _empty_score(istanza)

    last = history[-1]
    rac = last.get("raccolta") or {}
    totali = rac.get("totali")
    attive_now = rac.get("attive_post")

    if totali is None or attive_now is None:
        # Dati incompleti — score conservativo medio
        out = _empty_score(istanza)
        out["data_completa"] = False
        return out

    # Anzianità tick (tie-breaker: priorità a quelle in ritardo)
    try:
        ts_last = datetime.fromisoformat(last.get("ts", ""))
        anz_min = (datetime.now(timezone.utc) - ts_last).total_seconds() / 60
    except Exception:
        anz_min = 0.0

    # Cerca ultimo record con invii reali (per modello T_marcia)
    invii_record = None
    for r in reversed(history):
        if (r.get("raccolta") or {}).get("invii"):
            invii_record = r
            break

    # Slot già liberi ora
    slot_liberi_now = max(0, int(totali) - int(attive_now))

    if invii_record is None:
        # No invii nella storia → non possiamo stimare rientri.
        # Conservativo: assume slot_liberi_atteso = slot_liberi_now.
        # Tentativo di blend empirico usando gap = anzianita_tick + t_offset.
        out = {
            "ist": istanza,
            "totali": int(totali),
            "attive_now": int(attive_now),
            "rientro_atteso": 0,
            "slot_liberi_atteso": slot_liberi_now,
            "slot_liberi_now": slot_liberi_now,
            "score": float(slot_liberi_now),
            "elapsed_min": 0.0,
            "t_residue_min": [],
            "anzianita_tick_min": round(anz_min, 1),
            "data_completa": False,
        }
        return _blend_with_empirical(out, istanza, anz_min + t_offset_min)

    # Calcola T_marcia per ogni invio
    invii = invii_record["raccolta"]["invii"]
    t_marce = []
    for inv in invii:
        t = _calc_t_marcia_min(inv, istanza)
        if t is not None:
            t_marce.append(t)

    if not t_marce:
        # Dati pre-WU116 (load=-1) → conservativo + blend empirico se disponibile.
        out = {
            "ist": istanza,
            "totali": int(totali),
            "attive_now": int(attive_now),
            "rientro_atteso": 0,
            "slot_liberi_atteso": slot_liberi_now,
            "slot_liberi_now": slot_liberi_now,
            "score": float(slot_liberi_now),
            "elapsed_min": 0.0,
            "t_residue_min": [],
            "anzianita_tick_min": round(anz_min, 1),
            "data_completa": False,
        }
        return _blend_with_empirical(out, istanza, anz_min + t_offset_min)

    # Elapsed dal record con invii
    try:
        ts_inv = datetime.fromisoformat(invii_record["ts"])
        elapsed = max(0.0, (datetime.now(timezone.utc) - ts_inv).total_seconds() / 60)
    except Exception:
        elapsed = 0.0

    # T_residue dei singoli invii (da ADESSO)
    t_residue_min = [max(0.0, t - elapsed) for t in t_marce]

    # Squadre che rientreranno entro `t_offset_min`
    rientri = sum(1 for t in t_residue_min if t <= t_offset_min)
    # Cap: non possiamo avere più rientri delle squadre attive
    rientri = min(rientri, int(attive_now))

    slot_liberi_atteso = max(0, int(totali) - int(attive_now) + rientri)

    out = {
        "ist": istanza,
        "totali": int(totali),
        "attive_now": int(attive_now),
        "rientro_atteso": rientri,
        "slot_liberi_atteso": slot_liberi_atteso,
        "slot_liberi_now": slot_liberi_now,
        "score": float(slot_liberi_atteso),
        "elapsed_min": round(elapsed, 1),
        "t_residue_min": [round(t, 1) for t in sorted(t_residue_min)],
        "anzianita_tick_min": round(anz_min, 1),
        "data_completa": True,
    }
    # Blend con lookup empirico (proposta A 08/05).
    # gap_min = elapsed dal record con invii + t_offset_greedy
    return _blend_with_empirical(out, istanza, elapsed + t_offset_min)


def _empty_score(istanza: str) -> dict:
    """Score di fallback per istanze senza dati."""
    return {
        "ist": istanza,
        "totali": 0,
        "attive_now": 0,
        "rientro_atteso": 0,
        "slot_liberi_atteso": 2,   # stima neutra
        "slot_liberi_now": 2,
        "score": 2.0,
        "elapsed_min": 0.0,
        "t_residue_min": [],
        "anzianita_tick_min": 0.0,
        "data_completa": False,
    }


# ─── Blend deterministico + empirico (proposta A 08/05) ─────────────────────

def _blend_alpha(n_samples: int) -> float:
    """Peso deterministico in funzione del numero di sample empirici disponibili.

    Più sample empirici → meno peso al deterministico → più peso a empirico.
        n>=30  → α=0.3 (peso forte empirico)
        15-29  → α=0.5 (50/50)
        5-14   → α=0.7 (peso forte deterministico)
        <5     → α=1.0 (solo deterministico, no fiducia empirica)
    """
    if n_samples >= 30: return 0.3
    if n_samples >= 15: return 0.5
    if n_samples >= 5:  return 0.7
    return 1.0


def _blend_with_empirical(out: dict, istanza: str, gap_min: float) -> dict:
    """Aggiorna `out` con blend deterministico + empirico per slot_liberi_atteso.

    Args:
        out: dict score uscita di `compute_slot_liberi_atteso` (deterministico).
        istanza: nome istanza.
        gap_min: minuti dall'ultimo passaggio (= elapsed + t_offset_greedy).

    Effetto:
        - Se sample empirici disponibili per (istanza, bucket gap):
          out["slot_liberi_atteso"] = round(α·det + (1-α)·median_empirical)
          out["score"] = stesso valore
          out["empirical"] = {n_samples, median, alpha, det_value, blended_value}
        - Se nessun sample → out invariato + out["empirical"] = None
    """
    try:
        from core.empirical_slot_predictor import lookup_slot_liberi
        emp = lookup_slot_liberi(istanza, gap_min)
    except Exception as exc:
        _log.debug("[ADAPT-SCHED] empirical lookup error: %s", exc)
        emp = None

    if emp is None or emp.get("n_samples", 0) == 0:
        out["empirical"] = None
        return out

    n = int(emp["n_samples"])
    alpha = _blend_alpha(n)
    det_val = float(out.get("slot_liberi_atteso", 0))
    emp_val = float(emp.get("median", 0.0))

    if alpha >= 1.0:
        # Solo deterministico, niente blend (ma esponi info)
        out["empirical"] = {
            "n_samples":   n,
            "median":      emp_val,
            "alpha":       1.0,
            "det_value":   det_val,
            "blended":     det_val,
            "bucket":      emp.get("bucket_label", ""),
        }
        return out

    blended = round(alpha * det_val + (1.0 - alpha) * emp_val)
    out["slot_liberi_atteso"] = int(blended)
    out["score"] = float(blended)
    out["empirical"] = {
        "n_samples":   n,
        "median":      emp_val,
        "alpha":       round(alpha, 2),
        "det_value":   det_val,
        "blended":     float(blended),
        "bucket":      emp.get("bucket_label", ""),
    }
    return out


# ─── Ordinamento adattivo greedy ───────────────────────────────────────────

_cycle_pred_cache: dict = {"ts": 0.0, "data": None}
_CYCLE_PRED_TTL_S = 60   # ammortizza chiamate multiple in un greedy


def _stima_durata_istanza_min(istanza: str) -> float:
    """T_predicted per istanza schedule-aware. Default 8min se non noto.

    08/05: refactor da `predict_istanza_duration(scheduled_tasks=[])` (sovrastima:
    sommava la mediana di TUTTI i task storici, anche quelli NON dovuti nel
    prossimo tick) a `predict_cycle_from_config(strict_schedule=True)` che
    filtra i task per `state[ist].schedule[task]` + `interval_hours` + edge
    cases (es. main_mission UTC≥20). Stima molto più aderente alla realtà.

    Cache TTL 60s: il greedy chiama `_stima_durata_istanza_min` 1×/istanza
    (~12 volte) entro pochi secondi → senza cache ricalcoleremmo la stessa
    pipeline (state + config) ad ogni iterazione.
    """
    import time as _t
    global _cycle_pred_cache

    try:
        # Cache hit per chiamate consecutive nello stesso greedy
        now_ts = _t.time()
        cached = _cycle_pred_cache.get("data")
        if cached is None or (now_ts - _cycle_pred_cache.get("ts", 0)) > _CYCLE_PRED_TTL_S:
            from core.cycle_duration_predictor import predict_cycle_from_config
            res = predict_cycle_from_config(strict_schedule=True) or {}
            _cycle_pred_cache = {"ts": now_ts, "data": res}
            cached = res

        per_ist = (cached.get("per_istanza") or {})
        pred = per_ist.get(istanza)
        if pred and pred.get("T_s") is not None:
            t_min = float(pred["T_s"]) / 60.0
        else:
            # Fallback (istanza assente in predict_cycle_from_config — raro):
            # `predict_istanza_duration([])` = media tutti i task storici.
            from core.cycle_duration_predictor import predict_istanza_duration
            pred2 = predict_istanza_duration(istanza, scheduled_tasks=[])
            t_min = float(pred2.get("T_s", 480.0)) / 60.0

        # Proposta D 08/05 — calibrazione closed-loop:
        # applica factor moltiplicativo basato su bias storico actual/predicted.
        # Default 1.0 (no calibrazione) se insufficienti samples o bias < trigger.
        try:
            from core.cycle_predictor_calibration import get_calibration_factor
            factor = get_calibration_factor()
            t_min *= factor
        except Exception:
            pass

        return t_min
    except Exception:
        return 8.0


def _invalidate_cycle_pred_cache() -> None:
    """Forza ricalcolo al prossimo `_stima_durata_istanza_min`. Utile per test."""
    global _cycle_pred_cache
    _cycle_pred_cache = {"ts": 0.0, "data": None}


def ordina_istanze_adaptive(istanze: list[str],
                              master_excluded: bool = True,
                              log_fn=None) -> list[dict]:
    """Greedy adattivo: ordina istanze per `slot_liberi_atteso` decrescente.

    Args:
        istanze: lista nomi istanze ordinarie (master tipicamente escluso).
        master_excluded: se True, master FauMorfeus (se presente) viene
                         appeso a fine lista senza partecipare al ranking.
        log_fn: callable opzionale `log_fn(msg: str)`. Se passato, emette un
                trace step-by-step del greedy con candidati + score + scelto.

    Returns:
        list[dict] in ordine ottimale, ciascuno con campi di
        `compute_slot_liberi_atteso` + `t_avvio_min` (offset previsto).
        Master sempre ultimo (con t_avvio_min calcolato).

    Logica greedy:
        - t_avvio_min[0] = 0
        - score[ist] = compute_slot_liberi_atteso(ist, t_avvio_min[i])
        - sceglie max score (tie-break: anzianità_tick desc)
        - t_avvio_min[i+1] = t_avvio_min[i] + T_predicted_istanza_scelta
        - ripete con istanze rimanenti
    """
    def _trace(msg: str) -> None:
        if log_fn is not None:
            try: log_fn(f"[ADAPT-TRACE] {msg}")
            except Exception: pass
    try:
        from shared.instance_meta import is_master_instance
    except Exception:
        is_master_instance = lambda x: False   # fallback

    # Separa ordinarie da master
    ordinarie = [i for i in istanze if not is_master_instance(i)]
    master = [i for i in istanze if is_master_instance(i)]

    if not master_excluded:
        ordinarie = ordinarie + master
        master = []

    risultato: list[dict] = []
    rimanenti = list(ordinarie)
    t_offset = 0.0
    step = 0

    _trace(f"start greedy · ordinarie={len(ordinarie)} master={len(master)}")

    while rimanenti:
        step += 1
        # Calcola score per tutte le rimanenti al momento `t_offset`
        scores = [compute_slot_liberi_atteso(ist, t_offset_min=t_offset)
                  for ist in rimanenti]

        # Ordina: score desc, poi anzianita_tick desc (più in ritardo prima)
        scores.sort(key=lambda x: (x["score"], x["anzianita_tick_min"]),
                    reverse=True)

        # Trace candidati (compatto, max 4 per step per non saturare log)
        if log_fn is not None:
            def _emp_str(s: dict) -> str:
                """Format compatto info empirical (se presente)."""
                e = s.get("empirical")
                if not e:
                    return ""
                return f",emp={e['blended']:.0f}/n{e['n_samples']}α{e['alpha']:.1f}"
            cand_str = " | ".join(
                f"{s['ist']}:sla={s['slot_liberi_atteso']}/{s['totali']}"
                f"(now={s['slot_liberi_now']},rientri={s['rientro_atteso']},"
                f"elap={s['elapsed_min']:.0f}m{_emp_str(s)})"
                for s in scores[:4]
            )
            extra = f" +{len(scores) - 4}" if len(scores) > 4 else ""
            _trace(f"step{step} t={t_offset:5.1f}m | {cand_str}{extra}")

        scelto = scores[0]
        scelto["t_avvio_min"] = round(t_offset, 1)
        risultato.append(scelto)
        rimanenti.remove(scelto["ist"])

        # Avanza offset di durata stimata istanza scelta + tick_sleep ratio
        durata_scelto = _stima_durata_istanza_min(scelto["ist"])
        _trace(f"  → scelto: {scelto['ist']} (sla={scelto['slot_liberi_atteso']}, "
               f"anzianità={scelto['anzianita_tick_min']:.0f}m) · "
               f"avanza t_offset +{durata_scelto:.1f}m → {t_offset + durata_scelto:.1f}m")
        t_offset += durata_scelto

    # Master in fondo (con t_avvio_min finale)
    for m in master:
        risultato.append({
            "ist": m,
            "score": -1,   # marker: fuori ranking
            "t_avvio_min": round(t_offset, 1),
            "data_completa": False,
            "is_master": True,
        })
        _trace(f"  master: {m} t_avvio={t_offset:.1f}m (sempre fondo)")
        t_offset += _stima_durata_istanza_min(m)

    if log_fn is not None:
        _trace(f"end · T_ciclo_atteso={t_offset:.1f}m · ordine={[r['ist'] for r in risultato]}")

    return risultato


# ─── Persistence ordine pianificato ───────────────────────────────────────

def save_planned_order(ordine: list[dict],
                        ts_inizio_ciclo: Optional[datetime] = None,
                        reasons: Optional[list[str]] = None) -> bool:
    """Persiste ordine pianificato in `data/scheduler_planned_order.json`.

    Args:
        ordine: lista dict da `ordina_istanze_adaptive` (con scores+offsets).
        ts_inizio_ciclo: timestamp inizio ciclo (default: now).
        reasons: precondizioni che hanno attivato (per audit).

    Returns: True se OK.
    """
    if ts_inizio_ciclo is None:
        ts_inizio_ciclo = datetime.now(timezone.utc)
    payload = {
        "ts_inizio_ciclo": ts_inizio_ciclo.isoformat(),
        "ts_saved":        datetime.now(timezone.utc).isoformat(),
        "reasons":         reasons or [],
        "ordine":          ordine,
        "completate":      [],   # lista istanze già processate (per resume)
    }
    p = _PLANNED_ORDER_PATH()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.error("[ADAPT-SCHED] save planned order fail: %s", exc)
        return False


def load_planned_order() -> Optional[dict]:
    """Carica ordine pianificato se fresh (< TTL_MIN).

    Returns: dict con `ordine` + `completate` + `reasons`, oppure None se:
        - file non esiste
        - ordine stantio (ts_saved > TTL_MIN fa)
        - parse error
    """
    p = _PLANNED_ORDER_PATH()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts_saved = datetime.fromisoformat(data.get("ts_saved", ""))
        age_min = (datetime.now(timezone.utc) - ts_saved).total_seconds() / 60
        if age_min > PLANNED_ORDER_TTL_MIN:
            _log.info("[ADAPT-SCHED] planned order stale (%.0f min) — ignored",
                      age_min)
            return None
        return data
    except Exception as exc:
        _log.warning("[ADAPT-SCHED] load planned order error: %s", exc)
        return None


def mark_completed(istanza: str) -> bool:
    """Aggiorna lista completate nel file pianificato (per resume).

    Idempotente: se istanza già in lista, no-op.
    """
    p = _PLANNED_ORDER_PATH()
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        completate = data.get("completate", []) or []
        if istanza not in completate:
            completate.append(istanza)
        data["completate"] = completate
        data["ts_last_update"] = datetime.now(timezone.utc).isoformat()
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.warning("[ADAPT-SCHED] mark_completed error: %s", exc)
        return False


def clear_planned_order() -> bool:
    """Rimuove file ordine pianificato (chiamare a fine ciclo OK)."""
    p = _PLANNED_ORDER_PATH()
    if not p.exists():
        return True
    try:
        p.unlink()
        return True
    except Exception:
        return False


def compute_ab_test_metrics(istanze: list[str]) -> dict:
    """Confronto A/B virtuale ordine adaptive vs ordine naive (proposta E 08/05).

    Calcola per entrambi gli ordini:
        Σ slot_liberi_atteso = score totale "produttività predetta del ciclo"

    Naive = alfabetico ordinarie + master in fondo (= ordine pre-adaptive).

    Returns:
        {
          "adaptive":  {"ordine": [...], "tot_slot": float, "scores": [...]},
          "naive":     {"ordine": [...], "tot_slot": float, "scores": [...]},
          "delta_slot": float,    # adaptive - naive
          "n_istanze":  int,
        }

    Notes:
        Confronto **virtuale**: entrambi gli ordini sono valutati con
        compute_slot_liberi_atteso(t_offset cumulativo). Non è un test
        controfattuale reale (bot esegue UN ordine), ma una stima di
        quanto valore aggiunge il riordino vs sequenza naive.
    """
    try:
        from shared.instance_meta import is_master_instance
    except Exception:
        is_master_instance = lambda x: False

    # Adaptive: greedy
    ord_adapt = ordina_istanze_adaptive(istanze)
    tot_adapt = sum(r.get("score", 0) for r in ord_adapt if not r.get("is_master"))
    scores_adapt = [(r["ist"], round(float(r.get("score", 0)), 1),
                     round(r.get("t_avvio_min", 0), 1))
                    for r in ord_adapt]

    # Naive: alfabetico ordinarie + master fondo
    ordinarie = sorted([i for i in istanze if not is_master_instance(i)])
    master    = sorted([i for i in istanze if is_master_instance(i)])
    naive_seq = ordinarie + master

    # Calcola score con t_offset cumulativo
    risultato_naive: list[dict] = []
    t_offset = 0.0
    for ist in naive_seq:
        s = compute_slot_liberi_atteso(ist, t_offset_min=t_offset)
        s["t_avvio_min"] = round(t_offset, 1)
        s["is_master"] = is_master_instance(ist)
        risultato_naive.append(s)
        t_offset += _stima_durata_istanza_min(ist)

    tot_naive = sum(r.get("score", 0) for r in risultato_naive
                    if not r.get("is_master"))
    scores_naive = [(r["ist"], round(float(r.get("score", 0)), 1),
                     round(r.get("t_avvio_min", 0), 1))
                    for r in risultato_naive]

    return {
        "adaptive": {
            "ordine":    [r["ist"] for r in ord_adapt],
            "tot_slot":  round(tot_adapt, 1),
            "scores":    scores_adapt,
        },
        "naive": {
            "ordine":    naive_seq,
            "tot_slot":  round(tot_naive, 1),
            "scores":    scores_naive,
        },
        "delta_slot":  round(tot_adapt - tot_naive, 1),
        "n_istanze":   len(istanze),
    }


def record_ab_test(metrics: dict, reasons: Optional[list[str]] = None) -> bool:
    """Persiste record A/B test in `data/predictions/scheduler_ab.jsonl`.

    Append-only. Ogni greedy aggiunge una riga.
    """
    p = _root() / "data" / "predictions" / "scheduler_ab.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts":           datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reasons":      reasons or [],
        "n_istanze":    metrics.get("n_istanze", 0),
        "tot_adaptive": metrics.get("adaptive", {}).get("tot_slot", 0),
        "tot_naive":    metrics.get("naive", {}).get("tot_slot", 0),
        "delta_slot":   metrics.get("delta_slot", 0),
        "ordine_adaptive": metrics.get("adaptive", {}).get("ordine", []),
        "ordine_naive":    metrics.get("naive", {}).get("ordine", []),
    }
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        _log.warning("[ADAPT-AB] write fail: %s", exc)
        return False


def get_remaining_from_resume() -> Optional[list[str]]:
    """Se planned order esiste fresh, ritorna nomi istanze NON ancora completate.

    Usato per resume post-restart: invece di ricalcolare ordine da zero, riprende
    dalla lista già pianificata nel ciclo precedente, dalla prossima istanza.

    Returns: lista nomi (in ordine pianificato) oppure None se nessun resume.
    """
    data = load_planned_order()
    if data is None:
        return None
    completate = set(data.get("completate", []) or [])
    rimanenti = [
        item.get("ist")
        for item in (data.get("ordine") or [])
        if item.get("ist") and item.get("ist") not in completate
    ]
    return rimanenti or None


# ─── CLI ad-hoc per debug ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    p = argparse.ArgumentParser(description="Test adaptive scheduler.")
    p.add_argument("--istanze", default=None,
                   help="CSV nomi istanze (default: legge da instances.json)")
    p.add_argument("--check", action="store_true",
                   help="Solo check precondizioni + score per istanza, no save")
    args = p.parse_args()

    active, reasons = should_activate_scheduler()
    print(f"=== Precondizioni: {'ATTIVO' if active else 'OFF'} ===")
    print(f"  master_drl_residuo_m   = {_master_drl_residuo_m():.1f}M")
    print(f"  rifornimento_abilitato = {_rifornimento_abilitato()}")
    print(f"  istanze_sature_pct     = {_percentuale_istanze_sature():.1f}%")
    print(f"  spedizioni_oggi        = {_spedizioni_oggi_totali()}")
    print(f"  reasons attive         = {reasons}")
    print()

    if args.istanze:
        istanze = [s.strip() for s in args.istanze.split(",") if s.strip()]
    else:
        try:
            inst_path = _root() / "config" / "instances.json"
            insts = json.loads(inst_path.read_text(encoding="utf-8"))
            istanze = [i.get("nome") for i in insts if i.get("abilitata", True)]
        except Exception as exc:
            print(f"errore lettura instances: {exc}")
            raise SystemExit(1)

    print(f"=== Ordine adattivo ({len(istanze)} istanze) ===")
    ordine = ordina_istanze_adaptive(istanze)
    print(f"{'#':3} {'istanza':14} {'t_avvio':9} {'slot_liberi':12} "
          f"{'now':5} {'rientri':8} {'anz_min':8} {'data':5}")
    print("-" * 70)
    for i, item in enumerate(ordine):
        if item.get("is_master"):
            print(f"{i:3} {item['ist']:14} (master, fissa fondo)")
            continue
        print(
            f"{i:3} {item['ist']:14} "
            f"{item['t_avvio_min']:6.1f}min  "
            f"{item['slot_liberi_atteso']}/{item['totali']:8}  "
            f"{item['slot_liberi_now']:5}  "
            f"{item['rientro_atteso']:8}  "
            f"{item['anzianita_tick_min']:6.0f}m  "
            f"{'OK' if item['data_completa'] else 'INC':5}"
        )
