# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/models.py
#
#  Modelli Pydantic v2 per la dashboard.
#
#  Struttura runtime_overrides.json (unica fonte di verità dashboard→bot):
#
#    globali:
#      task{}                  — flag on/off per ogni task
#      sistema{}               — max_parallel, tick_sleep_min  [NUOVO]
#      rifugio{}               — coord_x, coord_y
#      rifornimento_comune{}   — soglie, flag per risorsa, account [NUOVO]
#      rifornimento{}          — mappa_abilitata, membri_abilitati
#      zaino{}                 — modalita, soglie, flag per risorsa [NUOVO]
#      raccolta{}              — allocazione{} percentuali          [NUOVO]
#    istanze{}                 — per-istanza: abilitata, truppe,
#                                tipologia, fascia_oraria
#
#  I campi [NUOVO] sono aggiunte rispetto alla versione precedente.
#  Retrocompatibili: il bot legge con .get() + default, non crasha mai.
#
#  Nota: max_squadre, layout, livello vengono scritti anche su instances.json
#  dall'endpoint /api/config/istanze (config_manager.save_instances_fields).
# ==============================================================================

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ==============================================================================
# Task flags
# ==============================================================================

class TaskFlags(BaseModel):
    """Flag on/off per tutti i task.

    Nota: la sub-mode del rifornimento (mappa vs membri) NON è qui — è in
    `RifornimentoOverride.mappa_abilitata / membri_abilitati` (mutuamente esclusive).
    Il flag `rifornimento` è solo il master on/off del task.

    Bug storico (03/05): `raccolta` non era nel modello con il rationale "gira
    sempre" → ogni `_save_ov(ov)` serializzava il dict perdendo la chiave →
    `task_abilitato("raccolta")` cadeva sul default di global_config (False
    dopo il reset baseline WU94) → tutte le istanze skippavano raccolta. Fix:
    raccolta presente nel modello, default True. UI dashboard non la espone
    come toggle (resta sempre ON di fatto), ma la chiave viene preservata
    nel JSON al ogni salvataggio.
    """
    alleanza:           bool = True
    messaggi:           bool = True
    vip:                bool = True
    radar:              bool = True
    radar_census:       bool = False
    rifornimento:       bool = False
    raccolta:           bool = True      # sempre ON, NON esposta in UI come toggle
    donazione:          bool = True
    main_mission:       bool = True
    zaino:              bool = True
    arena:              bool = True
    arena_mercato:      bool = True
    district_showdown:  bool = False     # default OFF — evento mensile
    boost:              bool = True
    truppe:             bool = True
    store:              bool = True


# ==============================================================================
# Sezione sistema  [NUOVO]
# ==============================================================================

class SistemaOverride(BaseModel):
    """Parametri globali di esecuzione. Scritti su runtime_overrides.json."""
    max_parallel:    int = Field(default=1, ge=1, le=12)
    tick_sleep_min:  int = Field(default=30, ge=0, le=1440)


# ==============================================================================
# Rifugio (coordinate mappa)
# ==============================================================================

class RifugioOverride(BaseModel):
    coord_x: int = 687
    coord_y: int = 532


# ==============================================================================
# Rifornimento comune  [NUOVO — sostituisce RifornimentoOverride parziale]
# ==============================================================================

class RifornimentoComuneOverride(BaseModel):
    """
    Parametri comuni a entrambe le modalità rifornimento.
    Mappati su global_config.json.rifornimento_comune.* dal merge_config.
    """
    dooms_account:          str   = "FauMorfeus"
    max_spedizioni_ciclo:   int   = Field(default=5, ge=0, le=50)
    soglia_campo_m:         float = Field(default=5.0, ge=0)
    soglia_legno_m:         float = Field(default=5.0, ge=0)
    soglia_petrolio_m:      float = Field(default=2.5, ge=0)
    soglia_acciaio_m:       float = Field(default=3.5, ge=0)
    campo_abilitato:        bool  = True
    legno_abilitato:        bool  = True
    petrolio_abilitato:     bool  = True
    acciaio_abilitato:      bool  = False


