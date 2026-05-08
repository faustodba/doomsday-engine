"""core/daily_report.py — builder daily report email.

STEP D del modulo Email Notifier (memoria `project_email_notifier.md`).

Scope: aggrega dati di una giornata (default ieri UTC) e produce
`{subj, body_text, body_html}` da passare a `enqueue_email`.

Sezioni del report:
  1. Header — data, totale cicli, % completati, durata media
  2. Produzione — totali 4 risorse + spedizioni rifornimento
  3. Cicli — totale, ok/cascade/abort
  4. Truppe — totale + delta da ieri
  5. Anomalie — count per task con success=False (top)
  6. Footer — ts generazione

Output:
    {
      "subj":      "[Doomsday] daily report 2026-05-07",
      "body_text": "...",
      "body_html": "...",
    }

Sources letti (best-effort, ogni sezione protetta da try/except):
  data/storico_farm.json                   (produzione + spedizioni)
  data/telemetry/cicli.json                (cicli completati)
  data/telemetry/events/events_YYYY-MM-DD.jsonl  (eventi task per anomalie)
  data/storico_truppe.json                 (delta truppe)

Non in scope:
  - Scheduler (Step E lo userà)
  - Config dashboard UI (Step F)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


# ─── Path helpers ──────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _read_json(rel: str) -> Optional[dict]:
    p = _root() / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("[REPORT] read %s fallita: %s", rel, exc)
        return None


def _read_jsonl(rel: str, limit: Optional[int] = None) -> list[dict]:
    p = _root() / rel
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
                if limit and len(out) >= limit:
                    break
    except Exception as exc:
        _log.warning("[REPORT] read %s fallita: %s", rel, exc)
    return out


# ─── Format helpers ────────────────────────────────────────────────────────

def _fmt_n(n: float | int) -> str:
    """Formatta numero con suffisso K/M (es. 1500000 → '1.50M')."""
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:.0f}"


def _fmt_dur_s(s: float) -> str:
    s = int(s or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


# ─── Sezione 1: Cicli ──────────────────────────────────────────────────────

def _section_cicli(date: str) -> dict:
    """Statistiche cicli completati nella giornata `date` (YYYY-MM-DD UTC)."""
    data = _read_json("data/telemetry/cicli.json") or {"cicli": []}
    cicli = data.get("cicli") or []

    in_day = [c for c in cicli if (c.get("start_ts") or "")[:10] == date]
    n_tot = len(in_day)
    n_ok = sum(1 for c in in_day if c.get("completato") is True)
    durs = [float(c.get("durata_s") or 0) for c in in_day if c.get("durata_s")]
    avg_dur = sum(durs) / len(durs) if durs else 0

    # Outcome aggregato per istanza nei cicli del giorno
    outcomes = {"ok": 0, "cascade": 0, "abort": 0, "fail": 0, "altro": 0}
    n_ist_ticks = 0
    for c in in_day:
        for _, ist_data in (c.get("istanze") or {}).items():
            n_ist_ticks += 1
            esito = (ist_data.get("esito") or "altro").lower()
            outcomes[esito if esito in outcomes else "altro"] += 1

    return {
        "n_tot":         n_tot,
        "n_ok":          n_ok,
        "n_ko":          n_tot - n_ok,
        "avg_dur_s":     avg_dur,
        "n_ist_ticks":   n_ist_ticks,
        "outcomes":      outcomes,
    }


# ─── Sezione 2: Produzione ─────────────────────────────────────────────────

_RISORSE_ORDER = ("pomodoro", "legno", "acciaio", "petrolio")
_RIS_EMOJI = {"pomodoro": "🍅", "legno": "🪵", "acciaio": "⚙", "petrolio": "🛢"}


def _section_produzione(date: str) -> dict:
    """Totali produzione + spedizioni dalla giornata."""
    data = _read_json("data/storico_farm.json") or {}
    day = data.get(date) or {}

    tot = {r: 0 for r in _RISORSE_ORDER}
    sped_tot = 0
    n_ist = 0
    per_ist = []
    for ist, vals in day.items():
        if not isinstance(vals, dict):
            continue
        n_ist += 1
        sped = int(vals.get("spedizioni") or 0)
        sped_tot += sped
        prod_ist = 0
        for r in _RISORSE_ORDER:
            v = int(vals.get(r) or 0)
            tot[r] += v
            prod_ist += v
        per_ist.append({"nome": ist, "tot": prod_ist, "sped": sped})

    per_ist.sort(key=lambda x: x["tot"], reverse=True)
    return {
        "totali":   tot,
        "sped_tot": sped_tot,
        "n_ist":    n_ist,
        "per_ist":  per_ist,
    }


# ─── Sezione 3: Truppe ─────────────────────────────────────────────────────

def _section_truppe(date: str) -> dict:
    """Total squads della giornata + delta vs ieri."""
    data = _read_json("data/storico_truppe.json") or {}
    tot_oggi = 0
    tot_ieri = 0
    n_ist = 0
    delta_per_ist = []
    for ist, hist in data.items():
        if not isinstance(hist, list):
            continue
        oggi_v = next((h.get("total_squads", 0) for h in hist if h.get("data") == date), None)
        if oggi_v is None:
            continue
        ieri_date = (datetime.fromisoformat(date) - timedelta(days=1)).strftime("%Y-%m-%d")
        ieri_v = next((h.get("total_squads", 0) for h in hist if h.get("data") == ieri_date), None)
        n_ist += 1
        tot_oggi += int(oggi_v)
        if ieri_v is not None:
            tot_ieri += int(ieri_v)
            delta_per_ist.append({
                "nome": ist, "oggi": int(oggi_v), "delta": int(oggi_v) - int(ieri_v),
            })

    delta_per_ist.sort(key=lambda x: x["delta"], reverse=True)
    return {
        "tot_oggi":      tot_oggi,
        "delta_giorno":  tot_oggi - tot_ieri,
        "n_ist":         n_ist,
        "delta_per_ist": delta_per_ist,
    }


# ─── Sezione 5: Trend produzione 7gg ───────────────────────────────────────

def _section_trend_7gg(date: str) -> dict:
    """Media produzione ultimi 7 giorni (date escluso) + %Δ vs date.

    Compara produzione totale del giorno target vs media settimanale.
    """
    data = _read_json("data/storico_farm.json") or {}
    today = data.get(date) or {}

    # Totali del giorno target
    today_tot = {r: 0 for r in _RISORSE_ORDER}
    today_sped = 0
    for ist, vals in today.items():
        if not isinstance(vals, dict):
            continue
        for r in _RISORSE_ORDER:
            today_tot[r] += int(vals.get(r) or 0)
        today_sped += int(vals.get("spedizioni") or 0)

    # 7 giorni precedenti (escluso oggi)
    base_dt = datetime.fromisoformat(date)
    prev_days: list[dict] = []
    for d in range(1, 8):
        dt = base_dt - timedelta(days=d)
        ds = dt.strftime("%Y-%m-%d")
        if ds in data and isinstance(data[ds], dict):
            prev_days.append(data[ds])

    # Media settimanale
    avg_tot = {r: 0.0 for r in _RISORSE_ORDER}
    avg_sped = 0.0
    if prev_days:
        for d in prev_days:
            for ist, vals in d.items():
                if not isinstance(vals, dict):
                    continue
                for r in _RISORSE_ORDER:
                    avg_tot[r] += int(vals.get(r) or 0)
                avg_sped += int(vals.get("spedizioni") or 0)
        n = len(prev_days)
        for r in _RISORSE_ORDER:
            avg_tot[r] /= n
        avg_sped /= n

    # Delta %
    delta_pct = {}
    for r in _RISORSE_ORDER:
        if avg_tot[r] > 0:
            delta_pct[r] = ((today_tot[r] - avg_tot[r]) / avg_tot[r]) * 100
        else:
            delta_pct[r] = 0.0
    sped_delta_pct = ((today_sped - avg_sped) / avg_sped * 100) if avg_sped > 0 else 0.0

    return {
        "n_days":         len(prev_days),
        "avg_tot":        avg_tot,
        "avg_sped":       avg_sped,
        "today_tot":      today_tot,
        "today_sped":     today_sped,
        "delta_pct":      delta_pct,
        "sped_delta_pct": sped_delta_pct,
    }


# ─── Sezione 6: Rifornimento dettaglio ─────────────────────────────────────

def _section_rifornimento(date: str) -> dict:
    """Spedizioni rifornimento del giorno: per istanza, tassa media,
    valore medio per spedizione."""
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)
    rif = [e for e in events if e.get("task") == "rifornimento" and e.get("success")]

    by_ist: dict[str, dict] = {}
    n_invii_totali = 0
    tasse: list[float] = []
    for e in rif:
        out = e.get("output") or {}
        n = int(out.get("spedizioni") or 0)
        if n <= 0:
            continue
        n_invii_totali += n
        ist = e.get("instance", "?")
        slot = by_ist.setdefault(ist, {"nome": ist, "n_invii": 0, "tasse": []})
        slot["n_invii"] += n
        t = out.get("tassa_pct_avg")
        if t is not None and t > 0:
            slot["tasse"].append(float(t))
            tasse.append(float(t))

    # Valore totale netto del giorno (dalla produzione storico_farm)
    farm = _read_json("data/storico_farm.json") or {}
    day = farm.get(date) or {}
    valore_totale_netto = 0
    for ist, vals in day.items():
        if not isinstance(vals, dict):
            continue
        for r in _RISORSE_ORDER:
            valore_totale_netto += int(vals.get(r) or 0)

    per_ist = sorted(by_ist.values(), key=lambda x: x["n_invii"], reverse=True)
    for r in per_ist:
        r["tassa_avg"] = (sum(r["tasse"]) / len(r["tasse"])) if r["tasse"] else 0
        r.pop("tasse")

    return {
        "n_invii_totali":       n_invii_totali,
        "n_istanze":            len(per_ist),
        "tassa_avg_giornaliera": (sum(tasse) / len(tasse)) if tasse else 0,
        "valore_medio_per_invio": (valore_totale_netto / n_invii_totali) if n_invii_totali else 0,
        "per_ist":              per_ist,
    }


# ─── Sezione 7: Performance task (tempi medi + boot home) ──────────────────

def _section_performance_task(date: str) -> dict:
    """Tempi medi per task + boot home medio per istanza.

    Source: events_YYYY-MM-DD.jsonl (task durations) + istanza_metrics.jsonl
    (boot_home_s filtrato per giorno).
    """
    # 1) Tempi task da events (filtra task con almeno 5 esecuzioni)
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)
    by_task: dict[str, list[float]] = {}
    for e in events:
        d = e.get("duration_s")
        if d is None or d <= 0:
            continue
        task = e.get("task", "?")
        by_task.setdefault(task, []).append(float(d))

    task_stats = []
    for task, vals in by_task.items():
        if len(vals) < 3:
            continue
        # IQR Tukey filter (k=1.5) per outliers
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        q1 = vals_sorted[n // 4] if n >= 4 else vals_sorted[0]
        q3 = vals_sorted[3 * n // 4] if n >= 4 else vals_sorted[-1]
        iqr = q3 - q1
        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr
        clean = [v for v in vals if lo <= v <= hi]
        if not clean:
            clean = vals
        avg = sum(clean) / len(clean)
        task_stats.append({
            "task":   task,
            "n":      len(vals),
            "avg_s":  avg,
            "max_s":  max(vals),
            "outliers": len(vals) - len(clean),
        })
    task_stats.sort(key=lambda x: x["avg_s"], reverse=True)

    # 2) Boot home da istanza_metrics
    metrics = _read_jsonl("data/istanza_metrics.jsonl")
    by_ist: dict[str, list[float]] = {}
    for r in metrics:
        ts = r.get("ts", "")
        if ts[:10] != date:
            continue
        bh = r.get("boot_home_s")
        if bh is None or bh <= 0:
            continue
        ist = r.get("instance", "?")
        by_ist.setdefault(ist, []).append(float(bh))
    boot_stats = []
    for ist, vals in by_ist.items():
        boot_stats.append({
            "nome":  ist,
            "n":     len(vals),
            "avg_s": sum(vals) / len(vals),
            "min_s": min(vals),
            "max_s": max(vals),
        })
    boot_stats.sort(key=lambda x: x["avg_s"], reverse=True)

    return {
        "task_stats":   task_stats,
        "boot_stats":   boot_stats,
    }


# ─── Sezione 8: Copertura squadre (WU116) ──────────────────────────────────

def _section_copertura_squadre(date: str) -> dict:
    """Per (istanza, tipo): saturazione media = load_squadra / capacita.

    Verdetti: ok ≥95%, marginale 75-94%, ⚠ underprovisioned <75%.
    """
    samples = _read_jsonl("data/cap_nodi_dataset.jsonl")
    by_ist_tipo: dict[tuple, list[float]] = {}
    for s in samples:
        if (s.get("ts") or "")[:10] != date:
            continue
        cap = s.get("capacita")
        load = s.get("load_squadra")
        if not cap or not load or cap <= 0 or load <= 0:
            continue
        ratio = float(load) / float(cap)
        if ratio > 1.5:   # outlier OCR
            continue
        ratio = min(ratio, 1.0)
        ist = s.get("instance", "?")
        tipo = s.get("tipo", "?")
        by_ist_tipo.setdefault((ist, tipo), []).append(ratio)

    rows = []
    for (ist, tipo), ratios in by_ist_tipo.items():
        avg = sum(ratios) / len(ratios)
        if avg >= 0.95:
            verdict = "ok"
        elif avg >= 0.75:
            verdict = "marginale"
        else:
            verdict = "underprov"
        rows.append({
            "ist": ist, "tipo": tipo, "n": len(ratios),
            "avg_pct": avg * 100, "verdict": verdict,
        })
    rows.sort(key=lambda x: (x["ist"], x["tipo"]))

    # Aggregato per istanza
    ist_avg: dict[str, list[float]] = {}
    for r in rows:
        ist_avg.setdefault(r["ist"], []).append(r["avg_pct"])
    ist_summary = sorted([
        {"ist": ist, "avg_pct": sum(v)/len(v), "n_tipi": len(v)}
        for ist, v in ist_avg.items()
    ], key=lambda x: x["avg_pct"])

    return {"rows": rows, "ist_summary": ist_summary}


# ─── Sezione 9: Eventi rilevanti ───────────────────────────────────────────

def _section_eventi_rilevanti(date: str) -> dict:
    """Cascade ADB, restart, maintenance period, master saturo da cicli.json."""
    cicli_data = _read_json("data/telemetry/cicli.json") or {"cicli": []}
    cicli = cicli_data.get("cicli") or []
    in_day = [c for c in cicli if (c.get("start_ts") or "")[:10] == date]

    cascade_events = []
    abort_events = []
    not_completed = []
    for c in in_day:
        if not c.get("completato"):
            not_completed.append({
                "numero": c.get("numero"),
                "start":  (c.get("start_ts") or "")[11:16],
            })
        for ist, dat in (c.get("istanze") or {}).items():
            esito = (dat.get("esito") or "").lower()
            if esito == "cascade":
                cascade_events.append({
                    "ist": ist,
                    "start": (dat.get("start_ts") or "")[11:16],
                    "ciclo": c.get("numero"),
                })
            elif esito == "abort":
                abort_events.append({
                    "ist": ist,
                    "start": (dat.get("start_ts") or "")[11:16],
                    "ciclo": c.get("numero"),
                })

    # Master saturo: cerca DRL=0 nei record morfeus_state (snapshot odierno)
    # o nei log eventi rifornimento con `daily_recv_limit=0` skip.
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)
    rif_skip_master = 0
    for e in events:
        if e.get("task") != "rifornimento":
            continue
        msg = (e.get("msg") or "").lower()
        if "master saturo" in msg or "daily_recv_limit=0" in msg:
            rif_skip_master += 1

    return {
        "cascade_events":   cascade_events,
        "abort_events":     abort_events,
        "not_completed":    not_completed,
        "rif_skip_master":  rif_skip_master,
        "total_cicli":      len(in_day),
    }


# ─── Sezione 4: Anomalie ───────────────────────────────────────────────────

def _section_anomalie(date: str) -> dict:
    """Aggrega eventi task con success=False / outcome non OK / anomalies."""
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)

    by_task_ist: dict[tuple[str, str], dict] = {}
    by_anomaly: dict[str, int] = {}
    n_total_evt = len(events)
    n_fail = 0
    for e in events:
        task = e.get("task", "?")
        inst = e.get("instance", "?")
        if not e.get("success", True):
            n_fail += 1
            k = (task, inst)
            slot = by_task_ist.setdefault(k, {"task": task, "inst": inst, "n": 0})
            slot["n"] += 1
        for a in (e.get("anomalies") or []):
            tag = str(a.get("type") if isinstance(a, dict) else a)
            by_anomaly[tag] = by_anomaly.get(tag, 0) + 1

    top_fail = sorted(by_task_ist.values(), key=lambda x: x["n"], reverse=True)[:5]
    top_anom = sorted(by_anomaly.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "n_events":   n_total_evt,
        "n_fail":     n_fail,
        "top_fail":   top_fail,
        "top_anom":   top_anom,
    }


# ─── Builder ───────────────────────────────────────────────────────────────

def build_daily_report(date: Optional[str] = None) -> dict:
    """Costruisce daily report per la data UTC indicata (default: ieri).

    Args:
        date: YYYY-MM-DD UTC. None = ieri UTC.

    Returns:
        {"subj": str, "body_text": str, "body_html": str, "date": str}
    """
    if date is None:
        ieri = datetime.now(timezone.utc) - timedelta(days=1)
        date = ieri.strftime("%Y-%m-%d")

    cicli = _section_cicli(date)
    prod = _section_produzione(date)
    trend = _section_trend_7gg(date)
    rifornim = _section_rifornimento(date)
    truppe = _section_truppe(date)
    perf = _section_performance_task(date)
    cop = _section_copertura_squadre(date)
    eventi = _section_eventi_rilevanti(date)
    anom = _section_anomalie(date)

    sections = {
        "cicli": cicli, "prod": prod, "trend": trend, "rifornim": rifornim,
        "truppe": truppe, "perf": perf, "cop": cop, "eventi": eventi,
        "anom": anom,
    }

    subj = f"[Doomsday] daily report {date}"
    body_text = _render_text(date, sections)
    body_html = _render_html(date, sections)
    return {
        "subj":      subj,
        "body_text": body_text,
        "body_html": body_html,
        "date":      date,
    }


# ─── Rendering text ────────────────────────────────────────────────────────

def _render_text(date: str, s: dict) -> str:
    cicli, prod, trend, rifornim = s["cicli"], s["prod"], s["trend"], s["rifornim"]
    truppe, perf, cop, eventi, anom = s["truppe"], s["perf"], s["cop"], s["eventi"], s["anom"]

    L: list[str] = []
    L.append(f"DAILY REPORT {date} (UTC)")
    L.append("=" * 50)
    L.append("")

    # 1. CICLI
    L.append("[CICLI]")
    L.append(f"  totale: {cicli['n_tot']} ({cicli['n_ok']} ok, {cicli['n_ko']} non completati)")
    L.append(f"  durata media: {_fmt_dur_s(cicli['avg_dur_s'])}")
    o = cicli["outcomes"]
    L.append(f"  istanza-ticks: {cicli['n_ist_ticks']} "
             f"({o['ok']} ok · {o['cascade']} cascade · {o['abort']} abort · "
             f"{o['fail']} fail · {o['altro']} altro)")
    L.append("")

    # 2. PRODUZIONE
    L.append("[PRODUZIONE]")
    for r in _RISORSE_ORDER:
        L.append(f"  {r:10s}: {_fmt_n(prod['totali'][r])}")
    L.append(f"  spedizioni rifornimento: {prod['sped_tot']} "
             f"({prod['n_ist']} istanze)")
    if prod["per_ist"]:
        L.append("  top istanze (totale 4 risorse):")
        for r in prod["per_ist"][:5]:
            L.append(f"    {r['nome']:12s} {_fmt_n(r['tot']):>8s}  sped={r['sped']}")
    L.append("")

    # 3. TREND 7gg
    L.append(f"[TREND 7gg] (media ultimi {trend['n_days']} giorni)")
    for r in _RISORSE_ORDER:
        avg = trend["avg_tot"][r]
        d = trend["delta_pct"][r]
        L.append(f"  {r:10s}: media {_fmt_n(avg):>8s} → oggi {d:+.1f}%")
    sd = trend["sped_delta_pct"]
    L.append(f"  spedizioni: media {trend['avg_sped']:.1f} → oggi {sd:+.1f}%")
    L.append("")

    # 4. RIFORNIMENTO
    L.append("[RIFORNIMENTO]")
    L.append(f"  totale invii: {rifornim['n_invii_totali']} "
             f"({rifornim['n_istanze']} istanze)")
    L.append(f"  tassa media giornaliera: {rifornim['tassa_avg_giornaliera']*100:.1f}%")
    L.append(f"  valore medio per invio: {_fmt_n(rifornim['valore_medio_per_invio'])}")
    if rifornim["per_ist"]:
        L.append("  per istanza:")
        for r in rifornim["per_ist"][:8]:
            L.append(f"    {r['nome']:12s} invii={r['n_invii']:>2}  "
                     f"tassa={r['tassa_avg']*100:.1f}%")
    L.append("")

    # 5. TRUPPE
    L.append("[TRUPPE]")
    delta_sign = "+" if truppe["delta_giorno"] >= 0 else ""
    L.append(f"  totale: {_fmt_n(truppe['tot_oggi'])} "
             f"({delta_sign}{_fmt_n(truppe['delta_giorno'])} vs ieri, "
             f"{truppe['n_ist']} istanze)")
    if truppe["delta_per_ist"]:
        L.append("  top crescita:")
        for r in truppe["delta_per_ist"][:3]:
            sign = "+" if r["delta"] >= 0 else ""
            L.append(f"    {r['nome']:12s} {sign}{_fmt_n(r['delta']):>8s}")
        if len(truppe["delta_per_ist"]) > 3:
            L.append("  bottom crescita:")
            for r in truppe["delta_per_ist"][-3:]:
                sign = "+" if r["delta"] >= 0 else ""
                L.append(f"    {r['nome']:12s} {sign}{_fmt_n(r['delta']):>8s}")
    L.append("")

    # 6. PERFORMANCE TASK
    L.append("[PERFORMANCE TASK] (top 5 per durata media, IQR-filtered)")
    for t in perf["task_stats"][:5]:
        L.append(f"  {t['task']:20s} avg={_fmt_dur_s(t['avg_s'])} "
                 f"max={_fmt_dur_s(t['max_s'])} (n={t['n']}, outliers={t['outliers']})")
    L.append("")

    # 7. BOOT HOME per istanza
    L.append("[BOOT HOME] (per istanza, ordinato desc per avg)")
    for b in perf["boot_stats"][:6]:
        L.append(f"  {b['nome']:12s} avg={_fmt_dur_s(b['avg_s'])} "
                 f"min={_fmt_dur_s(b['min_s'])} max={_fmt_dur_s(b['max_s'])} (n={b['n']})")
    L.append("")

    # 8. COPERTURA SQUADRE
    L.append("[COPERTURA SQUADRE] (load/capacita; <75% = squadra debole)")
    if cop["ist_summary"]:
        L.append("  per istanza (peggiori prima):")
        for r in cop["ist_summary"][:6]:
            tag = "✓" if r["avg_pct"] >= 95 else "·" if r["avg_pct"] >= 75 else "⚠"
            L.append(f"    {r['ist']:12s} {tag} {r['avg_pct']:5.1f}%  ({r['n_tipi']} tipi)")
    underprov = [r for r in cop["rows"] if r["verdict"] == "underprov"]
    if underprov:
        L.append("  ⚠ underprovisioned (load < 75% cap):")
        for r in underprov[:5]:
            L.append(f"    {r['ist']:12s} {r['tipo']:10s} {r['avg_pct']:.1f}% (n={r['n']})")
    L.append("")

    # 9. EVENTI RILEVANTI
    L.append("[EVENTI RILEVANTI]")
    n_anom_total = (len(eventi["cascade_events"]) + len(eventi["abort_events"]) +
                    len(eventi["not_completed"]))
    if n_anom_total == 0 and eventi["rif_skip_master"] == 0:
        L.append("  nessuna anomalia rilevante registrata")
    else:
        if eventi["cascade_events"]:
            L.append(f"  cascade ADB ({len(eventi['cascade_events'])}):")
            for e in eventi["cascade_events"][:5]:
                L.append(f"    ciclo#{e['ciclo']} {e['ist']} @ {e['start']}")
        if eventi["abort_events"]:
            L.append(f"  abort ({len(eventi['abort_events'])}):")
            for e in eventi["abort_events"][:5]:
                L.append(f"    ciclo#{e['ciclo']} {e['ist']} @ {e['start']}")
        if eventi["not_completed"]:
            L.append(f"  cicli non completati: {len(eventi['not_completed'])}")
        if eventi["rif_skip_master"]:
            L.append(f"  rifornimento skip master saturo: {eventi['rif_skip_master']} occorrenze")
    L.append("")

    # 10. ANOMALIE TASK
    L.append("[ANOMALIE TASK]")
    L.append(f"  task fail: {anom['n_fail']} / {anom['n_events']} eventi totali")
    if anom["top_fail"]:
        L.append("  top fail (task × istanza):")
        for f in anom["top_fail"]:
            L.append(f"    {f['task']:18s} {f['inst']:12s} n={f['n']}")
    if anom["top_anom"]:
        L.append("  anomalie ricorrenti:")
        for tag, n in anom["top_anom"]:
            L.append(f"    {tag:30s} n={n}")
    L.append("")

    L.append("-" * 50)
    L.append(f"generato: {datetime.now(timezone.utc).isoformat()} UTC")
    return "\n".join(L)


# ─── Rendering HTML ────────────────────────────────────────────────────────

_CSS = """
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; color: #222;
         max-width: 720px; margin: 1em auto; }
  h1 { color: #0066cc; border-bottom: 2px solid #0066cc; padding-bottom: 4px; }
  h2 { color: #444; margin-top: 1.2em; border-bottom: 1px solid #ddd; }
  table { border-collapse: collapse; margin: 0.6em 0; font-size: 13px; }
  th, td { padding: 4px 10px; text-align: left; border-bottom: 1px solid #eee; }
  th { background: #f5f5f5; font-weight: 600; }
  td.num { font-family: monospace; text-align: right; }
  .pos { color: #0a8000; }
  .neg { color: #c00000; }
  .footer { color: #888; font-size: 11px; margin-top: 1.5em;
            border-top: 1px solid #eee; padding-top: 6px; }
</style>
"""


def _render_html(date: str, s: dict) -> str:
    cicli, prod, trend, rifornim = s["cicli"], s["prod"], s["trend"], s["rifornim"]
    truppe, perf, cop, eventi, anom = s["truppe"], s["perf"], s["cop"], s["eventi"], s["anom"]

    parts: list[str] = ["<html><head>", _CSS, "</head><body>"]
    parts.append(f"<h1>Daily Report — {date} (UTC)</h1>")

    # 1. CICLI
    parts.append("<h2>1. Cicli</h2>")
    o = cicli["outcomes"]
    parts.append(
        f"<p>Totale cicli: <b>{cicli['n_tot']}</b> "
        f"({cicli['n_ok']} ok, {cicli['n_ko']} non completati) · "
        f"durata media: <b>{_fmt_dur_s(cicli['avg_dur_s'])}</b><br>"
        f"Istanza-ticks: <b>{cicli['n_ist_ticks']}</b> "
        f"({o['ok']} ok · {o['cascade']} cascade · {o['abort']} abort · "
        f"{o['fail']} fail · {o['altro']} altro)</p>"
    )

    # 2. PRODUZIONE
    parts.append("<h2>2. Produzione</h2>")
    parts.append("<table><tr><th>risorsa</th><th>totale</th></tr>")
    for r in _RISORSE_ORDER:
        emoji = _RIS_EMOJI.get(r, "")
        parts.append(
            f"<tr><td>{emoji} {r}</td>"
            f"<td class='num'>{_fmt_n(prod['totali'][r])}</td></tr>"
        )
    parts.append(
        f"<tr><td>spedizioni rifornimento</td>"
        f"<td class='num'>{prod['sped_tot']}</td></tr></table>"
    )
    if prod["per_ist"]:
        parts.append("<p><b>Top istanze (totale 4 risorse):</b></p>")
        parts.append("<table><tr><th>istanza</th><th>totale</th><th>sped</th></tr>")
        for r in prod["per_ist"][:5]:
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{_fmt_n(r['tot'])}</td>"
                f"<td class='num'>{r['sped']}</td></tr>"
            )
        parts.append("</table>")

    # 3. TREND 7gg
    parts.append(f"<h2>3. Trend 7gg <span style='font-size:13px;color:#888'>"
                 f"(media ultimi {trend['n_days']} giorni → oggi)</span></h2>")
    parts.append("<table><tr><th>risorsa</th><th>media 7gg</th>"
                 "<th>oggi</th><th>Δ%</th></tr>")
    for r in _RISORSE_ORDER:
        avg = trend["avg_tot"][r]
        oggi = trend["today_tot"][r]
        d = trend["delta_pct"][r]
        cls = "pos" if d >= 0 else "neg"
        emoji = _RIS_EMOJI.get(r, "")
        parts.append(
            f"<tr><td>{emoji} {r}</td>"
            f"<td class='num'>{_fmt_n(avg)}</td>"
            f"<td class='num'>{_fmt_n(oggi)}</td>"
            f"<td class='num {cls}'>{d:+.1f}%</td></tr>"
        )
    sd = trend["sped_delta_pct"]
    cls_sd = "pos" if sd >= 0 else "neg"
    parts.append(
        f"<tr><td>spedizioni</td>"
        f"<td class='num'>{trend['avg_sped']:.1f}</td>"
        f"<td class='num'>{trend['today_sped']}</td>"
        f"<td class='num {cls_sd}'>{sd:+.1f}%</td></tr></table>"
    )

    # 4. RIFORNIMENTO
    parts.append("<h2>4. Rifornimento</h2>")
    parts.append(
        f"<p>Totale invii: <b>{rifornim['n_invii_totali']}</b> "
        f"({rifornim['n_istanze']} istanze) · "
        f"tassa media: <b>{rifornim['tassa_avg_giornaliera']*100:.1f}%</b> · "
        f"valore medio per invio: <b>{_fmt_n(rifornim['valore_medio_per_invio'])}</b></p>"
    )
    if rifornim["per_ist"]:
        parts.append("<table><tr><th>istanza</th><th>invii</th><th>tassa avg</th></tr>")
        for r in rifornim["per_ist"][:8]:
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{r['n_invii']}</td>"
                f"<td class='num'>{r['tassa_avg']*100:.1f}%</td></tr>"
            )
        parts.append("</table>")

    # 5. TRUPPE
    parts.append("<h2>5. Truppe</h2>")
    delta = truppe["delta_giorno"]
    cls = "pos" if delta >= 0 else "neg"
    sign = "+" if delta >= 0 else ""
    parts.append(
        f"<p>Totale: <b>{_fmt_n(truppe['tot_oggi'])}</b> "
        f"(<span class='{cls}'>{sign}{_fmt_n(delta)}</span> vs ieri, "
        f"{truppe['n_ist']} istanze)</p>"
    )
    if truppe["delta_per_ist"]:
        parts.append("<table><tr><th>istanza</th><th>oggi</th><th>Δ vs ieri</th></tr>")
        for r in truppe["delta_per_ist"]:
            cls_r = "pos" if r["delta"] >= 0 else "neg"
            sign_r = "+" if r["delta"] >= 0 else ""
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{_fmt_n(r['oggi'])}</td>"
                f"<td class='num {cls_r}'>{sign_r}{_fmt_n(r['delta'])}</td></tr>"
            )
        parts.append("</table>")

    # 6. PERFORMANCE TASK
    parts.append("<h2>6. Performance task <span style='font-size:13px;color:#888'>"
                 "(top 5, IQR-filtered)</span></h2>")
    if perf["task_stats"]:
        parts.append("<table><tr><th>task</th><th>avg</th><th>max</th>"
                     "<th>n</th><th>outliers</th></tr>")
        for t in perf["task_stats"][:5]:
            parts.append(
                f"<tr><td>{t['task']}</td>"
                f"<td class='num'>{_fmt_dur_s(t['avg_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(t['max_s'])}</td>"
                f"<td class='num'>{t['n']}</td>"
                f"<td class='num'>{t['outliers']}</td></tr>"
            )
        parts.append("</table>")

    # 7. BOOT HOME
    parts.append("<h2>7. Boot Home <span style='font-size:13px;color:#888'>"
                 "(per istanza, top 6 desc)</span></h2>")
    if perf["boot_stats"]:
        parts.append("<table><tr><th>istanza</th><th>avg</th><th>min</th>"
                     "<th>max</th><th>n</th></tr>")
        for b in perf["boot_stats"][:6]:
            parts.append(
                f"<tr><td>{b['nome']}</td>"
                f"<td class='num'>{_fmt_dur_s(b['avg_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(b['min_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(b['max_s'])}</td>"
                f"<td class='num'>{b['n']}</td></tr>"
            )
        parts.append("</table>")

    # 8. COPERTURA SQUADRE
    parts.append("<h2>8. Copertura squadre <span style='font-size:13px;color:#888'>"
                 "(load_squadra / capacita_nodo · &lt;75% = squadra debole)</span></h2>")
    if cop["ist_summary"]:
        parts.append("<table><tr><th>istanza</th><th>copertura avg</th><th>tipi</th></tr>")
        for r in cop["ist_summary"][:8]:
            if r["avg_pct"] >= 95:
                cls_c, tag = "pos", "✓"
            elif r["avg_pct"] >= 75:
                cls_c, tag = "", "·"
            else:
                cls_c, tag = "neg", "⚠"
            parts.append(
                f"<tr><td>{tag} {r['ist']}</td>"
                f"<td class='num {cls_c}'>{r['avg_pct']:.1f}%</td>"
                f"<td class='num'>{r['n_tipi']}</td></tr>"
            )
        parts.append("</table>")
    underprov = [r for r in cop["rows"] if r["verdict"] == "underprov"]
    if underprov:
        parts.append("<p><b>⚠ Underprovisioned (load &lt; 75%):</b></p>")
        parts.append("<table><tr><th>istanza</th><th>tipo</th><th>copertura</th><th>n</th></tr>")
        for r in underprov[:8]:
            parts.append(
                f"<tr><td>{r['ist']}</td><td>{r['tipo']}</td>"
                f"<td class='num neg'>{r['avg_pct']:.1f}%</td>"
                f"<td class='num'>{r['n']}</td></tr>"
            )
        parts.append("</table>")

    # 9. EVENTI RILEVANTI
    parts.append("<h2>9. Eventi rilevanti</h2>")
    n_anom_total = (len(eventi["cascade_events"]) + len(eventi["abort_events"]) +
                    len(eventi["not_completed"]))
    if n_anom_total == 0 and eventi["rif_skip_master"] == 0:
        parts.append("<p style='color:#0a8000'>✓ Nessuna anomalia rilevante registrata</p>")
    else:
        if eventi["cascade_events"]:
            parts.append(f"<p><b>Cascade ADB ({len(eventi['cascade_events'])}):</b></p>")
            parts.append("<table><tr><th>ciclo</th><th>istanza</th><th>ora</th></tr>")
            for e in eventi["cascade_events"][:5]:
                parts.append(
                    f"<tr><td class='num'>#{e['ciclo']}</td>"
                    f"<td>{e['ist']}</td><td>{e['start']}</td></tr>"
                )
            parts.append("</table>")
        if eventi["abort_events"]:
            parts.append(f"<p><b>Abort ({len(eventi['abort_events'])}):</b></p>")
            parts.append("<table><tr><th>ciclo</th><th>istanza</th><th>ora</th></tr>")
            for e in eventi["abort_events"][:5]:
                parts.append(
                    f"<tr><td class='num'>#{e['ciclo']}</td>"
                    f"<td>{e['ist']}</td><td>{e['start']}</td></tr>"
                )
            parts.append("</table>")
        if eventi["not_completed"]:
            parts.append(
                f"<p><b>Cicli non completati:</b> {len(eventi['not_completed'])}</p>"
            )
        if eventi["rif_skip_master"]:
            parts.append(
                f"<p><b>Rifornimento skip master saturo:</b> "
                f"{eventi['rif_skip_master']} occorrenze</p>"
            )

    # 10. ANOMALIE TASK
    parts.append("<h2>10. Anomalie task</h2>")
    parts.append(
        f"<p>Task fail: <b>{anom['n_fail']}</b> / {anom['n_events']} "
        f"eventi totali ({(anom['n_fail']/anom['n_events']*100) if anom['n_events'] else 0:.1f}%)</p>"
    )
    if anom["top_fail"]:
        parts.append("<p><b>Top fail (task × istanza):</b></p>")
        parts.append("<table><tr><th>task</th><th>istanza</th><th>n</th></tr>")
        for f in anom["top_fail"]:
            parts.append(
                f"<tr><td>{f['task']}</td><td>{f['inst']}</td>"
                f"<td class='num'>{f['n']}</td></tr>"
            )
        parts.append("</table>")
    if anom["top_anom"]:
        parts.append("<p><b>Anomalie ricorrenti:</b></p>")
        parts.append("<table><tr><th>tipo</th><th>n</th></tr>")
        for tag, n in anom["top_anom"]:
            parts.append(
                f"<tr><td>{tag}</td><td class='num'>{n}</td></tr>"
            )
        parts.append("</table>")

    parts.append(
        f"<div class='footer'>generato: "
        f"{datetime.now(timezone.utc).isoformat()} UTC</div>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


# ─── Step E — scheduler 1×/die ─────────────────────────────────────────────
#
# Hook idempotente da chiamare ad ogni tick / fine ciclo bot. Decide se inviare
# il daily report basandosi su:
#   - `globali.notifications.enabled` AND `daily_report_enabled` (config)
#   - ora UTC corrente >= `daily_report_hour_utc` (config, default 6)
#   - data del report (= ieri UTC) NON ancora inviata
#
# State persistente: `data/daily_report_state.json` con `last_sent_date`.
# Idempotenza: chiamate multiple nello stesso giorno-ora producono al massimo
# un invio. Se bot fermo durante la finestra → skip giorno (accettato).

_STATE_REL = "data/daily_report_state.json"


def _load_state() -> dict:
    p = _root() / _STATE_REL
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    p = _root() / _STATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
    except Exception as exc:
        _log.warning("[REPORT] save state fallito: %s", exc)


def maybe_send_daily_report() -> dict:
    """Hook idempotente: invia daily report se finestra raggiunta + non già fatto.

    Returns:
        dict {sent: bool, reason: str, date: str | None, enqueue_id: str | None}
        Mai solleva eccezioni — best-effort.
    """
    result = {"sent": False, "reason": "", "date": None, "enqueue_id": None}

    # 1) Leggi config (merge baseline + runtime_overrides)
    try:
        from config.config_loader import load_effective_notifications
        notif = load_effective_notifications()
    except Exception as exc:
        result["reason"] = f"config error: {exc}"
        return result

    if not notif.get("enabled", False):
        result["reason"] = "notifications disabled"
        return result
    if not notif.get("daily_report_enabled", True):
        result["reason"] = "daily_report disabled"
        return result

    hour_target = int(notif.get("daily_report_hour_utc", 6))
    now_utc = datetime.now(timezone.utc)

    # 2) Decide la data del report = ieri UTC (sempre report giornata completa)
    report_date = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    today_utc = now_utc.strftime("%Y-%m-%d")

    # 3) Window check: devo essere in `today_utc` e ora >= target
    if now_utc.hour < hour_target:
        result["reason"] = (f"window non ancora aperta "
                            f"(ora UTC={now_utc.hour}, target={hour_target})")
        return result

    # 4) Idempotenza: report di `report_date` già inviato?
    state = _load_state()
    last_sent = state.get("last_sent_date", "")
    if last_sent == report_date:
        result["reason"] = f"già inviato per {report_date}"
        return result
    # Edge case: oggi UTC == report_date significa che è ancora "ieri-non-passato"
    # (impossibile per costruzione: report_date = ieri quindi oggi != report_date).

    # 5) Costruisci report
    try:
        rep = build_daily_report(report_date)
    except Exception as exc:
        result["reason"] = f"build error: {exc}"
        return result

    # 6) Enqueue (recipients/from_addr SEMPRE dalla config — no fallback hardcoded)
    recipients = notif.get("recipients") or []
    if not recipients:
        result["reason"] = ("recipients vuoto in config: configura "
                            "globali.notifications.recipients dalla dashboard")
        _log.warning("[REPORT] %s", result["reason"])
        return result
    try:
        from core.notifier import enqueue_email
        eid = enqueue_email(recipients, rep["subj"],
                            rep["body_text"], html=rep["body_html"],
                            from_addr=notif.get("from_addr") or None)
    except Exception as exc:
        result["reason"] = f"enqueue error: {exc}"
        return result

    # 7) Persisti state
    state["last_sent_date"] = report_date
    state["last_sent_ts"] = now_utc.isoformat()
    state["last_enqueue_id"] = eid
    _save_state(state)

    result.update({
        "sent": True, "reason": "ok", "date": report_date, "enqueue_id": eid,
    })
    _log.info("[REPORT] daily report enqueued date=%s id=%s recipients=%s",
              report_date, eid, recipients)
    return result


# ─── CLI test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    p = argparse.ArgumentParser(description="Build/preview daily report.")
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD UTC (default: ieri UTC)")
    p.add_argument("--out-html", default=None,
                   help="Path file dove salvare HTML preview (default: stampa text)")
    p.add_argument("--enqueue", action="store_true",
                   help="Aggiungi alla queue (richiede notifier)")
    p.add_argument("--maybe-send", action="store_true",
                   help="Esegui hook idempotente maybe_send_daily_report() "
                        "(rispetta config + state; per test scheduler)")
    args = p.parse_args()

    if args.maybe_send:
        res = maybe_send_daily_report()
        print(f"maybe_send_daily_report: {res}")
        raise SystemExit(0 if res["sent"] else 1)

    rep = build_daily_report(args.date)
    print(f"== {rep['subj']} ==")
    print(rep["body_text"])

    if args.out_html:
        Path(args.out_html).write_text(rep["body_html"], encoding="utf-8")
        print(f"\n[HTML salvato in {args.out_html}]")

    if args.enqueue:
        from core.notifier import enqueue_email
        from config.config_loader import load_effective_notifications
        notif = load_effective_notifications()
        recipients = notif.get("recipients", []) or []
        if not recipients:
            print("\n[ERROR] recipients vuoto — configura in dashboard")
            raise SystemExit(2)
        eid = enqueue_email(recipients, rep["subj"],
                            rep["body_text"], html=rep["body_html"])
        print(f"\n[ENQUEUED id={eid}]")
