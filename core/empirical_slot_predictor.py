"""core/empirical_slot_predictor.py — lookup empirico slot_liberi vs gap.

Source: `data/istanza_metrics.jsonl` (coppie consecutive di record per istanza).
Per ogni coppia (N, N+1):
    gap_min     = ts(N+1) - ts(N)
    slot_liberi = totali - attive_pre(N+1)

Espone `lookup_slot_liberi(istanza, gap_min)` che ritorna mediana/p25/p75/n_samples
del bucket appropriato. Usato dall'adaptive scheduler (proposta A 08/05) per
blendare la stima deterministica T_marcia con la realtà empirica osservata.

Bucket: <60, 60-90, 90-120, 120-150, 150-180, 180-240, >240 min (stessi del
pannello dashboard `/ui/partial/predictor-slot-distribuzione`, che consuma
questo modulo tramite `get_full_lookup()`/`bucket_labels()` — nessuna copia
locale dei bucket, per evitare il disallineamento osservato il 05/07 quando
il commento "il ciclo bot raramente supera 2-3h" (vero l'8/05) non rifletteva
più i cicli reali da 150-220min osservati con l'adaptive scheduler LIVE).

WU — finestra mobile 05/07: la lookup non aveva MAI un limite temporale,
scansionava l'intero storico (fino a 59 giorni) mescolando regimi radicalmente
diversi (switch raccolta_fast→full del 09/05, crescita truppe/livelli). Ora
limitata a `WINDOW_DAYS` giorni più recenti. Soglia minima `MIN_SAMPLES`
campioni per bucket, sotto la quale il lookup ritorna None (niente blend,
resta il valore deterministico) invece di usare una mediana costruita su un
singolo campione rumoroso.

Cache TTL 60s per evitare ricalcolo della scansione JSONL ad ogni `compute_slot_liberi_atteso`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Optional

_log = logging.getLogger(__name__)

# Bucket (lo, hi) in minuti — coerenti col pannello dashboard (letti da lì
# via `bucket_labels()`, mai duplicati).
BUCKETS: list[tuple[int, int]] = [
    (0, 60), (60, 90), (90, 120), (120, 150), (150, 180), (180, 240), (240, 99999),
]

WINDOW_DAYS  = 14   # solo record più recenti di N giorni — esclude regimi datati
MIN_SAMPLES  = 5    # sotto questa soglia il bucket è troppo rumoroso per un blend

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


def bucket_label(bucket_idx: int) -> str:
    """Etichetta leggibile per un bucket (es. '120-150', '>240')."""
    lo, hi = BUCKETS[bucket_idx]
    return f"{lo}-{hi}" if hi < 99999 else f">{lo}"


def bucket_labels() -> list[str]:
    """Etichette di tutti i bucket, nell'ordine — usate da `core` e dashboard
    per evitare una lista hardcoded duplicata (vedi nota di modulo)."""
    return [bucket_label(i) for i in range(len(BUCKETS))]


def _build_lookup(window_days: float = WINDOW_DAYS) -> dict:
    """Scansiona JSONL e costruisce dict {istanza: {bucket_idx: [slot_liberi, ...]}}.

    Solo i record con `ts` più recente di `window_days` giorni entrano nel
    lookup (esclude regimi datati — vedi nota di modulo).

    Returns:
        {
          "per_inst":      {ist: {bucket_idx: list[int]}},
          "max_squadre":   {ist: int},
          "n_samples_tot": int,
          "ts_built":      float (epoch),
          "window_days":   float,
        }
    """
    p = _metrics_path()
    out_per_inst: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    out_max_sq: dict[str, int] = {}

    if not p.exists():
        return {"per_inst": {}, "max_squadre": {}, "n_samples_tot": 0,
                "ts_built": time.time(), "window_days": window_days}

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
                "ts_built": time.time(), "window_days": window_days}

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

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
            if t_curr < cutoff:
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
        "window_days":   window_days,
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


def get_full_lookup() -> dict:
    """Espone la lookup table completa (cached) per consumer esterni al
    modulo — es. il pannello dashboard `/ui/partial/predictor-slot-distribuzione`,
    che prima manteneva una propria copia della scansione JSONL (bucket e
    finestra temporale potevano disallinearsi da questo modulo, come successo
    il 05/07). Stessa shape di `_build_lookup()`.
    """
    return _get_lookup()


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
        oppure None se nessun sample per quel bucket/istanza, o se sotto
        `MIN_SAMPLES` (bucket troppo rumoroso per un blend affidabile).
    """
    bi = _bucket_idx(gap_min)
    if bi is None:
        return None
    lookup = _get_lookup()
    per_inst = lookup.get("per_inst") or {}
    samples = (per_inst.get(istanza) or {}).get(bi) or []
    if len(samples) < MIN_SAMPLES:
        return None
    samples_sorted = sorted(samples)
    n = len(samples_sorted)

    def _percentile(p: float) -> float:
        if n == 0:
            return 0.0
        idx = int(round(p * (n - 1)))
        return float(samples_sorted[max(0, min(n - 1, idx))])

    return {
        "n_samples":    n,
        "mean":         sum(samples_sorted) / n,
        "median":       float(median(samples_sorted)),
        "p25":          _percentile(0.25),
        "p75":          _percentile(0.75),
        "max_squadre":  int(lookup.get("max_squadre", {}).get(istanza, 0) or 0),
        "bucket_idx":   bi,
        "bucket_label": bucket_label(bi),
    }


def lookup_p_saturo_globale(istanza: str) -> Optional[float]:
    """Frazione di sample storici con `slot_liberi==0` (saturo) per istanza,
    aggregata su tutti i bucket gap. Usato come tie-breaker nel greedy
    (proposta C 08/05): a parità di score, preferire istanze con bassa
    P_saturo storica.

    Returns:
        float in [0.0, 1.0], oppure None se nessun sample per quell'istanza.
    """
    lookup = _get_lookup()
    per_inst = (lookup.get("per_inst") or {}).get(istanza, {})
    if not per_inst:
        return None
    all_samples: list[int] = []
    for bucket_samples in per_inst.values():
        all_samples.extend(bucket_samples)
    if not all_samples:
        return None
    n_saturo = sum(1 for s in all_samples if s == 0)
    return n_saturo / len(all_samples)


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
