# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/report_raccolta_reader.py     WU200bis
#
#  Read-only — non scrive nessun file. Pannello di appoggio per la fase di
#  validazione di report_raccolta (WU199) e tempo_raccolta_estimator (WU200):
#  espone lo stato dei due dataset sorgente (occupazioni invio + report
#  completamento), il pool pending (raccoglitori "in volo") e gli ultimi
#  match riconciliati, incluso il tasso di mismatch livello_invio vs livello
#  (fonte di verità = report, vedi shared/tempo_raccolta_estimator.py).
#
#  API pubblica:
#    get_riepilogo()            -> dict   statistiche aggregate + config TTL/retention
#    get_occupati_in_volo()     -> list   raccoglitori pending (non ancora matchati)
#    get_ultimi_eventi(n)       -> list   merge invii+completamenti, ordine cronologico inverso
#    get_stima_per_cella()      -> list   tempo raccolta aggregato per (istanza, tipo, livello)
#    get_produzione_unificata() -> dict   prod. oraria unificata per istanza + totali farm
# ==============================================================================

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT      = Path(__file__).parent.parent.parent
_PROD_ROOT = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_DATA_DIR  = _PROD_ROOT / "data"

_PATH_OCCUPAZIONI = _DATA_DIR / "nodi_mappa_observations.jsonl"
_PATH_REPORT      = _DATA_DIR / "report_raccolta_dataset.jsonl"
_PATH_MATCH       = _DATA_DIR / "tempo_raccolta_dataset.jsonl"
_PATH_STATE       = _DATA_DIR / "tempo_raccolta_match_state.json"


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _load_state() -> dict:
    if not _PATH_STATE.exists():
        return {"pending": {}}
    try:
        return json.loads(_PATH_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": {}}


def _ts_local_hhmm(ts: str) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%H:%M")
    except Exception:
        return ts[11:16] if len(ts) >= 16 else "—"


def _ts_local_full(ts: str) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%d/%m %H:%M")
    except Exception:
        return ts


def get_riepilogo() -> dict:
    """Statistiche aggregate sui due dataset sorgente + dataset match,
    più i parametri di configurazione correnti (TTL orfane, retention)."""
    from shared.tempo_raccolta_estimator import TTL_ORFANE_ORE, RETENTION_GIORNI

    occupazioni = [o for o in _load_jsonl(_PATH_OCCUPAZIONI) if o.get("esito") == "occupato"]
    report = _load_jsonl(_PATH_REPORT)
    match = _load_jsonl(_PATH_MATCH)
    state = _load_state()
    pending = state.get("pending", {})
    pending_attuali = sum(len(v) for v in pending.values())

    con_livello_invio = [m for m in match if m.get("livello_invio") is not None]
    mismatch = [m for m in con_livello_invio if m.get("livello_invio") != m.get("livello")]
    mismatch_pct = (100 * len(mismatch) / len(con_livello_invio)) if con_livello_invio else None

    return {
        "occupazioni_totali": len(occupazioni),
        "report_totali":      len(report),
        "match_totali":       len(match),
        "pending_attuali":    pending_attuali,
        "mismatch_campioni":  len(con_livello_invio),
        "mismatch_count":     len(mismatch),
        "mismatch_pct":       mismatch_pct,
        "ttl_orfane_ore":     TTL_ORFANE_ORE,
        "retention_giorni":   RETENTION_GIORNI,
    }


def get_occupati_in_volo() -> list[dict]:
    """Raccoglitori attualmente in volo (occupazioni pending, non ancora
    abbinate a un report di completamento). Una voce per occupazione, con
    stima arrivo se disponibile tramite stima_tempo_raccolta()."""
    from shared.tempo_raccolta_estimator import stima_tempo_raccolta

    state = _load_state()
    pending: dict = state.get("pending", {})
    ora = datetime.now(timezone.utc)

    righe: list[dict] = []
    for key, voci in pending.items():
        parti = key.split("|")
        if len(parti) != 3:
            continue
        instance, coordinata, tipo = parti
        for v in voci:
            ts_invio = v.get("ts")
            livello = v.get("livello")
            if not ts_invio:
                continue
            try:
                dt_invio = datetime.fromisoformat(ts_invio)
            except Exception:
                continue
            elapsed_min = (ora - dt_invio).total_seconds() / 60

            stima_s = None
            if isinstance(livello, int):
                stima_s = stima_tempo_raccolta(instance, tipo, livello)
            stima_min = stima_s / 60 if stima_s is not None else None
            residuo_min = (stima_min - elapsed_min) if stima_min is not None else None

            righe.append({
                "instance":       instance,
                "coordinata":     coordinata,
                "tipo":           tipo,
                "livello":        livello,
                "ts_invio":       ts_invio,
                "partenza_local": _ts_local_hhmm(ts_invio),
                "elapsed_min":    elapsed_min,
                "stima_min":      stima_min,
                "residuo_min":    residuo_min,
            })

    righe.sort(key=lambda r: (r["instance"], r["ts_invio"]))
    return righe


def get_ultimi_eventi(n: int = 15) -> list[dict]:
    """Merge cronologico inverso degli ultimi N eventi invio (occupazione)
    e completamento (report), per un colpo d'occhio sul flusso live."""
    occupazioni = [o for o in _load_jsonl(_PATH_OCCUPAZIONI) if o.get("esito") == "occupato"]
    report = _load_jsonl(_PATH_REPORT)

    eventi: list[dict] = []
    for o in occupazioni:
        ts = o.get("ts")
        if not ts:
            continue
        eventi.append({
            "ts": ts, "tipo_evento": "invio",
            "instance": o.get("instance"), "coordinata": o.get("chiave"),
            "tipo": o.get("tipo"), "livello": o.get("livello"),
            "dettaglio": None,
        })
    for r in report:
        ts = r.get("ts_raccolta")
        if not ts:
            continue
        qta = r.get("quantita_totale")
        eventi.append({
            "ts": ts, "tipo_evento": "completamento",
            "instance": r.get("instance"), "coordinata": r.get("coordinata"),
            "tipo": r.get("tipo"), "livello": r.get("livello"),
            "dettaglio": f"{qta:,}".replace(",", ".") if isinstance(qta, (int, float)) else None,
        })

    eventi.sort(key=lambda e: e["ts"], reverse=True)
    eventi = eventi[:n]
    for e in eventi:
        e["ts_local"] = _ts_local_full(e["ts"])
    return eventi


def get_stima_per_cella() -> list[dict]:
    """Tempo di raccolta stimato per cella (istanza, tipo, livello),
    aggregando l'intero dataset match — mediana/media/range/n campioni.
    Rappresentazione compatta per confronto rapido fra istanze, stessa
    granularità e stessa soglia di affidabilità (MIN_CAMPIONI_CELLA) usate
    da stima_tempo_raccolta() in shared/tempo_raccolta_estimator.py."""
    from shared.tempo_raccolta_estimator import MIN_CAMPIONI_CELLA

    match = _load_jsonl(_PATH_MATCH)
    celle: dict[tuple, list[float]] = {}
    for m in match:
        instance = m.get("instance")
        tipo = m.get("tipo")
        livello = m.get("livello")
        durata_s = m.get("durata_s")
        if not instance or not tipo or livello is None or not isinstance(durata_s, (int, float)):
            continue
        celle.setdefault((instance, tipo, livello), []).append(durata_s)

    righe: list[dict] = []
    for (instance, tipo, livello), durate in celle.items():
        n = len(durate)
        righe.append({
            "instance":   instance,
            "tipo":       tipo,
            "livello":    livello,
            "n":          n,
            "mediana_h":  statistics.median(durate) / 3600,
            "media_h":    (sum(durate) / n) / 3600,
            "min_h":      min(durate) / 3600,
            "max_h":      max(durate) / 3600,
            "affidabile": n >= MIN_CAMPIONI_CELLA,
        })
    righe.sort(key=lambda r: (r["instance"], r["tipo"], r["livello"]))
    return righe


_RISORSE = ("pomodoro", "legno", "acciaio", "petrolio")


def get_produzione_unificata() -> dict:
    """Produzione oraria unificata (pom-eq) per istanza e per tipo di
    risorsa, e totale farm — riusa la stessa metrica già in produzione su
    /ui (get_produzione_istanze -> shared/prod_unificata.py): finestra
    fissa 24h su produzione_storico (sessioni chiuse), pesi
    {pomodoro:1, legno:1, acciaio:2, petrolio:5}. Master esclusa
    (produzione_qty include risorse ricevute da alleati via rifornimento,
    non produzione interna castello) — stessa convenzione di
    get_risorse_farm()/prod_unif_agg in dashboard/app.py.

    prod_unif_h è già una velocità oraria (Σpom_eq nella finestra 24h / 24)
    nonostante il nome storico — non richiede ulteriore normalizzazione."""
    from dashboard.services.stats_reader import get_produzione_istanze

    dati = get_produzione_istanze(include_master=False)

    per_istanza: list[dict] = []
    tot_pom_eq = 0
    tot_per_risorsa: dict[str, dict] = {r: {"qta_tot": 0, "pom_eq": 0} for r in _RISORSE}

    for entry in dati:
        pu = entry.get("prod_unificata") or {}
        pom_eq_tot = int(pu.get("pom_eq_totale", 0) or 0)
        per_r_raw = pu.get("per_risorsa") or {}
        per_r: dict[str, dict] = {}
        for r in _RISORSE:
            v = per_r_raw.get(r) or {}
            qta = int(v.get("qta_tot", 0) or 0)
            pe = int(v.get("pom_eq", 0) or 0)
            per_r[r] = {"qta_h": qta / 24.0}
            tot_per_risorsa[r]["qta_tot"] += qta
            tot_per_risorsa[r]["pom_eq"] += pe
        prod_unif_h = float(pu.get("prod_unif_h", -1.0) or -1.0)
        per_istanza.append({
            "nome":         entry.get("nome"),
            "prod_unif_h":  prod_unif_h if prod_unif_h > 0 else 0.0,
            "per_risorsa":  per_r,
        })
        tot_pom_eq += pom_eq_tot

    per_istanza.sort(key=lambda r: r["nome"] or "")

    totale_prod_unif_h = tot_pom_eq / 24.0 / 1_000_000
    totale_per_risorsa = {
        r: {"qta_h": tot_per_risorsa[r]["qta_tot"] / 24.0,
            "pom_eq_h": tot_per_risorsa[r]["pom_eq"] / 24.0 / 1_000_000}
        for r in _RISORSE
    }

    return {
        "per_istanza":         per_istanza,
        "totale_prod_unif_h":  totale_prod_unif_h,
        "totale_per_risorsa":  totale_per_risorsa,
    }
