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
from datetime import datetime, timedelta, timezone
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
    stima arrivo se disponibile tramite stima_tempo_raccolta().

    Ordine (richiesta utente 15/07): per RITARDO decrescente — `residuo_min`
    crescente, quindi i piu' negativi (in ritardo da piu' tempo) in testa, poi
    quelli ancora in volo per residuo crescente, infine le voci senza stima
    (`residuo_min is None`, cella con pochi campioni) in fondo.
    """
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

    righe.sort(key=lambda r: (r["residuo_min"] is None,
                              r["residuo_min"] if r["residuo_min"] is not None else 0.0,
                              r["instance"], r["ts_invio"]))
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


# Etichette risorsa per la matrice (dataset usa i nomi dei nodi).
_TIPO_LABEL = {"campo": "pomodoro", "segheria": "legno",
               "acciaio": "acciaio", "petrolio": "petrolio"}
# Ordine righe della matrice: 4 tipi × livelli 6/7 (8 righe fisse).
_MATRICE_RIGHE = [("campo", 6), ("campo", 7), ("segheria", 6), ("segheria", 7),
                  ("acciaio", 6), ("acciaio", 7), ("petrolio", 6), ("petrolio", 7)]
_MATRICE_N_BUCKET = 5


def get_stima_matrice() -> dict:
    """Pivot di get_stima_per_cella() in MATRICE: righe = (tipo, livello) in
    ordine fisso (8: pomodoro/legno/acciaio/petrolio × L6/L7), colonne =
    istanze. Ogni cella riporta i campi di get_stima_per_cella + `bucket`
    (0..N-1 = heat sequenziale sulla mediana, calcolato solo sulle celle
    affidabili, min/max delle mediane affidabili). Etichette: campo=pomodoro,
    segheria=legno.
    """
    celle = get_stima_per_cella()
    istanze = sorted({c["instance"] for c in celle})
    idx = {(c["instance"], c["tipo"], c["livello"]): c for c in celle}

    med_aff = [c["mediana_h"] for c in celle if c["affidabile"]]
    lo = min(med_aff) if med_aff else 0.0
    hi = max(med_aff) if med_aff else 1.0
    span = (hi - lo) or 1.0

    righe: list[dict] = []
    for tipo, liv in _MATRICE_RIGHE:
        riga_celle: dict[str, dict] = {}
        for ist in istanze:
            c = idx.get((ist, tipo, liv))
            if not c:
                continue
            bucket = None
            if c["affidabile"]:
                t = (c["mediana_h"] - lo) / span
                bucket = min(_MATRICE_N_BUCKET - 1, max(0, int(t * _MATRICE_N_BUCKET)))
            riga_celle[ist] = dict(c, bucket=bucket)
        righe.append({"tipo": tipo, "label": _TIPO_LABEL.get(tipo, tipo),
                      "livello": liv, "celle": riga_celle})

    return {"istanze": istanze, "righe": righe,
            "min_h": lo, "max_h": hi, "n_bucket": _MATRICE_N_BUCKET}


_RISORSE = ("pomodoro", "legno", "acciaio", "petrolio")

# WU200 finalità 2 (13/07) — produzione oraria unificata DAL TAB REPORT.
# WU204 (13/07): la logica di lettura/aggregazione è ora nel modulo canonico
# shared/produzione_report.py (riusato da dashboard + daily report + telegram).
# Qui resta solo lo shaping specifico del pannello (esclusione master,
# completamento colonne a zero, struttura di ritorno).
_PROD_WINDOW_H = 24.0


def get_produzione_unificata() -> dict:
    """Produzione oraria unificata (pom-eq) per istanza, per tipo di risorsa e
    totale farm, calcolata DAL TAB REPORT (WU200 finalità 2, 13/07).

    Somma le quantità REALMENTE raccolte dai nodi
    (report_raccolta_dataset.jsonl::quantita_totale) nelle ultime
    _PROD_WINDOW_H ore per (istanza, risorsa), pesate {pomodoro:1, legno:1,
    acciaio:2, petrolio:5}, e le normalizza a velocità oraria (Σ / finestra).

    Perché dal report e non da produzione_storico: la metrica delta-castello
    (compute_from_storico) somma `rifornimento_inviato` e sottrae `zaino_delta`,
    ed è quindi esposta ad anomalie enormi quando una spedizione di rifornimento
    o uno svuotamento zaino attraversa il deposito (es. FAU_00 = 209 M/h per un
    rifornimento_inviato di 999M petrolio pari al cap di config). Il report
    misura la resa diretta dei nodi raccolti → immune a rifornimento/zaino/OCR
    castello. Master (FauMorfeus) esclusa dagli aggregati.

    Struttura di ritorno invariata (endpoint/template non cambiano)."""
    from shared.instance_meta import is_master_instance
    from shared.produzione_report import produzione_per_istanza, PESI as _PESI

    prod = produzione_per_istanza(window_h=_PROD_WINDOW_H)["per_istanza"]

    # Colonne: tutte le istanze ordinarie note (config) + eventuali presenti nel
    # report, master esclusa. Istanze senza raccolte nella finestra → 0.
    try:
        from dashboard.services.config_manager import get_instances
        nomi_cfg = [i.get("nome") for i in (get_instances() or []) if i.get("nome")]
    except Exception:
        nomi_cfg = []
    istanze = sorted(set(nomi_cfg) | set(prod.keys()))

    per_istanza: list[dict] = []
    tot_qta: dict[str, float] = {r: 0.0 for r in _RISORSE}
    for inst in istanze:
        if is_master_instance(inst):
            continue
        p = prod.get(inst)
        if p:
            per_r = {r: {"qta_h": p["qta_h"].get(r, 0.0)} for r in _RISORSE}
            prod_unif_h = p["pom_eq_h"]
            for r in _RISORSE:
                tot_qta[r] += p["risorse"].get(r, 0.0)
        else:
            per_r = {r: {"qta_h": 0.0} for r in _RISORSE}
            prod_unif_h = 0.0
        per_istanza.append({
            "nome":        inst,
            "prod_unif_h": prod_unif_h,
            "per_risorsa": per_r,
        })

    totale_prod_unif_h = (sum(tot_qta[r] * _PESI[r] for r in _RISORSE)
                          / _PROD_WINDOW_H / 1_000_000)
    totale_per_risorsa = {
        r: {"qta_h":    tot_qta[r] / _PROD_WINDOW_H,
            "pom_eq_h": tot_qta[r] * _PESI[r] / _PROD_WINDOW_H / 1_000_000}
        for r in _RISORSE
    }

    return {
        "per_istanza":         per_istanza,
        "totale_prod_unif_h":  totale_prod_unif_h,
        "totale_per_risorsa":  totale_per_risorsa,
    }
