# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/stats_reader.py
#
#  Read-only — non scrive nessun file.
#  Legge e aggrega dati di stato/statistiche per la dashboard.
#
#  Fonti:
#    - engine_status.json  : stato live engine + storico eventi
#    - state/<nome>.json   : stato persistito per istanza (schedule, metrics,
#                            rifornimento, daily_tasks, boost/vip/arena su prod)
#    - runtime_overrides   : tipologia / abilitata per istanza (via config_manager)
#    - instances.json      : elenco istanze (via config_manager, read-only)
#
#  API pubblica:
#    get_engine_status()           -> EngineStatus
#    get_instance_stats(nome)      -> InstanceStats
#    get_all_stats()               -> list[InstanceStats]
#    get_storico(n=50)             -> list[StoricoEntry]
#    get_risorse_farm()            -> RisorseFarm
#
#  Nota: nessun filtro per nome (es. startswith "FAU_") o per flag `abilitata`.
#  Tutte le istanze presenti in instances.json vengono aggregate. Le eventuali
#  istanze senza state/<nome>.json vengono saltate automaticamente (state vuoto).
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dashboard.models import (
    EngineStatus, IstanzaStatus, StoricoEntry,
    InstanceStats, TickStats, RaccoltaStats, TipologiaIstanza,
)
from dashboard.services.config_manager import get_overrides, get_instances


# ==============================================================================
# Path costanti — coerenti con main.py (_ROOT/...)
# ==============================================================================
_ROOT          = Path(__file__).parent.parent.parent
_PROD_ROOT     = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_ENGINE_STATUS = _PROD_ROOT / "engine_status.json"
_STATE_DIR     = _PROD_ROOT / "state"
_LOGS_DIR      = _PROD_ROOT / "logs"
_MORFEUS_STATE = _PROD_ROOT / "data" / "morfeus_state.json"

# Soglia anti-falso-positivo OCR (Issue #16: legno=999M da FAU_10).
# Una singola spedizione reale non supera mai 100M.
_MAX_QTA_SPEDIZIONE = 100_000_000  # 100M

# Risorse gestite — garantisce presenza nel dict anche se non inviate
_RISORSE_STANDARD = ("pomodoro", "legno", "acciaio", "petrolio")


# ==============================================================================
# Modelli aggregati risorse farm
# ==============================================================================

@dataclass
class RifornimentoIstanza:
    """Dati rifornimento di una singola istanza (da state/<nome>.json)."""
    nome:                  str
    spedizioni_oggi:       int
    quota_max_per_ciclo:   int
    provviste_residue:     int                        # LORDO (OCR raw)
    provviste_residue_netta: int                      # = lordo × (1 - tassa_pct_avg)
    provviste_esaurite:    bool
    tassa_pct_avg:         float = 0.23
    inviato_oggi:          Dict[str, int] = field(default_factory=dict)


@dataclass
class MorfeusState:
    """
    Capienza giornaliera residua del destinatario (FauMorfeus).
    Letto da data/morfeus_state.json — aggiornato dall'ultima istanza che
    apre la maschera di invio.
    """
    daily_recv_limit: int    = -1            # -1 = mai letto
    ts:               str    = ""            # ISO ts ultimo update
    letto_da:         str    = ""            # nome istanza che ha letto
    tassa_pct:        float  = 0.0


@dataclass
class RisorseFarm:
    """
    Aggregato risorse per tutte le istanze con state persistito.

    Campi:
      - inviato_per_risorsa     : totale inviato oggi per risorsa (NETTO)
                                  Fonte: dettaglio_oggi[*].qta_inviata
      - provviste_residue       : somma provviste residue LORDE (OCR raw)
      - provviste_residue_netta : somma provviste residue NETTE (post-tassa stimata)
      - spedizioni_oggi         : somma spedizioni oggi (cumulativo giornaliero)
      - quota_max_per_ciclo     : somma quota_max per-ciclo tutte istanze
      - istanze_detail          : lista RifornimentoIstanza
      - produzione_per_ora      : somma metrics.*_per_ora da tutte le istanze
      - morfeus                 : stato globale destinatario (Daily Receiving Limit)
    """
    inviato_per_risorsa:    Dict[str, int]             = field(default_factory=dict)
    provviste_residue:      int                         = 0
    provviste_residue_netta: int                        = 0
    spedizioni_oggi:        int                         = 0
    quota_max_per_ciclo:    int                         = 0
    istanze_detail:         List[RifornimentoIstanza]  = field(default_factory=list)
    produzione_per_ora:     Dict[str, float]            = field(default_factory=dict)
    morfeus:                MorfeusState                = field(default_factory=MorfeusState)


# ==============================================================================
# Helpers interni
# ==============================================================================

def _load_engine_status() -> EngineStatus:
    es = EngineStatus.load(_ENGINE_STATUS)
    for nome, ist in es.istanze.items():
        ist.nome = nome
    return es


# ==============================================================================
# WU56 — Storico produzione/ora ultime 24h aggregato per finestra oraria
# ==============================================================================

