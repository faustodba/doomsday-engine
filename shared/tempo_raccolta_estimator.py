# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/tempo_raccolta_estimator.py               WU200
#
#  Stimatore empirico del tempo di raccolta reale per (istanza, tipo,
#  livello), incrociando due dataset indipendenti costruiti in
#  parallelo, entrambi già attivi:
#    - data/nodi_mappa_observations.jsonl (esito="occupato") — evento
#      INVIO, scritto da tasks/raccolta.py quando una marcia è confermata
#      (hook WU177, riattivato WU199septies 10/07).
#    - data/report_raccolta_dataset.jsonl — evento COMPLETAMENTO, letto
#      dal tab Report in-game (shared/report_raccolta.py, WU199).
#
#  Analisi esplorativa 11/07 (script one-off, non questo modulo) su 89
#  righe report / 191 occupazioni: 82 match (92%), mediane per (tipo,
#  livello) già più alte della stima statica attuale (~2h per L7 in
#  reference_capacita_nodi) — e soprattutto DIVERSE per istanza (FAU_00
#  ~30-35% più veloce delle altre 11, coerente con essere l'istanza più
#  sviluppata). Da qui la granularità (istanza, tipo, livello), non solo
#  (tipo, livello).
#
#  ARCHITETTURA (richiesta esplicita utente 10/07): "il match deve essere
#  non nel task ma lanciato periodicamente" — questo modulo NON viene mai
#  chiamato da tasks/raccolta.py o da shared/report_raccolta.py. Va
#  invocato da un loop periodico esterno (dashboard, vedi
#  dashboard/app.py::_tempo_raccolta_loop, pattern identico a
#  _nodi_mappa_rebuild_loop/_predictor_recorder_loop).
#
#  MATCH: per ogni riga report non ancora abbinata, cerca nel pool delle
#  occupazioni pending (stessa chiave instance|coordinata) quella con
#  ts_invio più recente MA precedente a ts_raccolta. L'occupazione usata
#  viene rimossa dal pool (mai riusata per un match successivo) — evita
#  il rischio segnalato dall'utente 10/07: nodo che si ricrea alla stessa
#  coordinata/tipo/livello e viene occupato una seconda volta prima che
#  la prima occupazione trovi il suo match.
#
#  STATO: data/tempo_raccolta_match_state.json — cursori byte sui due
#  dataset sorgente (append-only, si leggono solo le righe nuove da un
#  run al successivo) + pool delle occupazioni pending non ancora
#  abbinate. Persistente, non uno scan stateless ogni volta.
#
#  PRUNING: un'occupazione senza match entro TTL_ORFANE_ORE (default 4h,
#  richiesta utente 11/07) viene rimossa dal pool — altrimenti resterebbe
#  a rischiare un match errato con un'occupazione successiva sullo stesso
#  nodo. Run frequenti (15 min, vedi dashboard/app.py) riducono
#  ulteriormente la finestra di rischio.
#
#  RETENTION: pota_dataset_vecchio() rimuove dal dataset di output le
#  righe più vecchie di RETENTION_GIORNI (default 15, richiesta utente
#  11/07 — poca variabilità attesa nel tempo di raccolta reale, non serve
#  storia lunga). Chiamata giornalmente dal loop dashboard.
#
#  OUTPUT: data/tempo_raccolta_dataset.jsonl (append-only) —
#  {ts_match, instance, coordinata, tipo, livello, ts_invio, ts_raccolta,
#   durata_s}
#
#  CONSUMO: stima_tempo_raccolta(instance, tipo, livello) — mediana per
#  la cella (istanza, tipo, livello) se ci sono abbastanza campioni,
#  fallback a (tipo, livello) globale, poi None (il chiamante userà la
#  stima statica esistente). Non ancora collegato al predictor — lo sarà
#  quando ci saranno abbastanza campioni per cella (memoria
#  project_tempo_raccolta_estimator).
# ==============================================================================

from __future__ import annotations

import json
import os
import statistics
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_lock = threading.Lock()

TTL_ORFANE_ORE = 4.0   # WU200bis (11/07, richiesta utente): oltre il max
                        # osservato finora (~4.3h) ma stretto — poca
                        # variabilita' attesa nei tempi di raccolta
RETENTION_GIORNI = 15   # WU200bis: poca variabilita' attesa nel tempo,
                        # non serve conservare storia lunga
MIN_CAMPIONI_CELLA = 3


def _root_dir() -> Path:
    root = os.environ.get("DOOMSDAY_ROOT")
    return Path(root) if root else Path(os.getcwd())


def _path_occupazioni() -> Path:
    return _root_dir() / "data" / "nodi_mappa_observations.jsonl"