class RifornimentoOverride(BaseModel):
    """Modalità e coordinate rifugio. Retrocompatibile con versione precedente.

    05/05: default `mappa_abilitata=True, membri_abilitati=False` per
    riflettere modalità operativa standard del bot (mappa è la modalità
    default). Pre-fix: default mappa=False/membri=True → ad ogni save
    dashboard PATCH parziale (es. modifica soglia), Pydantic
    ricostruiva il modello con default → mappa_abilitata resettata a
    False → task_abilitato('rifornimento') ritornava False perché
    `task_rifornimento AND (mappa OR membri) = True AND (False OR False)
    = False` (membri=True nel default ma le condizioni mode-mutex
    nell'altro endpoint forzano membri=False quando mappa attiva).
    Pattern identico a WU102 (TaskFlags.raccolta).
    """
    soglia_campo_m:   float = 50.0   # legacy — mantenuto per retrocompat.
    mappa_abilitata:  bool  = True
    membri_abilitati: bool  = False
    provviste_max:    int   = 100


# ==============================================================================
# Zaino  [NUOVO]
# ==============================================================================

class ZainoOverride(BaseModel):
    """
    Configurazione zaino. Modalità mutuamente esclusive: bag | svuota.
    Flag per risorsa: se False quella risorsa non viene mai scaricata.
    """
    modalita:           str   = Field(default="bag", pattern="^(bag|svuota)$")
    usa_pomodoro:       bool  = True
    usa_legno:          bool  = True
    usa_petrolio:       bool  = True
    usa_acciaio:        bool  = False
    soglia_pomodoro_m:  float = Field(default=20.0, ge=0)
    soglia_legno_m:     float = Field(default=20.0, ge=0)
    soglia_petrolio_m:  float = Field(default=5.0,  ge=0)
    soglia_acciaio_m:   float = Field(default=10.0, ge=0)


# ==============================================================================
# Raccolta — allocazione  [NUOVO]
# ==============================================================================

class AllocazioneOverride(BaseModel):
    """
    Percentuali allocazione raccolta. Somma deve essere 100.
    Il bot normalizza internamente ma la dashboard avverte se ≠ 100.
    Valori 0-100 (percentuale); il bot usa float 0.0-1.0 internamente.
    """
    pomodoro: float = Field(default=40.0, ge=0, le=100)
    legno:    float = Field(default=30.0, ge=0, le=100)
    petrolio: float = Field(default=20.0, ge=0, le=100)
    acciaio:  float = Field(default=10.0, ge=0, le=100)

    @field_validator("acciaio")
    @classmethod
    def check_total(cls, v, info):
        values = info.data
        total = values.get("pomodoro", 0) + values.get("legno", 0) + values.get("petrolio", 0) + v
        if abs(total - 100.0) > 0.5:
            # Warning solo — non blocca il salvataggio (il bot normalizza)
            pass
        return v

    def to_frazioni(self) -> dict:
        """Converte percentuali in frazioni 0.0-1.0 per il bot."""
        tot = self.pomodoro + self.legno + self.petrolio + self.acciaio
        if tot == 0:
            return {"pomodoro": 0.25, "legno": 0.25, "petrolio": 0.25, "acciaio": 0.25}
        return {
            "pomodoro": round(self.pomodoro / tot, 4),
            "legno":    round(self.legno    / tot, 4),
            "petrolio": round(self.petrolio / tot, 4),
            "acciaio":  round(self.acciaio  / tot, 4),
        }


class RaccoltaOverride(BaseModel):
    soglia_allocazione: int              = 3
    allocazione:        AllocazioneOverride = Field(default_factory=AllocazioneOverride)


# ==============================================================================
# GlobaliOverride — contenuto di runtime_overrides.json.globali
# ==============================================================================

