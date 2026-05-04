"""Backtest empirico Skip Predictor — modello "squadre fuori" raffinato.

Ricostruisce decisioni skip su dati storici `data/istanza_metrics.jsonl` usando
il modello empirico:

    T_marcia_i = 2 × eta_marcia_i + saturazione_i × T_L_max[livello_i, istanza]

    saturazione_i = load_squadra_i / cap_nominale_L_max[livello_i]

    SE attive_post[last_tick] = totali (slot saturi al rientro precedente)
       AND T_min_rientro = min(T_marcia_i) > gap_to_next_tick
    THEN predicted_skip = True

Quindi confronta con ground truth `attive_pre[next_tick] = totali` per
calcolare precision/recall.

VINCOLI:
  - Salta record post-restart bot (gap >30 min con record precedente stessa
    istanza) — cronologia stale durante stop.
  - Salta record con load_squadra=-1 (pre-WU116) — saturazione non calcolabile.
  - Salta record di istanze master (esclusa per design).

Uso:
    python tools/predictor_backtest.py [--prod] [--days N] [--istanza X]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Capacità nominale per (tipo, livello) — da reference_capacita_nodi.md
CAP_NOMINALE = {
    ("campo", 6):    1_200_000,
    ("campo", 7):    1_320_000,
    ("segheria", 6): 1_200_000,
    ("segheria", 7): 1_320_000,
    ("acciaio", 6):    600_000,
    ("acciaio", 7):    660_000,
    ("petrolio", 6):   240_000,
    ("petrolio", 7):   264_000,
}

# Master istanze (escluse per design dal predictor)
MASTERS = {"FauMorfeus"}

# Soglia gap per detectare restart bot (oltre questa = post-stop, history stale).
# Gap normale tick consecutivi stessa istanza ≈ 120min (12 istanze × 10min + sleep).
# Restart = gap molto maggiore. 4h = soglia conservativa.
RESTART_GAP_MIN = 240


def load_t_l_max_config(root: Path) -> dict:
    """Carica config/predictor_t_l_max.json. Fallback a default conservativi."""
    path = root / "config" / "predictor_t_l_max.json"
    if not path.exists():
        return {
            "_default_per_livello":   {"5": 100, "6": 114, "7": 125},
            "_multiplier_per_istanza": {"_default": 1.3, "FAU_00": 1.0, "FauMorfeus": 1.0},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def get_t_l_max(cfg: dict, istanza: str, livello: int) -> float:
    """T_L_max[livello, istanza] in minuti. Fallback a default 30min su mismatch."""
    base = cfg.get("_default_per_livello", {}).get(str(livello))
    if base is None:
        return 30.0
    mult = cfg.get("_multiplier_per_istanza", {}).get(
        istanza,
        cfg.get("_multiplier_per_istanza", {}).get("_default", 1.3),
    )
    return float(base) * float(mult)


def saturazione(load_squadra: int, livello: int, tipo: str) -> Optional[float]:
    """Calcola saturazione = load / cap_nominale_L_max. None se mancano dati."""
    if load_squadra is None or load_squadra <= 0:
        return None
    cap = CAP_NOMINALE.get((tipo, livello))
    if cap is None or cap <= 0:
        return None
    return min(1.0, load_squadra / cap)   # clamp a 1.0 (saturazione max)


def calc_t_marcia(invio: dict, t_l_max_cfg: dict, istanza: str) -> Optional[float]:
    """
    T_marcia totale stimato in minuti per un singolo invio.
    Ritorna None se dati insufficienti.

    T_marcia = 2 × eta_marcia_min + sat × T_L_max[livello, istanza]
    """
    livello = int(invio.get("livello", -1))
    tipo    = invio.get("tipo", "")
    load    = int(invio.get("load_squadra", -1))
    eta     = int(invio.get("eta_marcia_s", 0)) / 60.0  # sec → min

    if livello < 1:
        return None
    sat = saturazione(load, livello, tipo)
    if sat is None:
        return None

    t_l_max = get_t_l_max(t_l_max_cfg, istanza, livello)
    return 2 * eta + sat * t_l_max


def is_post_restart(curr_ts: str, prev_ts: Optional[str]) -> bool:
    """True se gap tra curr e prev > RESTART_GAP_MIN (history stale)."""
    if prev_ts is None:
        return True
    try:
        c = datetime.fromisoformat(curr_ts)
        p = datetime.fromisoformat(prev_ts)
        return (c - p).total_seconds() / 60 > RESTART_GAP_MIN
    except Exception:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true", help="Usa C:/doomsday-engine-prod")
    parser.add_argument("--days", type=int, default=7, help="Solo ultimi N giorni")
    parser.add_argument("--istanza", type=str, default="", help="Filtra per istanza")
    parser.add_argument("--verbose", action="store_true", help="Stampa ogni decisione")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    metrics_path = root / "data" / "istanza_metrics.jsonl"
    if not metrics_path.exists():
        print(f"Dataset non trovato: {metrics_path}")
        return 1

    cfg_t_l_max = load_t_l_max_config(root)
    print(f"Config T_L_max caricato (default L7={cfg_t_l_max.get('_default_per_livello',{}).get('7','?')} min)")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days > 0 else None

    # Carica + filtra + raggruppa per istanza
    by_inst: dict[str, list] = defaultdict(list)
    n_total = n_filtered = 0
    with metrics_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n_total += 1
            inst = r.get("instance", "")
            if not inst or inst in MASTERS:
                continue
            if args.istanza and inst != args.istanza:
                continue
            ts = r.get("ts", "")
            if cutoff and ts:
                try:
                    if datetime.fromisoformat(ts) < cutoff:
                        continue
                except Exception:
                    continue
            by_inst[inst].append(r)
            n_filtered += 1

    print(f"\nRecord totali: {n_total}, dopo filtri: {n_filtered}, istanze: {len(by_inst)}")

    # Analisi per istanza
    stats_global = {"tp": 0, "fp": 0, "fn": 0, "tn": 0,
                    "skipped_warmup": 0, "skipped_no_load": 0, "evaluated": 0}
    stats_per_inst: dict[str, dict] = {}

    for inst in sorted(by_inst.keys()):
        records = sorted(by_inst[inst], key=lambda r: r.get("ts", ""))
        s = {"tp": 0, "fp": 0, "fn": 0, "tn": 0,
             "skipped_warmup": 0, "skipped_no_load": 0, "evaluated": 0,
             "skip_candidates": []}

        for i in range(len(records) - 1):  # serve next per ground truth
            curr = records[i]
            nxt  = records[i + 1]
            prev_ts = records[i - 1]["ts"] if i > 0 else None

            # Salta post-restart
            if is_post_restart(curr["ts"], prev_ts):
                s["skipped_warmup"] += 1
                continue

            rac = curr.get("raccolta", {}) or {}
            invii = rac.get("invii", []) or []
            if not invii:
                continue   # niente invii → niente da valutare

            attive_post = rac.get("attive_post", -1)
            totali      = rac.get("totali", 4)

            # Verifica load_squadra valorizzato per almeno un invio
            t_marce = []
            for inv in invii:
                t = calc_t_marcia(inv, cfg_t_l_max, inst)
                if t is not None:
                    t_marce.append(t)
            if not t_marce:
                s["skipped_no_load"] += 1
                continue   # tutti pre-WU116, no load_squadra

            t_min_rientro = min(t_marce)

            # Gap to next tick (in minuti)
            try:
                c_dt = datetime.fromisoformat(curr["ts"])
                n_dt = datetime.fromisoformat(nxt["ts"])
                gap_min = (n_dt - c_dt).total_seconds() / 60
            except Exception:
                continue

            # Predizione: skip SE slot saturi at last AND squadre ancora fuori
            slot_saturi_now = (attive_post >= 0 and attive_post >= totali)
            predicted_skip = slot_saturi_now and (t_min_rientro > gap_min)

            # Ground truth: slot saturi all'inizio del tick successivo
            nxt_rac = (nxt.get("raccolta") or {})
            attive_pre_next = nxt_rac.get("attive_pre", -1)
            totali_next     = nxt_rac.get("totali", totali)
            actual_slots_full = (attive_pre_next >= 0 and attive_pre_next >= totali_next)

            s["evaluated"] += 1

            if predicted_skip and actual_slots_full:
                s["tp"] += 1
                s["skip_candidates"].append({
                    "ts": curr["ts"][:19], "n_invii": len(invii),
                    "t_min_rientro": round(t_min_rientro, 1),
                    "gap_min": round(gap_min, 1),
                })
            elif predicted_skip and not actual_slots_full:
                s["fp"] += 1
            elif not predicted_skip and actual_slots_full:
                s["fn"] += 1
            else:
                s["tn"] += 1

            if args.verbose:
                tag = "TP" if predicted_skip and actual_slots_full else \
                      "FP" if predicted_skip else \
                      "FN" if actual_slots_full else "TN"
                print(f"  [{tag}] {inst} {curr['ts'][:16]} pred={predicted_skip} "
                      f"actual={actual_slots_full} t_min={t_min_rientro:.0f}min "
                      f"gap={gap_min:.0f}min")

        stats_per_inst[inst] = s
        for k in ("tp", "fp", "fn", "tn", "skipped_warmup", "skipped_no_load", "evaluated"):
            stats_global[k] += s[k]

    # Output
    print("\n" + "=" * 75)
    print("BACKTEST PREDICTOR — risultati per istanza")
    print("=" * 75)
    print(f'{"istanza":<14} {"eval":>5} {"TP":>4} {"FP":>4} {"FN":>4} {"TN":>4} '
          f'{"prec%":>6} {"rec%":>6} {"warmup":>7} {"no_load":>8}')
    for inst in sorted(stats_per_inst.keys()):
        s = stats_per_inst[inst]
        prec = 100 * s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) > 0 else 0
        rec  = 100 * s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) > 0 else 0
        print(f'{inst:<14} {s["evaluated"]:>5} {s["tp"]:>4} {s["fp"]:>4} {s["fn"]:>4} {s["tn"]:>4} '
              f'{prec:>5.1f}% {rec:>5.1f}% {s["skipped_warmup"]:>7} {s["skipped_no_load"]:>8}')

    g = stats_global
    g_prec = 100 * g["tp"] / (g["tp"] + g["fp"]) if (g["tp"] + g["fp"]) > 0 else 0
    g_rec  = 100 * g["tp"] / (g["tp"] + g["fn"]) if (g["tp"] + g["fn"]) > 0 else 0
    print("-" * 75)
    print(f'{"TOTALE":<14} {g["evaluated"]:>5} {g["tp"]:>4} {g["fp"]:>4} {g["fn"]:>4} {g["tn"]:>4} '
          f'{g_prec:>5.1f}% {g_rec:>5.1f}% {g["skipped_warmup"]:>7} {g["skipped_no_load"]:>8}')
    print()
    print(f"Skip suggeriti totali: {g['tp'] + g['fp']}")
    print(f"  veri positivi (TP): {g['tp']}  ← skip giusti, evitano cicli sterili")
    print(f"  falsi positivi (FP): {g['fp']}  ← skip non necessari (errori)")
    print(f"Skip mancati (FN):     {g['fn']}  ← cicli sterili NON intercettati")
    print(f"Saving stimato: {g['tp']} cicli × ~600s = {(g['tp'] * 600 / 60):.1f} min totali risparmiati")
    print()
    print(f"Record skippati dal backtest:")
    print(f"  warmup post-restart:   {g['skipped_warmup']}")
    print(f"  no load_squadra (pre-WU116): {g['skipped_no_load']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
