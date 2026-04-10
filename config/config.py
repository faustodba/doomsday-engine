# ==============================================================================
#  DOOMSDAY ENGINE V6 - config/config.py
#
#  Costanti globali del bot e InstanceConfig tipizzata.
#
#  Contenuto:
#    BotConfig       — costanti globali (path MuMu, directory, risoluzione)
#    InstanceConfig  — configurazione per-istanza, caricata da instances.json
#    load_instances()— carica e valida la lista istanze dal file JSON
#
#  Design:
#    - BotConfig: costanti pure, nessun I/O
#    - InstanceConfig: dataclass con validazione in __post_init__
#    - load_instances(): unico punto di lettura del file JSON
#    - port e adb_serial sono @property derivate da index (mai nel JSON)
#    - Errori di validazione → ValueError con messaggio chiaro
# ==============================================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ==============================================================================
# BotConfig — costanti globali
# ==============================================================================

class BotConfig:
    """
    Costanti globali del bot. Tutti i path sono per Windows.
    Sovrascrivibili tramite variabili d'ambiente o config locale.
    """

    # ── MuMu Player ──────────────────────────────────────────────────────────
    MUMU_ADB_EXE: str = (
        r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
    )
    MUMU_MANAGER_EXE: str = (
        r"C:\Program Files\Netease\MuMuPlayer\shell\MuMuManager.exe"
    )

    # Porta ADB: 16384 + index * 32
    ADB_PORT_BASE: int = 16384
    ADB_PORT_STEP: int = 32

    # ── Directory del bot ────────────────────────────────────────────────────
    BOT_DIR:       str = r"C:\doomsday-engine"
    TEMPLATE_DIR:  str = r"C:\doomsday-engine\templates"
    STATE_DIR:     str = r"C:\doomsday-engine\state"
    LOG_DIR:       str = r"C:\doomsday-engine\logs"

    # ── Risoluzione schermo ───────────────────────────────────────────────────
    SCREEN_WIDTH:  int = 960
    SCREEN_HEIGHT: int = 540

    # ── Parametri bot ────────────────────────────────────────────────────────
    # Intervallo minimo tra cicli (secondi)
    CYCLE_INTERVAL_MIN: float = 10.0

    # Timeout ADB per operazioni singole (secondi)
    ADB_TIMEOUT: float = 30.0

    # Massimo istanze parallele attive contemporaneamente
    MAX_PARALLEL: int = 2

    @classmethod
    def adb_port(cls, index: int) -> int:
        return cls.ADB_PORT_BASE + index * cls.ADB_PORT_STEP

    @classmethod
    def adb_serial(cls, index: int) -> str:
        return f"127.0.0.1:{cls.adb_port(index)}"


# ==============================================================================
# Valori ammessi per validazione
# ==============================================================================

RISORSE_VALIDE   = frozenset({"pomodoro", "legno", "petrolio", "acciaio"})
PROFILI_VALIDI   = frozenset({"standard", "raccolta_only"})
LINGUE_VALIDE    = frozenset({"it", "en"})
TASK_VALIDI      = frozenset({
    "boost", "store", "messaggi", "alleanza", "vip",
    "arena", "arena_mercato", "radar", "zaino",
    "rifornimento", "raccolta",
})

# Intervalli default (ore) per task periodici
INTERVALLI_DEFAULT: dict[str, float] = {
    "store":         4.0,
    "messaggi":      4.0,
    "alleanza":      4.0,
    "radar":        12.0,
    "arena_mercato":12.0,
}


# ==============================================================================
# InstanceConfig — configurazione per-istanza
# ==============================================================================

