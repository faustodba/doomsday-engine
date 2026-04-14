# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/state.py
#
#  Stato runtime di una singola istanza, persistito su disco come JSON.
#
#  Classi:
#    RifornimentoState  — quota giornaliera spedizioni, reset automatico
#    DailyTasksState    — flag completamento task giornalieri con timestamp
#    MetricsState       — metriche produzione (risorse/ora, marce inviate)
#    InstanceState      — contenitore principale, carica/salva JSON
#
#  Design:
#    - Ogni sezione è un dataclass autonomo con metodi di business logic
#    - InstanceState è l'unico punto di I/O su disco (load/save)
#    - Nessuna dipendenza da device.py o config.py — layer puro di dati
#    - I timestamp sono sempre UTC (datetime.now(UTC))
#    - Il reset giornaliero usa la data UTC, non l'ora locale
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
    daily_tasks: DailyTasksState = field(default_factory=DailyTasksState)
    metrics: MetricsState = field(default_factory=MetricsState)

    # Stato runtime non persistito (ricostruito all'avvio)
    attivo: bool = False
    ultimo_errore: str | None = None
    ultimo_avvio: str | None = None

    # ── Serializzazione ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "instance_name": self.instance_name,
            "rifornimento": self.rifornimento.to_dict(),
            "daily_tasks": self.daily_tasks.to_dict(),
            "metrics": self.metrics.to_dict(),
            "ultimo_errore": self.ultimo_errore,
            "ultimo_avvio": self.ultimo_avvio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceState":
        return cls(
            instance_name=d.get("instance_name", "UNKNOWN"),
            rifornimento=RifornimentoState.from_dict(d.get("rifornimento", {})),
            daily_tasks=DailyTasksState.from_dict(d.get("daily_tasks", {})),
            metrics=MetricsState.from_dict(d.get("metrics", {})),
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
