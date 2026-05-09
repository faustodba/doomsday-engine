"""core/cycle_predictor_calibration.py — calibrazione closed-loop cycle predictor.

Proposta D 08/05: legge `data/predictions/cycle_accuracy.jsonl` (compilato dal
recorder dashboard), calcola bias sistematico (actual / predicted - 1) sui
cicli completati e produce un fattore moltiplicativo globale.

Persistenza in `data/predictions/cycle_calibration.json`:
    {
      "factor":           float,   # moltiplicatore (1.0 = no calibrazione)
      "n_samples":        int,
      "bias_pct":         float,   # bias medio (actual-predicted)/predicted
      "ts_computed":      "2026-05-08T...",
      "window_cycles":    [int],   # cycle_numero usati nel calcolo
      "confidence":       "alta" | "media" | "bassa",
    }

Hook: il `core.adaptive_scheduler._stima_durata_istanza_min` legge il factor
e lo applica alla stima `T_s` per istanza. Auto-rebuild ogni 30min.

Guardrail:
- factor clamped a [0.5, 2.0] per evitare scenari di calibrazione perversa
- min 5 cicli completati richiesti, altrimenti factor=1.0
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional

_log = logging.getLogger(__name__)

CALIBRATION_TTL_S = 30 * 60   # rebuild ogni 30min
WINDOW_DEFAULT    = 20        # ultimi N cicli (09/05: 10→20 per ridurre
                              # sensibilità a outlier; ogni anomalia conta
                              # 1/20 invece di 1/10. Trade-off: reagisce più
                              # lentamente a cambi sistemici, ma sistema ora
                              # ha 30+ cicli accumulati = fedeltà mantenuta)
MIN_SAMPLES       = 5         # serve almeno 5 cicli per calibrare
FACTOR_MIN        = 0.5       # clamp [0.5, 2.0]
FACTOR_MAX        = 2.0
TRIGGER_BIAS_PCT  = 5.0       # se |bias| < 5% → factor=1.0 (rumore)


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _accuracy_path() -> Path:
    return _root() / "data" / "predictions" / "cycle_accuracy.jsonl"


def _calibration_path() -> Path:
    return _root() / "data" / "predictions" / "cycle_calibration.json"


# ─── Cache ──────────────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "factor": 1.0, "data": None}


def _read_cycles(window: int) -> list[dict]:
    """Legge ultimi `window` cicli con accuracy disponibile."""
    p = _accuracy_path()
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception as exc:
        _log.warning("[CALIB] read failed: %s", exc)
        return []
    return out[-window:] if len(out) > window else out


def compute_calibration(window: int = WINDOW_DEFAULT) -> dict:
    """Calcola fattore di calibrazione dai dati accuracy.

    Logica:
    - Per ogni ciclo, prendi `predicted_min` mediano (su tutti gli snapshot
      del ciclo) e `actual_min`. Bias = (actual - predicted) / predicted.
    - Aggrega bias su tutti i cicli (mediana per robustezza vs outlier).
    - factor = 1 + bias_mediano (se |bias| ≥ TRIGGER, altrimenti 1.0).

    Returns:
        dict con factor + diagnostica (vedi schema in module docstring).
    """
    cycles = _read_cycles(window)
    if len(cycles) < MIN_SAMPLES:
        return {
            "factor":      1.0,
            "n_samples":   len(cycles),
            "bias_pct":    0.0,
            "ts_computed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window_cycles": [c.get("cycle_numero") for c in cycles],
            "confidence":  "bassa",
            "reason":      f"insufficienti cicli ({len(cycles)}<{MIN_SAMPLES})",
        }

    biases: list[float] = []
    cycle_nums: list[int] = []
    for c in cycles:
        actual = float(c.get("actual_min", 0) or 0)
        snaps = c.get("snapshots") or []
        if actual <= 0 or not snaps:
            continue
        # Mediana dei predicted del ciclo (più robusto della media)
        preds = [float(s.get("predicted_min", 0) or 0) for s in snaps if s.get("predicted_min")]
        if not preds:
            continue
        pred_med = median(preds)
        if pred_med <= 0:
            continue
        bias = (actual - pred_med) / pred_med
        biases.append(bias)
        cycle_nums.append(int(c.get("cycle_numero", 0)))

    if not biases:
        return {
            "factor":      1.0,
            "n_samples":   0,
            "bias_pct":    0.0,
            "ts_computed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window_cycles": cycle_nums,
            "confidence":  "bassa",
            "reason":      "nessun ciclo con dati validi",
        }

    bias_med = median(biases)
    bias_pct = round(bias_med * 100, 1)

    # Trigger threshold: se |bias| < TRIGGER → factor=1.0 (rumore)
    if abs(bias_pct) < TRIGGER_BIAS_PCT:
        factor = 1.0
        reason = f"bias |{bias_pct}%| < trigger {TRIGGER_BIAS_PCT}%"
    else:
        factor = 1.0 + bias_med
        # Clamp guardrail
        factor = max(FACTOR_MIN, min(FACTOR_MAX, factor))
        reason = f"bias mediano {bias_pct}% → factor {factor:.3f}"

    confidence = "alta" if len(biases) >= 8 else ("media" if len(biases) >= 5 else "bassa")

    return {
        "factor":         round(factor, 4),
        "n_samples":      len(biases),
        "bias_pct":       bias_pct,
        "ts_computed":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_cycles":  cycle_nums,
        "confidence":     confidence,
        "reason":         reason,
    }


def save_calibration(data: dict) -> bool:
    """Persiste calibrazione su disco (atomic write)."""
    p = _calibration_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.error("[CALIB] save failed: %s", exc)
        return False


def load_calibration() -> Optional[dict]:
    """Carica calibrazione da disco. Returns None se mancante o corrotto."""
    p = _calibration_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_calibration_factor() -> float:
    """API principale: ritorna factor corrente, ricalcola se TTL scaduto.

    Cache TTL 30min: per un greedy che gira ~1×/ciclo è più che sufficiente.
    Failsafe: errori → 1.0 (no impact).
    """
    with _cache_lock:
        now = time.time()
        if now - _cache.get("ts", 0) > CALIBRATION_TTL_S:
            try:
                # Prima prova: leggi da disco se esiste e fresco
                stored = load_calibration()
                if stored:
                    try:
                        ts_stored = datetime.fromisoformat(stored.get("ts_computed", ""))
                        age_min = (datetime.now(timezone.utc) - ts_stored).total_seconds() / 60
                        if age_min < (CALIBRATION_TTL_S / 60):
                            _cache["factor"] = float(stored.get("factor", 1.0))
                            _cache["data"] = stored
                            _cache["ts"] = now
                            return _cache["factor"]
                    except Exception:
                        pass

                # Ricalcola
                data = compute_calibration()
                save_calibration(data)
                _cache["factor"] = float(data.get("factor", 1.0))
                _cache["data"] = data
                _cache["ts"] = now
            except Exception as exc:
                _log.warning("[CALIB] auto-update failed: %s", exc)
                _cache["factor"] = 1.0   # safe default
                _cache["ts"] = now
        return _cache["factor"]


def get_calibration_info() -> Optional[dict]:
    """Ritorna dict completo per dashboard (last_computed, factor, bias, etc.)."""
    get_calibration_factor()   # forza refresh se serve
    return _cache.get("data")


def invalidate_cache() -> None:
    """Forza ricalcolo al prossimo `get_calibration_factor`."""
    with _cache_lock:
        _cache["ts"] = 0.0


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Test cycle predictor calibration.")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_c = sub.add_parser("compute", help="Compute + save calibration now")
    p_c.add_argument("--window", type=int, default=WINDOW_DEFAULT)
    sub.add_parser("show", help="Show current calibration from disk")
    sub.add_parser("factor", help="Print current cached factor")
    sub.add_parser("invalidate", help="Force recompute next call")

    args = p.parse_args()
    if args.cmd == "compute":
        data = compute_calibration(window=args.window)
        save_calibration(data)
        print(json.dumps(data, indent=2))
    elif args.cmd == "show":
        print(json.dumps(load_calibration() or {"error": "no calibration"}, indent=2))
    elif args.cmd == "factor":
        print(get_calibration_factor())
    elif args.cmd == "invalidate":
        invalidate_cache()
        print("cache invalidated")
