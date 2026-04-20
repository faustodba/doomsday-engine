# ==============================================================================
#  DOOMSDAY ENGINE V6 — config/config_loader.py
#
#  Unico punto di lettura e merge della configurazione V6.
#
#  Fonti (in ordine di precedenza crescente):
#    1. Default hardcoded in questo modulo   ← fallback finale
#    2. config/instances.json               ← parametri per-istanza
#    3. config/global_config.json           ← parametri globali (letto ad ogni tick)
#
#  Output:
#    MumuConfig     — parametri MuMuPlayer (path, timeout, ritardi)
#    GlobalConfig   — parametri globali tipizzati (task, rifornimento, zaino, raccolta, mumu)
#    InstanceCfg    — configurazione per singola istanza (merge globale + per-istanza)
#
#  Utilizzo in main.py:
#    from config.config_loader import load_global, build_instance_cfg
#
#    # Ad ogni tick:
#    gcfg = load_global()                        # rilegge global_config.json
#    cfg  = build_instance_cfg(ist_dict, gcfg)   # merge con dati istanza
#    ctx  = TaskContext(..., config=cfg)
#
#  Utilizzo in launcher.py:
#    from config.config_loader import load_global
#    _cfg = load_global().mumu                   # MumuConfig con path e timeout
#
#  Compatibilità task esistenti:
#    cfg.get(key, default)      → invariato
#    cfg.task_abilitato(nome)   → invariato
#    cfg.RIFORNIMENTO_ABILITATO → invariato (attributi uppercase per retrocompat.)
#
#  Aggiornamento dinamico:
#    global_config.json viene riletto ad ogni tick → modifiche dalla dashboard
#    hanno effetto al prossimo tick senza restart del processo.
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ==============================================================================
# Path default
# ==============================================================================

_ROOT = Path(__file__).parent.parent  # C:\doomsday-engine\
_GLOBAL_CONFIG_PATH = _ROOT / "config" / "global_config.json"
_INSTANCES_PATH     = _ROOT / "config" / "instances.json"


# ==============================================================================
# Default globali — fallback se global_config.json manca o è incompleto
# ==============================================================================

_DEFAULTS: dict[str, Any] = {
    # Sistema
    "tick_sleep":   300,
    "max_parallel": 2,

    # Task abilitati
    "task_raccolta":      True,
    "task_rifornimento":  False,
    "task_zaino":         False,
    "task_vip":           True,
    "task_alleanza":      True,
    "task_messaggi":      True,
    "task_arena":         True,
    "task_arena_mercato": True,
    "task_boost":         True,
    "task_store":         True,
    "task_radar":         True,
    "task_radar_census":  False,

    # Rifornimento — parametri comuni
    "DOOMS_ACCOUNT":                    "",
    "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 5,
    "RIFORNIMENTO_SOGLIA_CAMPO_M":      5.0,
    "RIFORNIMENTO_SOGLIA_LEGNO_M":      5.0,
    "RIFORNIMENTO_SOGLIA_PETROLIO_M":   2.5,
    "RIFORNIMENTO_SOGLIA_ACCIAIO_M":    3.5,
    "RIFORNIMENTO_CAMPO_ABILITATO":     True,
    "RIFORNIMENTO_LEGNO_ABILITATO":     True,
    "RIFORNIMENTO_PETROLIO_ABILITATO":  True,
    "RIFORNIMENTO_ACCIAIO_ABILITATO":   False,
    "RIFORNIMENTO_QTA_POMODORO":        999_000_000,
    "RIFORNIMENTO_QTA_LEGNO":           999_000_000,
    "RIFORNIMENTO_QTA_PETROLIO":        999_000_000,
    "RIFORNIMENTO_QTA_ACCIAIO":         999_000_000,

    # Rifornimento — modalità mappa (coordinate fisse)
    "RIFORNIMENTO_ABILITATO":       False,
    "RIFORNIMENTO_MAPPA_ABILITATO": False,
    "RIFUGIO_X":                    687,
    "RIFUGIO_Y":                    532,

    # Rifornimento — modalità membri (lista alleanza)
    "RIFORNIMENTO_MEMBRI_ABILITATO": False,
    "AVATAR_TEMPLATE":               "pin/avatar.png",

    # Zaino
    "ZAINO_ABILITATO":          False,
    "ZAINO_USA_POMODORO":       True,
    "ZAINO_USA_LEGNO":          True,
    "ZAINO_USA_PETROLIO":       True,
    "ZAINO_USA_ACCIAIO":        False,
    "ZAINO_SOGLIA_POMODORO_M":  10.0,
    "ZAINO_SOGLIA_LEGNO_M":     10.0,
    "ZAINO_SOGLIA_PETROLIO_M":   5.0,
    "ZAINO_SOGLIA_ACCIAIO_M":    7.0,

    # Raccolta
    "LIVELLO_NODO":             6,
    "ALLOCAZIONE_POMODORO":     0.4,
    "ALLOCAZIONE_LEGNO":        0.3,
    "ALLOCAZIONE_PETROLIO":     0.2,
    "ALLOCAZIONE_ACCIAIO":      0.1,

    # Task periodici (flag separati per retrocompat.)
    "ALLEANZA_ABILITATO":       True,
    "MESSAGGI_ABILITATO":       True,
    "VIP_ABILITATO":            True,
    "RADAR_ABILITATO":          True,
    "RADAR_CENSUS_ABILITATO":   False,
    "ARENA_OF_GLORY_ABILITATO": True,
    "ARENA_MERCATO_ABILITATO":  True,
    "BOOST_ABILITATO":          True,
    "STORE_ABILITATO":          True,
}


