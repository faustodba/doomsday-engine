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

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    grafica_hq:         bool = True
    pulizia_cache:      bool = True
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
    max_parallel:      int = Field(default=1, ge=1, le=12)
    tick_sleep_min:    int = Field(default=30, ge=0, le=1440)
    # WU155 — timeout polling HOME dopo avvio gioco (in secondi). Default 300
    # (era 180 hardcoded in mumu.timeout_carica_s). Path canonico legacy:
    # mumu.timeout_carica_s. Se presente in sistema.timeout_carica_s, prevale.
    timeout_carica_s:  int = Field(default=300, ge=30, le=900)


# ==============================================================================
# Rifugio (coordinate mappa)
# ==============================================================================

class RifugioOverride(BaseModel):
    coord_x: int = 687
    coord_y: int = 532


# ==============================================================================
# Rifornimento comune  [NUOVO — sostituisce RifornimentoOverride parziale]
# ==============================================================================

class RifornimentoAllocazioneOverride(BaseModel):
    """
    05/05: target proporzioni invio (analoga raccolta.allocazione).
    Default uniforme 25/25/25/25. Frazioni 0-1.
    L'algoritmo `_seleziona_risorsa` weighted-deficit normalizza
    automaticamente sia frazioni (somma~1) che percentuali (somma~100).
    """
    pomodoro: float = Field(default=0.25, ge=0, le=1.0)
    legno:    float = Field(default=0.25, ge=0, le=1.0)
    petrolio: float = Field(default=0.25, ge=0, le=1.0)
    acciaio:  float = Field(default=0.25, ge=0, le=1.0)


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
    allocazione:            RifornimentoAllocazioneOverride = Field(
        default_factory=RifornimentoAllocazioneOverride
    )


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


class TruppeCaserme(BaseModel):
    """
    06/05 — Flag per ognuna delle 4 caserme: addestra ON/OFF.

    Il bot itera sempre tutte e 4 le caserme; per ognuna se flag=False fa skip,
    altrimenti tap TRAIN col livello max disponibile (OCR titolo).
    Niente count_min (gioco usa default), niente livello (sempre max disponibile).
    """
    infantry: bool = True
    rider:    bool = True
    ranged:   bool = True
    engine:   bool = True


class TruppeOverride(BaseModel):
    """Default globale — applicato a tutte le istanze tranne quelle con override."""
    caserme: TruppeCaserme = Field(default_factory=TruppeCaserme)


class TruppeIstanzaCaserme(BaseModel):
    """
    Override per istanza, override completo (Opzione A): per ogni caserma
    True/False sovrascrive il default globale, None eredita.
    """
    infantry: Optional[bool] = None
    rider:    Optional[bool] = None
    ranged:   Optional[bool] = None
    engine:   Optional[bool] = None


class TruppeIstanzaOverride(BaseModel):
    """Override TruppeTask per singola istanza."""
    caserme: TruppeIstanzaCaserme = Field(default_factory=TruppeIstanzaCaserme)


# ==============================================================================
# GlobaliOverride — contenuto di runtime_overrides.json.globali
# ==============================================================================

class NotificationsSmtp(BaseModel):
    """SMTP server config (Email Notifier — Step C)."""
    host: str = "smtp.gmail.com"
    port: int = 465


class TelegramOverride(BaseModel):
    """Telegram bot config (WU-Telegram)."""
    enabled:              bool = False
    notify_cycle_every_n: int  = 5     # notifica ciclo completato ogni N cicli
    notify_cascade:       bool = True  # notifica cascade ADB
    notify_drl:           bool = True  # notifica DRL master saturo
    notify_daily_report:  bool = True  # forward daily report


class NotificationsOverride(BaseModel):
    """Email notifier config (memoria `project_email_notifier.md`).

    L'app password si legge da env var `DOOMSDAY_GMAIL_APP_PASSWORD`
    (non in config per sicurezza). Tutto il resto è in dashboard.

    Default vuoti per `from_addr` e `recipients`: l'utente DEVE configurarli
    in dashboard prima di abilitare le notifiche. Nessun fallback hardcoded.
    Vedi `config/global_config.json::notifications` per valori baseline.
    """
    # Master toggle: se False il dispatcher non parte e nessuna mail viene inviata
    enabled:                bool                = False
    # Fase 1: daily report giornaliero (Step D/E)
    daily_report_enabled:   bool                = True
    daily_report_hour_utc:  int                 = 6     # 06:00 UTC = 08:00 CEST
    # Mittente (account dedicato Gmail) — vuoto = NON configurato
    from_addr:              str                 = ""
    # Destinatari — vuoto = NON configurato (richiesto per abilitare invio)
    recipients:             List[str]           = Field(default_factory=list)
    smtp:                   NotificationsSmtp   = Field(default_factory=NotificationsSmtp)
    # Telegram bot (WU-Telegram)
    telegram:               TelegramOverride    = Field(default_factory=TelegramOverride)


