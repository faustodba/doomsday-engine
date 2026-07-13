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
    """Formatta numero con suffisso K/M (es. 1500000 → '1.50M', -28M → '-28.40M')."""
    n = float(n or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{sign}{n / 1_000:.1f}K"
    return f"{sign}{n:.0f}"


def _fmt_dur_s(s: float) -> str:
    """Format duration. Regola 10/05: >=1min mai secondi (vedi memoria
    feedback_format_durata).
      0-59s     → "Ns"
      60-3599s  → "Xm"           (no coda secondi)
      ≥3600s    → "XhYYm"        (no coda secondi)
    """
    s = int(s or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m"
    return f"{sec}s"


# ─── Sezione 1: Cicli ──────────────────────────────────────────────────────

def _section_cicli(date: str) -> dict:
    """Statistiche cicli completati nella giornata `date` (YYYY-MM-DD UTC).

    10/05 (rev): ridisegnata per fornire vera "salute esecuzione":
      - completati / in corso / non completati distinti (no falso "ko")
      - durata: media + range min/max (varianza giorno/notte)
      - uptime%: somma durate cicli vs 24h
      - produttività: marce raccolta + spedizioni + sfide arena (da events)
      - outcomes esposti ma render solo se ≠ tutto ok (sezione 9)
    """
    data = _read_json("data/telemetry/cicli.json") or {"cicli": []}
    cicli = data.get("cicli") or []

    in_day = [c for c in cicli if (c.get("start_ts") or "")[:10] == date]
    n_tot = len(in_day)

    # A. Distinzione completati / in corso / non completati
    n_completati = sum(1 for c in in_day if c.get("completato") is True)
    n_in_corso   = sum(1 for c in in_day
                       if c.get("completato") is not True
                       and not c.get("end_ts"))
    n_non_compl  = n_tot - n_completati - n_in_corso

    # B. Durata: media + range
    durs = [float(c.get("durata_s") or 0) for c in in_day if c.get("durata_s")]
    avg_dur = sum(durs) / len(durs) if durs else 0
    min_dur = min(durs) if durs else 0
    max_dur = max(durs) if durs else 0

    # D. Uptime%: somma durate cicli vs 24h (86400s). Se la giornata è in
    # corso (date == today UTC), confronto con elapsed dalla mezzanotte.
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if date == today_utc:
        midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        denom_s = (datetime.now(timezone.utc) - midnight).total_seconds()
    else:
        denom_s = 86400.0
    uptime_s = sum(durs)
    uptime_pct = (uptime_s / denom_s * 100) if denom_s > 0 else 0

    # Outcome aggregato per istanza nei cicli del giorno
    outcomes = {"ok": 0, "cascade": 0, "abort": 0, "fail": 0, "altro": 0}
    n_ist_ticks = 0
    for c in in_day:
        for _, ist_data in (c.get("istanze") or {}).items():
            n_ist_ticks += 1
            esito = (ist_data.get("esito") or "altro").lower()
            outcomes[esito if esito in outcomes else "altro"] += 1

    # C. Produttività: somma da events JSONL
    marce_racc = 0
    sped_rif = 0
    sfide_arena = 0
    try:
        events_path = f"data/telemetry/events/events_{date}.jsonl"
        for e in _read_jsonl(events_path):
            t = e.get("task", "")
            o = e.get("output") or {}
            if t in ("raccolta", "raccolta_fast", "raccolta_chiusura"):
                marce_racc += int(o.get("inviate") or 0)
            elif t == "rifornimento":
                # rifornimento ha output.invii_totali oppure rileggiamo da
                # storico_farm; più semplice: somma chiave `invii` se presente
                inv = o.get("invii_totali") or o.get("inviate") or 0
                sped_rif += int(inv or 0)
            elif t == "arena":
                sfide_arena += int(o.get("sfide_eseguite") or 0)
    except Exception:
        pass
    # Fallback per spedizioni: storico_farm.json (già aggregato netto giornaliero)
    if sped_rif == 0:
        try:
            sf = _read_json("data/storico_farm.json") or {}
            day = sf.get(date) or {}
            sped_rif = sum(int(v.get("spedizioni") or 0)
                           for v in day.values() if isinstance(v, dict))
        except Exception:
            pass

    return {
        "n_tot":         n_tot,
        "n_completati":  n_completati,
        "n_in_corso":    n_in_corso,
        "n_non_compl":   n_non_compl,
        # legacy (compat HTML render): n_ok = completati, n_ko = veri non completati
        "n_ok":          n_completati,
        "n_ko":          n_non_compl,
        "avg_dur_s":     avg_dur,
        "min_dur_s":     min_dur,
        "max_dur_s":     max_dur,
        "uptime_s":      uptime_s,
        "uptime_pct":    uptime_pct,
        "denom_s":       denom_s,
        "n_ist_ticks":   n_ist_ticks,
        "outcomes":      outcomes,
        "marce_racc":    marce_racc,
        "sped_rif":      sped_rif,
        "sfide_arena":   sfide_arena,
    }


# ─── Sezioni 2-3: Produzione (rifugio + inviato) ──────────────────────────

_RISORSE_ORDER = ("pomodoro", "legno", "acciaio", "petrolio")
_RIS_EMOJI = {"pomodoro": "🍅", "legno": "🪵", "acciaio": "⚙", "petrolio": "🛢"}


def _section_produzione_rifugio(date: str) -> dict:
    """Produzione INTERNA del rifugio per ogni istanza nel giorno UTC `date`,
    come RESA REALE DELLA RACCOLTA dal Tab Report.

    WU204 step 3 (13/07): passa dalla metrica castello
    (`produzione_storico::produzione_qty = Δcastello − zaino + rifornimento`,
    che un rifornimento/zaino gonfia enormemente — es. FAU_00 = 209 M/h) alla
    resa reale dei nodi raccolti (`report_raccolta_dataset` via
    `shared/produzione_report`). Immune alle anomalie castello, quindi **non
    serve più il filtro outlier 30M/h** (n_sess_anomali sempre 0).

    Master FauMorfeus scorporato dalle ordinarie (coerente con sez 6 TRUPPE).
    `n_sess` ora = numero di raccolte completate (report), `durata_s` non
    applicabile (0). Struttura di ritorno invariata (renderer aggiornati nei
    soli label).
    """
    try:
        from shared.instance_meta import is_master_instance
    except Exception:
        is_master_instance = lambda x: x == "FauMorfeus"
    from shared.produzione_report import produzione_per_istanza, PESI as _PESI

    prod = produzione_per_istanza(giorno=date).get("per_istanza", {})

    totali_ord    = {r: 0 for r in _RISORSE_ORDER}
    totali_master = {r: 0 for r in _RISORSE_ORDER}
    ordinarie: list[dict] = []
    master_row: dict | None = None

    for nome in sorted(prod.keys()):
        p = prod[nome]
        ist_tot = {r: int(p["risorse"].get(r, 0)) for r in _RISORSE_ORDER}
        if sum(ist_tot.values()) <= 0:
            continue
        pom_eq = sum(max(0, ist_tot[r]) * _PESI[r] for r in _RISORSE_ORDER)
        row = {
            "nome":        nome,
            "tot":         sum(ist_tot.values()),
            "risorse":     ist_tot,
            "n_sess":      int(p.get("n_report", 0)),   # n. raccolte completate
            "durata_s":    0.0,                          # non applicabile al report
            "prod_unif_h": round(pom_eq / 24.0 / 1_000_000, 3) if pom_eq > 0 else 0.0,
        }
        if is_master_instance(nome):
            master_row = row
            for r in _RISORSE_ORDER:
                totali_master[r] += ist_tot[r]
        else:
            ordinarie.append(row)
            for r in _RISORSE_ORDER:
                totali_ord[r] += ist_tot[r]

    ordinarie.sort(key=lambda x: x["tot"], reverse=True)

    totali_all   = {r: totali_ord[r] + totali_master[r] for r in _RISORSE_ORDER}
    tot_ord_4    = sum(totali_ord.values())
    tot_master_4 = sum(totali_master.values())

    farm_pom_eq = sum(max(0, totali_ord[r]) * _PESI[r] for r in _RISORSE_ORDER)
    prod_unif_farm_h = round(farm_pom_eq / 24.0 / 1_000_000, 3) if farm_pom_eq > 0 else 0.0

    return {
        # totali aggregati (master + ordinarie) — per compat e riga emoji
        "totali":          totali_all,
        "tot_4_risorse":   tot_ord_4 + tot_master_4,
        # scorporato (rev 10/05)
        "totali_ord":      totali_ord,
        "totali_master":   totali_master,
        "tot_ord_4":       tot_ord_4,
        "tot_master_4":    tot_master_4,
        "ordinarie":       ordinarie,
        "master_row":      master_row,
        "n_ord":           len(ordinarie),
        "durata_ord_s":    0.0,
        "durata_master_s": 0.0,
        "n_sess_anomali":  0,   # report pulito: nessun filtro outlier necessario
        # legacy (per_ist usato in qualche compat HTML)
        "per_ist":         ordinarie + ([master_row] if master_row else []),
        "n_ist":           len(ordinarie) + (1 if master_row else 0),
        "durata_tot_s":    0.0,
        # produzione unificata (M pom-eq/h, 24h, pesi L7) — resa raccolta report
        "prod_unif_farm_h": prod_unif_farm_h,
        "fonte":           "report",
    }


def _section_deposito_attuale() -> dict:
    """Ultima lettura nota delle risorse in deposito (barra HOME) per
    istanza — snapshot live, NON uno storico filtrato per giorno.

    Source: `state/<istanza>.json::produzione_corrente.risorse_iniziali`,
    popolato da `main.py::_leggi_risorse()` (OCR robusto a consenso) ad
    ogni avvio istanza — non solo quando gira ZainoTask. Rappresenta
    quindi il deposito "ad ora" (ultimo ciclo completato per l'istanza),
    non un valore storico del giorno del report.
    """
    import glob
    try:
        from shared.instance_meta import is_master_instance
    except Exception:
        is_master_instance = lambda x: x == "FauMorfeus"

    state_dir = _root() / "state"
    ordinarie: list[dict] = []
    master_row: dict | None = None

    for fp in sorted(glob.glob(str(state_dir / "FAU_*.json")) +
                     glob.glob(str(state_dir / "FauMorfeus.json"))):
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        nome = os.path.basename(fp).replace(".json", "")
        pc = d.get("produzione_corrente") or {}
        ris = pc.get("risorse_iniziali") or {}
        if not ris:
            continue
        row = {
            "nome":    nome,
            "risorse": {r: float(ris.get(r) or 0) for r in _RISORSE_ORDER},
            "ts":      pc.get("ts_inizio") or "",
        }
        if is_master_instance(nome):
            master_row = row
        else:
            ordinarie.append(row)

    ordinarie.sort(key=lambda x: x["nome"])
    return {
        "ordinarie":  ordinarie,
        "master_row": master_row,
        "n_ist":      len(ordinarie) + (1 if master_row else 0),
    }


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


# ─── Sezione 6: Truppe ─────────────────────────────────────────────────────

def _section_truppe(date: str) -> dict:
    """Total squads della giornata + delta vs ieri + Δ 7gg.

    Rev 10/05: separa master vs ordinarie, delta_giorno coerente
    (sum dei delta calcolati, esclude master senza lettura ieri),
    aggiunge Δ 7gg per istanza, mostra tutte le istanze.
    """
    try:
        from shared.instance_meta import is_master_instance
    except Exception:
        is_master_instance = lambda x: x == "FauMorfeus"

    data = _read_json("data/storico_truppe.json") or {}
    ieri_date = (datetime.fromisoformat(date) - timedelta(days=1)).strftime("%Y-%m-%d")
    sett_date = (datetime.fromisoformat(date) - timedelta(days=7)).strftime("%Y-%m-%d")

    ordinarie: list[dict] = []
    master_row: dict | None = None
    n_ist = 0

    for ist, hist in data.items():
        if not isinstance(hist, list):
            continue
        oggi_v = next((h.get("total_squads", 0) for h in hist if h.get("data") == date), None)
        if oggi_v is None:
            continue
        n_ist += 1
        oggi_int = int(oggi_v)
        ieri_v = next((h.get("total_squads", 0) for h in hist if h.get("data") == ieri_date), None)
        # Lettura più vicina ai 7gg fa: la più antica entro intervallo [-8, -6] giorni
        sett_v = None
        sett_data_actual = None
        for h in hist:
            d = h.get("data", "")
            if d and d <= sett_date:
                sett_v = h.get("total_squads", 0)
                sett_data_actual = d
        # Se non c'è lettura entro 7gg fa, prendi la prima disponibile (storia parziale)
        if sett_v is None and hist:
            primo = hist[0]
            if primo.get("data", "") < date:
                sett_v = primo.get("total_squads", 0)
                sett_data_actual = primo.get("data")

        delta_giorno_ist = (oggi_int - int(ieri_v)) if ieri_v is not None else None
        pct_giorno = (delta_giorno_ist / oggi_int * 100) if (delta_giorno_ist is not None and oggi_int > 0) else None
        delta_7gg = (oggi_int - int(sett_v)) if sett_v is not None else None
        pct_7gg = (delta_7gg / int(sett_v) * 100) if (sett_v is not None and int(sett_v) > 0) else None

        row = {
            "nome":        ist,
            "oggi":        oggi_int,
            "delta":       delta_giorno_ist,
            "pct_giorno":  pct_giorno,
            "delta_7gg":   delta_7gg,
            "pct_7gg":     pct_7gg,
            "sett_data":   sett_data_actual,
        }
        if is_master_instance(ist):
            master_row = row
        else:
            ordinarie.append(row)

    # Sort ordinarie per delta_giorno desc (None in coda)
    ordinarie.sort(key=lambda x: (x["delta"] if x["delta"] is not None else -10**18), reverse=True)

    # Totali
    tot_oggi_ord = sum(r["oggi"] for r in ordinarie)
    tot_oggi_master = master_row["oggi"] if master_row else 0
    tot_oggi = tot_oggi_ord + tot_oggi_master
    delta_giorno_ord = sum((r["delta"] or 0) for r in ordinarie if r["delta"] is not None)
    n_ord_con_delta = sum(1 for r in ordinarie if r["delta"] is not None)

    return {
        "tot_oggi":            tot_oggi,
        "tot_oggi_ord":        tot_oggi_ord,
        "tot_oggi_master":     tot_oggi_master,
        "delta_giorno":        delta_giorno_ord,
        "n_ord_con_delta":     n_ord_con_delta,
        "n_ist":               n_ist,
        "ordinarie":           ordinarie,
        "master_row":          master_row,
        # legacy compat (delta_per_ist usato da HTML)
        "delta_per_ist":       ordinarie,
    }


# ─── Sezione 4: Trend produzione 7gg ───────────────────────────────────────

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


# ─── Sezione 5: Rifornimento dettaglio ─────────────────────────────────────

def _section_rifornimento(date: str) -> dict:
    """Spedizioni rifornimento del giorno: per istanza, tassa media,
    netto inviato, valore per invio, provviste residue, saturazione.

    Rev 10/05: arricchita con per-istanza netto/v_invio/residuo + range tassa
    + n istanze in saturazione (provviste_residue < soglia).
    """
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

    # Arricchimento per-istanza da storico_farm: netto + provviste_residue
    farm = _read_json("data/storico_farm.json") or {}
    day = farm.get(date) or {}
    valore_totale_netto = 0
    for nome_ist, vals in day.items():
        if not isinstance(vals, dict):
            continue
        netto_ist = sum(int(vals.get(r) or 0) for r in _RISORSE_ORDER)
        valore_totale_netto += netto_ist
        if nome_ist in by_ist:
            by_ist[nome_ist]["netto"]    = netto_ist
            by_ist[nome_ist]["residuo"]  = int(vals.get("provviste_residue") or 0)

    # Finalize per-istanza
    per_ist = list(by_ist.values())
    for r in per_ist:
        r["tassa_avg"] = (sum(r["tasse"]) / len(r["tasse"])) if r["tasse"] else 0
        r.pop("tasse")
        r.setdefault("netto", 0)
        r.setdefault("residuo", 0)
        r["v_invio"] = (r["netto"] / r["n_invii"]) if r["n_invii"] else 0
    per_ist.sort(key=lambda x: x["netto"], reverse=True)

    # Range tassa + outlier (istanza con tassa più bassa = rifugio più sviluppato:
    # la tassa dipende dal livello del rifugio mittente, non dalla distanza)
    tassa_min = min((r["tassa_avg"] for r in per_ist if r["tassa_avg"] > 0), default=0)
    tassa_max = max((r["tassa_avg"] for r in per_ist), default=0)
    lo_tax_ist = next((r["nome"] for r in per_ist if r["tassa_avg"] == tassa_min), None)

    # Saturazione: provviste_residue < soglia (default 1M)
    SATURAZIONE_SOGLIA = 1_000_000
    saturate = [r["nome"] for r in per_ist if 0 < r["residuo"] < SATURAZIONE_SOGLIA]

    return {
        "n_invii_totali":         n_invii_totali,
        "n_istanze":              len(per_ist),
        "tassa_avg_giornaliera":  (sum(tasse) / len(tasse)) if tasse else 0,
        "tassa_min":              tassa_min,
        "tassa_max":              tassa_max,
        "lo_tax_ist":             lo_tax_ist,
        "valore_medio_per_invio": (valore_totale_netto / n_invii_totali) if n_invii_totali else 0,
        "saturate":               saturate,
        "saturazione_soglia":     SATURAZIONE_SOGLIA,
        "per_ist":                per_ist,
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
        # p95 sui valori grezzi (coda della distribuzione, no IQR filter)
        idx_p95 = max(0, int(0.95 * n) - 1)
        p95 = vals_sorted[idx_p95] if vals_sorted else 0
        task_stats.append({
            "task":      task,
            "n":         len(vals),
            "avg_s":     avg,
            "p95_s":     p95,
            "max_s":     max(vals),
            "outliers":  len(vals) - len(clean),
            "outliers_pct": (len(vals) - len(clean)) / len(vals) * 100,
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

    # Aggregato per istanza (rev 10/05): include n_attacchi totali
    ist_data: dict[str, dict] = {}
    for r in rows:
        slot = ist_data.setdefault(r["ist"], {"pcts": [], "n_attacchi": 0})
        slot["pcts"].append(r["avg_pct"])
        slot["n_attacchi"] += r["n"]
    ist_summary = sorted([
        {
            "ist": ist,
            "avg_pct": sum(d["pcts"]) / len(d["pcts"]),
            "n_tipi": len(d["pcts"]),
            "n_attacchi": d["n_attacchi"],
        }
        for ist, d in ist_data.items()
    ], key=lambda x: x["avg_pct"])

    return {"rows": rows, "ist_summary": ist_summary}


# ─── Sezione 9: Eventi rilevanti ───────────────────────────────────────────

def _section_eventi_rilevanti(date: str) -> dict:
    """Eventi rilevanti del giorno (rev 10/05): cascade/abort/fail tick + alert
    email + rifornimento skip master + HOME stab timeout + bot restart.

    Sources:
      - cicli.json (cascade/abort/fail per tick istanza)
      - events_jsonl (rifornimento skip master)
      - mail_queue.jsonl (alert email count per event_type)
      - logs/<ist>.jsonl (vai_in_home FALLITO count)
      - restart_state.json (bot boot del giorno)
    """
    import glob
    cicli_data = _read_json("data/telemetry/cicli.json") or {"cicli": []}
    cicli = cicli_data.get("cicli") or []
    in_day = [c for c in cicli if (c.get("start_ts") or "")[:10] == date]

    cascade_events = []
    abort_events = []
    fail_events = []
    n_ist_ticks = 0
    n_ok_ticks = 0
    for c in in_day:
        for ist, dat in (c.get("istanze") or {}).items():
            n_ist_ticks += 1
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
            elif esito == "fail":
                fail_events.append({
                    "ist": ist,
                    "start": (dat.get("start_ts") or "")[11:16],
                    "ciclo": c.get("numero"),
                })
            elif esito == "ok":
                n_ok_ticks += 1

    # Rifornimento skip master saturo
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)
    rif_skip_master = 0
    for e in events:
        if e.get("task") != "rifornimento":
            continue
        msg = (e.get("msg") or "").lower()
        if "master saturo" in msg or "daily_recv_limit=0" in msg:
            rif_skip_master += 1

    # Alert email del giorno (da mail_queue.jsonl, filtrato per ts_enqueue[:10])
    mail_records = _read_jsonl("data/mail_queue.jsonl")
    alert_count_by_type: dict[str, int] = {}
    for r in mail_records:
        ts = (r.get("ts_enqueue") or "")[:10]
        if ts != date:
            continue
        subj = r.get("subj", "") or ""
        # Skip daily report (non è un alert anomalia)
        if "daily report" in subj.lower():
            continue
        body = r.get("body", "") or ""
        # Estrai event_type da `Event: <name>` nel body
        ev_type = None
        for line in body.split("\n"):
            if line.startswith("Event: "):
                ev_type = line[len("Event: "):].strip()
                break
        ev_type = ev_type or "unknown"
        alert_count_by_type[ev_type] = alert_count_by_type.get(ev_type, 0) + 1

    # HOME stab timeout (vai_in_home FALLITO) per istanza dai log
    home_timeout_by_ist: dict[str, int] = {}
    log_dir = _root() / "logs"
    if log_dir.exists():
        for fp in sorted(log_dir.glob("FAU_*.jsonl")) + sorted(log_dir.glob("FauMorfeus.jsonl")):
            nome = fp.stem
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        if "vai_in_home FALLITO" not in line:
                            continue
                        try:
                            r = json.loads(line)
                        except Exception:
                            continue
                        ts = (r.get("ts") or "")[:10]
                        if ts != date:
                            continue
                        home_timeout_by_ist[nome] = home_timeout_by_ist.get(nome, 0) + 1
            except Exception:
                continue

    # Bot restart oggi (da restart_state.json::boot_ts)
    restart_state = _read_json("data/restart_state.json") or {}
    boot_ts = (restart_state.get("boot_ts") or "")
    bot_restart_oggi = 1 if boot_ts[:10] == date else 0
    boot_ts_str = boot_ts[:16] if boot_ts else "?"

    return {
        "cascade_events":   cascade_events,
        "abort_events":     abort_events,
        "fail_events":      fail_events,
        "n_ist_ticks":      n_ist_ticks,
        "n_ok_ticks":       n_ok_ticks,
        "rif_skip_master":  rif_skip_master,
        "total_cicli":      len(in_day),
        "alert_count_by_type": alert_count_by_type,
        "home_timeout_by_ist": home_timeout_by_ist,
        "n_home_timeout":    sum(home_timeout_by_ist.values()),
        "bot_restart_oggi":  bot_restart_oggi,
        "boot_ts":           boot_ts_str,
        # Legacy compat HTML render
        "not_completed":    [],
    }


# ─── Sezione 10: Anomalie ───────────────────────────────────────────────────

def _section_anomalie(date: str) -> dict:
    """Aggrega eventi task con success=False / anomalie strutturate.

    Rev 10/05: aggregazione per task (no più per task×istanza), fail_rate%,
    lista istanze colpite, causa principale (top msg).
    """
    rel = f"data/telemetry/events/events_{date}.jsonl"
    events = _read_jsonl(rel)

    by_task: dict[str, dict] = {}
    by_anomaly: dict[str, int] = {}
    n_total_evt = len(events)
    n_fail = 0
    for e in events:
        task = e.get("task", "?")
        inst = e.get("instance", "?")
        # Conta esecuzioni totali per task (per fail_rate)
        slot = by_task.setdefault(task, {
            "task": task, "n_exec": 0, "n_fail": 0,
            "istanze": {}, "msgs": {},
        })
        slot["n_exec"] += 1
        if not e.get("success", True):
            n_fail += 1
            slot["n_fail"] += 1
            slot["istanze"][inst] = slot["istanze"].get(inst, 0) + 1
            msg = (e.get("msg") or "").strip()
            if msg:
                slot["msgs"][msg] = slot["msgs"].get(msg, 0) + 1
        for a in (e.get("anomalies") or []):
            tag = str(a.get("type") if isinstance(a, dict) else a)
            by_anomaly[tag] = by_anomaly.get(tag, 0) + 1

    # Filtra solo task con fail e calcola metriche aggregate
    fail_per_task = []
    for slot in by_task.values():
        if slot["n_fail"] == 0:
            continue
        rate = slot["n_fail"] / slot["n_exec"] * 100 if slot["n_exec"] else 0
        ist_str = " · ".join(
            f"{ist}×{n}" if n > 1 else ist
            for ist, n in sorted(slot["istanze"].items(), key=lambda x: -x[1])
        )
        # Causa principale = top msg
        top_msg = ""
        top_msg_n = 0
        if slot["msgs"]:
            top = max(slot["msgs"].items(), key=lambda x: x[1])
            top_msg, top_msg_n = top
        fail_per_task.append({
            "task":       slot["task"],
            "n_fail":     slot["n_fail"],
            "n_exec":     slot["n_exec"],
            "fail_rate":  rate,
            "istanze":    ist_str,
            "top_msg":    top_msg,
            "top_msg_n":  top_msg_n,
        })
    fail_per_task.sort(key=lambda x: x["fail_rate"], reverse=True)
    top_anom = sorted(by_anomaly.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "n_events":      n_total_evt,
        "n_fail":        n_fail,
        "fail_per_task": fail_per_task,
        "top_anom":      top_anom,
        # Legacy compat (HTML render usava top_fail con campi task,inst,n)
        "top_fail":      [],
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
    rifugio = _section_produzione_rifugio(date)
    prod = _section_produzione(date)
    trend = _section_trend_7gg(date)
    rifornim = _section_rifornimento(date)
    truppe = _section_truppe(date)
    perf = _section_performance_task(date)
    cop = _section_copertura_squadre(date)
    eventi = _section_eventi_rilevanti(date)
    anom = _section_anomalie(date)
    deposito = _section_deposito_attuale()

    sections = {
        "cicli": cicli, "rifugio": rifugio, "prod": prod, "trend": trend,
        "rifornim": rifornim, "truppe": truppe, "perf": perf, "cop": cop,
        "eventi": eventi, "anom": anom, "deposito": deposito,
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
    rifugio = s["rifugio"]
    deposito = s["deposito"]

    L: list[str] = []
    L.append(f"DAILY REPORT {date} (UTC)")
    L.append("=" * 50)
    L.append("")

    # 1. CICLI (revisione 10/05)
    L.append("[CICLI]")
    parts = [f"{cicli['n_completati']} completati"]
    if cicli["n_in_corso"]:
        parts.append(f"{cicli['n_in_corso']} in corso")
    if cicli["n_non_compl"]:
        parts.append(f"{cicli['n_non_compl']} non completati")
    L.append(f"  cicli: {cicli['n_tot']} ({' · '.join(parts)})")

    if cicli["avg_dur_s"] > 0:
        L.append(f"  durata: media {_fmt_dur_s(cicli['avg_dur_s'])}  "
                 f"range {_fmt_dur_s(cicli['min_dur_s'])} → "
                 f"{_fmt_dur_s(cicli['max_dur_s'])}")
        L.append(f"  uptime: {_fmt_dur_s(cicli['uptime_s'])} / "
                 f"{_fmt_dur_s(cicli['denom_s'])} ({cicli['uptime_pct']:.1f}%)")

    prod_parts = []
    if cicli["marce_racc"]:
        prod_parts.append(f"{cicli['marce_racc']} marce raccolta")
    if cicli["sped_rif"]:
        prod_parts.append(f"{cicli['sped_rif']} spedizioni")
    if cicli["sfide_arena"]:
        prod_parts.append(f"{cicli['sfide_arena']} sfide arena")
    if prod_parts:
        L.append(f"  produttività: {' · '.join(prod_parts)}")

    # E. Outcomes ticks ora consolidati nella sezione 10 [EVENTI RILEVANTI]
    # (rev 10/05 — no duplicazione)
    L.append("")

    # 2. PRODUZIONE INTERNA RIFUGIO — WU204: resa raccolta reale dal Tab Report
    # (immune ad anomalie castello). Master FauMorfeus scorporato.
    L.append("[PRODUZIONE INTERNA RIFUGIO] (resa raccolta dal Tab Report, "
             "per istanza, giorno UTC)")
    if rifugio["n_ist"] == 0:
        L.append("  nessuna raccolta registrata nel giorno (Tab Report)")
    else:
        denom_h_rif = (cicli["denom_s"] / 3600) if cicli.get("denom_s") else 24
        if rifugio["master_row"]:
            tot_ord = rifugio["tot_ord_4"]
            tot_mas = rifugio["tot_master_4"]
            tot_all = tot_ord + tot_mas
            thr_all = (tot_all / denom_h_rif) if denom_h_rif > 0 else 0
            L.append(f"  totale: {_fmt_n(tot_all)} "
                     f"(master FauMorfeus {_fmt_n(tot_mas)} · "
                     f"{rifugio['n_ord']} ordinarie {_fmt_n(tot_ord)}, "
                     f"{_fmt_n(thr_all)}/h)")
            # Riga risorse: ordinarie + master separate
            riga_ord = "  ordinarie: " + "  ·  ".join(
                f"{_RIS_EMOJI.get(r,'')} {r} {_fmt_n(rifugio['totali_ord'][r])}"
                for r in _RISORSE_ORDER
            )
            L.append(riga_ord)
            riga_mas = "  master:    " + "  ·  ".join(
                f"{_RIS_EMOJI.get(r,'')} {r} {_fmt_n(rifugio['totali_master'][r])}"
                for r in _RISORSE_ORDER
            )
            L.append(riga_mas)
        else:
            tot_all = rifugio["tot_4_risorse"]
            thr_all = (tot_all / denom_h_rif) if denom_h_rif > 0 else 0
            L.append(f"  totale: {_fmt_n(tot_all)} "
                     f"({rifugio['n_ord']} ordinarie, {_fmt_n(thr_all)}/h)")
            riga_ord = "  " + "  ·  ".join(
                f"{_RIS_EMOJI.get(r,'')} {r} {_fmt_n(rifugio['totali_ord'][r])}"
                for r in _RISORSE_ORDER
            )
            L.append(riga_ord)
        # Top 5 ordinarie (no master)
        if rifugio["ordinarie"]:
            L.append(f"  top 5 ordinarie:")
            for r in rifugio["ordinarie"][:5]:
                L.append(f"    {r['nome']:12s} {_fmt_n(r['tot']):>8s}  "
                         f"({r['n_sess']} raccolte)")
        # Master in coda
        if rifugio["master_row"]:
            mr = rifugio["master_row"]
            L.append(f"  master:")
            L.append(f"    {mr['nome']:12s} {_fmt_n(mr['tot']):>8s}  "
                     f"({mr['n_sess']} raccolte)")
        if rifugio.get("n_sess_anomali"):
            L.append(f"  ⚠ {rifugio['n_sess_anomali']} sessione/i scartate "
                     f"(OCR sospetto: >30M/h per risorsa)")
        # Produzione unificata (M pom-eq/h)
        puf = rifugio.get("prod_unif_farm_h", 0.0)
        if puf > 0:
            L.append(f"  prod. unif. farm: {puf:.2f} M pom-eq/h  (🍅×1 🪵×1 ⚙×2 🛢×5)")
            top_pu = sorted(
                [r for r in rifugio["ordinarie"] if r.get("prod_unif_h", 0) > 0],
                key=lambda x: x["prod_unif_h"], reverse=True
            )
            if top_pu:
                pu_str = "  ".join(
                    f"{r['nome']}={r['prod_unif_h']:.2f}"
                    for r in top_pu[:6]
                )
                L.append(f"  per istanza: {pu_str}")
    L.append("")

    # 3. RISORSE INVIATE AL MASTER (rev 10/05) — NON la produzione interna
    # delle istanze, ma il netto post-tassa effettivamente inviato a FauMorfeus.
    L.append("[RISORSE INVIATE AL MASTER] (netto post-tassa, da farm a master)")
    netto_tot = sum(prod["totali"][r] for r in _RISORSE_ORDER)
    # Throughput orario su denom (24h o elapsed se giornata in corso)
    denom_h = (cicli["denom_s"] / 3600) if cicli.get("denom_s") else 24
    thr_h = (netto_tot / denom_h) if denom_h > 0 else 0
    L.append(f"  totale: {_fmt_n(netto_tot)} netti ({_fmt_n(thr_h)}/h)")
    riga_ris = "  " + "  ·  ".join(
        f"{_RIS_EMOJI.get(r,'')} {r} {_fmt_n(prod['totali'][r])}"
        for r in _RISORSE_ORDER
    )
    L.append(riga_ris)
    # Tassa scartata (lordo = netto / (1-tassa)) usando tassa_avg_giornaliera
    tassa = float(rifornim.get("tassa_avg_giornaliera") or 0)
    if tassa > 0 and tassa < 1:
        lordo = netto_tot / (1 - tassa)
        scartato = lordo - netto_tot
        L.append(f"  spedizioni: {prod['sped_tot']} da {prod['n_ist']} istanze · "
                 f"tassa scartata ~{_fmt_n(scartato)} ({tassa*100:.0f}%)")
    else:
        L.append(f"  spedizioni: {prod['sped_tot']} da {prod['n_ist']} istanze")
    if prod["per_ist"]:
        L.append("  top 5 istanze invianti:")
        for r in prod["per_ist"][:5]:
            L.append(f"    {r['nome']:12s} {_fmt_n(r['tot']):>8s}  {r['sped']:>2} sped")
    L.append("")

    # 4. TREND vs media 7gg (rev 10/05) — sempre risorse INVIATE al master,
    # NON produzione interna castello. Layout: valore_oggi · ▲▼= delta% · media.
    L.append(f"[TREND vs media 7gg] (risorse inviate, ultimi {trend['n_days']} "
             f"giorni precedenti, escluso oggi)")

    def _arrow(pct: float) -> str:
        if pct > 5:    return "▲"
        if pct < -5:   return "▼"
        return "="

    # Riga totale aggregato
    netto_today = sum(trend["today_tot"][r] for r in _RISORSE_ORDER)
    netto_avg   = sum(trend["avg_tot"][r]   for r in _RISORSE_ORDER)
    delta_tot   = ((netto_today - netto_avg) / netto_avg * 100) if netto_avg > 0 else 0
    L.append(f"  totale     {_fmt_n(netto_today):>8s}  {_arrow(delta_tot)} {delta_tot:+.1f}%   "
             f"(media {_fmt_n(netto_avg):>8s})")

    # Per risorsa
    for r in _RISORSE_ORDER:
        emoji = _RIS_EMOJI.get(r, "")
        avg = trend["avg_tot"][r]
        today = trend["today_tot"][r]
        d = trend["delta_pct"][r]
        L.append(f"  {emoji} {r:9s} {_fmt_n(today):>8s}  {_arrow(d)} {d:+.1f}%   "
                 f"(media {_fmt_n(avg):>8s})")

    sd = trend["sped_delta_pct"]
    L.append(f"  spedizioni    {trend['today_sped']:>5d}  {_arrow(sd)} {sd:+.1f}%   "
             f"(media {trend['avg_sped']:.1f})")
    L.append("")

    # 5. RIFORNIMENTO (rev 10/05) — dettaglio per istanza, no ridondanze sez 3
    L.append("[RIFORNIMENTO] (dettaglio per istanza, ordinato per netto desc)")
    if rifornim["per_ist"]:
        # Riga tassa: min/max + outlier
        tmin = rifornim["tassa_min"] * 100
        tmax = rifornim["tassa_max"] * 100
        lo = rifornim.get("lo_tax_ist")
        if lo:
            L.append(f"  tassa: media {rifornim['tassa_avg_giornaliera']*100:.0f}% · "
                     f"range {tmin:.0f}% ({lo}) → {tmax:.0f}%")
        else:
            L.append(f"  tassa: media {rifornim['tassa_avg_giornaliera']*100:.0f}% · "
                     f"range {tmin:.0f}% → {tmax:.0f}%")
        # Saturazione
        n_sat = len(rifornim["saturate"])
        if n_sat > 0:
            soglia_m = rifornim["saturazione_soglia"] / 1_000_000
            sat_str = ", ".join(rifornim["saturate"][:5])
            if len(rifornim["saturate"]) > 5:
                sat_str += f" +{len(rifornim['saturate'])-5}"
            L.append(f"  saturazione: {n_sat}/{rifornim['n_istanze']} istanze "
                     f"con residuo <{soglia_m:.0f}M ({sat_str})")
        else:
            L.append(f"  saturazione: 0/{rifornim['n_istanze']} istanze "
                     f"sotto soglia residuo")
        # Tabella tutte le istanze
        L.append(f"  {'ist':<12} {'invii':>5}  {'netto':>9}  {'v/invio':>8}  "
                 f"{'tassa':>5}  {'residuo':>9}")
        for r in rifornim["per_ist"]:
            warn = " ⚠" if (0 < r["residuo"] < rifornim["saturazione_soglia"]) else ""
            L.append(f"  {r['nome']:<12} {r['n_invii']:>5}  "
                     f"{_fmt_n(r['netto']):>9}  {_fmt_n(r['v_invio']):>8}  "
                     f"{r['tassa_avg']*100:>4.0f}%  {_fmt_n(r['residuo']):>9}{warn}")
    else:
        L.append("  nessun invio rifornimento nel giorno")
    L.append("")

    # 6. TRUPPE (rev 10/05) — separato master vs ordinarie, tutte le istanze
    # in tabella, delta giorno coerente con somma deltas calcolati.
    L.append("[TRUPPE] (totale squadre per istanza, delta vs ieri/7gg)")
    if truppe["tot_oggi_master"]:
        L.append(f"  totale: {_fmt_n(truppe['tot_oggi'])} "
                 f"(master FauMorfeus {_fmt_n(truppe['tot_oggi_master'])} · "
                 f"{len(truppe['ordinarie'])} ordinarie {_fmt_n(truppe['tot_oggi_ord'])})")
    else:
        L.append(f"  totale: {_fmt_n(truppe['tot_oggi'])} "
                 f"({len(truppe['ordinarie'])} ordinarie)")
    sign = "+" if truppe["delta_giorno"] >= 0 else ""
    L.append(f"  Δ giorno: {sign}{_fmt_n(truppe['delta_giorno'])} "
             f"(su {truppe['n_ord_con_delta']} ordinarie con lettura ieri)")

    # Tabella tutte le istanze (ordinarie ordinate per delta desc, master in coda)
    if truppe["ordinarie"] or truppe["master_row"]:
        L.append(f"  {'ist':<12} {'oggi':>9}  {'Δ ieri':>9}  {'Δ %':>6}  "
                 f"{'Δ 7gg':>9}  {'Δ%/7gg':>7}")

        def _fmt_d(v):
            if v is None: return "n/a"
            return ("+" if v >= 0 else "") + _fmt_n(v)
        def _fmt_p(v):
            if v is None: return "n/a"
            return f"{v:+.1f}%"

        for r in truppe["ordinarie"]:
            L.append(f"  {r['nome']:<12} {_fmt_n(r['oggi']):>9}  "
                     f"{_fmt_d(r['delta']):>9}  {_fmt_p(r['pct_giorno']):>6}  "
                     f"{_fmt_d(r['delta_7gg']):>9}  {_fmt_p(r['pct_7gg']):>7}")
        if truppe["master_row"]:
            mr = truppe["master_row"]
            note = ""
            if mr["delta"] is None:
                note = "  *  storia parziale: prima lettura più recente di 7gg fa"
            L.append(f"  {mr['nome']:<12} {_fmt_n(mr['oggi']):>9}  "
                     f"{_fmt_d(mr['delta']):>9}  {_fmt_p(mr['pct_giorno']):>6}  "
                     f"{_fmt_d(mr['delta_7gg']):>9}  {_fmt_p(mr['pct_7gg']):>7}{note}")
    L.append("")

    # 7. PERFORMANCE TASK (rev 10/05) — tabella tutti i task, sort avg desc
    L.append("[PERFORMANCE TASK] (durata, IQR-filtered, ordinato per avg desc)")
    if perf["task_stats"]:
        L.append(f"  {'task':<22} {'n':>4}  {'avg':>5}  {'p95':>5}  {'max':>5}  outliers")
        for t in perf["task_stats"]:
            out_str = (f"{t['outliers']} ({t['outliers_pct']:.0f}%)"
                       if t["outliers"] else "—")
            L.append(f"  {t['task']:<22} {t['n']:>4}  {_fmt_dur_s(t['avg_s']):>5}  "
                     f"{_fmt_dur_s(t['p95_s']):>5}  {_fmt_dur_s(t['max_s']):>5}  {out_str}")
    L.append("")

    # 8. BOOT HOME per istanza (rev 10/05) — tutte le istanze, label chiarito
    L.append("[BOOT HOME → READY] (avvio istanza fino a tick orchestrator pronto, "
             "include settings+troops post-HOME — WU127)")
    if perf["boot_stats"]:
        L.append(f"  {'ist':<13} {'n':>3}  {'avg':>5}  {'min':>5}  {'max':>5}")
        for b in perf["boot_stats"]:
            L.append(f"  {b['nome']:<13} {b['n']:>3}  "
                     f"{_fmt_dur_s(b['avg_s']):>5}  {_fmt_dur_s(b['min_s']):>5}  "
                     f"{_fmt_dur_s(b['max_s']):>5}")
    L.append("")

    # 9. COPERTURA SQUADRE (rev 10/05) — solo istanze <100%, summary 100%, underprov dettaglio
    L.append("[COPERTURA SQUADRE] (load_squadra / capacita_nodo · <75% = squadra debole)")
    if cop["ist_summary"]:
        # Separa istanze al 100% dalle altre
        sotto_100 = [r for r in cop["ist_summary"] if r["avg_pct"] < 100]
        cento     = [r for r in cop["ist_summary"] if r["avg_pct"] >= 100]
        if sotto_100:
            L.append(f"  {'ist':<13} {'coverage':>10}  {'n_attacchi':>10}")
            for r in sotto_100:
                tag = "✓" if r["avg_pct"] >= 100 else "·" if r["avg_pct"] >= 95 else "⚠"
                L.append(f"  {r['ist']:<13} {r['avg_pct']:>7.1f}% {tag}  {r['n_attacchi']:>10}")
        if cento:
            nomi = ", ".join(r["ist"] for r in cento)
            L.append(f"  altre {len(cento)} istanze al 100% ✓: {nomi}")
    else:
        L.append("  nessun dato copertura per il giorno")

    underprov = [r for r in cop["rows"] if r["verdict"] == "underprov"]
    if underprov:
        L.append(f"  ⚠ squadre deboli per (ist, tipo) — nodo non chiuso, "
                 f"produzione ridotta:")
        for r in underprov[:5]:
            L.append(f"    {r['ist']:<13} {r['tipo']:<10} {r['avg_pct']:>5.1f}%  "
                     f"({r['n']} attacchi)")
        if len(underprov) > 5:
            L.append(f"    +{len(underprov)-5} altre")
    L.append("")

    # 10. EVENTI RILEVANTI (rev 10/05) — anomalie + alert + restart + HOME timeout
    L.append("[EVENTI RILEVANTI]")
    nc = len(eventi["cascade_events"])
    na = len(eventi["abort_events"])
    nf = len(eventi["fail_events"])
    n_problemi = nc + na + nf

    # Esiti istanza-tick (consolidato qui da sez 1)
    if eventi["n_ist_ticks"] > 0:
        if n_problemi == 0:
            L.append(f"  ✓ {eventi['n_ok_ticks']}/{eventi['n_ist_ticks']} "
                     f"istanza-tick completati senza errori")
        else:
            L.append(f"  esiti istanza-tick: {eventi['n_ok_ticks']} ok · "
                     f"{nc} cascade · {na} abort · {nf} fail "
                     f"(totale {eventi['n_ist_ticks']})")
            if eventi["cascade_events"]:
                L.append(f"  ⚠ cascade ADB:")
                for e in eventi["cascade_events"][:5]:
                    L.append(f"    ciclo#{e['ciclo']} {e['ist']} @ {e['start']} UTC")
            if eventi["abort_events"]:
                L.append(f"  ⚠ abort:")
                for e in eventi["abort_events"][:5]:
                    L.append(f"    ciclo#{e['ciclo']} {e['ist']} @ {e['start']} UTC")
            if eventi["fail_events"]:
                L.append(f"  ⚠ fail:")
                for e in eventi["fail_events"][:5]:
                    L.append(f"    ciclo#{e['ciclo']} {e['ist']} @ {e['start']} UTC")

    # Alert email del giorno
    alerts = eventi["alert_count_by_type"]
    if alerts:
        n_alerts = sum(alerts.values())
        det = ", ".join(f"{n}× {t}" for t, n in sorted(alerts.items(),
                                                        key=lambda x: -x[1]))
        L.append(f"  alert email inviati: {n_alerts} ({det})")

    # Rifornimento skip master saturo
    if eventi["rif_skip_master"]:
        L.append(f"  rifornimento skip master saturo: "
                 f"{eventi['rif_skip_master']} esecuzioni")

    # HOME stab timeout
    if eventi["n_home_timeout"]:
        ist_list = ", ".join(f"{ist}×{n}" for ist, n in
                              sorted(eventi["home_timeout_by_ist"].items(),
                                     key=lambda x: -x[1]))
        L.append(f"  HOME stab timeout (vai_in_home FALLITO): "
                 f"{eventi['n_home_timeout']} eventi ({ist_list})")

    # Bot restart
    if eventi["bot_restart_oggi"]:
        L.append(f"  bot restart: 1 (boot @ {eventi['boot_ts']} UTC)")

    L.append("")

    # 11. ANOMALIE TASK (rev 10/05) — aggregato per task con fail_rate% e msg principale
    L.append("[ANOMALIE TASK]")
    if anom["n_fail"] == 0 and not anom["top_anom"]:
        L.append(f"  ✓ nessun task fail · nessuna anomalia strutturata "
                 f"({anom['n_events']} eventi totali)")
    else:
        rate_g = anom["n_fail"] / anom["n_events"] * 100 if anom["n_events"] else 0
        marker = "⚠" if rate_g >= 5 else "·"
        L.append(f"  {marker} task fail: {anom['n_fail']} / {anom['n_events']} eventi "
                 f"({rate_g:.1f}%)")
        if anom["fail_per_task"]:
            L.append(f"  per task fallito:")
            for f in anom["fail_per_task"]:
                tag = "⚠" if f["fail_rate"] >= 10 else "·"
                L.append(f"    {f['task']:<18} {f['n_fail']} fail / {f['n_exec']} esec  "
                         f"({f['fail_rate']:.1f}%)  {tag}")
                if f["istanze"]:
                    L.append(f"      istanze: {f['istanze']}")
                if f["top_msg"]:
                    msg_str = f['top_msg'][:80]
                    L.append(f"      causa principale: \"{msg_str}\" "
                             f"({f['top_msg_n']} occorrenze)")
        if anom["top_anom"]:
            L.append(f"  anomalie strutturate (top 5):")
            for tag, n in anom["top_anom"]:
                L.append(f"    {tag:<30} n={n}")
        else:
            L.append("  anomalie strutturate: nessuna")
    L.append("")

    # 12. DEPOSITO ATTUALE — snapshot live (non storico del giorno)
    L.append("[DEPOSITO ATTUALE] (ultima lettura nota, non storico del giorno)")
    if deposito["n_ist"] == 0:
        L.append("  nessuna lettura deposito disponibile")
    else:
        L.append(f"  {'ist':<12} {'pom':>7}  {'legno':>7}  {'acc':>7}  {'petr':>7}  aggiornato")
        for r in deposito["ordinarie"]:
            v = r["risorse"]
            L.append(
                f"  {r['nome']:<12} {v['pomodoro']/1e6:>6.1f}M {v['legno']/1e6:>6.1f}M "
                f"{v['acciaio']/1e6:>6.1f}M {v['petrolio']/1e6:>6.1f}M  {r['ts'][:16]}"
            )
        if deposito["master_row"]:
            r = deposito["master_row"]
            v = r["risorse"]
            L.append(
                f"  {r['nome']:<12} {v['pomodoro']/1e6:>6.1f}M {v['legno']/1e6:>6.1f}M "
                f"{v['acciaio']/1e6:>6.1f}M {v['petrolio']/1e6:>6.1f}M  {r['ts'][:16]} (master)"
            )
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
    rifugio = s["rifugio"]
    deposito = s["deposito"]

    parts: list[str] = ["<html><head>", _CSS, "</head><body>"]
    parts.append(f"<h1>Daily Report — {date} (UTC)</h1>")

    # 1. CICLI (revisione 10/05)
    parts.append("<h2>1. Cicli</h2>")
    o = cicli["outcomes"]
    riga_cicli = [f"<b>{cicli['n_completati']} completati</b>"]
    if cicli["n_in_corso"]:
        riga_cicli.append(f"{cicli['n_in_corso']} in corso")
    if cicli["n_non_compl"]:
        riga_cicli.append(f"<span style='color:#a00'>{cicli['n_non_compl']} non completati</span>")
    blocco = [f"<p>Cicli: <b>{cicli['n_tot']}</b> ({' · '.join(riga_cicli)})"]
    if cicli["avg_dur_s"] > 0:
        blocco.append(
            f"<br>Durata: media <b>{_fmt_dur_s(cicli['avg_dur_s'])}</b> · "
            f"range {_fmt_dur_s(cicli['min_dur_s'])} → "
            f"{_fmt_dur_s(cicli['max_dur_s'])}"
        )
        blocco.append(
            f"<br>Uptime: <b>{_fmt_dur_s(cicli['uptime_s'])}</b> / "
            f"{_fmt_dur_s(cicli['denom_s'])} "
            f"<b>({cicli['uptime_pct']:.1f}%)</b>"
        )
    prod_parts: list[str] = []
    if cicli["marce_racc"]:
        prod_parts.append(f"{cicli['marce_racc']} marce raccolta")
    if cicli["sped_rif"]:
        prod_parts.append(f"{cicli['sped_rif']} spedizioni")
    if cicli["sfide_arena"]:
        prod_parts.append(f"{cicli['sfide_arena']} sfide arena")
    if prod_parts:
        blocco.append(f"<br>Produttività: {' · '.join(prod_parts)}")
    # Anomalie ticks ora consolidate nella sezione 10 (rev 10/05 — no duplicazione)
    blocco.append("</p>")
    parts.append("".join(blocco))

    # 2. PRODUZIONE INTERNA RIFUGIO (rev 10/05 post-feedback) — scorporato master
    parts.append("<h2>2. Produzione interna rifugio</h2>")
    parts.append("<p style='color:#666;font-size:90%'>Produzione effettiva "
                 "per istanza, sommata dalle sessioni chiuse nel giorno. "
                 "Master FauMorfeus separata dalle ordinarie. "
                 "Distinta dalle risorse inviate al master (sezione 3).</p>")
    if rifugio["n_ist"] == 0:
        parts.append("<p>nessuna sessione chiusa nel giorno con dati produzione</p>")
    else:
        denom_h_rif_h = (cicli["denom_s"] / 3600) if cicli.get("denom_s") else 24
        if rifugio["master_row"]:
            tot_ord_h = rifugio["tot_ord_4"]
            tot_mas_h = rifugio["tot_master_4"]
            tot_all_h = tot_ord_h + tot_mas_h
            thr_all_h = (tot_all_h / denom_h_rif_h) if denom_h_rif_h > 0 else 0
            parts.append(
                f"<p>Totale: <b>{_fmt_n(tot_all_h)}</b> "
                f"(master FauMorfeus <b>{_fmt_n(tot_mas_h)}</b> · "
                f"{rifugio['n_ord']} ordinarie <b>{_fmt_n(tot_ord_h)}</b>, "
                f"<b>{_fmt_n(thr_all_h)}/h</b>)</p>"
            )
            # Tabella per risorsa: 3 colonne (risorsa | ordinarie | master)
            parts.append("<table><tr><th>risorsa</th><th>ordinarie</th>"
                         "<th>master</th></tr>")
            for r in _RISORSE_ORDER:
                parts.append(
                    f"<tr><td>{_RIS_EMOJI.get(r,'')} {r}</td>"
                    f"<td class='num'>{_fmt_n(rifugio['totali_ord'][r])}</td>"
                    f"<td class='num'>{_fmt_n(rifugio['totali_master'][r])}</td></tr>"
                )
            parts.append("</table>")
        else:
            tot_all_h = rifugio["tot_4_risorse"]
            thr_all_h = (tot_all_h / denom_h_rif_h) if denom_h_rif_h > 0 else 0
            parts.append(f"<p>Totale: <b>{_fmt_n(tot_all_h)}</b> "
                         f"(<b>{_fmt_n(thr_all_h)}/h</b>)</p>")
            parts.append("<table><tr><th>risorsa</th><th>totale</th></tr>")
            for r in _RISORSE_ORDER:
                parts.append(
                    f"<tr><td>{_RIS_EMOJI.get(r,'')} {r}</td>"
                    f"<td class='num'>{_fmt_n(rifugio['totali_ord'][r])}</td></tr>"
                )
            parts.append("</table>")

        # Top 5 ordinarie (no master)
        if rifugio["ordinarie"]:
            parts.append("<p><b>Top 5 ordinarie per produzione:</b></p>")
            parts.append("<table><tr><th>istanza</th><th>totale</th>"
                         "<th>raccolte</th></tr>")
            for r in rifugio["ordinarie"][:5]:
                parts.append(
                    f"<tr><td>{r['nome']}</td>"
                    f"<td class='num'>{_fmt_n(r['tot'])}</td>"
                    f"<td class='num'>{r['n_sess']}</td></tr>"
                )
            parts.append("</table>")
        # Master in tabella separata (sfondo dorato come sez 6)
        if rifugio["master_row"]:
            mr = rifugio["master_row"]
            parts.append("<table><tr><th>master</th><th>totale</th>"
                         "<th>raccolte</th></tr>")
            parts.append(
                f"<tr style='background:#fff7d0'><td>{mr['nome']} "
                f"<small>(master)</small></td>"
                f"<td class='num'>{_fmt_n(mr['tot'])}</td>"
                f"<td class='num'>{mr['n_sess']}</td></tr></table>"
            )
        if rifugio.get("n_sess_anomali"):
            parts.append(
                f"<p style='color:#c80'>⚠ <b>{rifugio['n_sess_anomali']}</b> "
                f"sessione/i scartate (OCR sospetto: produzione &gt;30M/h "
                f"per risorsa)</p>"
            )
        # Produzione unificata (M pom-eq/h)
        puf = rifugio.get("prod_unif_farm_h", 0.0)
        if puf and puf > 0:
            parts.append(
                f"<p><b>Produzione unificata farm: {puf:.2f} M pom-eq/h</b> "
                f"<small>(🍅×1 🪵×1 ⚙×2 🛢×5 · resa raccolta dal Tab Report · 24h)</small></p>"
            )
            top_pu = sorted(
                [r for r in rifugio.get("ordinarie", []) if r.get("prod_unif_h", 0) > 0],
                key=lambda x: x["prod_unif_h"], reverse=True,
            )
            if top_pu:
                parts.append(
                    "<table><tr><th>istanza</th><th>prod. unif. (M/h)</th></tr>"
                )
                for r in top_pu:
                    parts.append(
                        f"<tr><td>{r['nome']}</td>"
                        f"<td class='num'>{r['prod_unif_h']:.2f}</td></tr>"
                    )
                parts.append("</table>")

    # 3. RISORSE INVIATE AL MASTER (rev 10/05) — netto post-tassa, NON la
    # produzione interna delle istanze.
    parts.append("<h2>3. Risorse inviate al master</h2>")
    parts.append("<p style='color:#666;font-size:90%'>Netto post-tassa "
                 "effettivamente inviato dalle istanze al master FauMorfeus. "
                 "Non è la produzione interna castello.</p>")
    netto_tot_h = sum(prod["totali"][r] for r in _RISORSE_ORDER)
    denom_h = (cicli["denom_s"] / 3600) if cicli.get("denom_s") else 24
    thr_h = (netto_tot_h / denom_h) if denom_h > 0 else 0
    parts.append(f"<p>Totale: <b>{_fmt_n(netto_tot_h)}</b> netti "
                 f"(<b>{_fmt_n(thr_h)}/h</b>)</p>")
    parts.append("<table><tr><th>risorsa</th><th>totale</th></tr>")
    for r in _RISORSE_ORDER:
        emoji = _RIS_EMOJI.get(r, "")
        parts.append(
            f"<tr><td>{emoji} {r}</td>"
            f"<td class='num'>{_fmt_n(prod['totali'][r])}</td></tr>"
        )
    # Tassa scartata
    tassa_h = float(rifornim.get("tassa_avg_giornaliera") or 0)
    if tassa_h > 0 and tassa_h < 1:
        lordo_h = netto_tot_h / (1 - tassa_h)
        scartato_h = lordo_h - netto_tot_h
        parts.append(
            f"<tr><td>spedizioni</td>"
            f"<td class='num'>{prod['sped_tot']} · tassa scartata "
            f"~{_fmt_n(scartato_h)} ({tassa_h*100:.0f}%)</td></tr></table>"
        )
    else:
        parts.append(
            f"<tr><td>spedizioni rifornimento</td>"
            f"<td class='num'>{prod['sped_tot']}</td></tr></table>"
        )
    if prod["per_ist"]:
        parts.append("<p><b>Top 5 istanze invianti:</b></p>")
        parts.append("<table><tr><th>istanza</th><th>totale</th><th>sped</th></tr>")
        for r in prod["per_ist"][:5]:
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{_fmt_n(r['tot'])}</td>"
                f"<td class='num'>{r['sped']}</td></tr>"
            )
        parts.append("</table>")

    # 4. TREND 7gg
    # 4. TREND vs media 7gg (rev 10/05) — sempre risorse INVIATE
    parts.append(f"<h2>4. Trend vs media 7gg <span style='font-size:13px;color:#888'>"
                 f"(risorse inviate, ultimi {trend['n_days']} giorni precedenti, "
                 f"escluso oggi)</span></h2>")
    parts.append("<p style='color:#666;font-size:90%'>Confronto risorse inviate "
                 "al master vs media settimana. Non è la produzione interna castello.</p>")

    def _arrow_h(pct: float) -> str:
        if pct > 5:    return "▲"
        if pct < -5:   return "▼"
        return "="

    parts.append("<table><tr><th>risorsa</th><th>oggi</th>"
                 "<th>Δ%</th><th>media 7gg</th></tr>")

    # Riga totale aggregato
    netto_today_h = sum(trend["today_tot"][r] for r in _RISORSE_ORDER)
    netto_avg_h   = sum(trend["avg_tot"][r]   for r in _RISORSE_ORDER)
    delta_tot_h   = ((netto_today_h - netto_avg_h) / netto_avg_h * 100) if netto_avg_h > 0 else 0
    cls_tot = "pos" if delta_tot_h >= 0 else "neg"
    parts.append(
        f"<tr><td><b>totale</b></td>"
        f"<td class='num'><b>{_fmt_n(netto_today_h)}</b></td>"
        f"<td class='num {cls_tot}'>{_arrow_h(delta_tot_h)} {delta_tot_h:+.1f}%</td>"
        f"<td class='num'>{_fmt_n(netto_avg_h)}</td></tr>"
    )

    for r in _RISORSE_ORDER:
        avg = trend["avg_tot"][r]
        oggi = trend["today_tot"][r]
        d = trend["delta_pct"][r]
        cls = "pos" if d >= 0 else "neg"
        emoji = _RIS_EMOJI.get(r, "")
        parts.append(
            f"<tr><td>{emoji} {r}</td>"
            f"<td class='num'>{_fmt_n(oggi)}</td>"
            f"<td class='num {cls}'>{_arrow_h(d)} {d:+.1f}%</td>"
            f"<td class='num'>{_fmt_n(avg)}</td></tr>"
        )
    sd = trend["sped_delta_pct"]
    cls_sd = "pos" if sd >= 0 else "neg"
    parts.append(
        f"<tr><td>spedizioni</td>"
        f"<td class='num'>{trend['today_sped']}</td>"
        f"<td class='num {cls_sd}'>{_arrow_h(sd)} {sd:+.1f}%</td>"
        f"<td class='num'>{trend['avg_sped']:.1f}</td></tr></table>"
    )

    # 5. RIFORNIMENTO (rev 10/05) — dettaglio per istanza, no ridondanze sez 3
    parts.append("<h2>5. Rifornimento</h2>")
    parts.append("<p style='color:#666;font-size:90%'>Dettaglio operativo "
                 "per istanza. Aggregati totali invii / tassa media / valore "
                 "medio sono nella sezione 3.</p>")
    if rifornim["per_ist"]:
        # Header con tassa range + saturazione
        tmin_h = rifornim["tassa_min"] * 100
        tmax_h = rifornim["tassa_max"] * 100
        lo_h = rifornim.get("lo_tax_ist")
        riga_tassa = (
            f"Tassa: media <b>{rifornim['tassa_avg_giornaliera']*100:.0f}%</b> · "
            f"range {tmin_h:.0f}% "
            + (f"({lo_h}) " if lo_h else "")
            + f"→ {tmax_h:.0f}%"
        )
        n_sat = len(rifornim["saturate"])
        soglia_m = rifornim["saturazione_soglia"] / 1_000_000
        if n_sat > 0:
            sat_str = ", ".join(rifornim["saturate"][:5])
            if len(rifornim["saturate"]) > 5:
                sat_str += f" +{len(rifornim['saturate'])-5}"
            riga_sat = (f"<span style='color:#a00'>Saturazione: "
                        f"<b>{n_sat}/{rifornim['n_istanze']}</b> istanze con "
                        f"residuo &lt;{soglia_m:.0f}M ({sat_str})</span>")
        else:
            riga_sat = (f"Saturazione: 0/{rifornim['n_istanze']} istanze "
                        f"sotto soglia residuo")
        parts.append(f"<p>{riga_tassa}<br>{riga_sat}</p>")
        # Tabella tutte le istanze
        parts.append("<table><tr><th>istanza</th><th>invii</th>"
                     "<th>netto</th><th>v/invio</th>"
                     "<th>tassa</th><th>residuo</th></tr>")
        for r in rifornim["per_ist"]:
            warn_cls = ""
            warn_html = ""
            if 0 < r["residuo"] < rifornim["saturazione_soglia"]:
                warn_cls = " class='neg'"
                warn_html = " ⚠"
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{r['n_invii']}</td>"
                f"<td class='num'>{_fmt_n(r['netto'])}</td>"
                f"<td class='num'>{_fmt_n(r['v_invio'])}</td>"
                f"<td class='num'>{r['tassa_avg']*100:.0f}%</td>"
                f"<td class='num'{warn_cls}>{_fmt_n(r['residuo'])}{warn_html}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>nessun invio rifornimento nel giorno</p>")

    # 6. TRUPPE (rev 10/05) — separato master vs ordinarie, tutte le istanze
    parts.append("<h2>6. Truppe</h2>")
    parts.append("<p style='color:#666;font-size:90%'>Totale squadre per "
                 "istanza, delta vs ieri/7gg. Master FauMorfeus separata.</p>")

    if truppe["tot_oggi_master"]:
        parts.append(
            f"<p>Totale: <b>{_fmt_n(truppe['tot_oggi'])}</b> "
            f"(master FauMorfeus <b>{_fmt_n(truppe['tot_oggi_master'])}</b> · "
            f"{len(truppe['ordinarie'])} ordinarie "
            f"<b>{_fmt_n(truppe['tot_oggi_ord'])}</b>)</p>"
        )
    else:
        parts.append(f"<p>Totale: <b>{_fmt_n(truppe['tot_oggi'])}</b> "
                     f"({len(truppe['ordinarie'])} ordinarie)</p>")
    delta_g = truppe["delta_giorno"]
    cls_g = "pos" if delta_g >= 0 else "neg"
    sign_g = "+" if delta_g >= 0 else ""
    parts.append(
        f"<p>Δ giorno: <span class='{cls_g}'>{sign_g}{_fmt_n(delta_g)}</span> "
        f"(su {truppe['n_ord_con_delta']} ordinarie con lettura ieri)</p>"
    )

    def _fmt_d_h(v):
        if v is None: return "<span style='color:#888'>n/a</span>"
        cls_v = "pos" if v >= 0 else "neg"
        s = "+" if v >= 0 else ""
        return f"<span class='{cls_v}'>{s}{_fmt_n(v)}</span>"

    def _fmt_p_h(v):
        if v is None: return "<span style='color:#888'>n/a</span>"
        cls_v = "pos" if v >= 0 else "neg"
        return f"<span class='{cls_v}'>{v:+.1f}%</span>"

    if truppe["ordinarie"] or truppe["master_row"]:
        parts.append("<table><tr><th>istanza</th><th>oggi</th>"
                     "<th>Δ ieri</th><th>Δ %</th>"
                     "<th>Δ 7gg</th><th>Δ%/7gg</th></tr>")
        for r in truppe["ordinarie"]:
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{_fmt_n(r['oggi'])}</td>"
                f"<td class='num'>{_fmt_d_h(r['delta'])}</td>"
                f"<td class='num'>{_fmt_p_h(r['pct_giorno'])}</td>"
                f"<td class='num'>{_fmt_d_h(r['delta_7gg'])}</td>"
                f"<td class='num'>{_fmt_p_h(r['pct_7gg'])}</td></tr>"
            )
        if truppe["master_row"]:
            mr = truppe["master_row"]
            parts.append(
                f"<tr style='background:#fff7d0'><td>{mr['nome']} <small>(master)</small></td>"
                f"<td class='num'>{_fmt_n(mr['oggi'])}</td>"
                f"<td class='num'>{_fmt_d_h(mr['delta'])}</td>"
                f"<td class='num'>{_fmt_p_h(mr['pct_giorno'])}</td>"
                f"<td class='num'>{_fmt_d_h(mr['delta_7gg'])}</td>"
                f"<td class='num'>{_fmt_p_h(mr['pct_7gg'])}</td></tr>"
            )
        parts.append("</table>")

    # 7. PERFORMANCE TASK (rev 10/05) — tutti i task in tabella, sort avg desc
    parts.append("<h2>7. Performance task <span style='font-size:13px;color:#888'>"
                 "(durata, IQR-filtered, ordinato per avg desc)</span></h2>")
    if perf["task_stats"]:
        parts.append("<table><tr><th>task</th><th>n</th>"
                     "<th>avg</th><th>p95</th><th>max</th>"
                     "<th>outliers</th></tr>")
        for t in perf["task_stats"]:
            out_html = (f"{t['outliers']} <small>({t['outliers_pct']:.0f}%)</small>"
                        if t["outliers"] else "<span style='color:#888'>—</span>")
            parts.append(
                f"<tr><td>{t['task']}</td>"
                f"<td class='num'>{t['n']}</td>"
                f"<td class='num'>{_fmt_dur_s(t['avg_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(t['p95_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(t['max_s'])}</td>"
                f"<td class='num'>{out_html}</td></tr>"
            )
        parts.append("</table>")

    # 8. BOOT HOME → READY (rev 10/05) — label chiarito (WU127), tutte le istanze
    parts.append("<h2>8. Boot Home → Ready <span style='font-size:13px;color:#888'>"
                 "(avvio istanza fino a tick pronto, include settings+troops "
                 "post-HOME — WU127)</span></h2>")
    if perf["boot_stats"]:
        parts.append("<table><tr><th>istanza</th><th>n</th>"
                     "<th>avg</th><th>min</th><th>max</th></tr>")
        for b in perf["boot_stats"]:
            parts.append(
                f"<tr><td>{b['nome']}</td>"
                f"<td class='num'>{b['n']}</td>"
                f"<td class='num'>{_fmt_dur_s(b['avg_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(b['min_s'])}</td>"
                f"<td class='num'>{_fmt_dur_s(b['max_s'])}</td></tr>"
            )
        parts.append("</table>")

    # 9. COPERTURA SQUADRE (rev 10/05) — solo istanze <100%, summary 100%
    parts.append("<h2>9. Copertura squadre <span style='font-size:13px;color:#888'>"
                 "(load_squadra / capacita_nodo · &lt;75% = squadra debole)</span></h2>")
    if cop["ist_summary"]:
        sotto_100_h = [r for r in cop["ist_summary"] if r["avg_pct"] < 100]
        cento_h     = [r for r in cop["ist_summary"] if r["avg_pct"] >= 100]
        if sotto_100_h:
            parts.append("<table><tr><th>istanza</th><th>coverage</th>"
                         "<th>n attacchi</th></tr>")
            for r in sotto_100_h:
                if r["avg_pct"] >= 100:
                    cls_c, tag = "pos", "✓"
                elif r["avg_pct"] >= 95:
                    cls_c, tag = "", "·"
                else:
                    cls_c, tag = "neg", "⚠"
                parts.append(
                    f"<tr><td>{r['ist']}</td>"
                    f"<td class='num {cls_c}'>{r['avg_pct']:.1f}% {tag}</td>"
                    f"<td class='num'>{r['n_attacchi']}</td></tr>"
                )
            parts.append("</table>")
        if cento_h:
            nomi_h = ", ".join(r["ist"] for r in cento_h)
            parts.append(f"<p style='color:#0a8000'>"
                         f"<b>{len(cento_h)} istanze al 100% ✓</b>: {nomi_h}</p>")
    else:
        parts.append("<p>nessun dato copertura per il giorno</p>")

    underprov = [r for r in cop["rows"] if r["verdict"] == "underprov"]
    if underprov:
        parts.append("<p><b style='color:#a00'>⚠ Squadre deboli per (ist, tipo)</b> "
                     "— nodo non chiuso, produzione ridotta:</p>")
        parts.append("<table><tr><th>istanza</th><th>tipo</th>"
                     "<th>coverage</th><th>n attacchi</th></tr>")
        for r in underprov[:8]:
            parts.append(
                f"<tr><td>{r['ist']}</td><td>{r['tipo']}</td>"
                f"<td class='num neg'>{r['avg_pct']:.1f}%</td>"
                f"<td class='num'>{r['n']}</td></tr>"
            )
        parts.append("</table>")

    # 10. EVENTI RILEVANTI (rev 10/05) — anomalie + alert + restart + HOME timeout
    parts.append("<h2>10. Eventi rilevanti</h2>")
    nc_h = len(eventi["cascade_events"])
    na_h = len(eventi["abort_events"])
    nf_h = len(eventi["fail_events"])
    n_problemi_h = nc_h + na_h + nf_h

    # Esiti istanza-tick
    if eventi["n_ist_ticks"] > 0:
        if n_problemi_h == 0:
            parts.append(
                f"<p style='color:#0a8000'>✓ <b>{eventi['n_ok_ticks']}/"
                f"{eventi['n_ist_ticks']}</b> istanza-tick completati senza errori</p>"
            )
        else:
            parts.append(
                f"<p>Esiti istanza-tick: {eventi['n_ok_ticks']} ok · "
                f"<span style='color:#a00'>{nc_h} cascade · {na_h} abort · "
                f"{nf_h} fail</span> (totale {eventi['n_ist_ticks']})</p>"
            )
        for label, lst in (("Cascade ADB", eventi["cascade_events"]),
                            ("Abort", eventi["abort_events"]),
                            ("Fail", eventi["fail_events"])):
            if lst:
                parts.append(f"<p><b style='color:#a00'>⚠ {label} "
                             f"({len(lst)}):</b></p>")
                parts.append("<table><tr><th>ciclo</th><th>istanza</th>"
                             "<th>ora UTC</th></tr>")
                for e in lst[:5]:
                    parts.append(
                        f"<tr><td class='num'>#{e['ciclo']}</td>"
                        f"<td>{e['ist']}</td><td>{e['start']}</td></tr>"
                    )
                parts.append("</table>")

    # Alert email del giorno
    alerts_h = eventi["alert_count_by_type"]
    if alerts_h:
        n_alerts_h = sum(alerts_h.values())
        det_h = ", ".join(f"{n}× {t}" for t, n in sorted(alerts_h.items(),
                                                          key=lambda x: -x[1]))
        parts.append(f"<p>Alert email inviati: <b>{n_alerts_h}</b> ({det_h})</p>")

    # Rifornimento skip master saturo
    if eventi["rif_skip_master"]:
        parts.append(
            f"<p>Rifornimento skip master saturo: "
            f"<b>{eventi['rif_skip_master']}</b> esecuzioni</p>"
        )

    # HOME stab timeout
    if eventi["n_home_timeout"]:
        det_ho = ", ".join(f"{ist}×{n}" for ist, n in
                            sorted(eventi["home_timeout_by_ist"].items(),
                                   key=lambda x: -x[1]))
        parts.append(
            f"<p style='color:#c80'>HOME stab timeout (vai_in_home FALLITO): "
            f"<b>{eventi['n_home_timeout']}</b> eventi ({det_ho})</p>"
        )

    # Bot restart
    if eventi["bot_restart_oggi"]:
        parts.append(f"<p>Bot restart: <b>1</b> "
                     f"(boot @ {eventi['boot_ts']} UTC)</p>")

    # 11. ANOMALIE TASK (rev 10/05) — aggregato per task + fail_rate + msg principale
    parts.append("<h2>11. Anomalie task</h2>")
    if anom["n_fail"] == 0 and not anom["top_anom"]:
        parts.append(
            f"<p style='color:#0a8000'>✓ Nessun task fail · nessuna anomalia "
            f"strutturata ({anom['n_events']} eventi totali)</p>"
        )
    else:
        rate_g_h = anom["n_fail"] / anom["n_events"] * 100 if anom["n_events"] else 0
        cls_g = "neg" if rate_g_h >= 5 else ""
        parts.append(
            f"<p>Task fail: <b class='{cls_g}'>{anom['n_fail']}</b> / "
            f"{anom['n_events']} eventi totali ({rate_g_h:.1f}%)</p>"
        )
        if anom["fail_per_task"]:
            parts.append("<table><tr><th>task</th><th>fail / esec</th>"
                         "<th>fail_rate</th><th>istanze</th>"
                         "<th>causa principale</th></tr>")
            for f in anom["fail_per_task"]:
                cls_r = "neg" if f["fail_rate"] >= 10 else ""
                msg_h = (f["top_msg"][:80] + "…") if len(f["top_msg"]) > 80 else f["top_msg"]
                msg_full = (f"\"{msg_h}\" <small>({f['top_msg_n']}× )</small>"
                            if msg_h else "—")
                parts.append(
                    f"<tr><td>{f['task']}</td>"
                    f"<td class='num'>{f['n_fail']} / {f['n_exec']}</td>"
                    f"<td class='num {cls_r}'>{f['fail_rate']:.1f}%</td>"
                    f"<td><small>{f['istanze']}</small></td>"
                    f"<td><small>{msg_full}</small></td></tr>"
                )
            parts.append("</table>")
        if anom["top_anom"]:
            parts.append("<p><b>Anomalie strutturate (top 5):</b></p>")
            parts.append("<table><tr><th>tipo</th><th>n</th></tr>")
            for tag, n in anom["top_anom"]:
                parts.append(f"<tr><td>{tag}</td><td class='num'>{n}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p style='color:#888'>Anomalie strutturate: nessuna</p>")

    # 12. DEPOSITO ATTUALE — snapshot live (non storico del giorno)
    parts.append("<h2>12. Deposito attuale</h2>")
    parts.append("<p style='color:#666;font-size:90%'>Ultima lettura nota "
                 "delle risorse in deposito per istanza (barra HOME, "
                 "aggiornata ad ogni avvio istanza) — snapshot live, non "
                 "uno storico del giorno del report.</p>")
    if deposito["n_ist"] == 0:
        parts.append("<p>nessuna lettura deposito disponibile</p>")
    else:
        parts.append("<table><tr><th>istanza</th><th>🍅 pomodoro</th>"
                     "<th>🪵 legno</th><th>⚙ acciaio</th><th>🛢 petrolio</th>"
                     "<th>aggiornato</th></tr>")
        for r in deposito["ordinarie"]:
            v = r["risorse"]
            parts.append(
                f"<tr><td>{r['nome']}</td>"
                f"<td class='num'>{_fmt_n(v['pomodoro'])}</td>"
                f"<td class='num'>{_fmt_n(v['legno'])}</td>"
                f"<td class='num'>{_fmt_n(v['acciaio'])}</td>"
                f"<td class='num'>{_fmt_n(v['petrolio'])}</td>"
                f"<td><small>{r['ts'][:16]}</small></td></tr>"
            )
        if deposito["master_row"]:
            r = deposito["master_row"]
            v = r["risorse"]
            parts.append(
                f"<tr style='background:#fff7d0'><td>{r['nome']} "
                f"<small>(master)</small></td>"
                f"<td class='num'>{_fmt_n(v['pomodoro'])}</td>"
                f"<td class='num'>{_fmt_n(v['legno'])}</td>"
                f"<td class='num'>{_fmt_n(v['acciaio'])}</td>"
                f"<td class='num'>{_fmt_n(v['petrolio'])}</td>"
                f"<td><small>{r['ts'][:16]}</small></td></tr>"
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