# ==============================================================================
# Lettura global_config.json
# ==============================================================================

def load_global(path: str | Path | None = None) -> "GlobalConfig":
    """
    Legge global_config.json e ritorna GlobalConfig.
    Se il file manca o è corrotto ritorna i default hardcoded (mai crash).
    Chiamare ad ogni tick per effetto immediato delle modifiche dashboard.
    """
    p = Path(path) if path else _GLOBAL_CONFIG_PATH
    raw: dict = {}
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            print(f"[CONFIG] WARN: global_config.json non leggibile ({exc}) — uso default")

    return GlobalConfig._from_raw(raw)


def save_global(gcfg: "GlobalConfig", path: str | Path | None = None) -> bool:
    """
    Serializza GlobalConfig in global_config.json.
    Usato dalla dashboard per salvare modifiche.
    Scrittura atomica (tmp + rename).
    Ritorna True se OK, False in caso di errore.
    """
    p = Path(path) if path else _GLOBAL_CONFIG_PATH
    tmp = p.with_suffix(".tmp")
    try:
        data = gcfg.to_dict()
        data["_note"] = "Doomsday Engine V6 — Configurazione globale. Letto ad ogni tick."
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as exc:
        print(f"[CONFIG] ERRORE salvataggio global_config.json: {exc}")
        return False


# ==============================================================================
# Runtime overrides — load + merge con global_config (dict grezzi)
# ==============================================================================