class GlobaliOverride(BaseModel):
    # R-02 — extra='allow': preserva i campi globali runtime non dichiarati.
    model_config = ConfigDict(extra="allow")
    task:                 TaskFlags                  = Field(default_factory=TaskFlags)
    sistema:              SistemaOverride             = Field(default_factory=SistemaOverride)
    rifugio:              RifugioOverride             = Field(default_factory=RifugioOverride)
    rifornimento_comune:  RifornimentoComuneOverride  = Field(default_factory=RifornimentoComuneOverride)
    rifornimento:         RifornimentoOverride        = Field(default_factory=RifornimentoOverride)
    zaino:                ZainoOverride               = Field(default_factory=ZainoOverride)
    raccolta:             RaccoltaOverride            = Field(default_factory=RaccoltaOverride)
    truppe:               TruppeOverride              = Field(default_factory=TruppeOverride)
    # Step C — Email Notifier
    notifications:        NotificationsOverride       = Field(default_factory=NotificationsOverride)
    # WU55 — Data collection OCR slot HOME vs MAPPA
    raccolta_ocr_debug:   bool                       = False
    # WU93 — BannerLearner auto-apprendimento banner non catalogati
    auto_learn_banner:    bool                       = False  # WU110: deprecato, default disable
    # 08/05 — WU89 Skip Predictor RIMOSSO (regola "no skip istanza"). I flag
    # `skip_predictor_*` non sono più definiti nello schema. Lasciati in
    # runtime_overrides legacy verranno ignorati silenziosamente.
    # 08/05 — Adaptive Scheduler ordine istanze (default OFF + shadow first).
    # Se enabled=True, calcola ordine adattivo. Se shadow_only=True, logga
    # ma NON riordina il ciclo (osservabilità senza side-effect).
    adaptive_scheduler_enabled:     bool             = False
    adaptive_scheduler_shadow_only: bool             = True
    # Soglie precondizioni (dict per evitare proliferazione campi top-level)
    adaptive_scheduler_thresholds:  Dict[str, int]  = Field(
        default_factory=lambda: {
            "drl_residuo_pct":  30,    # master DRL: residuo >= X% del totale
            "pct_istanze_sat":  50,    # >= Y% istanze sature (provviste esaurite)
            "spedizioni_oggi":  100,   # spedizioni cumulative > N
        }
    )
    # WU115 — Debug screenshot per task (hot-reload via dashboard).
    # Dict {task_name: bool}, default empty (= tutti False).
    # Vedi shared/debug_buffer.py per architettura completa.
    debug_tasks:          Dict[str, bool]            = Field(default_factory=dict)


# ==============================================================================
# IstanzaOverride — override per singola istanza
# ==============================================================================

class TipologiaIstanza(str, Enum):
    full          = "full"
    # 08/05: rimossa `raccolta` (alias morto di `full`, non gestita dal bot —
    # main.py:732-744 mappava solo raccolta_only e raccolta_fast).
    raccolta_only = "raccolta_only"   # alias profilo bot (FauMorfeus)
    raccolta_fast = "raccolta_fast"   # WU57 — RaccoltaFastTask al posto di RaccoltaTask