@dataclass
class InstanceConfig:
    """
    Configurazione completa di una singola istanza bot.

    Caricata da instances.json, validata in __post_init__.
    Le proprietà `port` e `adb_serial` sono derivate da `index`
    e non devono mai comparire nel file JSON.
    """

    # ── Identità ─────────────────────────────────────────────────────────────
    name:     str   # "FAU_00"
    index:    int   # 0 → porta = 16384 + 0*32 = 16384
    language: str   # "it" | "en"

    # ── Profilo ──────────────────────────────────────────────────────────────
    max_squadre:  int          # 4 | 5
    profilo:      str          # "standard" | "raccolta_only"
    fascia_oraria: tuple[int, int] | None  # (ora_inizio, ora_fine) UTC oppure None

    # ── Raccolta ─────────────────────────────────────────────────────────────
    risorse_abilitate: list[str]          # es. ["pomodoro", "legno"]
    soglie_raccolta:   dict[str, float]   # es. {"pomodoro": 5.0}

    # ── Rifornimento ─────────────────────────────────────────────────────────
    rifornimento_abilitato:     bool
    rifornimento_risorse:       dict[str, bool]   # risorsa → abilitata
    rifornimento_soglie:        dict[str, float]  # risorsa → soglia minima
    rifornimento_max_spedizioni: int

    # ── Task periodici ────────────────────────────────────────────────────────
    intervalli:    dict[str, float]  # task → ore tra esecuzioni
    task_abilitati: list[str]        # lista task abilitati

    # ── Proprietà derivate (non nel JSON) ────────────────────────────────────

    @property
    def port(self) -> int:
        """Porta ADB: 16384 + index * 32."""
        return BotConfig.ADB_PORT_BASE + self.index * BotConfig.ADB_PORT_STEP

    @property
    def adb_serial(self) -> str:
        """Stringa serial ADB: "127.0.0.1:{port}"."""
        return f"127.0.0.1:{self.port}"

    @property
    def task_set(self) -> frozenset[str]:
        """Set dei task abilitati per lookup O(1)."""
        return frozenset(self.task_abilitati)

    @property
    def risorse_set(self) -> frozenset[str]:
        """Set delle risorse abilitate per lookup O(1)."""
        return frozenset(self.risorse_abilitate)

    def task_abilitato(self, task: str) -> bool:
        return task in self.task_set

    def intervallo_ore(self, task: str) -> float:
        """Intervallo in ore per un task periodico (default da INTERVALLI_DEFAULT)."""
        return self.intervalli.get(task, INTERVALLI_DEFAULT.get(task, 4.0))

    # ── Validazione ──────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        self._valida()

    def _valida(self) -> None:
        errors: list[str] = []

        # Identità
        if not self.name:
            errors.append("name non può essere vuoto")
        if self.index < 0 or self.index > 15:
            errors.append(f"index deve essere 0-15, ricevuto: {self.index}")
        if self.language not in LINGUE_VALIDE:
            errors.append(f"language non valido: {self.language!r}")

        # Profilo
        if self.max_squadre not in (4, 5):
            errors.append(f"max_squadre deve essere 4 o 5, ricevuto: {self.max_squadre}")
        if self.profilo not in PROFILI_VALIDI:
            errors.append(f"profilo non valido: {self.profilo!r}")
        if self.fascia_oraria is not None:
            if len(self.fascia_oraria) != 2:
                errors.append("fascia_oraria deve essere [ora_inizio, ora_fine]")
            else:
                h_start, h_end = self.fascia_oraria
                if not (0 <= h_start <= 23 and 0 <= h_end <= 23):
                    errors.append("fascia_oraria: ore devono essere 0-23")

        # Risorse raccolta
        for r in self.risorse_abilitate:
            if r not in RISORSE_VALIDE:
                errors.append(f"risorsa non valida in risorse_abilitate: {r!r}")

        # Task
        for t in self.task_abilitati:
            if t not in TASK_VALIDI:
                errors.append(f"task non valido in task_abilitati: {t!r}")

        # Rifornimento
        if self.rifornimento_max_spedizioni < 0:
            errors.append("rifornimento_max_spedizioni non può essere negativo")

        if errors:
            raise ValueError(
                f"InstanceConfig '{self.name}' non valida:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # ── Serializzazione ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InstanceConfig":
        """
        Costruisce InstanceConfig da un dict (letto dal JSON).
        Converte fascia_oraria da lista a tuple se presente.
        """
        fascia = d.get("fascia_oraria")
        if fascia is not None:
            fascia = tuple(fascia)

        return cls(
            name=d["name"],
            index=d["index"],
            language=d.get("language", "it"),
            max_squadre=d.get("max_squadre", 4),
            profilo=d.get("profilo", "standard"),
            fascia_oraria=fascia,
            risorse_abilitate=list(d.get("risorse_abilitate", [])),
            soglie_raccolta=dict(d.get("soglie_raccolta", {})),
            rifornimento_abilitato=d.get("rifornimento_abilitato", False),
            rifornimento_risorse=dict(d.get("rifornimento_risorse", {})),
            rifornimento_soglie=dict(d.get("rifornimento_soglie", {})),
            rifornimento_max_spedizioni=d.get("rifornimento_max_spedizioni", 5),
            intervalli=dict(d.get("intervalli", INTERVALLI_DEFAULT)),
            task_abilitati=list(d.get("task_abilitati", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializza in dict compatibile con JSON (senza port/adb_serial)."""
        return {
            "name":                       self.name,
            "index":                      self.index,
            "language":                   self.language,
            "max_squadre":                self.max_squadre,
            "profilo":                    self.profilo,
            "fascia_oraria":              list(self.fascia_oraria) if self.fascia_oraria else None,
            "risorse_abilitate":          self.risorse_abilitate,
            "soglie_raccolta":            self.soglie_raccolta,
            "rifornimento_abilitato":     self.rifornimento_abilitato,
            "rifornimento_risorse":       self.rifornimento_risorse,
            "rifornimento_soglie":        self.rifornimento_soglie,
            "rifornimento_max_spedizioni": self.rifornimento_max_spedizioni,
            "intervalli":                 self.intervalli,
            "task_abilitati":             self.task_abilitati,
        }

    def __repr__(self) -> str:
        return (
            f"InstanceConfig(name={self.name!r}, index={self.index}, "
            f"port={self.port}, profilo={self.profilo!r}, "
            f"task={len(self.task_abilitati)})"
        )


# ==============================================================================
# load_instances() — carica instances.json
# ==============================================================================

def load_instances(
    path: str | Path = "config/instances.json",
) -> list[InstanceConfig]:
    """
    Carica e valida tutte le istanze da un file JSON.

    Args:
        path: percorso del file instances.json

    Returns:
        Lista di InstanceConfig validati.

    Raises:
        FileNotFoundError: se il file non esiste
        json.JSONDecodeError: se il JSON è malformato
        ValueError: se una o più istanze non superano la validazione
        KeyError: se un campo obbligatorio è assente
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File configurazione non trovato: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError("instances.json deve contenere una lista JSON")

    configs: list[InstanceConfig] = []
    errors:  list[str]            = []

    for i, entry in enumerate(raw):
        try:
            configs.append(InstanceConfig.from_dict(entry))
        except (ValueError, KeyError, TypeError) as e:
            name = entry.get("name", f"entry[{i}]") if isinstance(entry, dict) else f"entry[{i}]"
            errors.append(f"{name}: {e}")

    if errors:
        raise ValueError(
            f"Errori in {path}:\n" + "\n".join(errors)
        )

    # Verifica indici duplicati
    indices = [c.index for c in configs]
    if len(indices) != len(set(indices)):
        raise ValueError("instances.json: indici duplicati tra le istanze")

    return configs