def load_overrides(path) -> dict:
    """
    Legge runtime_overrides.json e restituisce il dict grezzo.
    Failsafe totale: qualsiasi errore -> {} senza eccezioni.
    Il bot non crasha mai per un override mancante o corrotto.
    NON importa Pydantic — solo dict grezzi.
    """
    try:
        from pathlib import Path
        return __import__('json').loads(
            Path(path).read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def merge_config(gcfg: dict, overrides: dict) -> dict:
    """
    Merge tra global_config.json raw (gcfg: dict) e runtime_overrides (overrides: dict).
    Priorità: override > gcfg per chiave identica.
    Ogni sezione in try/except separato: un override malformato non blocca gli altri.
    Restituisce sempre un dict (mai None, mai eccezioni).

    Chiave speciale iniettata nel risultato:
      _istanze_overrides: dict[nome -> dict] — estratto da main.py
      e passato a build_instance_cfg(overrides=ist_ovr)
    """
    import copy
    merged = copy.deepcopy(gcfg)
    if not overrides:
        return merged

    globali = overrides.get("globali", {})

    # ── task flags ──────────────────────────────────────────────────────────
    try:
        ov_task = globali.get("task", {})
        if ov_task:
            if "task" not in merged:
                merged["task"] = {}
            for k, v in ov_task.items():
                merged["task"][k] = v
    except Exception:
        pass

    # ── rifugio ─────────────────────────────────────────────────────────────
    try:
        ov_rifugio = globali.get("rifugio")
        if ov_rifugio:
            merged["rifugio"] = ov_rifugio
    except Exception:
        pass

    # ── rifornimento (merge su rifornimento_comune e rifornimento_mappa) ────
    try:
        ov_rif = globali.get("rifornimento", {})
        if ov_rif:
            for sezione in ("rifornimento_comune", "rifornimento_mappa"):
                if sezione in merged:
                    for k, v in ov_rif.items():
                        if k in merged[sezione]:
                            merged[sezione][k] = v
    except Exception:
        pass

    # ── raccolta ────────────────────────────────────────────────────────────
    try:
        ov_racc = globali.get("raccolta", {})
        if ov_racc:
            if "raccolta" not in merged:
                merged["raccolta"] = {}
            for k, v in ov_racc.items():
                merged["raccolta"][k] = v
    except Exception:
        pass

    # ── per-istanza (iniettato come chiave speciale) ─────────────────────────
    try:
        ov_ist = overrides.get("istanze", {})
        if ov_ist:
            merged["_istanze_overrides"] = ov_ist
    except Exception:
        pass

    return merged


# ==============================================================================
# MumuConfig — parametri MuMuPlayer
# ==============================================================================

@dataclass
class MumuConfig:
    """
    Parametri MuMuPlayer letti dalla sezione "mumu" di global_config.json.
    Prodotto da load_global().mumu.
    """
    manager:             str = (
        r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe"
    )
    adb:                 str = (
        r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
    )
    timeout_adb_s:       int = 120
    timeout_carica_s:    int = 180
    delay_carica_iniz_s: int = 45
    n_back_pulizia:      int = 5
    player_exe:          str = ""
    timeout_player_s:    int = 60


# ==============================================================================
# GlobalConfig — parametri globali tipizzati
# ==============================================================================

@dataclass
class GlobalConfig:
    """
    Parametri globali del bot. Prodotto da load_global().
    Accesso diretto agli attributi oppure via get(key, default).
    """

    # MuMu
    mumu: MumuConfig = field(default_factory=MumuConfig)

    # Sistema
    tick_sleep:   int   = 300
    max_parallel: int   = 2

    # Task abilitati
    task_raccolta:      bool = True
    task_rifornimento:  bool = False
    task_zaino:         bool = False
    task_vip:           bool = True
    task_alleanza:      bool = True
    task_messaggi:      bool = True
    task_arena:         bool = True
    task_arena_mercato: bool = True
    task_boost:         bool = True
    task_store:         bool = True
    task_radar:         bool = True
    task_radar_census:  bool = False

    # Rifornimento — parametri comuni
    dooms_account:                    str   = ""
    rifornimento_max_spedizioni_ciclo: int  = 5
    rifornimento_soglia_campo_m:      float = 5.0
    rifornimento_soglia_legno_m:      float = 5.0
    rifornimento_soglia_petrolio_m:   float = 2.5
    rifornimento_soglia_acciaio_m:    float = 3.5
    rifornimento_campo_abilitato:     bool  = True
    rifornimento_legno_abilitato:     bool  = True
    rifornimento_petrolio_abilitato:  bool  = True
    rifornimento_acciaio_abilitato:   bool  = False
    rifornimento_qta_pomodoro:        int   = 999_000_000
    rifornimento_qta_legno:           int   = 999_000_000
    rifornimento_qta_petrolio:        int   = 999_000_000
    rifornimento_qta_acciaio:         int   = 999_000_000

    # Rifornimento — modalità mappa
    rifornimento_abilitato:       bool = False
    rifornimento_mappa_abilitato: bool = False
    rifugio_x:                    int  = 687
    rifugio_y:                    int  = 532

    # Rifornimento — modalità membri
    rifornimento_membri_abilitato: bool = False
    avatar_template:               str  = "pin/avatar.png"

    # Zaino
    zaino_modalita:          str   = "bag"   # "bag" | "svuota"
    zaino_usa_pomodoro:      bool  = True
    zaino_usa_legno:         bool  = True
    zaino_usa_petrolio:      bool  = True
    zaino_usa_acciaio:       bool  = False
    zaino_soglia_pomodoro_m: float = 10.0
    zaino_soglia_legno_m:    float = 10.0
    zaino_soglia_petrolio_m: float =  5.0
    zaino_soglia_acciaio_m:  float =  7.0

    # Raccolta
    livello_nodo:         int   = 6
    allocazione_pomodoro: float = 0.4
    allocazione_legno:    float = 0.3
    allocazione_petrolio: float = 0.2
    allocazione_acciaio:  float = 0.1

    @classmethod
    def _from_raw(cls, raw: dict) -> "GlobalConfig":
        """Costruisce GlobalConfig da dict grezzo (global_config.json)."""
        s  = raw.get("sistema", {})
        m  = raw.get("mumu", {})
        t  = raw.get("task", {})
        rc = raw.get("rifornimento_comune", {})
        rm = raw.get("rifornimento_mappa", {})
        rb = raw.get("rifornimento_membri", {})
        z  = raw.get("zaino", {})
        ra = raw.get("raccolta", {})
        al = ra.get("allocazione", {})

        return cls(
            # MuMu
            mumu = MumuConfig(
                manager             = str(m.get("manager",
                    r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe")),
                adb                 = str(m.get("adb",
                    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe")),
                timeout_adb_s       = int(m.get("timeout_adb_s",       120)),
                timeout_carica_s    = int(m.get("timeout_carica_s",    180)),
                delay_carica_iniz_s = int(m.get("delay_carica_iniz_s", 45)),
                n_back_pulizia      = int(m.get("n_back_pulizia",      5)),
            ),

            # Sistema
            tick_sleep   = int(s.get("tick_sleep",   300)),
            max_parallel = int(s.get("max_parallel", 2)),

            # Task
            task_raccolta      = bool(t.get("raccolta",      True)),
            task_rifornimento  = bool(t.get("rifornimento",  False)),
            task_zaino         = bool(t.get("zaino",         False)),
            task_vip           = bool(t.get("vip",           True)),
            task_alleanza      = bool(t.get("alleanza",      True)),
            task_messaggi      = bool(t.get("messaggi",      True)),
            task_arena         = bool(t.get("arena",         True)),
            task_arena_mercato = bool(t.get("arena_mercato", True)),
            task_boost         = bool(t.get("boost",         True)),
            task_store         = bool(t.get("store",         True)),
            task_radar         = bool(t.get("radar",         True)),
            task_radar_census  = bool(t.get("radar_census",  False)),

            # Rifornimento — comune
            dooms_account                    = str(rc.get("dooms_account",        "")),
            rifornimento_max_spedizioni_ciclo= int(rc.get("max_spedizioni_ciclo", 5)),
            rifornimento_soglia_campo_m      = float(rc.get("soglia_campo_m",     5.0)),
            rifornimento_soglia_legno_m      = float(rc.get("soglia_legno_m",     5.0)),
            rifornimento_soglia_petrolio_m   = float(rc.get("soglia_petrolio_m",  2.5)),
            rifornimento_soglia_acciaio_m    = float(rc.get("soglia_acciaio_m",   3.5)),
            rifornimento_campo_abilitato     = bool(rc.get("campo_abilitato",     True)),
            rifornimento_legno_abilitato     = bool(rc.get("legno_abilitato",     True)),
            rifornimento_petrolio_abilitato  = bool(rc.get("petrolio_abilitato",  True)),
            rifornimento_acciaio_abilitato   = bool(rc.get("acciaio_abilitato",   False)),
            rifornimento_qta_pomodoro        = int(rc.get("qta_pomodoro",         1_000_000)),
            rifornimento_qta_legno           = int(rc.get("qta_legno",            1_000_000)),
            rifornimento_qta_petrolio        = int(rc.get("qta_petrolio",         0)),
            rifornimento_qta_acciaio         = int(rc.get("qta_acciaio",          0)),

            # Rifornimento — mappa
            rifornimento_abilitato       = bool(rm.get("abilitato", False)),
            rifornimento_mappa_abilitato = bool(rm.get("abilitato", False)),
            rifugio_x                    = int(rm.get("rifugio_x",  687)),
            rifugio_y                    = int(rm.get("rifugio_y",  532)),

            # Rifornimento — membri
            rifornimento_membri_abilitato = bool(rb.get("abilitato",       False)),
            avatar_template               = str(rb.get("avatar_template",  "pin/avatar.png")),

            # Zaino
            zaino_modalita          = str(z.get("modalita",          "bag")),
            zaino_usa_pomodoro      = bool(z.get("usa_pomodoro",      True)),
            zaino_usa_legno         = bool(z.get("usa_legno",         True)),
            zaino_usa_petrolio      = bool(z.get("usa_petrolio",      True)),
            zaino_usa_acciaio       = bool(z.get("usa_acciaio",       False)),
            zaino_soglia_pomodoro_m = float(z.get("soglia_pomodoro_m", 10.0)),
            zaino_soglia_legno_m    = float(z.get("soglia_legno_m",    10.0)),
            zaino_soglia_petrolio_m = float(z.get("soglia_petrolio_m",  5.0)),
            zaino_soglia_acciaio_m  = float(z.get("soglia_acciaio_m",   7.0)),

            # Raccolta
            livello_nodo         = int(ra.get("livello_nodo",   6)),
            allocazione_pomodoro = float(al.get("pomodoro",     0.4)),
            allocazione_legno    = float(al.get("legno",        0.3)),
            allocazione_petrolio = float(al.get("petrolio",     0.2)),
            allocazione_acciaio  = float(al.get("acciaio",      0.1)),
        )

    def to_dict(self) -> dict:
        """Serializza in dict compatibile con global_config.json."""
        return {
            "sistema": {
                "tick_sleep":   self.tick_sleep,
                "max_parallel": self.max_parallel,
            },
            "mumu": {
                "manager":             self.mumu.manager,
                "adb":                 self.mumu.adb,
                "timeout_adb_s":       self.mumu.timeout_adb_s,
                "timeout_carica_s":    self.mumu.timeout_carica_s,
                "delay_carica_iniz_s": self.mumu.delay_carica_iniz_s,
                "n_back_pulizia":      self.mumu.n_back_pulizia,
            },
            "task": {
                "raccolta":      self.task_raccolta,
                "rifornimento":  self.task_rifornimento,
                "zaino":         self.task_zaino,
                "vip":           self.task_vip,
                "alleanza":      self.task_alleanza,
                "messaggi":      self.task_messaggi,
                "arena":         self.task_arena,
                "arena_mercato": self.task_arena_mercato,
                "boost":         self.task_boost,
                "store":         self.task_store,
                "radar":         self.task_radar,
                "radar_census":  self.task_radar_census,
            },
            "rifornimento_comune": {
                "dooms_account":        self.dooms_account,
                "max_spedizioni_ciclo": self.rifornimento_max_spedizioni_ciclo,
                "soglia_campo_m":       self.rifornimento_soglia_campo_m,
                "soglia_legno_m":       self.rifornimento_soglia_legno_m,
                "soglia_petrolio_m":    self.rifornimento_soglia_petrolio_m,
                "soglia_acciaio_m":     self.rifornimento_soglia_acciaio_m,
                "campo_abilitato":      self.rifornimento_campo_abilitato,
                "legno_abilitato":      self.rifornimento_legno_abilitato,
                "petrolio_abilitato":   self.rifornimento_petrolio_abilitato,
                "acciaio_abilitato":    self.rifornimento_acciaio_abilitato,
                "qta_pomodoro":         self.rifornimento_qta_pomodoro,
                "qta_legno":            self.rifornimento_qta_legno,
                "qta_petrolio":         self.rifornimento_qta_petrolio,
                "qta_acciaio":          self.rifornimento_qta_acciaio,
            },
            "rifornimento_mappa": {
                "abilitato": self.rifornimento_mappa_abilitato,
                "rifugio_x": self.rifugio_x,
                "rifugio_y": self.rifugio_y,
            },
            "rifornimento_membri": {
                "abilitato":       self.rifornimento_membri_abilitato,
                "avatar_template": self.avatar_template,
            },
            "zaino": {
                "modalita":          self.zaino_modalita,
                "usa_pomodoro":      self.zaino_usa_pomodoro,
                "usa_legno":         self.zaino_usa_legno,
                "usa_petrolio":      self.zaino_usa_petrolio,
                "usa_acciaio":       self.zaino_usa_acciaio,
                "soglia_pomodoro_m": self.zaino_soglia_pomodoro_m,
                "soglia_legno_m":    self.zaino_soglia_legno_m,
                "soglia_petrolio_m": self.zaino_soglia_petrolio_m,
                "soglia_acciaio_m":  self.zaino_soglia_acciaio_m,
            },
            "raccolta": {
                "livello_nodo": self.livello_nodo,
                "allocazione": {
                    "pomodoro": self.allocazione_pomodoro,
                    "legno":    self.allocazione_legno,
                    "petrolio": self.allocazione_petrolio,
                    "acciaio":  self.allocazione_acciaio,
                },
            },
        }


# ==============================================================================
# build_instance_cfg — merge GlobalConfig + dati per-istanza
# Produce oggetto compatibile con l'attuale _Cfg di main.py
# ==============================================================================

def build_instance_cfg(ist: dict, gcfg: GlobalConfig, overrides: dict | None = None):
    """
    Costruisce la configurazione per una singola istanza.

    Precedenza:
      overrides (runtime per-istanza) > ist (instances.json) > gcfg (globale)

    Ritorna un oggetto con:
      - Tutti gli attributi uppercase che i task usano via ctx.config.get()
      - task_abilitato(nome) per lo scheduler
      - get(key, default) per retrocompatibilità

    Args:
        ist       : dict istanza da instances.json
        gcfg      : GlobalConfig letto da global_config.json
        overrides : dict opzionale per override per-istanza (es. da runtime.json)
    """
    ovr = overrides or {}
    nome = ist.get("nome", ist.get("name", "UNKNOWN"))
    _tipologia = ovr.get("tipologia") or ist.get("profilo", "full")

    class _InstanceCfg:
        # ── Identità istanza ─────────────────────────────────────────────────
        instance_name = nome
        truppe        = ovr.get("truppe",      ist.get("truppe",      12000))
        max_squadre   = ovr.get("max_squadre", ist.get("max_squadre", 4))
        layout        = ovr.get("layout",      ist.get("layout",      1))
        livello       = ovr.get("livello",     ist.get("livello",     gcfg.livello_nodo))
        profilo       = ovr.get("profilo",     ist.get("profilo",     "full"))
        fascia_oraria = ovr.get("fascia_oraria", ist.get("fascia_oraria", ""))
        lingua        = ist.get("lingua", "en")
        abilitata     = ist.get("abilitata", True)
        tipologia     = _tipologia

        # ── Rifornimento — comune ────────────────────────────────────────────
        DOOMS_ACCOUNT                    = gcfg.dooms_account
        RIFORNIMENTO_MAX_SPEDIZIONI_CICLO= gcfg.rifornimento_max_spedizioni_ciclo
        RIFORNIMENTO_SOGLIA_CAMPO_M      = gcfg.rifornimento_soglia_campo_m
        RIFORNIMENTO_SOGLIA_LEGNO_M      = gcfg.rifornimento_soglia_legno_m
        RIFORNIMENTO_SOGLIA_PETROLIO_M   = gcfg.rifornimento_soglia_petrolio_m
        RIFORNIMENTO_SOGLIA_ACCIAIO_M    = gcfg.rifornimento_soglia_acciaio_m
        RIFORNIMENTO_CAMPO_ABILITATO     = gcfg.rifornimento_campo_abilitato
        RIFORNIMENTO_LEGNO_ABILITATO     = gcfg.rifornimento_legno_abilitato
        RIFORNIMENTO_PETROLIO_ABILITATO  = gcfg.rifornimento_petrolio_abilitato
        RIFORNIMENTO_ACCIAIO_ABILITATO   = gcfg.rifornimento_acciaio_abilitato
        RIFORNIMENTO_QTA_POMODORO        = gcfg.rifornimento_qta_pomodoro
        RIFORNIMENTO_QTA_LEGNO           = gcfg.rifornimento_qta_legno
        RIFORNIMENTO_QTA_PETROLIO        = gcfg.rifornimento_qta_petrolio
        RIFORNIMENTO_QTA_ACCIAIO         = gcfg.rifornimento_qta_acciaio

        # ── Rifornimento — modalità mappa ────────────────────────────────────
        RIFORNIMENTO_ABILITATO       = gcfg.rifornimento_mappa_abilitato
        RIFORNIMENTO_MAPPA_ABILITATO = gcfg.rifornimento_mappa_abilitato
        RIFUGIO_X                    = gcfg.rifugio_x
        RIFUGIO_Y                    = gcfg.rifugio_y

        # ── Rifornimento — modalità membri ───────────────────────────────────
        RIFORNIMENTO_MEMBRI_ABILITATO = gcfg.rifornimento_membri_abilitato
        AVATAR_TEMPLATE               = gcfg.avatar_template

        # ── Zaino ─────────────────────────────────────────────────────────────
        ZAINO_MODALITA          = gcfg.zaino_modalita
        ZAINO_ABILITATO         = gcfg.task_zaino
        ZAINO_USA_POMODORO      = gcfg.zaino_usa_pomodoro
        ZAINO_USA_LEGNO         = gcfg.zaino_usa_legno
        ZAINO_USA_PETROLIO      = gcfg.zaino_usa_petrolio
        ZAINO_USA_ACCIAIO       = gcfg.zaino_usa_acciaio
        ZAINO_SOGLIA_POMODORO_M = gcfg.zaino_soglia_pomodoro_m
        ZAINO_SOGLIA_LEGNO_M    = gcfg.zaino_soglia_legno_m
        ZAINO_SOGLIA_PETROLIO_M = gcfg.zaino_soglia_petrolio_m
        ZAINO_SOGLIA_ACCIAIO_M  = gcfg.zaino_soglia_acciaio_m

        # ── Raccolta ──────────────────────────────────────────────────────────
        LIVELLO_NODO         = gcfg.livello_nodo
        ALLOCAZIONE_POMODORO = gcfg.allocazione_pomodoro
        ALLOCAZIONE_LEGNO    = gcfg.allocazione_legno
        ALLOCAZIONE_PETROLIO = gcfg.allocazione_petrolio
        ALLOCAZIONE_ACCIAIO  = gcfg.allocazione_acciaio

        # ── Task flag (retrocompat. uppercase) ───────────────────────────────
        ALLEANZA_ABILITATO        = gcfg.task_alleanza
        MESSAGGI_ABILITATO        = gcfg.task_messaggi
        VIP_ABILITATO             = gcfg.task_vip
        RADAR_ABILITATO           = gcfg.task_radar
        RADAR_CENSUS_ABILITATO    = gcfg.task_radar_census
        ARENA_OF_GLORY_ABILITATO  = gcfg.task_arena
        ARENA_MERCATO_ABILITATO   = gcfg.task_arena_mercato
        BOOST_ABILITATO           = gcfg.task_boost
        STORE_ABILITATO           = gcfg.task_store

        def get(self, key: str, default=None):
            return getattr(self, key, default)

        def task_abilitato(self, nome_task: str) -> bool:
            mappa = {
                "raccolta":              gcfg.task_raccolta,
                "rifornimento":          gcfg.task_rifornimento and (gcfg.rifornimento_mappa_abilitato or gcfg.rifornimento_membri_abilitato),
                "rifornimento_mappa":    gcfg.rifornimento_mappa_abilitato,
                "rifornimento_membri":   gcfg.rifornimento_membri_abilitato,
                "zaino":                 gcfg.task_zaino,
                "vip":                   gcfg.task_vip,
                "alleanza":              gcfg.task_alleanza,
                "messaggi":              gcfg.task_messaggi,
                "arena":                 gcfg.task_arena,
                "arena_mercato":         gcfg.task_arena_mercato,
                "boost":                 gcfg.task_boost,
                "store":                 gcfg.task_store,
                "radar":                 gcfg.task_radar,
                "radar_census":          gcfg.task_radar_census,
            }
            return mappa.get(nome_task, True)

        def __repr__(self):
            return (
                f"InstanceCfg(nome={nome!r}, profilo={self.profilo!r}, "
                f"layout={self.layout}, livello={self.livello})"
            )

    return _InstanceCfg()


# ==============================================================================
# load_instances — carica instances.json (standalone, senza dipendenze)
# ==============================================================================

def load_instances(path: str | Path | None = None) -> list[dict]:
    """
    Carica instances.json come lista di dict.
    Ritorna lista vuota se il file manca o è corrotto.
    """
    p = Path(path) if path else _INSTANCES_PATH
    if not p.exists():
        print(f"[CONFIG] WARN: {p} non trovato")
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"[CONFIG] ERRORE: {p} deve contenere una lista JSON")
            return []
        return data
    except Exception as exc:
        print(f"[CONFIG] ERRORE lettura {p}: {exc}")
        return []
