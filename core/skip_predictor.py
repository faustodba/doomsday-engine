# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/skip_predictor.py
# ==============================================================================
#
#  WU89 Step 3 — Skip Predictor (no side-effect, flag-driven).
#
#  Modulo standalone che predice se un'istanza dovrebbe essere skippata al
#  prossimo tick, basandosi su metriche storiche (data/istanza_metrics.jsonl)
#  e state di produzione (state/FAU_*.json).
#
#  USO:
#      from core.skip_predictor import predict, SkipDecision
#      dec = predict("FAU_04", history)
#      if dec.should_skip and skip_predictor_enabled and not shadow_only:
#          # bot salta l'istanza
#
#  GUARDRAIL — anti-stallo (l'istanza non muore mai):
#    - Max 3 skip consecutivi → 4° tick forza retry
#    - Re-evaluation ogni 6 cicli totali (anche se predictor dice skip)
#    - Cooldown 2 cicli post-retry: skip disabilitato
#    - Growth phase: istanze con truppe < 100K NON vengono mai skippate
#      per regole "low_prod" (loop raccolta→truppe→raccoglitori critico)
#
#  REGOLE (in ordine valutazione):
#    1. growth_phase_block — se total_squads < 100K, blocca skip low_prod
#    2. squadre_fuori — slot saturi + ritorno bot prematuro
#    3. trend_magro — last_3 avg_inv (raccolta) < 0.5
#    4. low_total_invii — last_3 avg(rac+rif) < target*ratio (default 2.5)
#    5. recovery — outcome 'degraded' recente
#    6. low_prod — produzione cumulativa bassa (con override growth)
#    7. default — NO skip
#
#  Questo modulo NON modifica state/files. Lettura sola.
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ==============================================================================
# Tunables (override via config futuro se serve)
# ==============================================================================

# Soglie regole
GROWTH_PHASE_TRUPPE = 100_000      # sotto questa soglia: NO skip low_prod
LOW_PROD_THRESHOLD = 100_000       # <100K/h cumulativo = produzione bassa
MIN_CICLI_LOW_PROD = 5             # serve dataset minimo per regola low_prod
TREND_MAGRO_AVG_THRESHOLD = 0.5    # avg_inv ultimi 3 cicli < 0.5 = magro
TREND_MAGRO_WINDOW = 3
RECOVERY_GAP_S = 300               # se outcome degraded e gap < 5min, skip

# Target invii (raccolta + rifornimento) per ciclo
TARGET_INVII_CICLO = 5             # ciclo produttivo se total_invii >= 5
LOW_INVII_WINDOW   = 3             # finestra valutazione (ultimi N cicli)
LOW_INVII_AVG_RATIO = 0.5          # avg_3 < target * 0.5 = ciclo improduttivo

# Guardrail
MAX_SKIP_CONSECUTIVI = 3           # dopo N skip, forza retry
RE_EVAL_CICLI = 6                  # ogni N cicli totali, retry obbligato
COOLDOWN_POST_RETRY_CICLI = 2      # dopo retry forzato, skip disabilitato per N cicli


# ==============================================================================
# Data classes
# ==============================================================================

@dataclass
class SkipDecision:
    """Output del predictor per una singola valutazione."""
    should_skip: bool
    reason: str                              # codice regola (es. "low_prod")
    score: float                             # 0..1 confidence
    signals: dict = field(default_factory=dict)   # raw values usati
    growth_phase: bool = False               # True se istanza in growth phase
    guardrail_triggered: Optional[str] = None  # se guardrail ha bloccato skip


@dataclass
class IstanzaSkipState:
    """
    State per-istanza per guardrail (opzionale, in-memory dal caller).

    `cicli_dall_ultimo_retry` parte da COOLDOWN_POST_RETRY_CICLI per indicare
    "nessun retry forzato recente": altrimenti il primo skip di un'istanza
    fresh sarebbe sempre bloccato dalla regola cooldown_post_retry. Va
    azzerato dal caller quando guardrail forza un retry (max_skip_consec
    o re_eval_periodic) e incrementato di 1 ad ogni altro ciclo (clamp a
    COOLDOWN_POST_RETRY_CICLI).
    """
    last_skip_count_consec: int = 0
    last_skip_ts: Optional[float] = None
    cicli_dall_ultimo_retry: int = COOLDOWN_POST_RETRY_CICLI
    cicli_totali: int = 0


