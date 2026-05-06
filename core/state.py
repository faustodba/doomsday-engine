# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/state.py
#
#  Stato runtime di una singola istanza, persistito su disco come JSON.
#
#  Classi:
#    RifornimentoState  — quota giornaliera spedizioni + guard provviste_esaurite
#    ScheduleState      — persistenza scheduling task (restart-safe)
#    DailyTasksState    — flag completamento task giornalieri con timestamp
#    MetricsState       — metriche produzione (risorse/ora, marce inviate)
#    BoostState         — scheduling intelligente Gathering Speed Boost
#    VipState           — stato giornaliero ricompense VIP
#    ArenaState         — stato giornaliero sfide Arena of Glory
#    InstanceState      — contenitore principale, carica/salva JSON
#
#  Design:
#    - Ogni sezione è un dataclass autonomo con metodi di business logic
#    - InstanceState è l'unico punto di I/O su disco (load/save)
#    - Nessuna dipendenza da device.py o config.py — layer puro di dati
#    - I timestamp sono sempre UTC (datetime.now(UTC))
#    - Il reset giornaliero usa la data UTC, non l'ora locale
#
#  REFACTORING 16/04/2026 — RifornimentoState:
#    - aggiunto campo provviste_esaurite: bool
#    - aggiunto metodo segna_provviste_esaurite()
#    - _controlla_reset() resetta anche provviste_esaurite
#    - should_run() → False se provviste_esaurite (guard persistente)
#
#  FIX 14/04/2026 — ScheduleState:
#    - timestamps ora salvati come ISO string (es. "2026-04-14T16:45:39+00:00")
#      invece di Unix float — leggibili direttamente nel JSON
#    - get() converte ISO → float per compatibilità orchestrator
#    - set() accetta float, converte in ISO per la persistenza
#    - restore_to_orchestrator() converte ISO → float prima di set_last_run()
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ==============================================================================
# Helpers
# ==============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today_utc() -> str:
    """Data corrente UTC come stringa ISO (YYYY-MM-DD)."""
    return _utc_now().strftime("%Y-%m-%d")


def _ts_now() -> str:
    """Timestamp corrente UTC come stringa ISO."""
    return _utc_now().isoformat()