def get_produzione_storico_24h(hours: int = 12) -> dict:
    """
    Aggrega produzione_oraria delle ultime `hours` ore (default 12) da tutte
    le istanze. Default 12h per limitare larghezza sparkline in sidebar.

    Per ogni ora UTC degli ultimi `hours`:
      - Trova sessioni con ts_fine in quella finestra
      - Somma produzione_oraria per risorsa (mantiene magnitudo della farm)
      - Se nessuna sessione in quella ora, valore = 0 (gap)

    Returns:
        {
            "ore":       ["HH:00", ...],
            "serie":     {pomodoro: [v..], legno, acciaio, petrolio},
            "media_24h": {pomodoro, legno, acciaio, petrolio},
            "min_24h":   {pomodoro, ...},
            "max_24h":   {pomodoro, ...},
            "samples":   int,
            "window_h":  int,   # finestra effettiva (era 24h, ora default 12h)
        }
    """
    from datetime import datetime, timedelta, timezone
    h_window = max(1, min(48, int(hours)))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=h_window)

    # Inizializza N bin orari (chiavi: ora UTC inizio finestra)
    bins: Dict[str, Dict[str, float]] = {}
    bin_count: Dict[str, int] = {}
    for h in range(h_window):
        bin_dt  = (now - timedelta(hours=h_window - 1 - h)).replace(minute=0, second=0, microsecond=0)
        key = bin_dt.strftime("%Y-%m-%dT%H")
        bins[key] = {r: 0.0 for r in _RISORSE_STANDARD}
        bin_count[key] = 0

    from shared.instance_meta import is_master_instance
    samples_total = 0
    insts = get_instances() if callable(get_instances) else []
    for ist in insts:
        nome = ist.get("nome", "")
        if not nome:
            continue
        if is_master_instance(nome):
            continue   # Master fuori dagli aggregati ordinari
        state = _load_state(nome)
        if not state:
            continue
        for sess in state.get("produzione_storico", []) or []:
            ts_fine = sess.get("ts_fine")
            if not ts_fine:
                continue
            try:
                t = datetime.fromisoformat(ts_fine)
            except Exception:
                continue
            if t < window_start or t > now:
                continue
            po = sess.get("produzione_oraria") or {}
            if not po:
                continue
            bin_key = t.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H")
            if bin_key not in bins:
                continue
            for r in _RISORSE_STANDARD:
                v = po.get(r, 0)
                if v and v > 0:
                    bins[bin_key][r] += float(v)
            bin_count[bin_key] += 1
            samples_total += 1

    # Ordina chiavi cronologicamente
    keys_sorted = sorted(bins.keys())
    ore_labels = [k[11:13] + ":00" for k in keys_sorted]

    serie: Dict[str, list] = {r: [] for r in _RISORSE_STANDARD}
    for k in keys_sorted:
        for r in _RISORSE_STANDARD:
            serie[r].append(round(bins[k][r], 0))

    # Statistiche aggregato
    media_24h: Dict[str, float] = {}
    min_24h:   Dict[str, float] = {}
    max_24h:   Dict[str, float] = {}
    for r in _RISORSE_STANDARD:
        vals = [v for v in serie[r] if v > 0]
        if vals:
            media_24h[r] = round(sum(vals) / len(vals), 0)
            min_24h[r]   = round(min(vals), 0)
            max_24h[r]   = round(max(vals), 0)
        else:
            media_24h[r] = 0.0
            min_24h[r]   = 0.0
            max_24h[r]   = 0.0

    return {
        "ore":       ore_labels,
        "serie":     serie,
        "media_24h": media_24h,
        "min_24h":   min_24h,
        "max_24h":   max_24h,
        "samples":   samples_total,
        "window_h":  h_window,
    }


def _load_storico_farm_today(istanza: str) -> Optional[dict]:
    """
    Legge entry odierna per istanza da data/storico_farm.json.
    Fonte di verità DAILY scritta ad ogni spedizione (sopravvive ai reset state).
    Returns None se file mancante o nessun dato per oggi/istanza.
    """
    try:
        from datetime import datetime, timezone
        path = _PROD_ROOT / "data" / "storico_farm.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        today = datetime.now(timezone.utc).date().isoformat()
        return d.get(today, {}).get(istanza)
    except Exception:
        return None


def _load_storico_truppe() -> dict:
    """
    Legge data/storico_truppe.json. Schema:
      {"FAU_00": [{"data":"YYYY-MM-DD","total_squads":N,"ts":"..."}, ...], ...}
    Ritorna {} se file mancante o malformato.
    """
    try:
        path = _PROD_ROOT / "data" / "storico_truppe.json"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_truppe_istanza(nome: str) -> dict:
    """
    WU66 (Layout A) — dati truppe per card istanza.
    Returns dict con:
      - oggi:        int | None   (ultimo total_squads se data == today UTC)
      - sette_gg_fa: int | None   (entry con data == today-7d, se esiste)
      - delta:       int | None   (oggi - sette_gg_fa, se entrambi presenti)
      - delta_pct:   float | None
      - serie_7d:    list[int|None] (ultimi 7 giorni cronologici, fill con None)
    """
    from datetime import date, timedelta
    storico = _load_storico_truppe()
    entries = storico.get(nome) or []
    today = date.today()  # UTC dipende dal context — usiamo locale del server (= UTC docker, locale dev)
    # _today_utc() del modulo troops_reader usa UTC, ricalcolo manuale
    from datetime import datetime, timezone
    today_utc = datetime.now(timezone.utc).date()

    # mappa data -> total_squads per accesso O(1)
    by_date: dict[str, int] = {}
    for e in entries:
        try:
            by_date[e["data"]] = int(e["total_squads"])
        except Exception:
            continue

    oggi_iso = today_utc.isoformat()
    sette_iso = (today_utc - timedelta(days=7)).isoformat()

    oggi        = by_date.get(oggi_iso)
    sette_gg_fa = by_date.get(sette_iso)
    delta = (oggi - sette_gg_fa) if (oggi is not None and sette_gg_fa is not None) else None
    delta_pct = (
        round(delta / sette_gg_fa * 100, 1)
        if delta is not None and sette_gg_fa
        else None
    )

    # serie_7d: 7 valori cronologici, oggi-6 .. oggi
    serie_7d: list[Optional[int]] = []
    for d in range(6, -1, -1):
        iso = (today_utc - timedelta(days=d)).isoformat()
        serie_7d.append(by_date.get(iso))

    return {
        "oggi":        oggi,
        "sette_gg_fa": sette_gg_fa,
        "delta":       delta,
        "delta_pct":   delta_pct,
        "serie_7d":    serie_7d,
    }