# ==============================================================================
# Helpers — lettura dati
# ==============================================================================

def _resolve_root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def load_metrics_history(istanza: str, last_n: int = 20) -> list[dict]:
    """
    Legge ultimi N record da `data/istanza_metrics.jsonl` per l'istanza.
    Best-effort, ritorna [] su errore o file mancante.
    """
    root = _resolve_root()
    path = root / "data" / "istanza_metrics.jsonl"
    if not path.exists():
        return []
    records = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("instance") == istanza:
                    records.append(r)
    except Exception:
        return []
    return records[-last_n:]


def load_state_metrics(istanza: str) -> dict:
    """Legge metrics da state/FAU_XX.json. Ritorna {} su errore."""
    root = _resolve_root()
    path = root / "state" / f"{istanza}.json"
    if not path.exists():
        return {}
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
        return s.get("metrics", {}) or {}
    except Exception:
        return {}


def load_truppe(istanza: str) -> int:
    """
    Legge total_squads da `data/storico_truppe.json`.
    Ritorna ultimo valore o 0 se mancante/errato.
    NOTA: l'OCR di Total Squads può essere errato (vedi memoria).
    Il predictor usa questo dato SOLO come hint per growth_phase
    (sotto 100K → blocca skip low_prod). Non sicuramente gating.
    """
    root = _resolve_root()
    path = root / "data" / "storico_truppe.json"
    if not path.exists():
        return 0
    try:
        ts = json.loads(path.read_text(encoding="utf-8"))
        hist = ts.get(istanza, [])
        if not hist:
            return 0
        return int(hist[-1].get("total_squads", 0))
    except Exception:
        return 0


# ==============================================================================
# WU-CycleDur — Modello empirico T_marcia (vedi config/predictor_t_l_max.json)
# Sostituisce il calcolo "2 × avg_eta_marcia + 30" della vecchia _rule_squadre_fuori
# con: T_marcia = 2 × eta_marcia + saturazione × T_L_max[livello, istanza]
# ==============================================================================

# Capacità nominale max per (tipo, livello). Coerente con tools/analisi_cap_nodi.
CAP_NOMINALE = {
    ("campo", 6):    1_200_000, ("campo", 7):    1_320_000,
    ("segheria", 6): 1_200_000, ("segheria", 7): 1_320_000,
    ("acciaio", 6):    600_000, ("acciaio", 7):    660_000,
    ("petrolio", 6):   240_000, ("petrolio", 7):   264_000,
}

_t_l_max_cache: dict = {"loaded_at": 0.0, "data": None}


def _load_t_l_max_config() -> dict:
    """Carica config/predictor_t_l_max.json (cached). Default conservativi."""
    import time as _t
    if _t_l_max_cache["data"] and (_t.time() - _t_l_max_cache["loaded_at"]) < 60:
        return _t_l_max_cache["data"]
    root = _resolve_root()
    path = root / "config" / "predictor_t_l_max.json"
    if not path.exists():
        cfg = {
            "_default_per_livello":   {"5": 100, "6": 114, "7": 125},
            "_multiplier_per_istanza": {"_default": 1.3},
        }
    else:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {"_default_per_livello": {"5": 100, "6": 114, "7": 125},
                   "_multiplier_per_istanza": {"_default": 1.3}}
    _t_l_max_cache["data"] = cfg
    _t_l_max_cache["loaded_at"] = _t.time()
    return cfg


