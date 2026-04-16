# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/state.py
#
#  Stato runtime di una singola istanza, persistito su disco come JSON.
#
#  Classi:
#    RifornimentoState  — quota giornaliera spedizioni, reset automatico
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

    # Statistiche giornaliere
    provviste_residue: int = -1
    inviato_oggi: dict = field(default_factory=dict)   # {risorsa: int}
    dettaglio_oggi: list = field(default_factory=list) # [{ts, risorsa, qta, provviste}]

    def _controlla_reset(self) -> None:
        """Se siamo in un nuovo giorno UTC, azzera il contatore e le statistiche."""
        oggi = _today_utc()
        if self.data_riferimento != oggi:
            self.spedizioni_oggi = 0
            self.data_riferimento = oggi
            self.provviste_residue = -1
            self.inviato_oggi = {}
            self.dettaglio_oggi = []

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

    def registra_spedizione(self,
                            risorsa: str = "",
                            qta_inviata: int = 0,
                            provviste_residue: int = -1) -> None:
        """
        Incrementa il contatore, aggiorna timestamp e registra statistiche.

        Args:
            risorsa:          nome risorsa inviata (es. "pomodoro")
            qta_inviata:      quantità reale inviata (snapshot_pre - snapshot_post)
            provviste_residue: provviste rimanenti lette dopo il VAI (-1 = non lette)
        """
        self._controlla_reset()
        self.spedizioni_oggi += 1
        self.ultima_spedizione = _ts_now()

        if provviste_residue >= 0:
            self.provviste_residue = provviste_residue

        if risorsa and qta_inviata > 0:
            self.inviato_oggi[risorsa] = self.inviato_oggi.get(risorsa, 0) + qta_inviata
            self.dettaglio_oggi.append({
                "ts":               self.ultima_spedizione,
                "risorsa":          risorsa,
                "qta_inviata":      qta_inviata,
                "provviste_residue": provviste_residue,
            })

    def totale_inviato(self) -> int:
        """Totale risorse inviate oggi su tutte le risorse."""
        return sum(self.inviato_oggi.values())

    def reset_forzato(self) -> None:
        """Azzera manualmente la quota (es. dopo cambio data manuale)."""
        self.spedizioni_oggi = 0
        self.data_riferimento = _today_utc()
        self.ultima_spedizione = None
        self.provviste_residue = -1
        self.inviato_oggi = {}
        self.dettaglio_oggi = []

    @classmethod
    def from_dict(cls, d: dict) -> "RifornimentoState":
        return cls(
            spedizioni_oggi=d.get("spedizioni_oggi", 0),
            quota_max=d.get("quota_max", 5),
            data_riferimento=d.get("data_riferimento", _today_utc()),
            ultima_spedizione=d.get("ultima_spedizione", None),
            provviste_residue=d.get("provviste_residue", -1),
            inviato_oggi=dict(d.get("inviato_oggi", {})),
            dettaglio_oggi=list(d.get("dettaglio_oggi", [])),
        )

    def to_dict(self) -> dict:
        return {
            "spedizioni_oggi":    self.spedizioni_oggi,
            "quota_max":          self.quota_max,
            "data_riferimento":   self.data_riferimento,
            "ultima_spedizione":  self.ultima_spedizione,
            "provviste_residue":  self.provviste_residue,
            "inviato_oggi":       self.inviato_oggi,
            "dettaglio_oggi":     self.dettaglio_oggi,
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
            "ultimo_errore": self.ultimo_errore,
            "ultimo_avvio":  self.ultimo_avvio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceState":
        return cls(
            instance_name=d.get("instance_name", "UNKNOWN"),
            rifornimento=RifornimentoState.from_dict(d.get("rifornimento", {})),
            daily_tasks=DailyTasksState.from_dict(d.get("daily_tasks", {})),
            metrics=MetricsState.from_dict(d.get("metrics", {})),
            schedule=ScheduleState.from_dict(d.get("schedule", {})),
            boost=BoostState.from_dict(d.get("boost", {})),
            vip=VipState.from_dict(d.get("vip", {})),
            arena=ArenaState.from_dict(d.get("arena", {})),
            ultimo_errore=d.get("ultimo_errore", None),
            ultimo_avvio=d.get("ultimo_avvio", None),
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
        Salva lo stato su disco in formato JSON.
        Crea la directory se non esiste.

        Args:
            state_dir: directory dove salvare il file JSON
        """
        path = Path(state_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / f"{self.instance_name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

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
