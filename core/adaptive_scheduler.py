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
  3. Master FauMorfeus (WU216): partecipa al ranking greedy come le ordinarie
     (ordine 1 = scheduler). L'ordine fisso base (`_carica_istanze_ciclo`) resta
     invariato → master ultimo solo quando lo scheduler NON si attiva.
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

    Priorità: DYNAMIC (`runtime_overrides.json::globali`) > STATIC
    (`global_config.json`). Coerente con architecture_config_static_dynamic.md:
    DYNAMIC modificato da HOME prevale sullo STATIC a runtime.
    Default (False, True) — sicuro.

    Bug fix 11/05 (WU148): pre-fix usava `load_global()` che legge SOLO static
    → flag disabilitato in dashboard veniva ignorato dal bot. Ora pattern
    uguale a `_rifornimento_abilitato` (sopra in questo stesso modulo).
    """
    enabled = None
    shadow  = None
    try:
        # 1) DYNAMIC (runtime_overrides) — prevale se presente
        ov_path = _root() / "config" / "runtime_overrides.json"
        if ov_path.exists():
            ov = json.loads(ov_path.read_text(encoding="utf-8"))
            globali = (ov.get("globali") or {})
            if "adaptive_scheduler_enabled" in globali:
                enabled = bool(globali["adaptive_scheduler_enabled"])
            if "adaptive_scheduler_shadow_only" in globali:
                shadow = bool(globali["adaptive_scheduler_shadow_only"])
        # 2) STATIC fallback per i campi non override-ati
        if enabled is None or shadow is None:
            gc_path = _root() / "config" / "global_config.json"
            if gc_path.exists():
                gc = json.loads(gc_path.read_text(encoding="utf-8"))
                if enabled is None:
                    enabled = bool(gc.get("adaptive_scheduler_enabled", False))
                if shadow is None:
                    shadow = bool(gc.get("adaptive_scheduler_shadow_only", True))
    except Exception:
        pass
    # 3) Default safe
    if enabled is None:
        enabled = False
    if shadow is None:
        shadow = True
    return (enabled, shadow)


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
    # WU200 Fase B — flag stima empirica tempo di raccolta (lettura fresca,
    # DYNAMIC>STATIC) per il toggle nella card predictor.
    try:
        from core.skip_predictor import _read_tempo_raccolta_empirico_flag
        tempo_raccolta_empirico = _read_tempo_raccolta_empirico_flag()
    except Exception:
        tempo_raccolta_empirico = False
    return {
        "enabled":      enabled,
        "shadow_only":  shadow,
        "active":       active,
        "reasons":      reasons,
        "thresholds":   soglie,
        "tempo_raccolta_empirico": tempo_raccolta_empirico,
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

    # WU200ter (11/07) — import lazy dello stimatore empirico nuovo, stesso
    # pattern di _calc_t_marcia_min. Usato SOLO per un campo di confronto
    # osservativo (vedi sotto) — nessuna decisione di scheduling ne dipende.
    try:
        from shared.tempo_raccolta_estimator import stima_tempo_raccolta
    except Exception:
        stima_tempo_raccolta = None  # type: ignore[assignment]

    # Calcola T_marcia per ogni invio, mantenendo l'associazione col suo
    # `ts_invio` reale (necessario per l'anchoring corretto del residuo, vedi sotto).
    invii = invii_record["raccolta"]["invii"]
    t_marce_ts: list[tuple[float, Optional[str]]] = []
    confronto_tempo_raccolta: list[dict] = []
    for inv in invii:
        t = _calc_t_marcia_min(inv, istanza)
        if t is not None:
            t_marce_ts.append((t, inv.get("ts_invio")))

        # WU200ter — affiancamento in sola osservazione del nuovo stimatore
        # empirico (shared/tempo_raccolta_estimator.py, basato su durate
        # reali invio→completamento report, non su formula/saturazione).
        # Campo aggiuntivo nell'output, MAI usato per t_residue_min/
        # rientro_atteso/slot_liberi_atteso — zero rischio di regressione
        # sul comportamento esistente, serve solo a confrontare le due
        # stime nel tempo prima di considerare un eventuale cutover.
        if stima_tempo_raccolta is not None and t is not None:
            tipo_inv = inv.get("tipo")
            livello_inv = inv.get("livello")
            if tipo_inv and livello_inv:
                try:
                    t_emp_s = stima_tempo_raccolta(istanza, tipo_inv, int(livello_inv))
                except Exception:
                    t_emp_s = None
                if t_emp_s is not None:
                    eta_s = int(inv.get("eta_marcia_s") or 0)
                    # WU200 Fase B — `t_emp_s` (durata_s) include GIÀ l'andata
                    # (report a raccolta completata). Per l'equivalente
                    # round-trip (slot libero al rientro) si aggiunge SOLO
                    # l'eta di ritorno, non 2×eta. Pre-fix WU200ter usava
                    # 2×eta (un eta di troppo, ~1min con eta mediano 59s):
                    # cosmetico ma corretto per coerenza con _calc_t_marcia_min.
                    t_emp_min = (eta_s + t_emp_s) / 60.0
                    confronto_tempo_raccolta.append({
                        "tipo": tipo_inv, "livello": livello_inv,
                        "t_det_min": round(t, 1),
                        "t_emp_min": round(t_emp_min, 1),
                        "diff_min": round(t_emp_min - t, 1),
                    })

    if not t_marce_ts:
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

    # Elapsed dal record con invii — fallback quando la singola marcia non ha
    # `ts_invio` (dati storici antecedenti al campo).
    try:
        ts_inv = datetime.fromisoformat(invii_record["ts"])
        elapsed = max(0.0, (datetime.now(timezone.utc) - ts_inv).total_seconds() / 60)
    except Exception:
        elapsed = 0.0

    # T_residue per singola marcia (fix 05/07 — anchoring temporale):
    # ancorato al `ts_invio` REALE della marcia, non al `ts` di fine-tick del
    # record. Il fine-tick sottostimava l'elapsed per le marce partite a
    # inizio di un tick lungo (raccolta invia più squadre nell'arco di
    # minuti), gonfiando il residuo e sottocontando i rientri attesi — bias
    # verso la sottostima confermato empiricamente (40% sottostima vs 32%
    # sovrastima sui cicli LIVE osservati). Fallback al vecchio `elapsed`
    # uniforme se `ts_invio` manca o non è parsabile.
    now_utc = datetime.now(timezone.utc)
    t_residue_min = []
    for t, ts_invio_raw in t_marce_ts:
        residuo = None
        if ts_invio_raw:
            try:
                dep = datetime.fromisoformat(ts_invio_raw)
                residuo = max(0.0, t - (now_utc - dep).total_seconds() / 60)
            except Exception:
                residuo = None
        if residuo is None:
            residuo = max(0.0, t - elapsed)
        t_residue_min.append(residuo)

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
        "confronto_tempo_raccolta": confronto_tempo_raccolta,  # WU200ter, solo osservativo
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
    """Peso deterministico, continuo in n_samples (WU168 19/06 — prima era a
    gradini: n=4→α=1.0, n=5→α=0.7, salto di 0.3 per UN solo campione in più,
    poteva far cambiare bruscamente lo score/ordine senza nulla di reale
    cambiato). Ora interpolazione lineare tra α=1.0 (n=0, solo deterministico)
    e α=0.3 (n>=30, peso forte empirico) — stessi estremi, nessun salto.
    """
    n = max(0, n_samples)
    return max(0.3, 1.0 - 0.7 * min(n, 30) / 30.0)


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

    # P_saturo globale per tie-breaker (proposta C 08/05)
    try:
        from core.empirical_slot_predictor import lookup_p_saturo_globale
        p_sat = lookup_p_saturo_globale(istanza)
    except Exception:
        p_sat = None
    out["p_saturo_glob"] = p_sat   # None se no samples

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
                              master_excluded: bool = False,
                              log_fn=None) -> list[dict]:
    """Greedy adattivo: ordina istanze per `slot_liberi_atteso` decrescente.

    Args:
        istanze: lista nomi istanze (master incluso).
        master_excluded: WU216 — default **False**: il master FauMorfeus
                         partecipa al ranking greedy come le ordinarie (entra
                         in rotazione). Se True: appeso a fine lista fuori
                         ranking (comportamento pre-WU216).
        log_fn: callable opzionale `log_fn(msg: str)`. Se passato, emette un
                trace step-by-step del greedy con candidati + score + scelto.

    Returns:
        list[dict] in ordine ottimale, ciascuno con campi di
        `compute_slot_liberi_atteso` + `t_avvio_min` (offset previsto).
        Con `master_excluded=False` il master è ordinato come le altre;
        con True è sempre ultimo (fuori ranking).

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

        # Ordina (proposta C 08/05): score desc, poi p_saturo asc (preferisci
        # istanze con bassa probabilità storica di essere sature), poi
        # anzianita_tick desc (più in ritardo prima).
        # `p_saturo_glob` può essere None → trattato come 0.5 (neutro) per non
        # penalizzare/favorire istanze senza dati storici.
        scores.sort(key=lambda x: (
            x["score"],
            1.0 - (x.get("p_saturo_glob") if x.get("p_saturo_glob") is not None else 0.5),
            x["anzianita_tick_min"],
        ), reverse=True)

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
    """Carica ordine pianificato se fresh (< TTL_MIN) E stesso giorno UTC.

    Returns: dict con `ordine` + `completate` + `reasons`, oppure None se:
        - file non esiste
        - ordine stantio (ts_saved > TTL_MIN fa)
        - **ts_saved giorno UTC diverso da oggi** (reset cross-mezzanotte UTC,
          WU148 11/05: il gioco resetta DRL master + spedizioni + arena a 00:00
          UTC → planned order pre-mezzanotte è obsoleto anche se entro 4h)
        - parse error
    """
    p = _PLANNED_ORDER_PATH()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts_saved = datetime.fromisoformat(data.get("ts_saved", ""))
        now_utc = datetime.now(timezone.utc)
        age_min = (now_utc - ts_saved).total_seconds() / 60
        if age_min > PLANNED_ORDER_TTL_MIN:
            _log.info("[ADAPT-SCHED] planned order stale (%.0f min) — ignored",
                      age_min)
            return None
        # WU148: reset cross-mezzanotte UTC — contatori di gioco si azzerano
        if ts_saved.date() != now_utc.date():
            _log.info("[ADAPT-SCHED] planned order cross-mezzanotte UTC "
                      "(saved=%s vs now=%s) — ignored (reset 00:00 UTC)",
                      ts_saved.date().isoformat(), now_utc.date().isoformat())
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
