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
    "task_raccolta":          True,
    "task_rifornimento":      False,
    "task_donazione":         True,
    "task_main_mission":      True,
    "task_district_showdown": False,
    "task_zaino":             False,
    "task_vip":               True,
    "task_alleanza":          True,
    "task_messaggi":          True,
    "task_arena":             True,
    "task_arena_mercato":     True,
    "task_boost":             True,
    "task_truppe":            True,
    "task_store":             True,
    "task_radar":             True,
    "task_radar_census":      False,

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
    # 05/05: target proporzioni invio (analoga raccolta.allocazione).
    # None -> uniforme 25/25/25/25 (default). Configurabile da dashboard:
    # rifornimento.allocazione = {pomodoro: 30, legno: 30, acciaio: 20, petrolio: 20}.
    "RIFORNIMENTO_ALLOCAZIONE":         None,

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

    # ── truppe (06/05): tipo_solo + livello + count_min ─────────────────────
    try:
        ov_truppe = globali.get("truppe", {})
        if ov_truppe:
            if "truppe" not in merged:
                merged["truppe"] = {}
            for k, v in ov_truppe.items():
                merged["truppe"][k] = v
    except Exception:
        pass

    # ── flag globali root-level (WU55, WU93, WU89-step3, WU115) ─────────────
    # Flag a livello root di globali che non hanno una sezione dedicata.
    # Estendibile: aggiungere chiavi qui se servono nuovi flag globali.
    for _k in ("raccolta_ocr_debug", "auto_learn_banner",
               "skip_predictor_enabled", "skip_predictor_shadow_only",
               "debug_tasks"):
        try:
            if _k in globali:
                merged[_k] = globali[_k]
        except Exception:
            pass

    # ── sistema ─────────────────────────────────────────────────────────────
    # Alias `tick_sleep_min` (dashboard Pydantic SistemaOverride, MINUTI) →
    # `tick_sleep` (bot nativo, SECONDI). Conversione esplicita ×60.
    # Bug storico (03/05): l'alias era senza conversione → dashboard mostrava
    # tick=5 mentre il bot girava a tick=60s indipendentemente dal config.
    try:
        ov_sistema = globali.get("sistema", {})
        if ov_sistema:
            if "sistema" not in merged:
                merged["sistema"] = {}
            for k, v in ov_sistema.items():
                if k == "tick_sleep_min":
                    merged["sistema"]["tick_sleep"] = int(v) * 60
                else:
                    merged["sistema"][k] = v
    except Exception:
        pass

    # ── zaino ───────────────────────────────────────────────────────────────
    try:
        ov_zaino = globali.get("zaino", {})
        if ov_zaino:
            if "zaino" not in merged:
                merged["zaino"] = {}
            for k, v in ov_zaino.items():
                merged["zaino"][k] = v
    except Exception:
        pass

    # ── rifornimento_comune ─────────────────────────────────────────────────
    try:
        ov_rc = globali.get("rifornimento_comune", {})
        if ov_rc:
            if "rifornimento_comune" not in merged:
                merged["rifornimento_comune"] = {}
            for k, v in ov_rc.items():
                merged["rifornimento_comune"][k] = v
    except Exception:
        pass

    # ── rifornimento_mappa — propagazione da globali.rifornimento.mappa_abilitata ──
    # Sub-mode del task rifornimento: unica fonte di verità è
    # globali.rifornimento.mappa_abilitata (mutuamente esclusiva con membri_abilitati).
    # Il flag master task.rifornimento decide se il task gira; la sub-mode
    # decide COME gira (via mappa o via membri).
    #
    # 05/05: aggiunto mirror nel merged["rifornimento"] (top-level) per
    # consumo della dashboard. Pre-fix: template index.html legge
    # `cfg.rifornimento.mappa_abilitata` ma il merge esponeva solo
    # `rifornimento_mappa.abilitato` → cfg.rifornimento=None → toggle UI
    # sempre OFF al refresh. Ora rifornimento dict copia mappa_abilitata e
    # membri_abilitati per coerenza con schema runtime_overrides.
    try:
        ov_rif = globali.get("rifornimento", {}) or {}
        ov_mappa = ov_rif.get("mappa_abilitata")
        ov_membri = ov_rif.get("membri_abilitati")
        if ov_mappa is not None or ov_membri is not None:
            if "rifornimento_mappa" not in merged:
                merged["rifornimento_mappa"] = {}
            if ov_mappa is not None:
                merged["rifornimento_mappa"]["abilitato"] = bool(ov_mappa)
            # Mirror top-level per dashboard
            if "rifornimento" not in merged:
                merged["rifornimento"] = {}
            if ov_mappa is not None:
                merged["rifornimento"]["mappa_abilitata"] = bool(ov_mappa)
            if ov_membri is not None:
                merged["rifornimento"]["membri_abilitati"] = bool(ov_membri)
            # Copia anche soglia_campo_m + provviste_max se presenti
            for k in ("soglia_campo_m", "provviste_max"):
                if k in ov_rif:
                    merged["rifornimento"][k] = ov_rif[k]
    except Exception:
        pass

    try:
        ov_rifugio = globali.get("rifugio")
        if ov_rifugio:
            if "rifornimento_mappa" not in merged:
                merged["rifornimento_mappa"] = {}
            # Schema reale in global_config.json.rifornimento_mappa:
            # rifugio_x (int), rifugio_y (int). Il modello RuntimeOverrides
            # usa coord_x/coord_y -> rimappa qui ai nomi reali.
            cx = ov_rifugio.get("coord_x")
            cy = ov_rifugio.get("coord_y")
            if cx is not None:
                merged["rifornimento_mappa"]["rifugio_x"] = cx
            if cy is not None:
                merged["rifornimento_mappa"]["rifugio_y"] = cy
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
    task_raccolta:          bool = True
    task_rifornimento:      bool = False
    task_donazione:         bool = True
    task_main_mission:      bool = True
    task_district_showdown: bool = False
    task_zaino:             bool = False
    task_vip:               bool = True
    task_alleanza:          bool = True
    task_messaggi:          bool = True
    task_arena:             bool = True
    task_arena_mercato:     bool = True
    task_boost:             bool = True
    task_truppe:            bool = True
    task_store:             bool = True
    task_radar:             bool = True
    task_radar_census:      bool = False

    # WU55 — Data collection OCR slot (debug analisi HOME vs MAPPA)
    raccolta_ocr_debug:     bool = False

    # WU93 — BannerLearner auto-apprendimento banner non catalogati
    # WU110 (03/05) — DEPRECATO, default False. La pipeline learn non scattava
    # mai in pratica perché il fallback X cerchio dorato dismisses i banner
    # prima del learner. Vedi shared/banner_learner.py + shared/learned_banners.py.
    auto_learn_banner:      bool = False

    # WU89 Step 3 — Skip Predictor (flag-driven, default OFF + shadow first)
    skip_predictor_enabled:     bool = False
    skip_predictor_shadow_only: bool = True

    # WU115 — Debug screenshot per task (hot-reload via shared/debug_buffer.py)
    debug_tasks:            dict = field(default_factory=dict)

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
    # 05/05: target proporzioni invio (analoga raccolta.allocazione).
    # Default uniforme 25/25/25/25 (frazioni 0-1). Sum != 1 viene normalizzato.
    # 06/05: truppe filtri (tipologia caserma + livello + soglia count)
    truppe_tipo_solo:    str = "all"     # all|infantry|rider|ranged|engine
    truppe_livello:      str = "auto"    # auto|I|II|III|IV|V|VI
    truppe_count_min:    int = 0         # 0 = no soglia

    rifornimento_allocazione_pomodoro: float = 0.25
    rifornimento_allocazione_legno:    float = 0.25
    rifornimento_allocazione_petrolio: float = 0.25
    rifornimento_allocazione_acciaio:  float = 0.25

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
        tr = raw.get("truppe", {})   # 06/05 filtri TruppeTask

        # Normalizza percentuali → frazioni 0-1
        # AllocazioneOverride (dashboard Pydantic) salva 0-100 espliciti;
        # global_config in 0-1. Se max>1 assume percentuali e divide.
        _al_max = max((float(v) for v in al.values()), default=0.0) if al else 0.0
        _al_div = 100.0 if _al_max > 1.0 else 1.0

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
            task_raccolta          = bool(t.get("raccolta",          True)),
            task_rifornimento      = bool(t.get("rifornimento",      False)),
            task_donazione         = bool(t.get("donazione",         True)),
            task_main_mission      = bool(t.get("main_mission",      True)),
            task_district_showdown = bool(t.get("district_showdown", False)),
            task_zaino             = bool(t.get("zaino",             False)),
            task_vip               = bool(t.get("vip",               True)),
            task_alleanza          = bool(t.get("alleanza",          True)),
            task_messaggi          = bool(t.get("messaggi",          True)),
            task_arena             = bool(t.get("arena",             True)),
            task_arena_mercato     = bool(t.get("arena_mercato",     True)),
            task_boost             = bool(t.get("boost",             True)),
            task_truppe            = bool(t.get("truppe",            True)),
            task_store             = bool(t.get("store",             True)),
            task_radar             = bool(t.get("radar",             True)),
            task_radar_census      = bool(t.get("radar_census",      False)),

            # WU55 — debug OCR slot (legge da raw o globali.raccolta_ocr_debug)
            raccolta_ocr_debug     = bool(
                raw.get("raccolta_ocr_debug",
                        raw.get("globali", {}).get("raccolta_ocr_debug", False))
            ),

            # WU93/WU110 — BannerLearner auto-apprendimento (default False, deprecato)
            auto_learn_banner      = bool(
                raw.get("auto_learn_banner",
                        raw.get("globali", {}).get("auto_learn_banner", False))
            ),

            # WU89 Step 3 — Skip Predictor (default OFF, shadow first)
            skip_predictor_enabled     = bool(
                raw.get("skip_predictor_enabled",
                        raw.get("globali", {}).get("skip_predictor_enabled", False))
            ),
            skip_predictor_shadow_only = bool(
                raw.get("skip_predictor_shadow_only",
                        raw.get("globali", {}).get("skip_predictor_shadow_only", True))
            ),
            # WU115 — Debug screenshot per task (dict {task: bool}, hot-reload)
            debug_tasks = dict(
                raw.get("debug_tasks",
                        raw.get("globali", {}).get("debug_tasks", {})) or {}
            ),

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
            # Allocazione proporzioni invio (05/05). Letto da rifornimento_comune.allocazione
            # se presente, altrimenti default uniforme 25/25/25/25. Normalizzazione
            # automatica gestita in _seleziona_risorsa (somma 1 o 100 o anche zero).
            rifornimento_allocazione_pomodoro = float((rc.get("allocazione") or {}).get("pomodoro", 0.25)),
            rifornimento_allocazione_legno    = float((rc.get("allocazione") or {}).get("legno",    0.25)),
            rifornimento_allocazione_petrolio = float((rc.get("allocazione") or {}).get("petrolio", 0.25)),
            rifornimento_allocazione_acciaio  = float((rc.get("allocazione") or {}).get("acciaio",  0.25)),

            # Truppe filtri (06/05): tipologia caserma + livello + soglia count
            truppe_tipo_solo  = str(tr.get("tipo_solo", "all")),
            truppe_livello    = str(tr.get("livello",   "auto")),
            truppe_count_min  = int(tr.get("count_min", 0)),

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
            allocazione_pomodoro = float(al.get("pomodoro",     0.4)) / _al_div,
            allocazione_legno    = float(al.get("legno",        0.3)) / _al_div,
            allocazione_petrolio = float(al.get("petrolio",     0.2)) / _al_div,
            allocazione_acciaio  = float(al.get("acciaio",      0.1)) / _al_div,
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
                "raccolta":          self.task_raccolta,
                "rifornimento":      self.task_rifornimento,
                "donazione":         self.task_donazione,
                "main_mission":      self.task_main_mission,
                "district_showdown": self.task_district_showdown,
                "zaino":             self.task_zaino,
                "vip":               self.task_vip,
                "alleanza":          self.task_alleanza,
                "messaggi":          self.task_messaggi,
                "arena":             self.task_arena,
                "arena_mercato":     self.task_arena_mercato,
                "boost":             self.task_boost,
                "truppe":            self.task_truppe,
                "store":             self.task_store,
                "radar":             self.task_radar,
                "radar_census":      self.task_radar_census,
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
                "allocazione": {
                    "pomodoro": self.rifornimento_allocazione_pomodoro,
                    "legno":    self.rifornimento_allocazione_legno,
                    "petrolio": self.rifornimento_allocazione_petrolio,
                    "acciaio":  self.rifornimento_allocazione_acciaio,
                },
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
            "truppe": {
                "tipo_solo": self.truppe_tipo_solo,
                "livello":   self.truppe_livello,
                "count_min": self.truppe_count_min,
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

    def _ovr(key, fallback):
        """dict.get che tratta None come chiave mancante.
        Pydantic IstanzaOverride salva campi Optional non settati come null
        esplicito nel JSON → `ovr.get(key, default)` ritorna None, non default.
        """
        v = ovr.get(key)
        return fallback if v is None else v

    class _InstanceCfg:
        # ── Identità istanza ─────────────────────────────────────────────────
        instance_name = nome
        truppe        = _ovr("truppe",      ist.get("truppe",      12000))
        max_squadre   = _ovr("max_squadre", ist.get("max_squadre", 4))
        layout        = _ovr("layout",      ist.get("layout",      1))
        livello       = _ovr("livello",     ist.get("livello",     gcfg.livello_nodo))
        profilo       = _ovr("profilo",     ist.get("profilo",     "full"))
        fascia_oraria = _ovr("fascia_oraria", ist.get("fascia_oraria", ""))
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
        # 05/05: dict di allocazione per _seleziona_risorsa weighted-deficit
        RIFORNIMENTO_ALLOCAZIONE         = {
            "pomodoro": gcfg.rifornimento_allocazione_pomodoro,
            "legno":    gcfg.rifornimento_allocazione_legno,
            "petrolio": gcfg.rifornimento_allocazione_petrolio,
            "acciaio":  gcfg.rifornimento_allocazione_acciaio,
        }

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
        # WU50 — modalità fuori territorio (per istanza).
        # Precedenza: override runtime > instances.json (default statico).
        RACCOLTA_FUORI_TERRITORIO_ABILITATA = bool(_ovr(
            "raccolta_fuori_territorio",
            ist.get("raccolta_fuori_territorio", False),
        ))
        # WU55 — Data collection OCR slot per analisi HOME vs MAPPA.
        # Flag globale (non per istanza) — attivato per 1 ciclo di analisi.
        RACCOLTA_OCR_DEBUG = bool(getattr(gcfg, "raccolta_ocr_debug", False))

        # ── Truppe filtri (06/05) ─────────────────────────────────────────────
        TRUPPE_TIPO_SOLO  = str(getattr(gcfg, "truppe_tipo_solo", "all")).lower()
        TRUPPE_LIVELLO    = str(getattr(gcfg, "truppe_livello",   "auto"))
        TRUPPE_COUNT_MIN  = int(getattr(gcfg, "truppe_count_min", 0))

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
                "donazione":             gcfg.task_donazione,
                "main_mission":          gcfg.task_main_mission,
                "district_showdown":     gcfg.task_district_showdown,
                "zaino":                 gcfg.task_zaino,
                "vip":                   gcfg.task_vip,
                "alleanza":              gcfg.task_alleanza,
                "messaggi":              gcfg.task_messaggi,
                "arena":                 gcfg.task_arena,
                "arena_mercato":         gcfg.task_arena_mercato,
                "boost":                 gcfg.task_boost,
                "truppe":                gcfg.task_truppe,
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