def get_truppe_storico_aggregato(days: int = 8) -> dict:
    """
    WU66 (Layout B) — pannello storico truppe.
    Ritorna dict con:
      - per_istanza: list[dict] per ogni istanza, ognuno = output di
                     get_truppe_istanza(nome) + nome
      - totale:      dict con somme {oggi, sette_gg_fa, delta, delta_pct,
                     serie_<days>}, basato sulle istanze con dati validi
      - days:        finestra temporale (default 8 = oggi + 7 indietro)
      - data_oggi:   ISO YYYY-MM-DD UTC

    Mostra TUTTE le istanze in instances.json (incluso disabilitate +
    quelle senza storico) — riga vuota se nessun dato registrato.
    """
    from datetime import datetime, timezone, timedelta
    storico = _load_storico_truppe()
    today_utc = datetime.now(timezone.utc).date()

    # serie da considerare: oggi-(days-1) .. oggi
    iso_seq = [
        (today_utc - timedelta(days=d)).isoformat()
        for d in range(days - 1, -1, -1)
    ]

    from shared.instance_meta import is_master_instance

    per_istanza: list[dict] = []
    master_row:  Optional[dict] = None
    sum_serie:   list[Optional[int]] = [None] * days

    # Iter su tutte le istanze configurate (anche disabilitate / senza storico)
    try:
        from config.config_loader import load_instances
        nomi_configurati = [i.get("nome", "") for i in load_instances() if i.get("nome")]
    except Exception:
        nomi_configurati = []
    # Fallback ai nomi presenti nello storico (compat)
    nomi_storico = list(storico.keys())
    nomi_tutti = list(dict.fromkeys(nomi_configurati + nomi_storico))  # dedup mantenendo ordine

    for nome in nomi_tutti:
        entries = storico.get(nome, []) or []
        by_date: dict[str, int] = {}
        for e in entries:
            try:
                by_date[e["data"]] = int(e["total_squads"])
            except Exception:
                continue

        oggi        = by_date.get(iso_seq[-1])
        sette_gg_fa = by_date.get(iso_seq[0])
        delta = (oggi - sette_gg_fa) if (oggi is not None and sette_gg_fa is not None) else None
        delta_pct = (
            round(delta / sette_gg_fa * 100, 1)
            if delta is not None and sette_gg_fa
            else None
        )
        serie = [by_date.get(iso) for iso in iso_seq]

        row = {
            "nome":        nome,
            "oggi":        oggi,
            "sette_gg_fa": sette_gg_fa,
            "delta":       delta,
            "delta_pct":   delta_pct,
            "serie":       serie,
        }

        # Master istanze (FauMorfeus): fuori dagli aggregati ordinari,
        # esposte in campo dedicato per la sezione "Master" della dashboard.
        if is_master_instance(nome):
            master_row = row
            continue

        per_istanza.append(row)

        for i, v in enumerate(serie):
            if v is None:
                continue
            sum_serie[i] = (sum_serie[i] or 0) + v

    # Sort: per nome istanza alfabetico (FAU_00..FAU_10)
    # Cambio richiesto utente 30/04: prima era delta_pct desc, ora indice naturale.
    per_istanza.sort(key=lambda r: r["nome"])

    tot_oggi   = sum_serie[-1]
    tot_sette  = sum_serie[0]
    tot_delta  = (tot_oggi - tot_sette) if (tot_oggi is not None and tot_sette is not None) else None
    tot_pct    = (
        round(tot_delta / tot_sette * 100, 1)
        if tot_delta is not None and tot_sette
        else None
    )

    return {
        "per_istanza": per_istanza,
        "totale": {
            "oggi":        tot_oggi,
            "sette_gg_fa": tot_sette,
            "delta":       tot_delta,
            "delta_pct":   tot_pct,
            "serie":       sum_serie,
        },
        "master":    master_row,   # FauMorfeus, fuori dagli aggregati ordinari
        "days":      days,
        "data_oggi": today_utc.isoformat(),
    }


def _load_morfeus_state() -> MorfeusState:
    """
    Legge data/morfeus_state.json. Ritorna stato 'mai letto' se file mancante.

    WU58 (29/04): se ts è di un giorno UTC passato (capienza letta ieri o
    prima), il limite NON è valido per oggi — ritorno daily_recv_limit=-1
    per far mostrare "—" alla dashboard. Il bot rileggerà via OCR al primo
    tick rifornimento di oggi.
    """
    try:
        if not _MORFEUS_STATE.exists():
            return MorfeusState()
        with open(_MORFEUS_STATE, encoding="utf-8") as f:
            d = json.load(f)
        ts_str = str(d.get("ts", ""))
        recv   = int(d.get("daily_recv_limit", -1))
        # Check stale: ts in giorno UTC passato → invalida valore daily
        if ts_str and recv >= 0:
            try:
                from datetime import datetime, timezone
                today_utc = datetime.now(timezone.utc).date().isoformat()
                ts_date   = ts_str[:10]   # "YYYY-MM-DD" da ISO
                if ts_date and ts_date != today_utc:
                    recv = -1
            except Exception:
                pass
        return MorfeusState(
            daily_recv_limit = recv,
            ts               = ts_str,
            letto_da         = str(d.get("letto_da", "")),
            tassa_pct        = float(d.get("tassa_pct", 0.0) or 0.0),
        )
    except Exception:
        return MorfeusState()