def _float_to_iso(ts: float) -> str:
    """Converte Unix timestamp float in stringa ISO UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _iso_to_float(iso: str) -> float:
    """Converte stringa ISO in Unix timestamp float. Ritorna 0.0 se non parsabile."""
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _ts_after(iso: str, cutoff: datetime) -> bool:
    """True se il timestamp ISO è successivo al cutoff (datetime UTC). False se non parsabile."""
    try:
        ts = datetime.fromisoformat(iso)
        return ts > cutoff
    except (ValueError, TypeError):
        return False


def _calcola_ricevuto_da_alleati(master_name: str, t0_iso: str, t1_iso: str) -> dict:
    """
    Per istanza master: somma risorse ricevute (NETTO) nella finestra [t0, t1]
    leggendo `state/*.json::rifornimento.dettaglio_oggi` di tutte le altre
    istanze (escluso il master stesso).

    Schema dettaglio_oggi: [{ts, risorsa, qta_inviata (NETTO), qta_lorda,
    tassa_amount, provviste_residue}].

    Best-effort: errori di lettura producono ricevuto=0 per quell'istanza.
    Necessario per produzione/ora corretta del master (vedi
    `chiudi_sessione_e_calcola` per il rationale).
    """
    out = {"pomodoro": 0, "legno": 0, "acciaio": 0, "petrolio": 0}
    try:
        t0 = datetime.fromisoformat(t0_iso)
        t1 = datetime.fromisoformat(t1_iso)
    except Exception:
        return out
    state_dir = Path(os.environ.get("DOOMSDAY_ROOT", os.getcwd())) / "state"
    if not state_dir.exists():
        return out
    for f in state_dir.glob("*.json"):
        if f.stem == master_name or f.stem.endswith("_timing"):
            continue
        try:
            with f.open(encoding="utf-8") as fh:
                s = json.load(fh)
            for d in (s.get("rifornimento") or {}).get("dettaglio_oggi", []) or []:
                ts = d.get("ts", "")
                try:
                    dt = datetime.fromisoformat(ts)
                except Exception:
                    continue
                if t0 <= dt <= t1:
                    risorsa = d.get("risorsa", "")
                    qta = int(d.get("qta_inviata", 0))
                    if risorsa in out:
                        out[risorsa] += qta
        except Exception:
            continue
    return out


# ==============================================================================
# RifornimentoState — quota giornaliera spedizioni
# ==============================================================================

@dataclass
class RifornimentoState:
    """
    Traccia le spedizioni di rifornimento della giornata corrente.

    La quota si resetta automaticamente all'inizio di ogni nuovo giorno UTC.
    Quando spedizioni_oggi >= quota_max, il rifornimento è bloccato.

    Statistiche giornaliere (reset insieme alla quota):
      provviste_residue  — ultime provviste lette dalla maschera (-1 = non lette)
      inviato_oggi       — dict {risorsa: qta_totale_inviata_oggi} (quantità reali)
      dettaglio_oggi     — lista [{ts, risorsa, qta_inviata, provviste_residue}]
    """

    spedizioni_oggi: int = 0
    quota_max: int = 5
    data_riferimento: str = field(default_factory=_today_utc)
    ultima_spedizione: str | None = None   # timestamp ISO ultima spedizione

    # Issue #64 — timestamp ISO atteso di rientro dell'ULTIMA spedizione inviata.
    # Letto da RaccoltaTask all'inizio per evitare di leggere slot quando le
    # spedizioni rifornimento sono ancora in volo (occupano slot squadra).
    # = ts_invio + eta_andata_ritorno (margine già incluso da _attesa_ultima).
    eta_rientro_ultima: str | None = None  # ISO UTC

    # Guard persistente: True quando il gioco segnala provviste=0
    # Blocca il task per tutta la giornata UTC su tutti i riavvii dell'istanza
    provviste_esaurite: bool = False

    # Statistiche giornaliere
    provviste_residue: int = -1
    inviato_oggi: dict = field(default_factory=dict)   # {risorsa: int} NETTO
    dettaglio_oggi: list = field(default_factory=list) # [{ts, risorsa, qta, provviste}]

    # auto-WU34 (27/04): aggiunte statistiche LORDO + TASSA per tracking
    # completo. Default empty dict (retrocompatibile con state pre-WU34).
    inviato_lordo_oggi: dict = field(default_factory=dict)  # {risorsa: int} LORDO
    tassa_oggi:         dict = field(default_factory=dict)  # {risorsa: int} tassa
    # Tassa percentuale media corrente (running avg, usata per stima
    # provviste_residue netta = lordo × (1 - tassa_pct_avg)).
    tassa_pct_avg: float = 0.23  # default 23% comune nel gioco

    # WU106 (03/05) — cap di invio individuale dell'istanza, scoperto alla
    # PRIMA spedizione del giorno UTC e cristallizzato fino al reset.
    # Permette di stimare quante spedizioni può fare l'istanza nel giorno
    # senza dover dipendere dal `Daily Receiving Limit` del master (che è
    # un limite separato, globale, gestito da provviste_esaurite).
    cap_invio_iniziale_oggi: int = -1   # NETTO, primo provviste_residue letto
    qta_max_invio_lordo:     int = -1   # LORDO max per singolo invio (clamped form)

    def _controlla_reset(self) -> None:
        """Se siamo in un nuovo giorno UTC, azzera il contatore e le statistiche."""
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.spedizioni_oggi    = 0
            self.data_riferimento   = oggi
            self.provviste_esaurite = False
            self.provviste_residue  = -1
            self.inviato_oggi       = {}
            self.dettaglio_oggi     = []
            # WU34: reset anche LORDO/TASSA daily
            self.inviato_lordo_oggi = {}
            self.tassa_oggi         = {}
            # tassa_pct_avg si conserva (è una stima cumulativa, no reset)
            # WU106: reset cap istanza giornaliero (verrà ri-scoperto al primo invio)
            self.cap_invio_iniziale_oggi = -1
            self.qta_max_invio_lordo     = -1

    @property
    def quota_esaurita(self) -> bool:
        """True se la quota giornaliera è stata raggiunta."""
        self._controlla_reset()
        return self.spedizioni_oggi >= self.quota_max

    @property
    def spedizioni_rimaste(self) -> int:
        """Numero di spedizioni ancora disponibili oggi."""
        self._controlla_reset()
        return max(0, self.quota_max - self.spedizioni_oggi)

    def should_run(self) -> bool:
        """
        Guard persistente per RifornimentoTask.should_run().
        False se le provviste giornaliere sono esaurite (segnalato dal gioco).
        Reset automatico a mezzanotte UTC.
        NON considera quota_max — quella è un limite di sessione gestito in run().
        """
        self._controlla_reset()
        return not self.provviste_esaurite

    def registra_cap_giornaliero(self, cap_invio: int, qta_max_lordo: int) -> None:
        """
        WU106 — Salva il cap di invio individuale dell'istanza alla PRIMA
        spedizione del giorno UTC. Idempotente intra-giornata: se i campi
        sono già valorizzati (>= 0) non li sovrascrive.

        Args:
            cap_invio:     provviste_residue letto al popup di invio (NETTO)
            qta_max_lordo: input clamped al popup compila (LORDO singolo invio)
        """
        self._controlla_reset()
        # Idempotenza: una sola scrittura per giornata UTC
        if self.cap_invio_iniziale_oggi < 0 and cap_invio >= 0:
            self.cap_invio_iniziale_oggi = int(cap_invio)
        if self.qta_max_invio_lordo < 0 and qta_max_lordo > 0:
            self.qta_max_invio_lordo = int(qta_max_lordo)

    def segna_provviste_esaurite(self) -> None:
        """
        Chiamato da RifornimentoTask quando _compila_e_invia() rileva provviste=0.
        Persiste su disco — blocca il task per tutta la giornata UTC
        indipendentemente dai riavvii dell'istanza.
        """
        self._controlla_reset()
        self.provviste_esaurite = True

    def registra_spedizione(self,
                            risorsa: str = "",
                            qta_inviata: int = 0,
                            provviste_residue: int = -1,
                            qta_lorda: int = 0,
                            tassa_amount: int = 0) -> None:
        """
        Incrementa il contatore, aggiorna timestamp e registra statistiche.

        Args:
            risorsa:          nome risorsa inviata (es. "pomodoro")
            qta_inviata:      quantità NETTA arrivata al destinatario
                              (qta_lorda × (1-tassa))
            provviste_residue: provviste rimanenti lette dopo il VAI (-1 = non lette)
            qta_lorda:        quantità LORDA uscita dal castello (input form OCR)
                              auto-WU34 (27/04). Default 0 = legacy compat.
            tassa_amount:     quantità tassa = qta_lorda - qta_inviata
                              auto-WU34 (27/04). Default 0 = legacy compat.
        """
        self._controlla_reset()
        self.spedizioni_oggi += 1
        self.ultima_spedizione = _ts_now()

        if provviste_residue >= 0:
            self.provviste_residue = provviste_residue

        if risorsa and qta_inviata > 0:
            self.inviato_oggi[risorsa] = self.inviato_oggi.get(risorsa, 0) + qta_inviata
            entry = {
                "ts":               self.ultima_spedizione,
                "risorsa":          risorsa,
                "qta_inviata":      qta_inviata,           # NETTO
                "provviste_residue": provviste_residue,
            }
            # auto-WU34: estensione con LORDO + TASSA (se forniti)
            if qta_lorda > 0:
                entry["qta_lorda"]    = qta_lorda
                entry["tassa_amount"] = tassa_amount
                self.inviato_lordo_oggi[risorsa] = (
                    self.inviato_lordo_oggi.get(risorsa, 0) + qta_lorda
                )
                if tassa_amount > 0:
                    self.tassa_oggi[risorsa] = (
                        self.tassa_oggi.get(risorsa, 0) + tassa_amount
                    )
                # Update running avg tassa_pct: media pesata tra avg corrente
                # e nuova osservazione (peso 0.1 per smoothing)
                if qta_lorda > 0:
                    nuova_pct = tassa_amount / qta_lorda
                    self.tassa_pct_avg = (self.tassa_pct_avg * 0.9 + nuova_pct * 0.1)
            self.dettaglio_oggi.append(entry)

    def totale_inviato(self) -> int:
        """Totale risorse inviate oggi su tutte le risorse."""
        return sum(self.inviato_oggi.values())

    def reset_forzato(self) -> None:
        """Azzera manualmente la quota (es. dopo cambio data manuale)."""
        self.spedizioni_oggi    = 0
        self.data_riferimento   = _today_utc()
        self.ultima_spedizione  = None
        self.provviste_esaurite = False
        self.provviste_residue  = -1
        self.inviato_oggi       = {}
        self.dettaglio_oggi     = []

    @classmethod
    def from_dict(cls, d: dict) -> "RifornimentoState":
        return cls(
            spedizioni_oggi     = d.get("spedizioni_oggi",     0),
            quota_max           = d.get("quota_max",           5),
            data_riferimento    = d.get("data_riferimento",    _today_utc()),
            ultima_spedizione   = d.get("ultima_spedizione",   None),
            provviste_esaurite  = d.get("provviste_esaurite",  False),
            provviste_residue   = d.get("provviste_residue",   -1),
            inviato_oggi        = dict(d.get("inviato_oggi",   {})),
            dettaglio_oggi      = list(d.get("dettaglio_oggi", [])),
            # auto-WU34: nuovi campi LORDO + TASSA (default empty per legacy)
            inviato_lordo_oggi  = dict(d.get("inviato_lordo_oggi", {})),
            tassa_oggi          = dict(d.get("tassa_oggi",         {})),
            tassa_pct_avg       = float(d.get("tassa_pct_avg",     0.23)),
            # WU106: cap istanza giornaliero (default -1 per legacy)
            cap_invio_iniziale_oggi = int(d.get("cap_invio_iniziale_oggi", -1)),
            qta_max_invio_lordo     = int(d.get("qta_max_invio_lordo",     -1)),
        )

    def to_dict(self) -> dict:
        return {
            "spedizioni_oggi":    self.spedizioni_oggi,
            "quota_max":          self.quota_max,
            "data_riferimento":   self.data_riferimento,
            "ultima_spedizione":  self.ultima_spedizione,
            "provviste_esaurite": self.provviste_esaurite,
            "provviste_residue":  self.provviste_residue,
            "inviato_oggi":       self.inviato_oggi,
            "dettaglio_oggi":     self.dettaglio_oggi,
            # auto-WU34: persisti LORDO + TASSA + media tassa
            "inviato_lordo_oggi": self.inviato_lordo_oggi,
            "tassa_oggi":         self.tassa_oggi,
            "tassa_pct_avg":      self.tassa_pct_avg,
            # WU106: cap istanza giornaliero scoperto al primo invio
            "cap_invio_iniziale_oggi": self.cap_invio_iniziale_oggi,
            "qta_max_invio_lordo":     self.qta_max_invio_lordo,
        }


# ==============================================================================
# ScheduleState — persistenza scheduling task (restart-safe)
# ==============================================================================

@dataclass
class ScheduleState:
    """
    Persiste i timestamp dell'ultimo run di ogni task su disco.
    Sopravvive al restart — all'avvio main.py lo legge e ripristina
    i last_run nell'orchestrator tramite set_last_run().

    I timestamp sono salvati come ISO string leggibili nel JSON:
      {
        "schedule": {
          "raccolta":      "2026-04-14T12:00:00+00:00",
          "rifornimento":  "2026-04-14T11:00:00+00:00",
          "arena":         null,          ← mai eseguito
          ...
        }
      }

    Internamente get() converte ISO → float per compatibilità con
    l'orchestrator che usa time.time() (Unix float).
    """
    timestamps: dict = field(default_factory=dict)  # {task_name: str ISO | None}

    def get(self, task_name: str) -> float:
        """
        Ritorna timestamp ultimo run come Unix float.
        0.0 se mai eseguito o valore non parsabile.
        """
        val = self.timestamps.get(task_name)
        if not val:
            return 0.0
        return _iso_to_float(val)

    def set(self, task_name: str, ts: float) -> None:
        """
        Registra timestamp ultimo run.
        Accetta Unix float (da time.time()), salva come ISO string leggibile.
        """
        self.timestamps[task_name] = _float_to_iso(ts)

    def update_from_stato(self, stato: dict) -> None:
        """
        Aggiorna da dict orchestrator.stato() dopo ogni tick.
        stato = {task_name: {"last_run": float, ...}}
        """
        for name, info in stato.items():
            lr = info.get("last_run", 0.0)
            if lr and lr > 0.0:
                self.timestamps[name] = _float_to_iso(lr)

    def restore_to_orchestrator(self, orchestrator) -> None:
        """
        Ripristina i last_run nell'orchestrator all'avvio.
        Converte ISO string → float prima di chiamare set_last_run().
        """
        for name, iso in self.timestamps.items():
            if not iso:
                continue
            ts = _iso_to_float(iso)
            if ts > 0.0:
                orchestrator.set_last_run(name, ts)

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleState":
        """
        Carica da dict JSON.
        Compatibile con vecchio formato float: se trova un numero lo converte in ISO.
        """
        converted = {}
        for k, v in d.items():
            if v is None:
                converted[k] = None
            elif isinstance(v, (int, float)):
                # retrocompatibilità: vecchio formato Unix float → converti in ISO
                converted[k] = _float_to_iso(float(v))
            else:
                converted[k] = v  # già ISO string
        return cls(timestamps=converted)

    def to_dict(self) -> dict:
        return dict(self.timestamps)


# ==============================================================================
# BoostState — stato e scheduling intelligente del Gathering Speed Boost
# ==============================================================================

# Durate boost in secondi
_BOOST_DURATE: dict[str, float] = {
    "8h": 8  * 3600.0,
    "1d": 24 * 3600.0,
}

# Margine di anticipo prima della scadenza (secondi) — entra 5 minuti prima
_BOOST_ANTICIPO_S: float = 5 * 60.0


@dataclass
class BoostState:
    """
    Stato persistente del Gathering Speed Boost per istanza.

    Logica di scheduling:
      - tipo:         "8h" | "1d" | None  (ultimo boost attivato)
      - attivato_il:  ISO UTC attivazione  (None = mai attivato)
      - scadenza:     ISO UTC scadenza     (None = mai attivato)
      - disponibile:  True  = boost trovato e attivato
                      False = nessun boost disponibile in quel tick

    Regole should_run():
      1. Mai attivato (scadenza=None)              → entra sempre
      2. disponibile=False                          → entra sempre (riprova)
      3. now >= scadenza - ANTICIPO                 → entra (boost scaduto/in scadenza)
      4. now <  scadenza - ANTICIPO                 → skip

    Tempo 0 (primo avvio, nessuno storico):
      Il task entra, trova boost GIÀ ATTIVO (pin_50_), chiama
      registra_attivo("8h") con attivato_il=now → scadenza = now + 8h.

    Formato JSON in state/<ISTANZA>.json:
      "boost": {
        "tipo":        "8h",
        "attivato_il": "2026-04-16T08:00:00+00:00",
        "scadenza":    "2026-04-16T16:00:00+00:00",
        "disponibile": true
      }
    """

    tipo:        str | None = None   # "8h" | "1d" | None
    attivato_il: str | None = None   # ISO UTC
    scadenza:    str | None = None   # ISO UTC
    disponibile: bool       = True   # False = nessun boost trovato nell'ultimo run

    # ── Proprietà derivate ────────────────────────────────────────────────────

    @property
    def scadenza_dt(self) -> datetime | None:
        """Scadenza come datetime UTC. None se non impostata."""
        if not self.scadenza:
            return None
        try:
            return datetime.fromisoformat(self.scadenza)
        except (ValueError, TypeError):
            return None

    @property
    def secondi_alla_scadenza(self) -> float:
        """
        Secondi mancanti alla scadenza (negativo = già scaduto).
        Ritorna -1.0 se scadenza non impostata.
        """
        dt = self.scadenza_dt
        if dt is None:
            return -1.0
        return (dt - _utc_now()).total_seconds()

    @property
    def is_attivo(self) -> bool:
        """True se il boost è ancora attivo (scadenza nel futuro con margine)."""
        return self.secondi_alla_scadenza > _BOOST_ANTICIPO_S

    # ── Business logic ────────────────────────────────────────────────────────

    def should_run(self) -> bool:
        """
        True se BoostTask deve essere eseguito.

        Ritorna True se:
          - mai attivato (nessuna scadenza)
          - ultimo run senza boost disponibile (riprova)
          - boost scaduto o in scadenza (entro ANTICIPO)
        """
        if self.scadenza is None:
            return True          # mai attivato → entra
        if not self.disponibile:
            return True          # nessun boost trovato → riprova sempre
        return not self.is_attivo  # scaduto/in scadenza → entra

    def registra_attivo(self, tipo: str, riferimento: datetime | None = None) -> None:
        """
        Registra attivazione boost (o boost già attivo trovato).

        Args:
            tipo:        "8h" | "1d"
            riferimento: datetime UTC di riferimento per il calcolo scadenza.
                         None = ora corrente. Usare ora corrente anche quando
                         il boost è già attivo (approssimazione conservativa).
        """
        durata = _BOOST_DURATE.get(tipo, _BOOST_DURATE["8h"])
        t0     = riferimento or _utc_now()
        self.tipo        = tipo
        self.attivato_il = t0.isoformat()
        self.scadenza    = (t0 + __import__("datetime").timedelta(seconds=durata)).isoformat()
        self.disponibile = True

    def registra_non_disponibile(self) -> None:
        """
        Nessun boost gratuito trovato. Non altera tipo/scadenza esistenti.
        Al prossimo tick should_run() tornerà True (riprova).
        """
        self.disponibile = False

    def log_stato(self) -> str:
        """Stringa descrittiva per il log."""
        if self.scadenza is None:
            return "mai attivato"
        rimasti = self.secondi_alla_scadenza
        segno   = "+" if rimasti >= 0 else "-"
        minuti  = abs(int(rimasti)) // 60
        ore     = minuti // 60
        min_r   = minuti % 60
        stato   = "ATTIVO" if self.is_attivo else "SCADUTO"
        disp    = "" if self.disponibile else " [nessun boost]"
        return (
            f"tipo={self.tipo}  scadenza={self.scadenza}  "
            f"{stato} ({segno}{ore}h{min_r:02d}m){disp}"
        )

    # ── Serializzazione ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "BoostState":
        return cls(
            tipo        = d.get("tipo",        None),
            attivato_il = d.get("attivato_il", None),
            scadenza    = d.get("scadenza",    None),
            disponibile = d.get("disponibile", True),
        )

    def to_dict(self) -> dict:
        return {
            "tipo":        self.tipo,
            "attivato_il": self.attivato_il,
            "scadenza":    self.scadenza,
            "disponibile": self.disponibile,
        }




# ==============================================================================
# VipState — stato giornaliero ricompense VIP
# ==============================================================================

@dataclass
class VipState:
    """
    Stato giornaliero delle ricompense VIP per istanza.

    Due ricompense indipendenti:
      - cass_ritirata: cassaforte (pin_vip_03_cass_aperta)
      - free_ritirato: claim free daily (pin_vip_05_free_aperto)

    Logica:
      - should_run() = True finché almeno una ricompensa non è stata ritirata
      - Quando entrambe ritirate → skip fino a mezzanotte UTC
      - Reset automatico a mezzanotte UTC
      - Schedule: always-run (interval=0.0) — gestisce anomalie e retry

    Aggiornamento in vip.py:
      - cass_aperta già al check iniziale → segna_cass()
      - free_aperto già al check iniziale → segna_free()
      - run COMPLETATO (cass_ok AND free_ok) → segna_completato()

    JSON in state/<ISTANZA>.json:
      "vip": {
        "cass_ritirata":    false,
        "free_ritirato":    false,
        "data_riferimento": "2026-04-16"
      }
    """

    cass_ritirata:    bool = False
    free_ritirato:    bool = False
    data_riferimento: str  = field(default_factory=_today_utc)

    # ── Business logic ────────────────────────────────────────────────────────

    def _controlla_reset(self) -> None:
        """Nuovo giorno UTC → reset entrambe le ricompense."""
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.cass_ritirata    = False
            self.free_ritirato    = False
            self.data_riferimento = oggi

    def should_run(self) -> bool:
        """True se almeno una ricompensa non è ancora stata ritirata oggi."""
        self._controlla_reset()
        return not (self.cass_ritirata and self.free_ritirato)

    def segna_cass(self) -> None:
        """Cassaforte ritirata (o già trovata aperta al check iniziale)."""
        self._controlla_reset()
        self.cass_ritirata = True

    def segna_free(self) -> None:
        """Claim free ritirato (o già trovato aperto al check iniziale)."""
        self._controlla_reset()
        self.free_ritirato = True

    def segna_completato(self) -> None:
        """Entrambe le ricompense ritirate in questo run."""
        self._controlla_reset()
        self.cass_ritirata = True
        self.free_ritirato = True

    def log_stato(self) -> str:
        """Stringa descrittiva per il log."""
        self._controlla_reset()
        cass = "OK" if self.cass_ritirata else "DA RITIRARE"
        free = "OK" if self.free_ritirato else "DA RITIRARE"
        if self.cass_ritirata and self.free_ritirato:
            return f"VIP COMPLETATO oggi ({self.data_riferimento})"
        return f"cassaforte={cass}  free={free} ({self.data_riferimento})"

    # ── Serializzazione ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "VipState":
        return cls(
            cass_ritirata    = d.get("cass_ritirata",    False),
            free_ritirato    = d.get("free_ritirato",    False),
            data_riferimento = d.get("data_riferimento", _today_utc()),
        )

    def to_dict(self) -> dict:
        return {
            "cass_ritirata":    self.cass_ritirata,
            "free_ritirato":    self.free_ritirato,
            "data_riferimento": self.data_riferimento,
        }


# ==============================================================================
# ArenaState — stato giornaliero sfide Arena of Glory
# ==============================================================================

@dataclass
class ArenaState:
    """
    Stato giornaliero delle sfide Arena of Glory.

    Design intenzionalmente minimale: non contiamo le sfide (nessun OCR
    sul contatore). L'unico segnale affidabile è il pin pin_arena_06_purchase
    che compare quando le sfide giornaliere sono esaurite.

    Logica:
      - esaurite=False → should_run()=True → ArenaTask entra
      - esaurite=True  → should_run()=False → skip per il resto del giorno
      - Reset automatico a mezzanotte UTC → esaurite torna False

    JSON in state/<ISTANZA>.json:
      "arena": {
        "esaurite":         false,
        "data_riferimento": "2026-04-16"
      }
    """

    esaurite:         bool = False
    data_riferimento: str  = field(default_factory=_today_utc)

    # ── Business logic ────────────────────────────────────────────────────────

    def _controlla_reset(self) -> None:
        """Nuovo giorno UTC → reset esaurite."""
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.esaurite         = False
            self.data_riferimento = oggi

    def should_run(self) -> bool:
        """True se le sfide non sono ancora esaurite oggi."""
        self._controlla_reset()
        return not self.esaurite

    def segna_esaurite(self) -> None:
        """
        Chiamato da ArenaTask quando pin_arena_06_purchase è rilevato.
        Blocca ulteriori esecuzioni fino alla mezzanotte UTC.
        """
        self._controlla_reset()
        self.esaurite = True

    def log_stato(self) -> str:
        """Stringa descrittiva per il log."""
        self._controlla_reset()
        if self.esaurite:
            return f"sfide ESAURITE oggi ({self.data_riferimento})"
        return f"sfide disponibili ({self.data_riferimento})"

    # ── Serializzazione ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "ArenaState":
        return cls(
            esaurite         = d.get("esaurite",         False),
            data_riferimento = d.get("data_riferimento", _today_utc()),
        )

    def to_dict(self) -> dict:
        return {
            "esaurite":         self.esaurite,
            "data_riferimento": self.data_riferimento,
        }


# ==============================================================================
# TruppeState — consumo risorse per addestramenti truppe (06/05)
# ==============================================================================

@dataclass
class TruppeState:
    """
    Stato giornaliero consumo risorse TruppeTask.

    Tracking del consumo cumulativo per scorporare prod_ora in
    chiudi_sessione_e_calcola: la formula reale di produzione e' infatti
        prod_qty = delta_castle - zaino_delta + rifornimento_inviato + Σ consumo_addestramenti
    Senza il termine consumo, prod_qty risulta NEGATIVO quando il gioco
    consuma piu' risorse (truppe + costruzioni) di quanto produce.

    Reset 00:00 UTC via _controlla_reset al cambio data_riferimento.

    JSON in state/<ISTANZA>.json:
      "truppe": {
        "consumo_oggi": {"pomodoro": 524300, "legno": 262100, ...},
        "data_riferimento": "2026-05-06"
      }
    """

    consumo_oggi:     dict = field(default_factory=dict)
    data_riferimento: str  = field(default_factory=_today_utc)

    def _controlla_reset(self) -> None:
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.consumo_oggi = {}
            self.data_riferimento = oggi

    def aggiungi_consumo(self, consumo: dict) -> None:
        """
        Accumula il consumo letto da OCR maschera Squad Training.
        Sanity check: scarta valori implausibili (< 100 = OCR fail).
        """
        self._controlla_reset()
        for risorsa, qta in consumo.items():
            try:
                qta_int = int(qta)
                if qta_int < 100:   # OCR fail (es. "5" da "45.0K") → scarto
                    continue
                if qta_int > 10_000_000:   # sanity: max 10M per training
                    continue
                self.consumo_oggi[risorsa] = self.consumo_oggi.get(risorsa, 0) + qta_int
            except (ValueError, TypeError):
                continue

    @classmethod
    def from_dict(cls, d: dict) -> "TruppeState":
        return cls(
            consumo_oggi     = dict(d.get("consumo_oggi", {})),
            data_riferimento = d.get("data_riferimento", _today_utc()),
        )

    def to_dict(self) -> dict:
        return {
            "consumo_oggi":     dict(self.consumo_oggi),
            "data_riferimento": self.data_riferimento,
        }


# ==============================================================================
# DailyTasksState — completamento task giornalieri
# ==============================================================================

# Nomi canonici dei task giornalieri
DAILY_TASK_KEYS = frozenset({
    "boost",
    "vip",
    "store",
    "messaggi",
    "alleanza",
    "arena",
    "arena_mercato",
    "zaino",
    "radar",
})


@dataclass
class DailyTasksState:
    """
    Traccia quali task giornalieri sono stati completati.

    Ogni task ha:
      - completato: bool
      - timestamp: str | None (ISO UTC dell'ultimo completamento)

    Il reset avviene all'inizio di ogni nuovo giorno UTC.
    """

    data_riferimento: str = field(default_factory=_today_utc)
    completati: dict[str, bool] = field(default_factory=dict)
    timestamps: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Assicura che tutte le chiavi canoniche esistano
        for key in DAILY_TASK_KEYS:
            self.completati.setdefault(key, False)
            self.timestamps.setdefault(key, None)

    def _controlla_reset(self) -> None:
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.data_riferimento = oggi
            for key in DAILY_TASK_KEYS:
                self.completati[key] = False
                self.timestamps[key] = None

    def is_completato(self, task: str) -> bool:
        """True se il task è già stato completato oggi."""
        self._controlla_reset()
        return self.completati.get(task, False)

    def segna_completato(self, task: str) -> None:
        """Marca il task come completato con timestamp corrente."""
        self._controlla_reset()
        self.completati[task] = True
        self.timestamps[task] = _ts_now()

    def task_pendenti(self, task_abilitati: set[str] | None = None) -> list[str]:
        """
        Ritorna la lista dei task non ancora completati.
        Se task_abilitati è fornito, filtra solo quelli abilitati per l'istanza.
        """
        self._controlla_reset()
        filtro = task_abilitati or DAILY_TASK_KEYS
        return [k for k in filtro if not self.completati.get(k, False)]

    @property
    def tutti_completati(self) -> bool:
        """True se tutti i task canonici sono completati."""
        self._controlla_reset()
        return all(self.completati.get(k, False) for k in DAILY_TASK_KEYS)

    @classmethod
    def from_dict(cls, d: dict) -> "DailyTasksState":
        obj = cls(
            data_riferimento=d.get("data_riferimento", _today_utc()),
            completati=dict(d.get("completati", {})),
            timestamps=dict(d.get("timestamps", {})),
        )
        # Assicura chiavi canoniche anche su dati letti da disco
        obj.__post_init__()
        return obj

    def to_dict(self) -> dict:
        return {
            "data_riferimento": self.data_riferimento,
            "completati": dict(self.completati),
            "timestamps": dict(self.timestamps),
        }


# ==============================================================================
# MetricsState — metriche produzione
# ==============================================================================

# ==============================================================================
# ProduzioneSession — auto-WU14: tracciamento produzione oraria per sessione
# ==============================================================================

@dataclass
class ProduzioneSession:
    """
    Sessione di produzione: dati aggregati tra avvio istanza N e avvio N+1.

    Calcolo produzione (alla chiusura, all'avvio della sessione successiva):
        delta_castle  = risorse_finali - risorse_iniziali
        produzione    = delta_castle - zaino_delta + rifornimento_inviato
        prod_oraria   = produzione / durata_sec × 3600

    Tutti i campi _delta accumulano segno positivo=entrato/segno negativo=uscito
    dal castello durante la sessione.
    """
    ts_inizio: str = ""                                 # ISO timestamp avvio
    risorse_iniziali: dict = field(default_factory=dict)  # {pomodoro, legno, acciaio, petrolio} (M float)
    diamanti_iniziali: int = -1                         # snapshot diamanti

    # Cumulativi durante sessione
    rifornimento_inviato: dict = field(default_factory=dict)  # {risorsa: qta_clamped}
    rifornimento_tassa:   dict = field(default_factory=dict)  # {risorsa: qta_clamped × tassa}
    rifornimento_provviste_residue: int = -1                  # 0 = quota esaurita, -1 = mai letto
    zaino_delta: dict = field(default_factory=dict)           # {risorsa: delta} +entra castle, -esce
    truppe_raccolta_inviate: int = 0                          # count nodi raccolta avviati
    tasks_count: dict = field(default_factory=dict)           # auto-WU14: {task_name: count} eseguiti in sessione

    # Chiusura (popolata dalla sessione successiva)
    ts_fine:           str | None = None
    risorse_finali:    dict | None = None
    durata_sec:        float | None = None
    produzione_qty:    dict | None = None  # {risorsa: qty totale prodotta}
    produzione_oraria: dict | None = None  # {risorsa: qty/h}
    # Issue #25 fix (03/05): tracking delta diamanti per sessione
    diamanti_finali:   int  = -1
    diamanti_delta:    int  = 0   # diamanti_finali - diamanti_iniziali (calcolato a chiusura)

    @classmethod
    def from_dict(cls, d: dict) -> "ProduzioneSession":
        return cls(
            ts_inizio=d.get("ts_inizio", ""),
            risorse_iniziali=dict(d.get("risorse_iniziali", {})),
            diamanti_iniziali=d.get("diamanti_iniziali", -1),
            rifornimento_inviato=dict(d.get("rifornimento_inviato", {})),
            rifornimento_tassa=dict(d.get("rifornimento_tassa", {})),
            rifornimento_provviste_residue=d.get("rifornimento_provviste_residue", -1),
            zaino_delta=dict(d.get("zaino_delta", {})),
            truppe_raccolta_inviate=d.get("truppe_raccolta_inviate", 0),
            tasks_count=dict(d.get("tasks_count", {})),
            ts_fine=d.get("ts_fine"),
            risorse_finali=d.get("risorse_finali"),
            durata_sec=d.get("durata_sec"),
            produzione_qty=d.get("produzione_qty"),
            produzione_oraria=d.get("produzione_oraria"),
            diamanti_finali=d.get("diamanti_finali", -1),
            diamanti_delta=d.get("diamanti_delta", 0),
        )

    def to_dict(self) -> dict:
        return {
            "ts_inizio": self.ts_inizio,
            "risorse_iniziali": dict(self.risorse_iniziali),
            "diamanti_iniziali": self.diamanti_iniziali,
            "rifornimento_inviato": dict(self.rifornimento_inviato),
            "rifornimento_tassa": dict(self.rifornimento_tassa),
            "rifornimento_provviste_residue": self.rifornimento_provviste_residue,
            "zaino_delta": dict(self.zaino_delta),
            "truppe_raccolta_inviate": self.truppe_raccolta_inviate,
            "tasks_count": dict(self.tasks_count),
            "ts_fine": self.ts_fine,
            "risorse_finali": self.risorse_finali,
            "durata_sec": self.durata_sec,
            "produzione_qty": self.produzione_qty,
            "produzione_oraria": self.produzione_oraria,
            "diamanti_finali": self.diamanti_finali,
            "diamanti_delta":  self.diamanti_delta,
        }

    def aggiungi_rifornimento(self, risorsa: str, qta_clamped: int, tassa_amount: int) -> None:
        """Hook chiamato da rifornimento ad ogni spedizione completata."""
        self.rifornimento_inviato[risorsa] = self.rifornimento_inviato.get(risorsa, 0) + qta_clamped
        self.rifornimento_tassa[risorsa]   = self.rifornimento_tassa.get(risorsa, 0)   + tassa_amount

    def aggiungi_zaino_delta(self, risorsa: str, delta: int) -> None:
        """Hook chiamato da zaino post-operazione (positivo=entrato castle)."""
        self.zaino_delta[risorsa] = self.zaino_delta.get(risorsa, 0) + delta

    def incrementa_truppe(self, n: int = 1) -> None:
        """Hook chiamato da raccolta ad ogni marcia avviata."""
        self.truppe_raccolta_inviate += n

    def incrementa_task(self, task_name: str, n: int = 1) -> None:
        """Hook chiamato dall'orchestrator per task eseguiti nel tick."""
        self.tasks_count[task_name] = self.tasks_count.get(task_name, 0) + n


@dataclass
class MetricsState:
    """
    Metriche di produzione dell'istanza (aggiornate ad ogni ciclo di raccolta).

    Tutte le metriche _per_ora sono valori float calcolati esternamente
    e scritti qui per la visualizzazione nel dashboard.
    """

    # Risorse raccolte nell'ultima sessione
    pomodoro_per_ora: float = 0.0
    legno_per_ora: float = 0.0
    petrolio_per_ora: float = 0.0
    acciaio_per_ora: float = 0.0

    # Contatori cumulativi dalla partenza del bot (non si resettano)
    marce_inviate_totali: int = 0
    cicli_completati: int = 0
    errori_totali: int = 0

    # Timestamp ultimo aggiornamento
    ultimo_aggiornamento: str | None = None

    def aggiorna_risorse(
        self,
        pomodoro: float = 0.0,
        legno: float = 0.0,
        petrolio: float = 0.0,
        acciaio: float = 0.0,
    ) -> None:
        """Aggiorna le metriche di produzione oraria."""
        self.pomodoro_per_ora = pomodoro
        self.legno_per_ora = legno
        self.petrolio_per_ora = petrolio
        self.acciaio_per_ora = acciaio
        self.ultimo_aggiornamento = _ts_now()

    def incrementa_marce(self, n: int = 1) -> None:
        self.marce_inviate_totali += n

    def incrementa_cicli(self) -> None:
        self.cicli_completati += 1

    def incrementa_errori(self) -> None:
        self.errori_totali += 1

    @classmethod
    def from_dict(cls, d: dict) -> "MetricsState":
        return cls(
            pomodoro_per_ora=d.get("pomodoro_per_ora", 0.0),
            legno_per_ora=d.get("legno_per_ora", 0.0),
            petrolio_per_ora=d.get("petrolio_per_ora", 0.0),
            acciaio_per_ora=d.get("acciaio_per_ora", 0.0),
            marce_inviate_totali=d.get("marce_inviate_totali", 0),
            cicli_completati=d.get("cicli_completati", 0),
            errori_totali=d.get("errori_totali", 0),
            ultimo_aggiornamento=d.get("ultimo_aggiornamento", None),
        )

    def to_dict(self) -> dict:
        return {
            "pomodoro_per_ora": self.pomodoro_per_ora,
            "legno_per_ora": self.legno_per_ora,
            "petrolio_per_ora": self.petrolio_per_ora,
            "acciaio_per_ora": self.acciaio_per_ora,
            "marce_inviate_totali": self.marce_inviate_totali,
            "cicli_completati": self.cicli_completati,
            "errori_totali": self.errori_totali,
            "ultimo_aggiornamento": self.ultimo_aggiornamento,
        }


# ==============================================================================
# InstanceState — contenitore principale
# ==============================================================================

@dataclass
class InstanceState:
    """
    Stato completo di una singola istanza bot.

    È l'unico punto di I/O su disco: load() legge il JSON,
    save() lo scrive. Tutte le sezioni sono tipizzate.

    Il file JSON viene salvato in:
        {state_dir}/{instance_name}.json
    """

    instance_name: str
    rifornimento: RifornimentoState = field(default_factory=RifornimentoState)
    daily_tasks:  DailyTasksState   = field(default_factory=DailyTasksState)
    metrics:      MetricsState      = field(default_factory=MetricsState)
    schedule:     ScheduleState     = field(default_factory=ScheduleState)
    boost:        BoostState        = field(default_factory=BoostState)
    vip:          VipState          = field(default_factory=VipState)
    arena:        ArenaState        = field(default_factory=ArenaState)
    truppe:       TruppeState       = field(default_factory=TruppeState)   # 06/05

    # auto-WU14: produzione oraria per sessione
    produzione_corrente: ProduzioneSession | None = None
    produzione_storico:  list = field(default_factory=list)  # list[ProduzioneSession] ultime 24h

    # Stato runtime non persistito (ricostruito all'avvio)
    attivo: bool = False
    ultimo_errore: str | None = None
    ultimo_avvio: str | None = None

    # ── Serializzazione ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "instance_name": self.instance_name,
            "rifornimento":  self.rifornimento.to_dict(),
            "daily_tasks":   self.daily_tasks.to_dict(),
            "metrics":       self.metrics.to_dict(),
            "schedule":      self.schedule.to_dict(),
            "boost":         self.boost.to_dict(),
            "vip":           self.vip.to_dict(),
            "arena":         self.arena.to_dict(),
            "truppe":        self.truppe.to_dict(),   # 06/05 consumo addestramento
            # auto-WU14: produzione oraria
            "produzione_corrente": self.produzione_corrente.to_dict() if self.produzione_corrente else None,
            "produzione_storico":  [s.to_dict() for s in self.produzione_storico],
            "ultimo_errore": self.ultimo_errore,
            "ultimo_avvio":  self.ultimo_avvio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceState":
        # auto-WU14: deserializzazione produzione_corrente / storico
        pc_raw = d.get("produzione_corrente")
        pc = ProduzioneSession.from_dict(pc_raw) if pc_raw else None
        ps_raw = d.get("produzione_storico", [])
        ps = [ProduzioneSession.from_dict(s) for s in ps_raw if s]

        return cls(
            instance_name=d.get("instance_name", "UNKNOWN"),
            rifornimento=RifornimentoState.from_dict(d.get("rifornimento", {})),
            daily_tasks=DailyTasksState.from_dict(d.get("daily_tasks", {})),
            metrics=MetricsState.from_dict(d.get("metrics", {})),
            schedule=ScheduleState.from_dict(d.get("schedule", {})),
            boost=BoostState.from_dict(d.get("boost", {})),
            vip=VipState.from_dict(d.get("vip", {})),
            arena=ArenaState.from_dict(d.get("arena", {})),
            truppe=TruppeState.from_dict(d.get("truppe", {})),   # 06/05
            produzione_corrente=pc,
            produzione_storico=ps,
            ultimo_errore=d.get("ultimo_errore", None),
            ultimo_avvio=d.get("ultimo_avvio", None),
        )

    # ── auto-WU14: gestione produzione sessione ──────────────────────────────

    def chiudi_sessione_e_calcola(
        self,
        risorse_finali: dict,
        ts_fine: str,
        diamanti_finali: int = -1,
    ) -> "ProduzioneSession | None":
        """
        Chiude la sessione corrente con risorse_finali OCR (lette all'avvio
        della sessione SUCCESSIVA) e calcola produzione oraria.

        Formula:
            delta_castle  = risorse_finali - risorse_iniziali
            produzione    = delta_castle - zaino_delta + rifornimento_inviato
            prod_oraria   = produzione / durata_sec × 3600

        Archivia in produzione_storico (FIFO 24h) e ritorna la sessione chiusa.
        Se non c'era sessione corrente, ritorna None.
        """
        from datetime import datetime, timezone, timedelta

        sess = self.produzione_corrente
        if sess is None or not sess.ts_inizio:
            return None

        try:
            t0 = datetime.fromisoformat(sess.ts_inizio)
            t1 = datetime.fromisoformat(ts_fine)
            durata = max(0.0, (t1 - t0).total_seconds())
        except Exception:
            durata = 0.0

        # Calcolo produzione per ogni risorsa nota.
        # Formula: prod = delta_castle - zaino_delta + rifornimento_inv
        # 06/05: scorporo consumo addestramento RIMOSSO (era basato su OCR
        # `leggi_consumo_addestramento` troppo fragile — perdeva cifre iniziali
        # es "13.0K" letto come "3.0K", e i valori cumulativi amplificavano
        # l'errore). Per istanze ordinarie il delta_castle vede già
        # implicitamente il consumo (è la lettura DOPO l'addestramento).
        prod_qty = {}
        prod_ora = {}
        for r in ("pomodoro", "legno", "acciaio", "petrolio"):
            ini = float(sess.risorse_iniziali.get(r, 0) or 0)
            fin = float(risorse_finali.get(r, 0) or 0)
            inv = int(sess.rifornimento_inviato.get(r, 0))
            zd  = int(sess.zaino_delta.get(r, 0))
            delta_castle = fin - ini
            prod = delta_castle - zd + inv
            prod_qty[r] = prod
            prod_ora[r] = (prod / durata * 3600.0) if durata > 0 else 0.0

        sess.ts_fine        = ts_fine
        sess.risorse_finali = dict(risorse_finali)
        sess.durata_sec     = durata
        sess.produzione_qty = prod_qty
        sess.produzione_oraria = prod_ora
        # Issue #25 fix (03/05): persiste delta diamanti se entrambi i valori
        # sono validi (>= 0). Diamanti_iniziali a -1 = mai letto → no delta.
        if diamanti_finali >= 0 and sess.diamanti_iniziali >= 0:
            sess.diamanti_finali = int(diamanti_finali)
            sess.diamanti_delta  = int(diamanti_finali) - int(sess.diamanti_iniziali)
        elif diamanti_finali >= 0:
            sess.diamanti_finali = int(diamanti_finali)

        # 05/05: per istanze master (FauMorfeus), sottrai dal delta_castle le
        # risorse RICEVUTE dalle altre istanze nella finestra [ts_inizio,
        # ts_fine]. Fonte: state/{altra_istanza}.json::rifornimento.dettaglio_oggi
        # (filtrato per ts e risorsa, NETTO `qta_inviata` post-tassa). Senza
        # questa sottrazione prod_ora del master sarebbe gonfiato dal traffico
        # rifornimento (es. produzione interna 1M/h ma misurato 50M/h se 11
        # istanze inviano 50M nel periodo). Best-effort: errori di lettura
        # delle altre state files producono ricevuto=0 per quelle istanze.
        from shared.instance_meta import is_master_instance
        is_master = is_master_instance(self.instance_name)
        if is_master:
            ricevuto = _calcola_ricevuto_da_alleati(self.instance_name, sess.ts_inizio, ts_fine)
            for r in ("pomodoro", "legno", "acciaio", "petrolio"):
                qta_ricevuta = int(ricevuto.get(r, 0))
                prod_qty[r] = prod_qty[r] - qta_ricevuta
                prod_ora[r] = (prod_qty[r] / durata * 3600.0) if durata > 0 else 0.0
            sess.produzione_qty = prod_qty
            sess.produzione_oraria = prod_ora

        # WU47 — propaga produzione_oraria a metrics.*_per_ora.
        # La dashboard "produzione/ora — farm aggregata" somma questi valori
        # tra tutte le istanze. Senza propagazione metrics restano 0.0 e il
        # pannello mostra "in attesa del primo ciclo raccolta" perpetuo.
        # Filtro: solo sessioni con durata >= 300s (5 min) per evitare swing
        # spurious da tick brevissimi.
        # 05/05: master ora usa prod_ora corretto (post-sottrazione ricevuto).
        if durata >= 300:
            try:
                self.metrics.aggiorna_risorse(
                    pomodoro = float(prod_ora.get("pomodoro", 0.0)),
                    legno    = float(prod_ora.get("legno",    0.0)),
                    petrolio = float(prod_ora.get("petrolio", 0.0)),
                    acciaio  = float(prod_ora.get("acciaio",  0.0)),
                )
            except Exception:
                pass

        # Archivia in storico
        self.produzione_storico.append(sess)

        # Cleanup FIFO 24h
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self.produzione_storico = [
            s for s in self.produzione_storico
            if s.ts_fine and _ts_after(s.ts_fine, cutoff)
        ]

        chiusa = sess
        self.produzione_corrente = None
        return chiusa

    def apri_sessione(self, risorse_iniziali: dict, diamanti: int, ts_inizio: str) -> None:
        """Apre una nuova sessione produzione con snapshot risorse all'avvio."""
        self.produzione_corrente = ProduzioneSession(
            ts_inizio=ts_inizio,
            risorse_iniziali=dict(risorse_iniziali),
            diamanti_iniziali=diamanti,
        )

    # ── Persistenza su disco ──────────────────────────────────────────────────

    @classmethod
    def load(cls, instance_name: str, state_dir: str | Path = "state") -> "InstanceState":
        """
        Carica lo stato dal file JSON.
        Se il file non esiste, ritorna uno stato nuovo (fresh start).

        Args:
            instance_name: nome istanza (es. "FAU_00")
            state_dir:     directory dove sono i file JSON
        """
        path = Path(state_dir) / f"{instance_name}.json"
        if not path.exists():
            return cls(instance_name=instance_name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            # File corrotto → ricomincia da zero, non crashare
            return cls(instance_name=instance_name)

    def save(self, state_dir: str | Path = "state") -> None:
        """
        Salva lo stato su disco in formato JSON, atomico.

        Pattern tmp + fsync + os.replace:
          - scrittura su file .tmp
          - f.flush() + os.fsync() forzano il write fisico su disco
            (evita corruzione in caso di crash / power-loss con HDD lento)
          - os.replace() rinomina atomicamente (NTFS/ext4)
          - Se il processo muore prima di os.replace: file originale intatto
          - Se muore dopo: nuovo file completo e consistente

        Args:
            state_dir: directory dove salvare il file JSON
        """
        path = Path(state_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / f"{self.instance_name}.json"
        tmp_path  = file_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)

    # ── Shortcut per i task (delegano alle sezioni) ───────────────────────────

    def segna_avvio(self) -> None:
        """Registra l'avvio dell'istanza."""
        self.attivo = True
        self.ultimo_avvio = _ts_now()

    def segna_errore(self, messaggio: str) -> None:
        """Registra l'ultimo errore e incrementa il contatore."""
        self.ultimo_errore = f"{_ts_now()} — {messaggio}"
        self.metrics.incrementa_errori()

    def __repr__(self) -> str:
        rf = self.rifornimento
        dt = self.daily_tasks
        return (
            f"InstanceState({self.instance_name!r}, "
            f"rif={rf.spedizioni_oggi}/{rf.quota_max}, "
            f"tasks_completati={sum(dt.completati.values())}/{len(DAILY_TASK_KEYS)})"
        )
