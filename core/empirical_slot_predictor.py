"""core/empirical_slot_predictor.py — lookup empirico slot_liberi vs gap.

Source: `data/istanza_metrics.jsonl` (coppie consecutive di record per istanza).
Per ogni coppia (N, N+1):
    gap_min     = ts(N+1) - ts(N)
    slot_liberi = totali - attive_pre(N+1)

Espone `lookup_slot_liberi(istanza, gap_min)` che ritorna mediana/p25/p75/n_samples
del bucket appropriato. Usato dall'adaptive scheduler (proposta A 08/05) per
blendare la stima deterministica T_marcia con la realtà empirica osservata.

Bucket: <60, 60-90, 90-120, >120 min (stessi del pannello dashboard).

Cache TTL 60s per evitare ricalcolo della scansione JSONL ad ogni `compute_slot_liberi_atteso`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

_log = logging.getLogger(__name__)

# Bucket (lo, hi) in minuti — coerenti col pannello dashboard
BUCKETS: list[tuple[int, int]] = [
    (0, 60), (60, 90), (90, 120), (120, 99999),
]

CACHE_TTL_S = 60


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _metrics_path() -> Path:
    return _root() / "data" / "istanza_metrics.jsonl"


# ─── Cache ──────────────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "data": None}


def _bucket_idx(gap_min: float) -> Optional[int]:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= gap_min < hi:
            return i
    return None


def _build_lookup() -> dict:
    """Scansiona JSONL e costruisce dict {istanza: {bucket_idx: [slot_liberi, ...]}}.

    Returns:
        {
          "per_inst":      {ist: {bucket_idx: list[int]}},
          "max_squadre":   {ist: int},
          "n_samples_tot": int,
          "ts_built":      float (epoch),
        }
    """
    p = _metrics_path()
    out_per_inst: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    out_max_sq: dict[str, int] = {}

    if not p.exists():
        return {"per_inst": {}, "max_squadre": {}, "n_samples_tot": 0,
                "ts_built": time.time()}

    raw_by_inst: dict[str, list[dict]] = defaultdict(list)
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    raw_by_inst[r.get("instance", "?")].append(r)
                except Exception:
                    continue
    except Exception as exc:
        _log.warning("[EMP-SLOT] read failed: %s", exc)
        return {"per_inst": {}, "max_squadre": {}, "n_samples_tot": 0,
                "ts_built": time.time()}

    n_total = 0
    for inst, records in raw_by_inst.items():
        records.sort(key=lambda r: r.get("ts", ""))
        for i in range(1, len(records)):
            r = records[i]
            prev = records[i - 1]
            rac = r.get("raccolta") or {}
            attive_pre = rac.get("attive_pre")
            tot = int(rac.get("totali", 0) or 0)
            if attive_pre is None or tot <= 0:
                continue
            try:
                t_curr = datetime.fromisoformat(r["ts"])
                t_prev = datetime.fromisoformat(prev["ts"])
                gap_min = (t_curr - t_prev).total_seconds() / 60.0
            except Exception:
                continue
            if gap_min < 1:
                continue
            bi = _bucket_idx(gap_min)
            if bi is None:
                continue
            slot_liberi = max(0, tot - int(attive_pre))
            out_per_inst[inst][bi].append(slot_liberi)
            out_max_sq[inst] = max(out_max_sq.get(inst, 0), tot)
            n_total += 1

    return {
        "per_inst":      {k: dict(v) for k, v in out_per_inst.items()},
        "max_squadre":   out_max_sq,
        "n_samples_tot": n_total,
        "ts_built":      time.time(),
    }


def _get_lookup() -> dict:
    """Restituisce la lookup table cached, ricostruita se TTL scaduto."""
    with _cache_lock:
        now = time.time()
        if _cache.get("data") is None or now - _cache.get("ts", 0) > CACHE_TTL_S:
            _cache["data"] = _build_lookup()
            _cache["ts"] = now
        return _cache["data"]


def invalidate_cache() -> None:
    """Forza ricalcolo al prossimo `lookup_slot_liberi`. Utile per test."""
    with _cache_lock:
        _cache["data"] = None
        _cache["ts"] = 0.0


# ─── API principale ─────────────────────────────────────────────────────────

def lookup_slot_liberi(istanza: str, gap_min: float) -> Optional[dict]:
    """Lookup empirico slot liberi attesi per istanza al gap dato.

    Args:
        istanza: nome (es. "FAU_05")
        gap_min: minuti dall'ultimo passaggio (= elapsed_min + t_offset_greedy)

    Returns:
        {
          "n_samples":   int,    # campioni nel bucket
          "mean":        float,
          "median":      float,
          "p25":         float,
          "p75":         float,
          "max_squadre": int,
          "bucket_idx":  int,
          "bucket_label": str,
        }
        oppure None se nessun sample per quel bucket/istanza.
    """
    bi = _bucket_idx(gap_min)
    if bi is None:
        return None
    lookup = _get_lookup()
    per_inst = lookup.get("per_inst") or {}
    samples = (per_inst.get(istanza) or {}).get(bi) or []
    if not samples:
        return None
    samples_sorted = sorted(samples)
    n = len(samples_sorted)

    def _percentile(p: float) -> float:
        if n == 0:
            return 0.0
        idx = int(round(p * (n - 1)))
        return float(samples_sorted[max(0, min(n - 1, idx))])

    lo, hi = BUCKETS[bi]
    label = f"{lo}-{hi}" if hi < 99999 else f">{lo}"

    return {
        "n_samples":    n,
        "mean":         sum(samples_sorted) / n,
        "median":       float(median(samples_sorted)),
        "p25":          _percentile(0.25),
        "p75":          _percentile(0.75),
        "max_squadre":  int(lookup.get("max_squadre", {}).get(istanza, 0) or 0),
        "bucket_idx":   bi,
        "bucket_label": label,
    }


def get_lookup_summary() -> dict:
    """Per dashboard / debug: stato corrente lookup table."""
    lookup = _get_lookup()
    per_inst = lookup.get("per_inst") or {}
    inst_counts: dict[str, int] = {}
    for ist, by_bucket in per_inst.items():
        inst_counts[ist] = sum(len(v) for v in by_bucket.values())
    return {
        "n_samples_tot": int(lookup.get("n_samples_tot", 0)),
        "n_istanze":     len(per_inst),
        "ts_built_iso":  datetime.fromtimestamp(lookup.get("ts_built", 0)).isoformat(timespec="seconds"),
        "samples_per_istanza": inst_counts,
    }


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Empirical slot lookup test.")
    p.add_argument("--ist", default="FAU_05")
    p.add_argument("--gap", type=float, default=60)
    p.add_argument("--summary", action="store_true")
    args = p.parse_args()

    if args.summary:
        s = get_lookup_summary()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        res = lookup_slot_liberi(args.ist, args.gap)
        if res is None:
            print(f"no samples for {args.ist} @ gap={args.gap}min")
        else:
            print(json.dumps(res, indent=2, ensure_ascii=False))