def _load_state(nome: str) -> dict:
    try:
        with open(_STATE_DIR / f"{nome}.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _raccolta_from_state(state: dict) -> RaccoltaStats:
    _ = state.get("metrics", {})
    return RaccoltaStats(
        slot_totali        = state.get("raccolta_slot_totali", 0),
        slot_usati         = state.get("raccolta_slot_usati", 0),
        nodi_raccolti      = state.get("raccolta_nodi_ok", 0),
        nodi_falliti       = state.get("raccolta_nodi_fail", 0),
        tipologie_bloccate = state.get("raccolta_tipologie_bloccate", []),
    )


def _tick_from_status_and_state(
    nome: str,
    ist_status: Optional[IstanzaStatus],
    state: dict,
) -> TickStats:
    ts_inizio = state.get("ultimo_avvio")
    durata_s: Optional[float] = None
    task_eseguiti: list[str] = []
    task_falliti:  list[str] = []

    if ist_status:
        te = ist_status.task_eseguiti or {}
        task_eseguiti = [k for k, v in te.items() if isinstance(v, int) and v > 0]
        ut = ist_status.ultimo_task
        if ut and getattr(ut, "esito", None) == "err":
            nome_task = getattr(ut, "nome", None)
            if nome_task:
                task_falliti = [nome_task]
        if ut:
            durata_s = getattr(ut, "durata_s", None)

    raccolta = _raccolta_from_state(state)
    return TickStats(
        ts_inizio     = ts_inizio,
        durata_s      = durata_s,
        task_eseguiti = task_eseguiti,
        task_falliti  = task_falliti,
        raccolta      = raccolta,
    )


def _tipologia_istanza(nome: str) -> TipologiaIstanza:
    try:
        ov = get_overrides()
        t  = ov.get("istanze", {}).get(nome, {}).get("tipologia", "full")
        return TipologiaIstanza(t)
    except Exception:
        return TipologiaIstanza.full


def _abilitata(nome: str) -> bool:
    try:
        ov = get_overrides()
        return bool(ov.get("istanze", {}).get(nome, {}).get("abilitata", True))
    except Exception:
        return True


# ==============================================================================
# API pubblica
# ==============================================================================

def get_engine_status() -> EngineStatus:
    return _load_engine_status()


def get_instance_stats(nome: str) -> InstanceStats:
    from shared.instance_meta import is_master_instance
    try:
        es          = _load_engine_status()
        ist_status  = es.istanze.get(nome)
        state       = _load_state(nome)
        stato_live  = ist_status.stato if ist_status else "unknown"
        ultimo_tick = _tick_from_status_and_state(nome, ist_status, state)
        return InstanceStats(
            nome        = nome,
            tipologia   = _tipologia_istanza(nome),
            abilitata   = _abilitata(nome),
            master      = is_master_instance(nome),
            stato_live  = stato_live,
            ultimo_tick = ultimo_tick,
        )
    except Exception:
        return InstanceStats(nome=nome, stato_live="unknown")


def get_all_stats(include_master: bool = False) -> list[InstanceStats]:
    """
    Ritorna InstanceStats per le istanze ordinarie in instances.json.
    Le istanze master (FauMorfeus) sono escluse di default — la dashboard
    le gestisce in una sezione dedicata. Pass `include_master=True` per
    includerle (utile per la sezione Master).
    """
    from shared.instance_meta import is_master_instance
    try:
        es     = _load_engine_status()
        insts  = get_instances()
        result: list[InstanceStats] = []
        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue
            if not include_master and is_master_instance(nome):
                continue
            ist_status  = es.istanze.get(nome)
            state       = _load_state(nome)
            stato_live  = ist_status.stato if ist_status else "unknown"
            ultimo_tick = _tick_from_status_and_state(nome, ist_status, state)
            result.append(InstanceStats(
                nome        = nome,
                tipologia   = _tipologia_istanza(nome),
                abilitata   = _abilitata(nome),
                master      = is_master_instance(nome),
                stato_live  = stato_live,
                ultimo_tick = ultimo_tick,
            ))
        return result
    except Exception:
        return []


def get_storico(n: int = 50) -> list[StoricoEntry]:
    try:
        es = _load_engine_status()
        return es.storico[-n:] if es.storico else []
    except Exception:
        return []


def get_produzione_istanze(include_master: bool = False, only_master: bool = False) -> list[dict]:
    """
    Auto-WU14 step3: ritorna dati produzione per ogni istanza.

    Auto-WU18 (27/04): arricchito con stato live, task corrente, errori,
    quota rifornimento (per card unificata).

    Per ogni istanza presente in instances.json, legge state/<nome>.json
    e estrae produzione_corrente + ultima sessione chiusa dal storico,
    arricchito con dati live da engine_status.json.

    Schema output:
    [{
      "nome": str,
      "abilitata": bool,
      "stato": "online" | "idle" | "error" | "unknown",
      "task_corrente": str | None,
      "errori_live": int,
      "quota_max": int,            # rifornimento.quota_max
      "spedizioni_oggi": int,      # rifornimento.spedizioni_oggi
      "quota_esaurita": bool,      # spedizioni_oggi >= quota_max
      "corrente": {...} | None,
      "precedente": {...} | None,
      "n_storico_24h": int,
    }, ...]
    """
    from shared.instance_meta import is_master_instance
    try:
        insts = get_instances()
        engine = get_engine_status()
        result: list[dict] = []
        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue
            is_m = is_master_instance(nome)
            if only_master and not is_m:
                continue
            if not only_master and not include_master and is_m:
                continue
            state = _load_state(nome)
            corrente = state.get("produzione_corrente")
            storico  = state.get("produzione_storico", []) or []
            precedente = storico[-1] if storico else None

            # Live state from engine_status
            ist_status = engine.istanze.get(nome) if engine else None
            stato = (ist_status.stato if ist_status else None) or "unknown"
            task_corrente = ist_status.task_corrente if ist_status else None
            errori_live = ist_status.errori if ist_status else 0
            # auto-WU19: ultimo task (per assorbire la card top inst-grid)
            ut = ist_status.ultimo_task if ist_status else None
            ultimo_task_nome  = (ut.nome if ut else None) or None
            ultimo_task_ts    = (ut.ts if ut else None) or None
            ultimo_task_msg   = ((ut.msg or "") if ut else "")[:50]
            ultimo_task_esito = (ut.esito if ut else None) or None

            # Quota rifornimento
            rif = state.get("rifornimento", {})
            # WU58 (29/04): se data_riferimento != oggi UTC, lo state è stale
            # (giorno precedente non resettato — task rifornimento OFF da >24h
            # oppure pausa manutenzione lunga). Azzero IN MEMORIA i totali daily
            # E le provviste OCR (sono di ieri, non valide come "snapshot oggi").
            # Senza toccare il file: il bot rilegge OCR al primo tick di oggi.
            from datetime import datetime, timezone
            today_utc = datetime.now(timezone.utc).date().isoformat()
            data_rif  = str(rif.get("data_riferimento") or "")
            stale     = bool(data_rif) and data_rif != today_utc
            if stale:
                # Reset in-memory: dashboard mostra stato pulito di oggi
                rif = {**rif,
                       "spedizioni_oggi": 0,
                       "inviato_oggi": {},
                       "inviato_lordo_oggi": {},
                       "tassa_oggi": {},
                       "dettaglio_oggi": [],
                       "provviste_residue": -1,        # — sul pannello
                       "provviste_esaurite": False}
            quota_max       = int(rif.get("quota_max", 0) or 0)
            spedizioni_oggi = int(rif.get("spedizioni_oggi", 0) or 0)
            quota_esaurita  = quota_max > 0 and spedizioni_oggi >= quota_max
            # auto-WU32: totale risorse inviate oggi (sum inviato_oggi)
            # + provviste residue = quota residua da inviare
            inviato_oggi    = rif.get("inviato_oggi", {}) or {}
            inviato_totale  = sum(int(v or 0) for v in inviato_oggi.values())
            provviste_res   = int(rif.get("provviste_residue", -1) or -1)
            provviste_esau  = bool(rif.get("provviste_esaurite", False))
            # auto-WU34 (27/04): aggregati LORDO + TASSA daily
            inviato_lordo_oggi = rif.get("inviato_lordo_oggi", {}) or {}
            tassa_oggi         = rif.get("tassa_oggi", {}) or {}
            inviato_lordo_tot  = sum(int(v or 0) for v in inviato_lordo_oggi.values())
            tassa_tot          = sum(int(v or 0) for v in tassa_oggi.values())
            tassa_pct_avg      = float(rif.get("tassa_pct_avg", 0.23))

            # auto-WU45 (27/04 fix race): fallback su data/storico_farm.json se
            # state.rifornimento è stato resettato dal bot durante il giorno
            # (es. _controlla_reset spurious dopo restart, race con _build_ctx).
            # storico_farm.json è scritto ad ogni spedizione e sopravvive ai
            # reset state — è la fonte di verità DAILY più affidabile.
            try:
                if (spedizioni_oggi == 0 and inviato_totale == 0
                        and not provviste_esau):
                    sf = _load_storico_farm_today(nome)
                    if sf:
                        spedizioni_oggi = int(sf.get("spedizioni", 0))
                        sf_inviato = {
                            r: int(sf.get(r, 0))
                            for r in ("pomodoro", "legno", "acciaio", "petrolio")
                        }
                        if any(v > 0 for v in sf_inviato.values()):
                            inviato_oggi    = sf_inviato
                            inviato_totale  = sum(sf_inviato.values())
                            quota_esaurita  = quota_max > 0 and spedizioni_oggi >= quota_max
                        # provviste_residue da storico (LORDO ultimo OCR)
                        if provviste_res < 0:
                            provviste_res = int(sf.get("provviste_residue", -1) or -1)
            except Exception:
                pass
            # Stima provviste residue NETTA = lordo × (1 - tassa_pct_avg)
            if provviste_res > 0:
                provviste_res_netta = int(provviste_res * (1.0 - tassa_pct_avg))
            else:
                provviste_res_netta = provviste_res

            result.append({
                "nome":              nome,
                "abilitata":         _abilitata(nome),
                "stato":             stato,
                "task_corrente":     task_corrente,
                "errori_live":       errori_live,
                "ultimo_task_nome":  ultimo_task_nome,
                "ultimo_task_ts":    ultimo_task_ts,
                "ultimo_task_msg":   ultimo_task_msg,
                "ultimo_task_esito": ultimo_task_esito,
                "quota_max":         quota_max,
                "spedizioni_oggi":   spedizioni_oggi,
                "quota_esaurita":    quota_esaurita,
                "inviato_totale":    inviato_totale,
                "provviste_residue": provviste_res,
                "provviste_esaurite": provviste_esau,
                # auto-WU34
                "inviato_lordo_totale": inviato_lordo_tot,
                "tassa_totale":         tassa_tot,
                "tassa_pct_avg":        tassa_pct_avg,
                "provviste_residue_netta": provviste_res_netta,
                "corrente":          corrente,
                "precedente":        precedente,
                "n_storico_24h":     len(storico),
                "master":            is_m,
            })
        return result
    except Exception:
        return []


def get_risorse_farm() -> RisorseFarm:
    """
    Aggrega dati risorse da tutti gli state/<nome>.json presenti.
    Nessun filtro per nome o per flag abilitata — tutte le istanze con
    state persistito contribuiscono ai totali.

    Fonte inviato: dettaglio_oggi[*].qta_inviata (NON inviato_oggi).
    Motivo: inviato_oggi può contenere falsi positivi OCR (Issue #16, legno=999M).
    dettaglio_oggi contiene i valori scritti dal bot al momento dell'invio reale.
    Sanity check aggiuntivo: qta_inviata > 100M viene scartata.

    Somma per tutte le istanze:
      - dettaglio_oggi[*].qta_inviata  → inviato_per_risorsa (filtrato)
      - rifornimento.provviste_residue  → provviste_residue (totale)
      - rifornimento.spedizioni_oggi    → spedizioni_oggi (cumulativo giornaliero)
      - rifornimento.quota_max          → quota_max_per_ciclo (per-ciclo)
      - metrics.*_per_ora               → produzione_per_ora (somma istanze)

    Failsafe: RisorseFarm() vuoto su errore.
    """
    from shared.instance_meta import is_master_instance
    try:
        insts = get_instances()

        # Inizializza tutte le risorse a 0 — garantisce presenza nel dict
        inviato:         Dict[str, int]   = {r: 0 for r in _RISORSE_STANDARD}
        provviste:       int              = 0
        provviste_netta: int              = 0
        sped_oggi:       int              = 0
        quota_ciclo:     int              = 0
        prod_ora:        Dict[str, float] = {r: 0.0 for r in _RISORSE_STANDARD}
        detail:          List[RifornimentoIstanza] = []

        for ist in insts:
            nome = ist.get("nome", "")
            if not nome:
                continue
            if is_master_instance(nome):
                continue   # Master: non somma ai totali farm ordinari

            state = _load_state(nome)
            if not state:
                continue

            rif = state.get("rifornimento", {})

            # WU58 (29/04): se data_riferimento != oggi UTC → state stale,
            # azzero IN MEMORIA i totali daily + provviste OCR (di ieri).
            # Dashboard mostra 0 fino al primo tick rifornimento di oggi.
            from datetime import datetime, timezone
            today_utc = datetime.now(timezone.utc).date().isoformat()
            data_rif  = str(rif.get("data_riferimento") or "")
            if data_rif and data_rif != today_utc:
                rif = {**rif,
                       "spedizioni_oggi": 0,
                       "inviato_oggi": {},
                       "inviato_lordo_oggi": {},
                       "tassa_oggi": {},
                       "dettaglio_oggi": [],
                       "provviste_residue": 0,
                       "provviste_esaurite": False}

            # --- Inviato oggi — fonte: dettaglio_oggi (valori reali bot) ---
            # dettaglio_oggi è scritto dal bot al momento dell'invio effettivo,
            # non da OCR — elimina alla radice Issue #16.
            # Sanity check residuo: scarta comunque qta > 100M.
            inviato_ist: Dict[str, int] = {r: 0 for r in _RISORSE_STANDARD}
            for entry in rif.get("dettaglio_oggi", []):
                risorsa = entry.get("risorsa", "")
                qta     = int(entry.get("qta_inviata", 0))
                if risorsa not in _RISORSE_STANDARD:
                    continue
                if qta > _MAX_QTA_SPEDIZIONE:
                    continue  # falso positivo OCR — scarta
                inviato_ist[risorsa] += qta

            for risorsa, qta in inviato_ist.items():
                inviato[risorsa] += qta

            # --- Provviste e spedizioni ---
            prov          = int(rif.get("provviste_residue", 0))
            tassa_pct_avg = float(rif.get("tassa_pct_avg", 0.23) or 0.23)
            prov_netta    = int(prov * (1.0 - tassa_pct_avg)) if prov > 0 else 0
            provviste       += prov
            provviste_netta += prov_netta
            sped_oggi       += int(rif.get("spedizioni_oggi", 0))
            quota_ciclo     += int(rif.get("quota_max", 0))

            detail.append(RifornimentoIstanza(
                nome                    = nome,
                spedizioni_oggi         = int(rif.get("spedizioni_oggi", 0)),
                quota_max_per_ciclo     = int(rif.get("quota_max", 0)),
                provviste_residue       = prov,
                provviste_residue_netta = prov_netta,
                provviste_esaurite      = bool(rif.get("provviste_esaurite", False)),
                tassa_pct_avg           = tassa_pct_avg,
                inviato_oggi            = inviato_ist,
            ))

            # --- Metrics (produzione/ora) ---
            m = state.get("metrics", {})
            for r in _RISORSE_STANDARD:
                prod_ora[r] = round(prod_ora[r] + float(m.get(f"{r}_per_ora", 0.0)), 2)

        return RisorseFarm(
            inviato_per_risorsa     = inviato,
            provviste_residue       = provviste,
            provviste_residue_netta = provviste_netta,
            spedizioni_oggi         = sped_oggi,
            quota_max_per_ciclo     = quota_ciclo,
            istanze_detail          = detail,
            produzione_per_ora      = prod_ora,
            morfeus                 = _load_morfeus_state(),
        )

    except Exception:
        return RisorseFarm()


# ==============================================================================
# WU118 — Copertura squadre ultimi N cicli per istanza
# Aggrega da data/istanza_metrics.jsonl raggruppando per (instance, cycle).
# Ordine tipi nodi UI fisso: pomodoro/legno/acciaio/petrolio (matching nomi
# interni: campo→pomodoro, segheria→legno).
# ==============================================================================

# Mappa tipo interno (raccolta) → label UI ordinata
_TIPO_TO_LABEL = {
    "campo":    "pomodoro",
    "segheria": "legno",
    "acciaio":  "acciaio",
    "petrolio": "petrolio",
}
_LABEL_ORDINE = ("pomodoro", "legno", "acciaio", "petrolio")
_LABEL_ICONA  = {
    "pomodoro": "🍅",
    "legno":    "🪵",
    "acciaio":  "⚙",
    "petrolio": "🛢",
}
# Soglia OCR noise (cf tools/report_copertura_ciclo.py)
_SOGLIA_SATURA = 0.95


def get_copertura_ultimi_cicli(n_cicli: int = 5) -> List[dict]:
    """
    Aggrega copertura squadre ultimi N cicli per ogni istanza
    (esclude master).

    Per ogni istanza ritorna:
        {
          "istanza": "FAU_00",
          "cicli": [   # lista N cicli più recenti, sort desc per ts
            {
              "cycle_id": 142,
              "ts":       "04/05 13:11",   # locale HH:MM DD/MM
              "outcome":  "ok",
              "n_invii":  3,
              "n_satura": 3,
              "n_unknown": 0,    # invii con load_squadra=-1
              "per_tipo": {
                "pomodoro": {"n":2, "sat":2, "unk":0},
                "legno":    {"n":0, "sat":0, "unk":0},
                "acciaio":  {"n":1, "sat":1, "unk":0},
                "petrolio": {"n":0, "sat":0, "unk":0},
              },
            }, ...
          ],
          "totali": {  # aggregato su gli N cicli mostrati
            "pomodoro": {"n":..., "sat":..., "unk":...},
            ...
          },
        }

    Sort istanze: ordine alfabetico (compatibile con altre tabelle UI).

    Failsafe: lista vuota se file non esiste / errore parsing.
    """
    from shared.instance_meta import is_master_instance
    metrics_path = _PROD_ROOT / "data" / "istanza_metrics.jsonl"
    if not metrics_path.exists():
        return []

    # Read jsonl raggruppando per istanza
    by_inst: Dict[str, List[dict]] = {}
    try:
        with metrics_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                inst = r.get("instance", "")
                if not inst or is_master_instance(inst):
                    continue
                # Solo cicli con almeno un invio raccolta
                rac = r.get("raccolta", {}) or {}
                if not rac.get("invii"):
                    continue
                by_inst.setdefault(inst, []).append(r)
    except Exception:
        return []

    out: List[dict] = []
    for inst in sorted(by_inst.keys()):
        cicli = by_inst[inst]
        # Sort desc per ts → ultimi N
        cicli.sort(key=lambda r: r.get("ts", ""), reverse=True)
        cicli = cicli[:n_cicli]
        # Riordina asc per visualizzazione cronologica (vecchio→nuovo)
        cicli_asc = list(reversed(cicli))

        cicli_out: List[dict] = []
        # Aggregato totali su gli N cicli mostrati
        tot_per_tipo: Dict[str, Dict[str, int]] = {
            lbl: {"n": 0, "sat": 0, "unk": 0} for lbl in _LABEL_ORDINE
        }

        for c in cicli_asc:
            invii = c.get("raccolta", {}).get("invii", []) or []
            per_tipo: Dict[str, Dict[str, int]] = {
                lbl: {"n": 0, "sat": 0, "unk": 0} for lbl in _LABEL_ORDINE
            }
            n_satura  = 0
            n_unknown = 0
            for inv in invii:
                tipo_int = inv.get("tipo", "")
                lbl = _TIPO_TO_LABEL.get(tipo_int)
                if lbl is None:
                    continue
                cap  = int(inv.get("cap_nodo", -1))
                load = int(inv.get("load_squadra", -1))
                per_tipo[lbl]["n"] += 1
                tot_per_tipo[lbl]["n"] += 1
                if load < 0 or cap <= 0:
                    per_tipo[lbl]["unk"] += 1
                    tot_per_tipo[lbl]["unk"] += 1
                    n_unknown += 1
                elif load >= cap * _SOGLIA_SATURA:
                    per_tipo[lbl]["sat"] += 1
                    tot_per_tipo[lbl]["sat"] += 1
                    n_satura += 1
            # Format ts locale HH:MM DD/MM
            ts_str = "?"
            ts_iso = c.get("ts", "")
            if ts_iso:
                try:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(ts_iso).astimezone()
                    ts_str = dt.strftime("%d/%m %H:%M")
                except Exception:
                    ts_str = ts_iso[:16]
            cicli_out.append({
                "cycle_id": c.get("cycle_id", 0),
                "ts":       ts_str,
                "outcome":  c.get("outcome", "?"),
                "n_invii":  len(invii),
                "n_satura": n_satura,
                "n_unknown": n_unknown,
                "per_tipo": per_tipo,
            })

        out.append({
            "istanza": inst,
            "cicli":   cicli_out,
            "totali":  tot_per_tipo,
        })

    return out


# ==============================================================================
# WU89-Step4 — Live decisions del Skip Predictor
# Legge data/predictor_decisions.jsonl (append-only, scritto da
# main.py::_append_predictor_decision al passaggio del hook).
# Ritorna le ultime N decisioni in ordine cronologico inverso (più recenti
# prime). Schema record: vedi main.py.
# ==============================================================================

def get_predictor_decisions(n: int = 20) -> List[dict]:
    """Ritorna le ultime N decisioni del predictor (desc per ts).

    Schema output per riga:
        {ts_local, istanza, mode, should_skip, reason, score, signals,
         growth_phase, guardrail, applied}

    `ts_local` = HH:MM:SS DD/MM (locale, comodo per dashboard).
    """
    path = _PROD_ROOT / "data" / "predictor_decisions.jsonl"
    if not path.exists():
        return []
    rows: List[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rows.append(r)
    except Exception:
        return []
    # Sort desc per ts (lex su ISO8601 funziona)
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    rows = rows[:n]
    # Format ts locale
    from datetime import datetime as _dt
    for r in rows:
        ts_iso = r.get("ts", "")
        try:
            dt = _dt.fromisoformat(ts_iso).astimezone()
            r["ts_local"] = dt.strftime("%H:%M:%S %d/%m")
        except Exception:
            r["ts_local"] = ts_iso[:16]
    return rows


# ==============================================================================
# Distribuzione slot per istanza — analisi empirica ciclo-su-ciclo
#
# Per ogni istanza, considera ogni coppia consecutiva di record:
#   (record N, record N+1)  con stesso `instance`, ordinati per ts.
#
# Eventi misurati:
#   - post_pieni[N]   = (attive_post[N] == totali[N])
#   - pre_pieni[N+1]  = (attive_pre[N+1] == totali[N+1])
#   - delta_t[N→N+1]  = ts[N+1] - ts[N]  (secondi)
#
# Aggregati:
#   - n_transizioni totali (dove sia N che N+1 hanno raccolta valorizzata)
#   - n_post_pieni (situazioni dove tick N esce con slot saturi)
#   - n_post_pieni_pre_pieni (delle precedenti, quante hanno N+1 ancora saturo)
#   - P_squadre_fuori = n_post_pieni_pre_pieni / n_post_pieni
#   - delta_t p25, p50, p75
#   - tabellina ultime 5 transizioni
# ==============================================================================

def _percentile(values: list[float], p: float) -> float:
    """Percentile p (0..1) su lista già float. Ritorna 0 se vuota."""
    if not values:
        return 0.0
    sv = sorted(values)
    if len(sv) == 1:
        return float(sv[0])
    k = (len(sv) - 1) * p
    f = int(k)
    c = min(f + 1, len(sv) - 1)
    if f == c:
        return float(sv[f])
    return float(sv[f] + (sv[c] - sv[f]) * (k - f))


def get_distribuzione_slot_per_istanza(window_records: int = 30) -> list[dict]:
    """
    Per ogni istanza, calcola la distribuzione empirica di P(slot pieni
    al ritorno del bot | erano pieni alla chiusura precedente) usando le
    ultime `window_records` transizioni consecutive disponibili nel file
    `data/istanza_metrics.jsonl`.

    Schema output per riga (istanza):
        {
          "istanza": "FAU_05",
          "totali": 4,
          "n_transizioni": 12,
          "n_post_pieni": 10,
          "P_squadre_fuori": 0.70,        # 0..1, None se n_post_pieni < 5
          "delta_t_min_p25": 65.3,
          "delta_t_min_p50": 70.1,
          "delta_t_min_p75": 75.8,
          "ultime": [
              {ts_local, delta_t_min, post, pre, totali, esito}
              ...max 5 records...
          ]
        }

    Solo lettura. No side-effect.
    """
    path = _PROD_ROOT / "data" / "istanza_metrics.jsonl"
    if not path.exists():
        return []

    # Raccogli per istanza, mantenendo ts e raccolta
    by_inst: dict[str, list[dict]] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                inst = r.get("instance")
                if not inst:
                    continue
                rac = r.get("raccolta") or {}
                # Salta record senza raccolta valorizzata (cycle_id=0 a volte)
                if rac.get("attive_post") is None or rac.get("totali") is None:
                    continue
                by_inst.setdefault(inst, []).append(r)
    except Exception:
        return []

    from datetime import datetime as _dt

    out: list[dict] = []
    for inst, recs in by_inst.items():
        # Ordina per ts crescente
        recs.sort(key=lambda r: r.get("ts", ""))
        # Tieni solo le ultime window_records+1 entry (per N+1 transizioni)
        recs = recs[-(window_records + 1):]

        # Costruisci coppie consecutive
        transizioni: list[dict] = []
        for i in range(len(recs) - 1):
            r0 = recs[i]
            r1 = recs[i + 1]
            rac0 = r0.get("raccolta") or {}
            rac1 = r1.get("raccolta") or {}
            post0 = rac0.get("attive_post")
            pre1  = rac1.get("attive_pre")
            tot   = rac1.get("totali") or rac0.get("totali")
            if post0 is None or pre1 is None or tot is None:
                continue
            try:
                t0 = _dt.fromisoformat(r0.get("ts", ""))
                t1 = _dt.fromisoformat(r1.get("ts", ""))
                delta_s = (t1 - t0).total_seconds()
                if delta_s <= 0:
                    continue
            except Exception:
                continue
            post_pieni = (post0 >= tot)
            pre_pieni  = (pre1  >= tot)
            transizioni.append({
                "ts_local":   t1.astimezone().strftime("%H:%M %d/%m"),
                "delta_s":    delta_s,
                "post":       post0,
                "pre":        pre1,
                "totali":     tot,
                "post_pieni": post_pieni,
                "pre_pieni":  pre_pieni,
            })

        if not transizioni:
            continue

        # Aggregati
        n_trans       = len(transizioni)
        n_post_pieni  = sum(1 for t in transizioni if t["post_pieni"])
        n_post_pre    = sum(1 for t in transizioni if t["post_pieni"] and t["pre_pieni"])
        # P(squadre fuori | slot saturi alla chiusura)
        p_squadre_fuori = (n_post_pre / n_post_pieni) if n_post_pieni >= 5 else None
        # Delta t solo dalle transizioni post_pieni (rilevanti per skip)
        deltas_min = [t["delta_s"] / 60.0 for t in transizioni if t["post_pieni"]]
        if not deltas_min:
            deltas_min = [t["delta_s"] / 60.0 for t in transizioni]
        # Tabellina ultime 5 transizioni
        ultime = []
        for t in transizioni[-5:]:
            esito = ""
            if t["post_pieni"] and t["pre_pieni"]:
                esito = "squadre fuori"
            elif t["post_pieni"] and not t["pre_pieni"]:
                liberate = t["post"] - t["pre"]
                esito = f"{liberate} rientrate"
            else:
                esito = "slot già liberi"
            ultime.append({
                "ts_local":     t["ts_local"],
                "delta_t_min":  round(t["delta_s"] / 60.0, 1),
                "post":         t["post"],
                "pre":          t["pre"],
                "totali":       t["totali"],
                "esito":        esito,
            })

        out.append({
            "istanza":          inst,
            "totali":           transizioni[-1]["totali"],
            "n_transizioni":    n_trans,
            "n_post_pieni":     n_post_pieni,
            "P_squadre_fuori":  p_squadre_fuori,
            "delta_t_min_p25":  round(_percentile(deltas_min, 0.25), 1),
            "delta_t_min_p50":  round(_percentile(deltas_min, 0.50), 1),
            "delta_t_min_p75":  round(_percentile(deltas_min, 0.75), 1),
            "ultime":           ultime,
        })

    # Esclude master (FauMorfeus): non rilevante per skip predictor
    try:
        from shared.instance_meta import is_master_instance
        out = [r for r in out if not is_master_instance(r["istanza"])]
    except Exception:
        pass

    # Ordina alfabetico per nome istanza
    out.sort(key=lambda r: r["istanza"])
    return out
