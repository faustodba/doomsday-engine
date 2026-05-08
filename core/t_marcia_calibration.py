"""core/t_marcia_calibration.py — calibrazione closed-loop T_marcia per (istanza, livello).

Proposta B 08/05: usa la coppia (predetto, reale) per stimare il bias del modello
T_marcia per ogni istanza e livello del nodo, e correggere via coefficiente
moltiplicativo applicato in `core.skip_predictor._calc_t_marcia_min`.

Pipeline:
1. Scansiona `data/istanza_metrics.jsonl` con record che hanno
   `adaptive_scheduler_meta.slot_liberi_attesi` (= predizione al ciclo N).
2. Per ogni record N, trova il SUCCESSIVO record della stessa istanza con
   `raccolta.attive_pre + raccolta.totali` valorizzati (= osservazione al
   ciclo N+1, quando il bot è arrivato a quell'istanza).
3. Calcola `error_slot = predicted_slot_liberi - real_slot_liberi`.
   - error > 0 → predetto più slot liberi del reale → squadre rientrate
                 MENO → T_marcia REALE > T_marcia predetto → coef > 1.0
   - error < 0 → predetto meno slot liberi del reale → squadre rientrate
                 PIÙ → T_marcia reale < T_marcia predetto → coef < 1.0
4. Aggrega per (istanza, livello_primo_invio) → bias mediano.
5. Coefficiente: `coef = 1.0 + bias_slot * SENSITIVITY` clamp [0.7, 1.5].

Persistenza: `data/predictor_t_l_calibration.json`:
    {
      "coefs": {"FAU_05|6": 1.12, "FAU_07|7": 0.95, ...},
      "samples": {"FAU_05|6": 18, ...},
      "bias_slot": {"FAU_05|6": 2.4, ...},
      "ts_computed": "...",
      "n_total_samples": int,
      "confidence": "alta" | "media" | "bassa",
    }

Hook: `core.skip_predictor._calc_t_marcia_min` legge `get_calibration_coef(ist, lv)`
e applica come moltiplicatore sul T_marcia totale. Default 1.0 se no samples.

Guardrail:
- min 5 sample per (ist, lv) per coefficiente non-1.0
- coef clamp [0.7, 1.5] per evitare scenari perversi
- cache TTL 30min
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional

_log = logging.getLogger(__name__)

CALIBRATION_TTL_S    = 30 * 60        # rebuild ogni 30min
WINDOW_RECORDS       = 500            # ultimi N record JSONL da scansionare
MIN_SAMPLES_KEY      = 5              # min sample per (ist, lv) per attivare calib
SENSITIVITY          = 0.05           # ogni slot di bias = 5% di coef
COEF_MIN             = 0.7
COEF_MAX             = 1.5
TRIGGER_BIAS_SLOT    = 0.5            # |bias_slot| < 0.5 → coef=1.0 (rumore)


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _metrics_path() -> Path:
    return _root() / "data" / "istanza_metrics.jsonl"


def _calib_path() -> Path:
    return _root() / "data" / "predictor_t_l_calibration.json"


_cache_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "data": None}


# ─── Build calibration ──────────────────────────────────────────────────────

def _read_records(window: int = WINDOW_RECORDS) -> list[dict]:
    p = _metrics_path()
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
        _log.warning("[T-CAL] read fail: %s", exc)
        return []
    return out[-window:] if len(out) > window else out


def compute_calibration(window: int = WINDOW_RECORDS) -> dict:
    """Computa coefficienti correttivi T_marcia per ogni (istanza, livello).

    Returns dict completo persistibile.
    """
    records = _read_records(window=window)
    if not records:
        return {
            "coefs": {}, "samples": {}, "bias_slot": {},
            "ts_computed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_total_samples": 0,
            "confidence": "bassa",
            "reason": "no records",
        }

    # Group records by instance, sorted by ts
    by_inst: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        ist = r.get("instance")
        if ist:
            by_inst[ist].append(r)
    for ist in by_inst:
        by_inst[ist].sort(key=lambda r: r.get("ts", ""))

    # Per ogni (istanza, livello) accumula error_slot per coppie consecutive
    bias_pool: dict[tuple[str, int], list[float]] = defaultdict(list)

    for ist, recs in by_inst.items():
        for i in range(len(recs) - 1):
            cur = recs[i]
            nxt = recs[i + 1]

            # Predizione al ciclo N
            meta = cur.get("adaptive_scheduler_meta") or {}
            predicted = meta.get("slot_liberi_attesi")
            if predicted is None:
                continue

            # Livello dal primo invio del record N (rappresenta il livello tipico)
            invii = (cur.get("raccolta") or {}).get("invii") or []
            if not invii:
                continue
            livello = int(invii[0].get("livello") or 0)
            if livello < 1:
                continue

            # Osservazione al ciclo N+1
            rac_nxt = nxt.get("raccolta") or {}
            attive_pre = rac_nxt.get("attive_pre")
            totali = rac_nxt.get("totali")
            if attive_pre is None or totali is None or totali <= 0:
                continue
            real_slot_liberi = max(0, int(totali) - int(attive_pre))

            error = float(predicted) - float(real_slot_liberi)
            bias_pool[(ist, livello)].append(error)

    # Aggrega → coef
    coefs: dict[str, float] = {}
    samples: dict[str, int] = {}
    bias_map: dict[str, float] = {}

    for (ist, lv), errors in bias_pool.items():
        n = len(errors)
        key = f"{ist}|{lv}"
        samples[key] = n
        bias = float(median(errors))
        bias_map[key] = round(bias, 2)

        if n < MIN_SAMPLES_KEY or abs(bias) < TRIGGER_BIAS_SLOT:
            coefs[key] = 1.0
            continue
        coef = 1.0 + bias * SENSITIVITY
        coef = max(COEF_MIN, min(COEF_MAX, coef))
        coefs[key] = round(coef, 4)

    n_total = sum(samples.values())
    if n_total >= 50:
        confidence = "alta"
    elif n_total >= 20:
        confidence = "media"
    else:
        confidence = "bassa"

    return {
        "coefs":           coefs,
        "samples":         samples,
        "bias_slot":       bias_map,
        "ts_computed":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_total_samples": n_total,
        "confidence":      confidence,
        "reason":          f"n_keys={len(coefs)} window={window}",
    }


def save_calibration(data: dict) -> bool:
    p = _calib_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.error("[T-CAL] save fail: %s", exc)
        return False


def load_calibration() -> Optional[dict]:
    p = _calib_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─── API principale (consumer in skip_predictor) ────────────────────────────

def _refresh_if_stale() -> dict:
    with _cache_lock:
        now = time.time()
        if _cache.get("data") is None or now - _cache.get("ts", 0) > CALIBRATION_TTL_S:
            try:
                stored = load_calibration()
                if stored:
                    try:
                        ts_stored = datetime.fromisoformat(stored.get("ts_computed", ""))
                        age_min = (datetime.now(timezone.utc) - ts_stored).total_seconds() / 60
                        if age_min < (CALIBRATION_TTL_S / 60):
                            _cache["data"] = stored
                            _cache["ts"] = now
                            return stored
                    except Exception:
                        pass
                # Recompute
                data = compute_calibration()
                save_calibration(data)
                _cache["data"] = data
                _cache["ts"] = now
            except Exception as exc:
                _log.warning("[T-CAL] auto-update fail: %s", exc)
                _cache["data"] = {"coefs": {}}
                _cache["ts"] = now
        return _cache["data"]


def get_calibration_coef(istanza: str, livello: int) -> float:
    """Coefficiente correttivo T_marcia per (istanza, livello). Default 1.0."""
    try:
        data = _refresh_if_stale()
        key = f"{istanza}|{livello}"
        return float((data.get("coefs") or {}).get(key, 1.0))
    except Exception:
        return 1.0


def get_calibration_info() -> dict:
    """Per dashboard / debug."""
    return _refresh_if_stale() or {}


def invalidate_cache() -> None:
    with _cache_lock:
        _cache["ts"] = 0.0
        _cache["data"] = None


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Test T_marcia calibration.")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_c = sub.add_parser("compute")
    p_c.add_argument("--window", type=int, default=WINDOW_RECORDS)
    sub.add_parser("show")
    p_g = sub.add_parser("coef")
    p_g.add_argument("--ist", required=True)
    p_g.add_argument("--lv", type=int, required=True)

    args = p.parse_args()
    if args.cmd == "compute":
        data = compute_calibration(window=args.window)
        save_calibration(data)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif args.cmd == "show":
        print(json.dumps(load_calibration() or {"error": "no calib"},
                         indent=2, ensure_ascii=False))
    elif args.cmd == "coef":
        print(get_calibration_coef(args.ist, args.lv))
