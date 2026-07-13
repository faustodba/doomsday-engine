"""tools/predictor_backtest_empirico.py — Backtest STATICO vs EMPIRICO del
modello T_marcia contro il ground truth reale (slot liberi osservati).

WU202 (12-13/07). Per ogni arrivo del bot su un'istanza (record N+1 in
`data/istanza_metrics.jsonl`), ricostruisce quanti slot liberi il modello
avrebbe predetto usando i raccoglitori inviati al record N, con DUE modelli:
  - STATICO   : core.skip_predictor._calc_t_marcia_static (formula nominale)
  - EMPIRICO  : shared.tempo_raccolta_estimator.stima_tempo_raccolta (durata
                reale invio→completamento + eta), fallback allo statico se la
                cella (istanza,tipo,livello) non ha abbastanza campioni.
E li confronta con gli slot liberi REALI osservati (`attive_pre` da OCR
all'arrivo). Metrica: MAE (errore medio in slot) + % match esatto + bias.

THREAD-SAFE: NON usa il flag globale né monkeypatch (calcola le due stime
esplicitamente) → si può eseguire dal processo dashboard mentre lo scheduler
live gira.

VINCOLO look-ahead: l'empirico ha dati solo da `--empirical-start`. Un
confronto pulito (senza look-ahead) è valido solo su arrivi >= quella data.
Per questo `run_backtest` riporta separatamente:
  - "all"         : tutte le coppie (con look-ahead, solo riferimento)
  - "recent"      : arrivi >= empirical_start (finestra pulita, metrica decisione)
  - "recent_flip" : recent DOVE l'empirico cambia davvero la decisione (~5%)

Uso CLI:
    py -3.14 -m tools.predictor_backtest_empirico [--empirical-start YYYY-MM-DD]
                                                  [--gap-min N] [--gap-max N] [--json]
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _root(root: Optional[str] = None) -> Path:
    if root:
        return Path(root)
    env = os.environ.get("DOOMSDAY_ROOT")
    return Path(env) if env else Path.cwd()


def _load_rows(root: Path) -> list[dict]:
    p = root / "data" / "istanza_metrics.jsonl"
    rows: list[dict] = []
    if not p.exists():
        return rows
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def _ts(r: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(r["ts"])
    except Exception:
        return None


def _rientri(invii, ist, arrival, tstart, empirico: bool) -> int:
    """Squadre rientrate entro `arrival`. `empirico=True` usa la stima empirica
    (fallback statico se cella scarna); False usa solo la statica. Deterministico,
    nessun flag globale."""
    from core.skip_predictor import _calc_t_marcia_static
    if empirico:
        from shared.tempo_raccolta_estimator import stima_tempo_raccolta
    n = 0
    for inv in invii:
        t = _calc_t_marcia_static(inv, ist)   # minuti (None se dati insuff.)
        if empirico:
            tipo, lv = inv.get("tipo"), inv.get("livello")
            if tipo and lv is not None:
                s = stima_tempo_raccolta(ist, tipo, int(lv))
                if s is not None:
                    eta_min = int(inv.get("eta_marcia_s", 0) or 0) / 60.0
                    t = s / 60.0 + eta_min
        if t is None:
            continue
        tsi = inv.get("ts_invio")
        try:
            dep = datetime.fromisoformat(tsi) if tsi else tstart
        except Exception:
            dep = tstart
        elapsed = (arrival - dep).total_seconds() / 60.0
        if t <= elapsed:
            n += 1
    return n


def _metrics(errs: list[float]) -> dict:
    n = len(errs)
    if n == 0:
        return {"n": 0, "mae": None, "bias": None,
                "match_pct": None, "over_pct": None, "under_pct": None}
    return {
        "n": n,
        "mae":  round(sum(abs(e) for e in errs) / n, 3),
        "bias": round(sum(errs) / n, 3),
        "match_pct": round(sum(1 for e in errs if e == 0) / n * 100, 1),
        "over_pct":  round(sum(1 for e in errs if e > 0) / n * 100, 1),
        "under_pct": round(sum(1 for e in errs if e < 0) / n * 100, 1),
    }


def run_backtest(root: Optional[str] = None, gap_min: float = 30.0,
                 gap_max: float = 300.0,
                 empirical_start: str = "2026-07-11") -> dict:
    """Esegue il backtest. Ritorna un dict serializzabile con le metriche
    (all / recent / recent_flip) per statico ed empirico."""
    base = _root(root)
    try:
        start_dt = datetime.fromisoformat(empirical_start).replace(tzinfo=timezone.utc)
    except Exception:
        start_dt = datetime(2026, 7, 11, tzinfo=timezone.utc)

    rows = _load_rows(base)
    seq: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("instance"):
            seq.setdefault(r["instance"], []).append(r)

    e_all = {"static": [], "emp": []}
    e_rec = {"static": [], "emp": []}
    e_flip = {"static": [], "emp": []}

    for ist, rs in seq.items():
        rs = [x for x in rs if _ts(x)]
        rs.sort(key=_ts)
        for a, b in zip(rs, rs[1:]):
            ra, rb = a.get("raccolta") or {}, b.get("raccolta") or {}
            invii = ra.get("invii") or []
            ap_post, tot = ra.get("attive_post"), ra.get("totali")
            pre_next, tot_next = rb.get("attive_pre"), rb.get("totali")
            if (not invii or ap_post is None or tot is None
                    or pre_next is None or tot_next is None):
                continue
            gap = (_ts(b) - _ts(a)).total_seconds() / 60.0
            if gap < gap_min or gap > gap_max:
                continue
            arrival, tstart = _ts(b), _ts(a)

            r_s = min(_rientri(invii, ist, arrival, tstart, False), int(ap_post))
            r_e = min(_rientri(invii, ist, arrival, tstart, True), int(ap_post))
            real_free = int(tot_next) - int(pre_next)
            es = (int(tot) - int(ap_post) + r_s) - real_free
            ee = (int(tot) - int(ap_post) + r_e) - real_free

            e_all["static"].append(es)
            e_all["emp"].append(ee)
            if arrival >= start_dt:
                e_rec["static"].append(es)
                e_rec["emp"].append(ee)
                if r_e != r_s:
                    e_flip["static"].append(es)
                    e_flip["emp"].append(ee)

    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "empirical_start": empirical_start,
        "gap_min": gap_min, "gap_max": gap_max,
        "all":         {"static": _metrics(e_all["static"]),  "emp": _metrics(e_all["emp"])},
        "recent":      {"static": _metrics(e_rec["static"]),  "emp": _metrics(e_rec["emp"])},
        "recent_flip": {"static": _metrics(e_flip["static"]), "emp": _metrics(e_flip["emp"])},
    }


def _verdict(rec: dict) -> str:
    s, e = rec["static"].get("mae"), rec["emp"].get("mae")
    n = rec["static"].get("n") or 0
    if s is None or e is None or n == 0:
        return "n/d (nessuna coppia)"
    if n < 150:
        base = f"n={n} INSUFFICIENTE (serve >=150 per decidere)"
    else:
        base = f"n={n} sufficiente"
    if s == 0:
        return base
    delta = (s - e) / s * 100
    verso = "empirico MEGLIO" if delta > 0 else ("statico MEGLIO" if delta < 0 else "pari")
    return f"{base} · MAE stat={s} emp={e} ({delta:+.1f}% -> {verso})"


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Backtest statico vs empirico T_marcia.")
    p.add_argument("--empirical-start", default="2026-07-11")
    p.add_argument("--gap-min", type=float, default=30.0)
    p.add_argument("--gap-max", type=float, default=300.0)
    p.add_argument("--json", action="store_true", help="output JSON grezzo")
    args = p.parse_args()

    res = run_backtest(gap_min=args.gap_min, gap_max=args.gap_max,
                       empirical_start=args.empirical_start)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    def _row(name, m):
        if m.get("n"):
            print(f"    {name:9s} n={m['n']:5d}  MAE={m['mae']:.3f}  match={m['match_pct']:.1f}%  "
                  f"bias={m['bias']:+.3f}")
        else:
            print(f"    {name:9s} n=0")

    print(f"backtest empirico (start={res['empirical_start']}, gap {args.gap_min:.0f}-{args.gap_max:.0f}min)")
    for sez in ("all", "recent", "recent_flip"):
        print(f"  [{sez}]")
        _row("statico", res[sez]["static"])
        _row("empirico", res[sez]["emp"])
    print(f"\n  VERDETTO (finestra pulita 'recent'): {_verdict(res['recent'])}")


if __name__ == "__main__":
    main()