def _get_t_l_max_min(istanza: str, livello: int) -> float:
    """T_L_max in minuti per (livello, istanza). Fallback default 30min."""
    cfg = _load_t_l_max_config()
    base = cfg.get("_default_per_livello", {}).get(str(livello))
    if base is None:
        return 30.0
    mult_map = cfg.get("_multiplier_per_istanza", {}) or {}
    mult = mult_map.get(istanza, mult_map.get("_default", 1.3))
    return float(base) * float(mult)


def _calc_t_marcia_min(invio: dict, istanza: str) -> Optional[float]:
    """
    Stima T_marcia totale (andata + raccolta + ritorno) in minuti per 1 invio.

    Formula: T_marcia = 2 × eta_marcia_min + saturazione × T_L_max[livello, istanza]

    Ritorna None se dati insufficienti (livello o load_squadra mancanti).
    """
    livello = int(invio.get("livello", -1))
    tipo    = invio.get("tipo", "")
    load    = int(invio.get("load_squadra", -1))
    eta_s   = int(invio.get("eta_marcia_s", 0) or 0)
    if livello < 1 or load <= 0:
        return None
    cap = CAP_NOMINALE.get((tipo, livello))
    if not cap or cap <= 0:
        return None
    saturazione = min(1.0, load / cap)
    eta_min = eta_s / 60.0
    t_l_max = _get_t_l_max_min(istanza, livello)
    return 2 * eta_min + saturazione * t_l_max


def _predict_gap_minutes() -> float:
    """
    Stima durata ciclo bot in minuti tramite cycle_duration_predictor.
    Fallback a 120min se modulo non disponibile.
    """
    try:
        from core.cycle_duration_predictor import predict_cycle_from_config
        res = predict_cycle_from_config()
        if "T_ciclo_min" in res:
            return float(res["T_ciclo_min"])
    except Exception:
        pass
    return 120.0   # fallback ragionevole


def _saving_estimato(istanza: str) -> tuple[float, float, float]:
    """
    Stima saving per skip di una istanza:
      saving_s = boot_home_s + Σ task_durations_s (al netto NOOP guards)

    Returns:
        (saving_s, boot_home_s, tasks_s). Tutti 0.0 se predictor non disponibile.
    """
    try:
        from core.cycle_duration_predictor import predict_cycle_from_config
        res = predict_cycle_from_config(strict_schedule=True)
        per_ist = (res.get("per_istanza") or {}).get(istanza)
        if not per_ist:
            return 0.0, 0.0, 0.0
        T_s    = float(per_ist.get("T_s", 0.0))
        boot_s = float(per_ist.get("boot_home_s", 0.0))
        return T_s, boot_s, max(0.0, T_s - boot_s)
    except Exception:
        return 0.0, 0.0, 0.0


# ==============================================================================
# Regole predittive
# ==============================================================================