class GlobaliOverride(BaseModel):
    task:                 TaskFlags                  = Field(default_factory=TaskFlags)
    sistema:              SistemaOverride             = Field(default_factory=SistemaOverride)
    rifugio:              RifugioOverride             = Field(default_factory=RifugioOverride)
    rifornimento_comune:  RifornimentoComuneOverride  = Field(default_factory=RifornimentoComuneOverride)
    rifornimento:         RifornimentoOverride        = Field(default_factory=RifornimentoOverride)
    zaino:                ZainoOverride               = Field(default_factory=ZainoOverride)
    raccolta:             RaccoltaOverride            = Field(default_factory=RaccoltaOverride)
    # WU55 — Data collection OCR slot HOME vs MAPPA
    raccolta_ocr_debug:   bool                       = False
    # WU93 — BannerLearner auto-apprendimento banner non catalogati
    auto_learn_banner:    bool                       = False  # WU110: deprecato, default disable
    # WU89 Step 3 — Skip Predictor (default OFF, shadow first)
    skip_predictor_enabled:     bool                 = False
    skip_predictor_shadow_only: bool                 = True
    # WU115 — Debug screenshot per task (hot-reload via dashboard).
    # Dict {task_name: bool}, default empty (= tutti False).
    # Vedi shared/debug_buffer.py per architettura completa.
    debug_tasks:          Dict[str, bool]            = Field(default_factory=dict)


# ==============================================================================
# IstanzaOverride — override per singola istanza
# ==============================================================================

class TipologiaIstanza(str, Enum):
    full          = "full"
    raccolta      = "raccolta"
    raccolta_only = "raccolta_only"   # alias profilo bot (FauMorfeus)
    raccolta_fast = "raccolta_fast"   # WU57 — RaccoltaFastTask al posto di RaccoltaTask


class IstanzaOverride(BaseModel):
    """
    Override per singola istanza. Scritto su runtime_overrides.json.istanze.
    max_squadre, layout, livello scritti ANCHE su instances.json
    dall'endpoint /api/config/istanze.
    """
    abilitata:    bool                    = True
    truppe:       int                     = Field(default=0, ge=0)
    tipologia:    TipologiaIstanza        = TipologiaIstanza.full
    fascia_oraria: Optional[str]          = None   # "HH:MM-HH:MM" | null
    max_squadre:  Optional[int]           = None   # scritto su instances.json
    layout:       Optional[int]           = None   # scritto su instances.json
    livello:      Optional[int]           = None   # scritto su instances.json
    # WU50 — raccolta fuori territorio (per istanza)
    raccolta_fuori_territorio: bool       = False
    # Master istanza (rifugio destinatario): esclusa dagli aggregati ordinari
    # (telemetria, predictor, ranking dashboard). Esposta in sezione UI dedicata.
    master:       bool                    = False


# ==============================================================================
# RuntimeOverrides — contenuto completo di runtime_overrides.json
# ==============================================================================

class RuntimeOverrides(BaseModel):
    """
    Contenuto completo di runtime_overrides.json.
    Letto ad ogni turno istanza dal bot. Failsafe: se manca → default.
    """
    globali: GlobaliOverride            = Field(default_factory=GlobaliOverride)
    istanze: Dict[str, IstanzaOverride] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "RuntimeOverrides":
        """Legge runtime_overrides.json. Se assente o corrotto → default."""
        try:
            return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return cls()

    def save(self, path: Path) -> None:
        """Scrittura atomica su runtime_overrides.json.

        exclude_none=True: i campi Optional non settati (max_squadre, layout,
        livello) NON vengono scritti come null nel JSON — così `dict.get` del
        bot fall-through correttamente al default `ist.get(...)`.
        """
        path = Path(path)
        tmp  = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        os.replace(tmp, path)

    def to_runtime_dict(self) -> dict:
        """
        Serializza in formato compatibile con merge_config() del bot.
        Le percentuali allocazione vengono convertite in frazioni 0.0-1.0.
        """
        d = self.model_dump()
        # Converti allocazione % → frazioni per il bot
        alloc = self.globali.raccolta.allocazione
        d["globali"]["raccolta"]["allocazione"] = alloc.to_frazioni()
        return d


# ==============================================================================
# InstanceEntry — voce di config/instances.json (read-only a runtime)
# ==============================================================================

class InstanceEntry(BaseModel):
    nome:          str
    indice:        int
    porta:         int
    truppe:        int           = 0
    max_squadre:   int           = 5
    layout:        int           = 1
    lingua:        str           = "en"
    livello:       int           = 7
    profilo:       str           = "full"
    abilitata:     bool          = True
    fascia_oraria: Optional[str] = None