class IstanzaOverride(BaseModel):
    """
    Override per singola istanza. Scritto su runtime_overrides.json.istanze.
    max_squadre, layout, livello scritti ANCHE su instances.json
    dall'endpoint /api/config/istanze.
    """
    # R-02 (revisione 07/2026) — extra='allow': preserva i campi runtime NON
    # dichiarati qui invece di scartarli al round-trip load→save (field-wipe).
    # Prima, un campo per-istanza mancante nel modello spariva dal file al primo
    # save dashboard (colpito 2 volte: raccolta_reset_leggero_abilitato,
    # master_task_whitelist). I campi espliciti sotto restano validati/tipizzati.
    model_config = ConfigDict(extra="allow")
    abilitata:    bool                    = True
    truppe:       int                     = Field(default=0, ge=0)
    tipologia:    TipologiaIstanza        = TipologiaIstanza.full
    fascia_oraria: Optional[str]          = None   # "HH:MM-HH:MM" | null
    max_squadre:  Optional[int]           = None   # scritto su instances.json
    # 08/05: `layout` rimosso (deprecato WU22 — TM dinamico, no coord per layout)
    livello:      Optional[int]           = None   # scritto su instances.json
    # WU211 — livello edificio di trasporto (1-25): capacità trasporto +
    # tassa per il calcolo deterministico dell'inviato rifornimento. Scritto
    # ANCHE su instances.json. Campo necessario qui altrimenti un save dashboard
    # lo perderebbe silenziosamente (bug-class WU199/WU102).
    livello_trasporto: Optional[int]        = None   # scritto su instances.json
    # WU50 — raccolta fuori territorio (per istanza)
    raccolta_fuori_territorio: bool       = False
    # WU199 — report_raccolta (per istanza). Campo mancante qui causava perdita
    # silenziosa ad ogni save dashboard (stesso bug-class di WU102: Pydantic
    # serializza solo campi noti, un save sovrascriveva runtime_overrides.json
    # senza queste 2 chiavi). Osservato live 09/07/2026: flag impostato a mano
    # su tutte le 12 istanze, sparito dopo un save dashboard nel giro di ~20min.
    report_raccolta_abilitato:  bool      = False
    report_raccolta_solo_reset: bool      = True
    # WU232 (16/07) — reset leggero raccolta (esteso a tutte le 12 istanze
    # 17/07). Campo mancante qui = stesso bug-class WU199/WU102: un save
    # dashboard lo strippava silenziosamente, revertendo il rollout. Aggiunto
    # 17/07 per blindarlo (era sopravvissuto finora solo perché mai passato da
    # un save dashboard).
    raccolta_reset_leggero_abilitato: bool = False
    # WU-MasterTasks (17/07) — whitelist task del master (nomi snake_case). Solo
    # per l'istanza master: i task selezionati girano OLTRE a raccolta con la
    # loro schedulazione normale. None/[] = solo raccolta (comportamento base).
    # Sostituisce il bundle fisso FauMorfeusSetupTask (WU234). Campo necessario
    # qui altrimenti un save dashboard lo perderebbe (bug-class WU199/WU102).
    master_task_whitelist: Optional[list[str]] = None
    # WU-TaskResolution Fase 2 (20/07) — override task GENERICO per-istanza
    # (add/remove: {"arena": false, "boost": true}). Meccanismo unico che
    # assorbe master_task_whitelist (in convivenza: il bot mergia i due,
    # l'esplicito vince). Campo necessario qui altrimenti un save dashboard lo
    # perderebbe (bug-class WU199/WU102). `profilo` = profilo profiles.json
    # (completo/solo_raccolta/fast/master); None = fallback a `tipologia`.
    profilo:       Optional[str]              = None
    task_overrides: Optional[dict[str, bool]] = None
    # Master istanza (rifugio destinatario): esclusa dagli aggregati ordinari
    # (telemetria, predictor, ranking dashboard). Esposta in sezione UI dedicata.
    master:       bool                    = False
    # 06/05 — override TruppeTask per istanza (caserme on/off, completo)
    truppe_override: Optional[TruppeIstanzaOverride] = None
    # WU205 — allocazione raccolta per-istanza (percentuali). None = usa il
    # globale raccolta.allocazione. Il bot (config_loader._InstanceCfg)
    # normalizza a frazioni somma=1. NB: campo necessario qui, altrimenti un
    # save dashboard lo perderebbe silenziosamente (bug-class WU199/WU102).
    allocazione: Optional[AllocazioneOverride] = None


# ==============================================================================
# RuntimeOverrides — contenuto completo di runtime_overrides.json
# ==============================================================================

class RuntimeOverrides(BaseModel):
    """
    Contenuto completo di runtime_overrides.json.
    Letto ad ogni turno istanza dal bot. Failsafe: se manca → default.
    """
    # R-02 — extra='allow': preserva eventuali chiavi top-level non dichiarate.
    model_config = ConfigDict(extra="allow")
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
    # 08/05: skip_predictor_* RIMOSSI (regola "no skip istanza"). PayloadGlobals
    # non li accetta più — il payload ignora silenziosamente eventuali residui
    # client-side.


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