def _rule_squadre_fuori(history: list[dict],
                          istanza: Optional[str] = None) -> Optional[SkipDecision]:
    """
    Regola CORE (refactor WU-CycleDur 04/05): squadre ancora in marcia
    al prossimo passaggio bot. Modello empirico per-marcia:

        T_marcia[i] = 2 × eta_marcia_i + saturazione_i × T_L_max[livello_i, istanza]
        saturazione_i = load_squadra_i / cap_nominale_L_max[livello_i, tipo_i]
        T_min_rientro = min(T_marcia[i] for i in invii)
        gap_atteso    = predict_cycle_duration() / 60   # minuti

    SE attive_post[last] = totali (slot saturi a fine tick prec.)
       AND invii_ultimo >= 3
       AND T_min_rientro > gap_atteso (nessuna squadra rientra in tempo)
    THEN SKIP — al prossimo passaggio gli slot sono ancora pieni → ciclo sterile.

    Vincoli rispetto alla v1:
    - Usa cap_nominale + load_squadra (post-WU116) invece di stima ETA andata sola
    - gap_atteso dinamico via cycle_duration_predictor invece di costante
    - Skippa se DATI INSUFFICIENTI (load=-1 ovunque) → fallback regole vecchie
    """
    if not history:
        return None
    last = history[-1]
    rac = last.get("raccolta", {}) or {}
    attive_post = rac.get("attive_post")
    totali      = rac.get("totali", 4)
    invii       = rac.get("invii", []) or []
    invii_n     = len(invii)

    # Slot non saturi a fine tick → niente da skippare
    if attive_post is None or attive_post < totali or invii_n < 3:
        return None

    # Calcola T_marcia per ogni invio (richiede load_squadra valorizzato)
    t_marce_min = []
    for inv in invii:
        t = _calc_t_marcia_min(inv, istanza or "_unknown")
        if t is not None:
            t_marce_min.append(t)
    if not t_marce_min:
        # Tutti pre-WU116 / dati insufficienti → no skip da questa regola
        return None

    # Tempo trascorso dal record (le marce si stanno già consumando)
    elapsed_min = 0.0
    try:
        last_ts_str = last.get("ts")
        if last_ts_str:
            last_ts = datetime.fromisoformat(last_ts_str)
            elapsed_min = max(0.0, (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0)
    except Exception:
        elapsed_min = 0.0

    # T_residuo[i] = max(0, T_marcia[i] - elapsed): tempo che manca da ADESSO
    t_marce_residue = [max(0.0, t - elapsed_min) for t in t_marce_min]
    t_min_rientro = min(t_marce_residue)
    t_max_rientro = max(t_marce_residue)
    gap_atteso_min = _predict_gap_minutes()

    if t_min_rientro <= gap_atteso_min:
        # Almeno 1 squadra rientrerà in tempo → slot si libererà → no skip
        return None

    return SkipDecision(
        should_skip=True,
        reason="squadre_fuori",
        score=0.90,   # aumentato (modello empirico più confidente)
        signals={
            "attive_post":      attive_post,
            "invii_ultimo":     invii_n,
            "T_min_rientro_min": round(t_min_rientro, 1),
            "T_max_rientro_min": round(t_max_rientro, 1),
            "T_marcia_totale_min": round(min(t_marce_min), 1),  # debug: pre-elapsed
            "elapsed_dal_record_min": round(elapsed_min, 1),
            "gap_atteso_min":    round(gap_atteso_min, 1),
            "delta_min":         round(t_min_rientro - gap_atteso_min, 1),
        },
    )


def _rule_trend_magro(history: list[dict]) -> Optional[SkipDecision]:
    """
    Regola 3: ultimi 3 cicli con avg_inv < 0.5 → istanza desaturata.
    """
    if len(history) < TREND_MAGRO_WINDOW:
        return None
    last_n = history[-TREND_MAGRO_WINDOW:]
    invii_per_ciclo = []
    for r in last_n:
        rac = r.get("raccolta", {}) or {}
        invii_per_ciclo.append(len(rac.get("invii", []) or []))
    if not invii_per_ciclo:
        return None
    avg_inv = sum(invii_per_ciclo) / len(invii_per_ciclo)
    if avg_inv >= TREND_MAGRO_AVG_THRESHOLD:
        return None
    return SkipDecision(
        should_skip=True,
        reason="trend_magro",
        score=0.65,
        signals={
            "avg_inv_last_3": round(avg_inv, 2),
            "window": TREND_MAGRO_WINDOW,
            "invii_per_ciclo": invii_per_ciclo,
        },
    )


def _rule_low_total_invii(history: list[dict]) -> Optional[SkipDecision]:
    """
    Regola: ultimi N cicli con avg(total_invii) < TARGET * RATIO → improduttivo.

    `total_invii` per ciclo = len(raccolta.invii) + len(rifornimento.invii).
    Combina marce raccolta + spedizioni rifornimento.

    Esempio default: TARGET=5, RATIO=0.5 → soglia avg = 2.5
    Se avg_3_cicli(total) < 2.5 → skip suggerito (basso utilizzo slot+rifugio)

    NON applicabile se rifornimento è strutturalmente OFF (no record rifornimento
    in nessun ciclo della finestra) — in quel caso la regola `_rule_trend_magro`
    già copre la valutazione su sola raccolta.
    """
    if len(history) < LOW_INVII_WINDOW:
        return None
    last_n = history[-LOW_INVII_WINDOW:]

    # Verifica che almeno 1 ciclo abbia rifornimento (altrimenti regola non
    # applicabile — copre _rule_trend_magro)
    has_rifornimento = any(
        (r.get("rifornimento") or {}).get("invii") for r in last_n
    )
    if not has_rifornimento:
        return None

    invii_per_ciclo = []
    for r in last_n:
        rac = (r.get("raccolta") or {}).get("invii", []) or []
        rif = (r.get("rifornimento") or {}).get("invii", []) or []
        invii_per_ciclo.append(len(rac) + len(rif))
    avg_inv = sum(invii_per_ciclo) / len(invii_per_ciclo)
    threshold = TARGET_INVII_CICLO * LOW_INVII_AVG_RATIO
    if avg_inv >= threshold:
        return None
    return SkipDecision(
        should_skip=True,
        reason="low_total_invii",
        score=0.60,
        signals={
            "avg_total_invii_last_3": round(avg_inv, 2),
            "target": TARGET_INVII_CICLO,
            "threshold_avg": round(threshold, 2),
            "invii_per_ciclo": invii_per_ciclo,
            "window": LOW_INVII_WINDOW,
        },
    )


def _rule_recovery(history: list[dict]) -> Optional[SkipDecision]:
    """
    Regola 4: outcome ultimo='degraded' (UNKNOWN/cascade/error) + gap < 5min.
    Dare tempo all'istanza di stabilizzarsi.
    """
    if not history:
        return None
    last = history[-1]
    outcome = last.get("outcome", "ok")
    if outcome == "ok" or outcome == "":
        return None
    try:
        last_ts = datetime.fromisoformat(last["ts"])
        gap_s = (datetime.now(timezone.utc) - last_ts).total_seconds()
    except Exception:
        return None
    if gap_s >= RECOVERY_GAP_S:
        return None
    return SkipDecision(
        should_skip=True,
        reason="recovery",
        score=0.75,
        signals={"outcome": outcome, "gap_s": int(gap_s)},
    )


def _rule_low_prod(istanza: str, history: list[dict]) -> Optional[SkipDecision]:
    """
    Regola 5: produzione cumulativa bassa (< 100K/h totale) E almeno 5 cicli.
    Restituisce decisione skip ONLY se non in growth phase (gestita dal caller).

    Edge case: prod=0 può significare "non aggiornato" (WU47, cicli < 300s)
    invece di "realmente basso". Protezione: prod deve essere > 0 per
    applicare la regola (un valore numerico significativo).
    """
    if len(history) < MIN_CICLI_LOW_PROD:
        return None
    state_metrics = load_state_metrics(istanza)
    prod = (
        (state_metrics.get("pomodoro_per_ora", 0) or 0)
        + (state_metrics.get("legno_per_ora", 0) or 0)
        + (state_metrics.get("petrolio_per_ora", 0) or 0)
        + (state_metrics.get("acciaio_per_ora", 0) or 0)
    )
    # Protezione: prod=0 = dato non disponibile, non "basso"
    if prod <= 0:
        return None
    if prod >= LOW_PROD_THRESHOLD:
        return None
    return SkipDecision(
        should_skip=True,
        reason="low_prod",
        score=0.55,
        signals={"prod_per_ora": int(prod), "threshold": LOW_PROD_THRESHOLD,
                 "cicli_history": len(history)},
    )


# ==============================================================================
# Guardrail
# ==============================================================================

def _check_guardrail(state: Optional[IstanzaSkipState],
                     decision: SkipDecision) -> Optional[str]:
    """
    Verifica guardrail anti-stallo. Ritorna ragione di blocco skip o None.
    """
    if not state or not decision.should_skip:
        return None
    # Max skip consecutivi: dopo MAX_SKIP_CONSECUTIVI, forza retry
    if state.last_skip_count_consec >= MAX_SKIP_CONSECUTIVI:
        return f"max_skip_consec_reached ({state.last_skip_count_consec})"
    # Re-eval periodica: ogni RE_EVAL_CICLI cicli totali, forza retry
    if state.cicli_totali > 0 and state.cicli_totali % RE_EVAL_CICLI == 0:
        return f"re_eval_periodic ({state.cicli_totali} cicli)"
    # Cooldown post-retry
    if state.cicli_dall_ultimo_retry < COOLDOWN_POST_RETRY_CICLI:
        return f"cooldown_post_retry ({state.cicli_dall_ultimo_retry}/{COOLDOWN_POST_RETRY_CICLI})"
    return None


# ==============================================================================
# Entry point principale
# ==============================================================================

def predict(istanza: str,
            history: Optional[list[dict]] = None,
            state: Optional[IstanzaSkipState] = None) -> SkipDecision:
    """
    Predice se l'istanza dovrebbe essere skippata al prossimo tick.

    Args:
        istanza: nome istanza (es. "FAU_04")
        history: opzionale, list[dict] di metrics record. Se None, carica da JSONL.
        state: opzionale, IstanzaSkipState per guardrail. Se None, no guardrail.

    Returns:
        SkipDecision con should_skip + reason + score + signals.
    """
    # Master istanze (es. FauMorfeus, rifugio destinatario): non vanno mai
    # skippate dal predictor — sono fuori dai ranking ordinari per scope.
    from shared.instance_meta import is_master_instance
    if is_master_instance(istanza):
        return SkipDecision(
            should_skip=False,
            reason="master_instance",
            score=0.0,
            signals={"istanza": istanza},
        )

    if history is None:
        history = load_metrics_history(istanza, last_n=10)

    # Growth phase check (truppe basse → skip low_prod inibito)
    truppe = load_truppe(istanza)
    growth_phase = 0 < truppe < GROWTH_PHASE_TRUPPE

    # Valuta regole in ordine di priorità (più specifiche prima).
    # _rule_squadre_fuori richiede `istanza` per accesso config T_L_max.
    decision: Optional[SkipDecision] = None
    decision = _rule_squadre_fuori(history, istanza=istanza)
    if decision is None:
        for rule in (
            _rule_trend_magro,
            _rule_low_total_invii,
            _rule_recovery,
        ):
            decision = rule(history)
            if decision:
                break

    # Regola low_prod solo se NON in growth phase
    if decision is None and not growth_phase:
        decision = _rule_low_prod(istanza, history)

    # Default: no skip
    if decision is None:
        decision = SkipDecision(
            should_skip=False,
            reason="proceed",
            score=0.0,
            signals={"truppe": truppe, "growth_phase": growth_phase},
            growth_phase=growth_phase,
        )

    decision.growth_phase = growth_phase
    if growth_phase and decision.signals is not None:
        decision.signals["growth_phase_active"] = True

    # Saving estimato per skip: rende esplicita la motivazione fondamentale
    # del predictor — risparmiare boot+task per istanze "improduttive" date
    # le condizioni correnti.
    if decision.should_skip:
        s_total, s_boot, s_tasks = _saving_estimato(istanza)
        if decision.signals is None:
            decision.signals = {}
        decision.signals["saving_estimato_s"]     = round(s_total, 1)
        decision.signals["saving_estimato_min"]   = round(s_total / 60, 1)
        decision.signals["saving_boot_home_s"]    = round(s_boot, 1)
        decision.signals["saving_tasks_s"]        = round(s_tasks, 1)

    # Guardrail check
    gr_block = _check_guardrail(state, decision)
    if gr_block and decision.should_skip:
        # Skip era previsto ma guardrail blocca: forza retry. Preserva
        # saving_estimato_* nei signals per visibilità "saving non realizzato".
        return SkipDecision(
            should_skip=False,
            reason=f"proceed_guardrail",
            score=0.0,
            signals={**(decision.signals or {}), "predicted_skip_reason": decision.reason},
            growth_phase=growth_phase,
            guardrail_triggered=gr_block,
        )

    return decision