# ==============================================================================
# Engine status — payload di engine_status.json
# ==============================================================================

class UltimoTask(BaseModel):
    nome:     Optional[str]   = None
    esito:    Optional[str]   = None
    msg:      Optional[str]   = None
    ts:       Optional[str]   = None
    durata_s: Optional[float] = None


class IstanzaStatus(BaseModel):
    nome:                 str                  = ""
    stato:                str                  = "unknown"
    task_corrente:        Optional[str]         = None
    task_eseguiti:        Dict[str, int]        = Field(default_factory=dict)
    ultimo_task:          Optional[UltimoTask]  = None
    scheduler:            Dict[str, str]        = Field(default_factory=dict)
    errori:               int                  = 0
    porta:                Optional[int]         = None
    ultimo_tick_ts:       Optional[str]         = None
    ultimo_tick_durata_s: Optional[float]       = None
    errori_consecutivi:   int                  = 0


class StoricoEntry(BaseModel):
    istanza:  str
    task:     str
    esito:    str
    ts:       str
    durata_s: float = 0.0
    msg:      str   = ""


class EngineStatus(BaseModel):
    version:  str                       = ""
    ts:       str                       = ""
    uptime_s: int                       = 0
    ciclo:    int                       = 0
    stato:    str                       = "unknown"
    istanze:  Dict[str, IstanzaStatus]  = Field(default_factory=dict)
    storico:  List[StoricoEntry]        = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "EngineStatus":
        try:
            return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return cls()


# ==============================================================================
# Statistiche istanza
# ==============================================================================

class RaccoltaStats(BaseModel):
    slot_totali:        int       = 0
    slot_usati:         int       = 0
    nodi_raccolti:      int       = 0
    nodi_falliti:       int       = 0
    tipologie_bloccate: List[str] = Field(default_factory=list)


class TickStats(BaseModel):
    ts_inizio:     Optional[str]   = None
    durata_s:      Optional[float] = None
    task_eseguiti: List[str]       = Field(default_factory=list)
    task_falliti:  List[str]       = Field(default_factory=list)
    raccolta:      RaccoltaStats   = Field(default_factory=RaccoltaStats)


class InstanceStats(BaseModel):
    nome:        str
    tipologia:   TipologiaIstanza = TipologiaIstanza.full
    abilitata:   bool             = True
    master:      bool             = False  # rifugio destinatario (esclusa aggregati)
    stato_live:  str              = "unknown"
    ultimo_tick: TickStats        = Field(default_factory=TickStats)


# ==============================================================================
# Payload request per endpoint sezione
# ==============================================================================

class PayloadGlobals(BaseModel):
    """PUT /api/config/globals — task flags + parametri sistema + predictor.

    WU89-Step4 (04/05): aggiunti `skip_predictor_*` opzionali (None = no
    update). Permette di toggleare il predictor da dashboard senza restart.
    """
    task:    TaskFlags      = Field(default_factory=TaskFlags)
    sistema: SistemaOverride = Field(default_factory=SistemaOverride)
    skip_predictor_enabled:     Optional[bool] = None
    skip_predictor_shadow_only: Optional[bool] = None


class PayloadRifornimento(BaseModel):
    """PUT /api/config/rifornimento — soglie, flag, modalità, coordinate."""
    rifornimento_comune: RifornimentoComuneOverride = Field(default_factory=RifornimentoComuneOverride)
    rifugio:             RifugioOverride             = Field(default_factory=RifugioOverride)
    mappa_abilitata:     bool                        = False
    membri_abilitati:    bool                        = True


class PayloadZaino(BaseModel):
    """PUT /api/config/zaino — modalità e soglie."""
    zaino: ZainoOverride = Field(default_factory=ZainoOverride)


class PayloadAllocazione(BaseModel):
    """PUT /api/config/allocazione — percentuali raccolta."""
    allocazione: AllocazioneOverride = Field(default_factory=AllocazioneOverride)


class PayloadIstanze(BaseModel):
    """PUT /api/config/istanze — lista override per-istanza."""
    istanze: Dict[str, IstanzaOverride] = Field(default_factory=dict)