def _path_report() -> Path:
    return _root_dir() / "data" / "report_raccolta_dataset.jsonl"


def _path_output() -> Path:
    p = _root_dir() / "data" / "tempo_raccolta_dataset.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _path_state() -> Path:
    return _root_dir() / "data" / "tempo_raccolta_match_state.json"


def _carica_stato() -> dict:
    p = _path_state()
    if not p.exists():
        return {"cursor_occupazioni": 0, "cursor_report": 0, "pending": {}}
    try:
        stato = json.loads(p.read_text(encoding="utf-8"))
        stato.setdefault("cursor_occupazioni", 0)
        stato.setdefault("cursor_report", 0)
        stato.setdefault("pending", {})
        return stato
    except Exception:
        return {"cursor_occupazioni": 0, "cursor_report": 0, "pending": {}}


def _salva_stato(state: dict) -> None:
    p = _path_state()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _leggi_righe_nuove(path: Path, cursor: int) -> tuple[list[dict], int]:
    """Legge le righe JSONL nuove a partire dall'offset byte `cursor`.

    Best-effort: l'ultima riga, se priva di newline finale (scrittura
    concorrente in corso da parte del bot), viene esclusa e il cursore
    NON avanza oltre l'ultima riga completa — verrà riletta al prossimo
    passaggio. Righe malformate vengono scartate silenziosamente (il
    cursore avanza comunque, non sono recuperabili in altro modo).

    Ritorna (righe_parsate, nuovo_cursor).
    """
    if not path.exists():
        return [], cursor
    with path.open("rb") as f:
        f.seek(cursor)
        raw = f.read()
    if not raw:
        return [], cursor

    righe: list[dict] = []
    pos = 0
    testo = raw.decode("utf-8", errors="replace")
    for line in testo.splitlines(keepends=True):
        if not line.endswith("\n"):
            break
        pos += len(line.encode("utf-8"))
        stripped = line.strip()
        if not stripped:
            continue
        try:
            righe.append(json.loads(stripped))
        except Exception:
            continue
    return righe, cursor + pos


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def esegui_riconciliazione(ttl_ore: float = TTL_ORFANE_ORE) -> dict:
    """Un passo di riconciliazione: legge le righe nuove da entrambi i
    dataset sorgente, abbina, scrive i match, pota le occupazioni orfane
    scadute. Mai solleva eccezioni — best-effort, pensata per un loop
    periodico che deve continuare a girare anche in caso di errore
    transitorio (file assente, JSON corrotto, ecc.).
    """
    esito = {"match_nuovi": 0, "report_orfane": 0, "occupazioni_potate": 0,
              "pending_attuali": 0, "errore": None}
    try:
        with _lock:
            state = _carica_stato()
            pending: dict[str, list[dict]] = state["pending"]

            ora = datetime.now(timezone.utc)

            nuove_occ, nuovo_cursor_occ = _leggi_righe_nuove(
                _path_occupazioni(), state["cursor_occupazioni"])
            for o in nuove_occ:
                if o.get("esito") != "occupato":
                    continue
                ts = o.get("ts")
                instance = o.get("instance")
                chiave = o.get("chiave")
                if not ts or not instance or not chiave:
                    continue
                key = f"{instance}|{chiave}"
                pending.setdefault(key, []).append({
                    "ts": ts, "tipo": o.get("tipo"), "livello": o.get("livello"),
                })

            # WU200quater (11/07) — MATCH prima della potatura, non dopo.
            # Bug reale trovato dall'utente: se un'occupazione e il suo
            # report arrivano entrambi nello stesso batch di lettura (tipico
            # al primo run "di recupero" su storico già accumulato, o dopo
            # un'interruzione del loop), potare per età PRIMA di aver
            # provato il match eliminava occupazioni che avevano già un
            # completamento valido e recente nello stesso batch — coppie
            # perse per sempre nonostante fossero abbinabili. Ora si tenta
            # SEMPRE il match contro tutto il pool corrente (indipendente
            # dall'età) prima di scartare qualunque cosa.
            nuove_report, nuovo_cursor_report = _leggi_righe_nuove(
                _path_report(), state["cursor_report"])

            nuovi_match = []
            for r in nuove_report:
                ts_racc_raw = r.get("ts_raccolta")
                instance = r.get("instance")
                coordinata = r.get("coordinata")
                if not ts_racc_raw or not instance or not coordinata:
                    continue
                try:
                    ts_racc = _parse_ts(ts_racc_raw)
                except Exception:
                    continue

                key = f"{instance}|{coordinata}"
                candidati = pending.get(key, [])
                best = None
                best_ts = None
                for o in candidati:
                    try:
                        ts_o = _parse_ts(o["ts"])
                    except Exception:
                        continue
                    if ts_o < ts_racc and (best_ts is None or ts_o > best_ts):
                        best = o
                        best_ts = ts_o

                if best is None:
                    esito["report_orfane"] += 1
                    continue

                durata_s = (ts_racc - best_ts).total_seconds()
                nuovi_match.append({
                    "ts_match": ora.isoformat(),
                    "instance": instance,
                    "coordinata": coordinata,
                    "tipo": r.get("tipo"),
                    "livello": r.get("livello"),
                    "ts_invio": best["ts"],
                    "ts_raccolta": ts_racc_raw,
                    "durata_s": durata_s,
                })
                candidati.remove(best)
                if not candidati:
                    pending.pop(key, None)
                esito["match_nuovi"] += 1

            if nuovi_match:
                lines = [json.dumps(m, ensure_ascii=False) for m in nuovi_match]
                with _path_output().open("a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

            # Pruning TTL — SOLO ora, su ciò che resta invenduto dopo il
            # match. Un'occupazione senza match entro TTL_ORFANE_ORE non è
            # più abbinabile in modo affidabile (rischio respawn nodo).
            potate = 0
            for key in list(pending.keys()):
                vive = []
                for o in pending[key]:
                    try:
                        eta_h = (ora - _parse_ts(o["ts"])).total_seconds() / 3600
                    except Exception:
                        potate += 1
                        continue
                    if eta_h < ttl_ore:
                        vive.append(o)
                    else:
                        potate += 1
                if vive:
                    pending[key] = vive
                else:
                    pending.pop(key, None)
            esito["occupazioni_potate"] = potate

            state["cursor_occupazioni"] = nuovo_cursor_occ
            state["cursor_report"] = nuovo_cursor_report
            state["pending"] = pending
            _salva_stato(state)
            esito["pending_attuali"] = sum(len(v) for v in pending.values())
    except Exception as exc:
        esito["errore"] = str(exc)
    return esito


def pota_dataset_vecchio(giorni: float = RETENTION_GIORNI) -> dict:
    """Rimuove dal dataset di output (WU200bis, 11/07) le righe con
    `ts_match` più vecchio di `giorni`. Poca variabilità attesa nel tempo
    di raccolta reale (dipende da ricerche/bonus dell'istanza, cambia
    raramente) — non serve conservare storia lunga, mantiene il dataset
    piccolo e la stima aggiornata sui dati recenti.

    Best-effort: righe che non si riescono a interpretare vengono
    conservate (mai perdere dati per un errore di parsing).
    Ritorna {"rimosse": N, "rimaste": N}.
    """
    path = _path_output()
    if not path.exists():
        return {"rimosse": 0, "rimaste": 0}

    limite = datetime.now(timezone.utc) - timedelta(days=giorni)
    tenute: list[str] = []
    rimosse = 0
    with _lock:
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        rec = json.loads(stripped)
                        ts = _parse_ts(rec["ts_match"])
                    except Exception:
                        tenute.append(stripped)
                        continue
                    if ts >= limite:
                        tenute.append(stripped)
                    else:
                        rimosse += 1
        except Exception:
            return {"rimosse": 0, "rimaste": 0}

        if rimosse:
            tmp = path.with_suffix(".tmp")
            contenuto = "\n".join(tenute) + ("\n" if tenute else "")
            tmp.write_text(contenuto, encoding="utf-8")
            os.replace(tmp, path)

    return {"rimosse": rimosse, "rimaste": len(tenute)}


def stima_tempo_raccolta(instance: str, tipo: str, livello: int,
                          min_campioni: int = MIN_CAMPIONI_CELLA) -> Optional[float]:
    """Stima in secondi il tempo di raccolta atteso per (istanza, tipo,
    livello), mediana delle osservazioni reali. Fallback a granularità
    più larga (tipo+livello, tutte le istanze insieme) se i campioni per
    la cella specifica sono insufficienti. None se anche il fallback non
    ha abbastanza dati — il chiamante userà la stima statica esistente.
    """
    path = _path_output()
    if not path.exists():
        return None
    cella: list[float] = []
    globale: list[float] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("tipo") != tipo or rec.get("livello") != livello:
                    continue
                durata = rec.get("durata_s")
                if not isinstance(durata, (int, float)):
                    continue
                globale.append(durata)
                if rec.get("instance") == instance:
                    cella.append(durata)
    except Exception:
        return None

    if len(cella) >= min_campioni:
        return statistics.median(cella)
    if len(globale) >= min_campioni:
        return statistics.median(globale)
    return None
