# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/models.py
#
#  Modelli Pydantic v2 per la dashboard:
#    - RuntimeOverrides    : nuovo layer override (runtime_overrides.json)
#    - InstanceEntry       : voce di config/instances.json (read-only a runtime)
#    - EngineStatus        : payload di engine_status.json (scritto da main.py
#                            ogni status_interval secondi)
#    - InstanceStats       : aggregato overview per la dashboard
#
#  Nota architetturale: questo modulo NON modifica i file esistenti. Serve da
#  contratto tipizzato per la nuova dashboard. Il collegamento tra
#  runtime_overrides.json e il bot (main.py / build_instance_cfg) e' una scelta
#  separata e non è implementata qui.
# ==============================================================================

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ==============================================================================
# Runtime overrides — contenuto di runtime_overrides.json
# ==============================================================================

class TaskFlags(BaseModel):
    """
    Flag on/off per tutti i task tranne raccolta.
    raccolta e' assente by design — gira sempre, non e' controllabile.
    """
    alleanza:           bool = True
    messaggi:           bool = True
    vip:                bool = True
    radar:              bool = True
    radar_census:       bool = False
    rifornimento:       bool = False
    rifornimento_mappa: bool = False
    zaino:              bool = True
    arena:              bool = True
    arena_mercato:      bool = True
    boost:              bool = True
    store:              bool = True


class RifugioOverride(BaseModel):
    coord_x: int
    coord_y: int


class RifornimentoOverride(BaseModel):
    soglia_campo_m:     int  = 50
    mappa_abilitata:    bool = False
    membri_abilitati:   bool = True
    provviste_max:      int  = 100


class RaccoltaOverride(BaseModel):
    soglia_allocazione: int = 3


class GlobaliOverride(BaseModel):
    task:         TaskFlags               = Field(default_factory=TaskFlags)
    rifugio:      Optional[RifugioOverride] = None
    rifornimento: RifornimentoOverride    = Field(default_factory=RifornimentoOverride)
    raccolta:     RaccoltaOverride        = Field(default_factory=RaccoltaOverride)


class TipologiaIstanza(str, Enum):
    """
    full     = esegue tutti i task abilitati in TaskFlags
    raccolta = esegue SOLO RaccoltaTask, zero altri task
    """
    full     = "full"
    raccolta = "raccolta"


class IstanzaOverride(BaseModel):
    abilitata:     bool             = True
    truppe:        int              = 0
    tipologia:     TipologiaIstanza = TipologiaIstanza.full
    fascia_oraria: Optional[str]    = None   # placeholder — da definire


class RuntimeOverrides(BaseModel):
    """
    Contenuto completo di runtime_overrides.json.
    Letto ad ogni turno istanza. Failsafe: se manca -> default.
    """
    globali: GlobaliOverride               = Field(default_factory=GlobaliOverride)
    istanze: Dict[str, IstanzaOverride]    = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "RuntimeOverrides":
        """Legge runtime_overrides.json. Se assente o corrotto -> default."""
        try:
            return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return cls()

    def save(self, path: Path) -> None:
        """
        Scrittura atomica su runtime_overrides.json.
        Pattern tmp + os.replace (evita file troncati su crash).
        """
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)


# ==============================================================================
# Istanza fisica — una voce di config/instances.json (read-only a runtime)
# ==============================================================================

class InstanceEntry(BaseModel):
    """Una voce di instances.json. Read-only a runtime."""
    nome:          str
    indice:        int
    porta:         int
    truppe:        int  = 0
    max_squadre:   int  = 5
    layout:        int  = 1
    lingua:        str  = "it"
    livello:       int  = 7
    profilo:       str  = ""
    abilitata:     bool = True
    fascia_oraria: Optional[str] = None


# ==============================================================================
# Engine status — payload di engine_status.json
# ==============================================================================

class UltimoTask(BaseModel):
    """Dettaglio ultimo task completato per un'istanza."""
    nome:     Optional[str]   = None
    esito:    Optional[str]   = None   # "ok" | "err" | ...
    msg:      Optional[str]   = None
    ts:       Optional[str]   = None   # formato "HH:MM:SS"
    durata_s: Optional[float] = None


class IstanzaStatus(BaseModel):
    """
    Stato live di una singola istanza nel payload engine_status.json.
    Schema allineato al reale scritto da main._scrivi_status_json().
    Il campo `nome` non e' nel payload (chiave dict in istanze{}) ma viene
    popolato dal caller quando costruisce questa rappresentazione.
    """
    nome:              str                  = ""                       # popolato dal caller
    stato:             str                  = "unknown"                # "idle"|"running"|"error"|"disabled"|"waiting"
    task_corrente:     Optional[str]        = None
    task_eseguiti:     Dict[str, int]       = Field(default_factory=dict)
    ultimo_task:       Optional[UltimoTask] = None
    scheduler:         Dict[str, str]       = Field(default_factory=dict)   # task_name -> "HH:MM:SS" | "adesso"
    errori:            int                  = 0
    porta:             Optional[int]        = None

    # Campi derivati / legacy — mantenuti per compatibilità con il contratto
    # proposto nella progettazione della nuova dashboard.
    ultimo_tick_ts:      Optional[str]   = None
    ultimo_tick_durata_s: Optional[float] = None
    errori_consecutivi:  int             = 0


class StoricoEntry(BaseModel):
    """Entry dello storico eventi (engine_status.json.storico)."""
    istanza:  str
    task:     str
    esito:    str                    # "ok" | "err"
    ts:       str                    # "HH:MM:SS"
    durata_s: float = 0.0
    msg:      str   = ""


class EngineStatus(BaseModel):
    """Payload completo di engine_status.json."""
    version:  str                        = ""
    ts:       str                        = ""
    uptime_s: int                        = 0
    ciclo:    int                        = 0
    stato:    str                        = "unknown"
    istanze:  Dict[str, IstanzaStatus]   = Field(default_factory=dict)
    storico:  List[StoricoEntry]         = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "EngineStatus":
        """Legge engine_status.json. Se assente o corrotto -> default."""
        try:
            return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return cls()


# ==============================================================================
# Statistiche istanza (aggregato state/ + logs/)
# ==============================================================================

class RaccoltaStats(BaseModel):
    """Aggregato raccolta per l'ultimo tick disponibile."""
    slot_totali:          int       = 0
    slot_usati:           int       = 0
    nodi_raccolti:        int       = 0
    nodi_falliti:         int       = 0
    tipologie_bloccate:   List[str] = Field(default_factory=list)


class TickStats(BaseModel):
    """Statistiche ultimo tick istanza."""
    ts_inizio:      Optional[str]   = None
    durata_s:       Optional[float] = None
    task_eseguiti:  List[str]       = Field(default_factory=list)
    task_falliti:   List[str]       = Field(default_factory=list)
    raccolta:       RaccoltaStats   = Field(default_factory=RaccoltaStats)


class InstanceStats(BaseModel):
    """Aggregato completo per la dashboard — overview + dettaglio."""
    nome:         str
    tipologia:    TipologiaIstanza = TipologiaIstanza.full
    abilitata:    bool             = True
    stato_live:   str              = "unknown"
    ultimo_tick:  TickStats        = Field(default_factory=TickStats)
