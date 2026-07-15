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
    # Sistema (chiave interna `tick_sleep` in secondi; raw config usa
    # `tick_sleep_min` in minuti — conversione in merge_config).
    "tick_sleep":   300,
    "max_parallel": 2,

    # Task abilitati
    "task_grafica_hq":        True,
    "task_pulizia_cache":     True,
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


def load_effective_global(path: str | Path | None = None) -> "GlobalConfig":
    """GlobalConfig EFFETTIVA = `global_config.json` (static) MERGED con
    `runtime_overrides.json` (dynamic), come la vede il bot ad ogni tick (stessa
    pipeline di `main.py`: `merge_config` → `_from_raw`).

    I moduli launcher DEVONO usare QUESTA per leggere i timeout `mumu.*`
    (`timeout_carica_s`, `timeout_adb_s`, ...). `load_global()` legge SOLO lo
    static, quindi gli override dynamic di quei campi (es. WU201 `timeout_carica_s`
    300→400, propagato via `sistema.timeout_carica_s` → `mumu.timeout_carica_s`)
    NON avrebbero mai effetto a runtime — bug WU209.
    """
    p = Path(path) if path else _GLOBAL_CONFIG_PATH
    static_raw: dict = {}
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                static_raw = json.load(f)
        except Exception as exc:
            print(f"[CONFIG] WARN: global_config.json non leggibile ({exc}) — uso default")
    ov = load_overrides(p.parent / "runtime_overrides.json")
    try:
        merged = merge_config(static_raw, ov)
    except Exception as exc:
        print(f"[CONFIG] WARN: merge_config fallito ({exc}) — uso solo static")
        merged = static_raw
    return GlobalConfig._from_raw(merged)


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


# ==============================================================================
# Bootstrap static → dynamic (regola architetturale 08/05)
# ==============================================================================

# Campi delle istanze copiati nel bootstrap (= mirror static→dynamic).
# Mapping nomi diversi: profilo (instances.json) → tipologia (override).
_INSTANCE_BOOTSTRAP_FIELDS = (
    "abilitata", "truppe", "fascia_oraria", "max_squadre",
    "livello", "raccolta_fuori_territorio", "master",
)


def _build_runtime_from_static(global_config: dict, instances: list) -> dict:
    """Costruisce dict runtime_overrides da global_config + instances.

    Replica TUTTI i campi configurabili (regola "bootstrap copia static→dynamic").
    Esclude campi read-only/architetturali (mumu, _note).
    """
    SKIP_KEYS = {"_note", "mumu"}

    globali: dict = {}
    if isinstance(global_config, dict):
        for k, v in global_config.items():
            if k in SKIP_KEYS:
                continue
            # Deep copy via json round-trip per evitare reference shared
            globali[k] = __import__('json').loads(
                __import__('json').dumps(v, ensure_ascii=False)
            )

    istanze: dict = {}
    if isinstance(instances, list):
        for ist in instances:
            if not isinstance(ist, dict):
                continue
            nome = ist.get("nome")
            if not nome:
                continue
            entry: dict = {}
            for f in _INSTANCE_BOOTSTRAP_FIELDS:
                if f == "fascia_oraria":
                    # Default vuoto se mancante
                    entry[f] = ist.get(f, "") or ""
                elif f in ist:
                    entry[f] = ist[f]
            # Mapping profilo → tipologia (instance.json usa profilo, override tipologia)
            if "profilo" in ist:
                entry["tipologia"] = ist["profilo"]
            istanze[nome] = entry

    return {"globali": globali, "istanze": istanze}


def _build_static_from_runtime(
    runtime: dict, current_global: dict, current_instances: list
) -> tuple[dict, list]:
    """Costruisce (global_config, instances) da runtime_overrides.

    Inverso di `_build_runtime_from_static`. Usato dall'endpoint
    `POST /api/config/promote` per "promuovere" la configurazione runtime
    corrente a baseline statico.

    Preserva i campi non gestiti dal runtime (mumu, _note, qta_*, ecc.):
    parte da `current_global` / `current_instances` e sovrascrive solo i
    campi presenti nel runtime.
    """
    import copy

    SKIP_KEYS = {"_note", "mumu"}

    def _deep_merge(dst: dict, src: dict) -> None:
        """Merge ricorsivo: src in dst. Sovrascrive scalari/list, fonde sub-dict.
        Preserva sub-key di dst non presenti in src (es. qta_* che vivono solo in static)."""
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _deep_merge(dst[k], v)
            else:
                dst[k] = copy.deepcopy(v)

    new_global = copy.deepcopy(current_global) if isinstance(current_global, dict) else {}
    rt_globali = runtime.get("globali", {}) if isinstance(runtime, dict) else {}
    if isinstance(rt_globali, dict):
        for k, v in rt_globali.items():
            if k in SKIP_KEYS:
                continue
            if isinstance(v, dict) and isinstance(new_global.get(k), dict):
                _deep_merge(new_global[k], v)
            else:
                new_global[k] = copy.deepcopy(v)

    # Cleanup migrazione 08/05: chiave legacy `sistema.tick_sleep` (secondi)
    # rimossa se affianca la nuova `sistema.tick_sleep_min` (minuti).
    sis = new_global.get("sistema") if isinstance(new_global.get("sistema"), dict) else None
    if sis and "tick_sleep_min" in sis and "tick_sleep" in sis:
        del sis["tick_sleep"]

    rt_istanze = runtime.get("istanze", {}) if isinstance(runtime, dict) else {}
    new_instances: list = []
    if isinstance(current_instances, list):
        for ist in current_instances:
            if not isinstance(ist, dict):
                continue
            entry = copy.deepcopy(ist)
            nome = entry.get("nome")
            if nome and isinstance(rt_istanze, dict) and nome in rt_istanze:
                ovr = rt_istanze[nome] or {}
                if isinstance(ovr, dict):
                    for f in _INSTANCE_BOOTSTRAP_FIELDS:
                        if f in ovr and ovr[f] is not None:
                            entry[f] = ovr[f]
                    # Mapping inverso: tipologia (override) → profilo (instances.json)
                    if "tipologia" in ovr and ovr["tipologia"] is not None:
                        entry["profilo"] = ovr["tipologia"]
                    # truppe_override: campo per-istanza, vive in instances.json
                    if "truppe_override" in ovr:
                        entry["truppe_override"] = copy.deepcopy(ovr["truppe_override"])
            new_instances.append(entry)

    return new_global, new_instances


def promote_runtime_to_static(
    overrides_path: str | Path | None = None,
    global_config_path: str | Path | None = None,
    instances_path: str | Path | None = None,
) -> dict:
    """Sovrascrive `global_config.json` + `instances.json` con i valori
    correnti di `runtime_overrides.json`.

    Inverso di `bootstrap_runtime_from_static_if_missing(force=True)`.

    Returns:
        dict con `{global_updated: bool, instances_updated: bool, error: str|None}`.
    """
    import json

    ov_path  = Path(overrides_path)       if overrides_path       else (_ROOT / "config" / "runtime_overrides.json")
    gc_path  = Path(global_config_path)   if global_config_path   else _GLOBAL_CONFIG_PATH
    ist_path = Path(instances_path)       if instances_path       else _INSTANCES_PATH

    try:
        runtime = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}
    except Exception as exc:
        return {"global_updated": False, "instances_updated": False,
                "error": f"runtime_overrides illeggibile: {exc}"}

    try:
        gc_raw = json.loads(gc_path.read_text(encoding="utf-8")) if gc_path.exists() else {}
    except Exception:
        gc_raw = {}
    try:
        ist_raw = json.loads(ist_path.read_text(encoding="utf-8")) if ist_path.exists() else []
    except Exception:
        ist_raw = []

    new_global, new_instances = _build_static_from_runtime(runtime, gc_raw, ist_raw)

    g_ok = i_ok = False
    err: str | None = None

    # Scrittura atomica global_config
    try:
        gc_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = gc_path.with_suffix(gc_path.suffix + ".tmp")
        tmp.write_text(json.dumps(new_global, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        os.replace(tmp, gc_path)
        g_ok = True
    except Exception as exc:
        err = f"global_config write fallita: {exc}"

    # Scrittura atomica instances
    try:
        ist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = ist_path.with_suffix(ist_path.suffix + ".tmp")
        tmp.write_text(json.dumps(new_instances, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        os.replace(tmp, ist_path)
        i_ok = True
    except Exception as exc:
        err = (err + " · " if err else "") + f"instances write fallita: {exc}"

    return {"global_updated": g_ok, "instances_updated": i_ok, "error": err}


def bootstrap_runtime_from_static_if_missing(
    overrides_path: str | Path | None = None,
    global_config_path: str | Path | None = None,
    instances_path: str | Path | None = None,
    force: bool = False,
) -> bool:
    """Crea `runtime_overrides.json` copiando static (`global_config.json` +
    `instances.json`) se file mancante o `force=True`.

    Regola architetturale: dynamic deve essere popolato dai valori static al
    primo avvio (o dopo reset esplicito). Da quel momento in poi, dynamic
    diventa indipendente — modifiche real-time dalla HOME non toccano static
    e modifiche dalla CONFIG non toccano dynamic.

    Args:
        force: se True, sovrascrive runtime_overrides anche se esiste (= reset).

    Returns:
        True se file creato/sovrascritto, False se esistente e non force.
    """
    import json
    from pathlib import Path

    ov_path = Path(overrides_path) if overrides_path else (_ROOT / "config" / "runtime_overrides.json")
    gc_path = Path(global_config_path) if global_config_path else _GLOBAL_CONFIG_PATH
    ist_path = Path(instances_path) if instances_path else _INSTANCES_PATH

    if ov_path.exists() and not force:
        return False

    # Leggi static
    try:
        gc_raw = json.loads(gc_path.read_text(encoding="utf-8")) if gc_path.exists() else {}
    except Exception:
        gc_raw = {}
    try:
        ist_raw = json.loads(ist_path.read_text(encoding="utf-8")) if ist_path.exists() else []
    except Exception:
        ist_raw = []

    runtime = _build_runtime_from_static(gc_raw, ist_raw)

    # Scrittura atomica
    ov_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ov_path.with_suffix(ov_path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(runtime, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, ov_path)
        return True
    except Exception:
        try:
            if tmp.exists(): tmp.unlink()
        except Exception:
            pass
        return False


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

    # Normalizzazione baseline: chiave raw `tick_sleep_min` (minuti, dashboard
    # 08/05 uniforma file static a minuti) → chiave interna `tick_sleep`
    # (secondi, usata dal bot per time.sleep). Conversione esplicita ×60.
    try:
        sis = merged.setdefault("sistema", {}) if isinstance(merged, dict) else {}
        if "tick_sleep_min" in sis:
            sis["tick_sleep"] = int(sis.pop("tick_sleep_min")) * 60
    except Exception:
        pass

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

    # ── flag globali root-level (WU55, WU93, WU89-step3, WU115, Step C) ─────
    # Flag a livello root di globali che non hanno una sezione dedicata.
    # Estendibile: aggiungere chiavi qui se servono nuovi flag globali.
    for _k in ("raccolta_ocr_debug", "auto_learn_banner",
               "adaptive_scheduler_enabled", "adaptive_scheduler_shadow_only",
               "adaptive_scheduler_thresholds",
               "debug_tasks", "notifications"):
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
            # WU155 — sistema.timeout_carica_s (path canonico dashboard) propaga
            # a mumu.timeout_carica_s (path canonico bot). Bot legge da mumu.*
            if "timeout_carica_s" in ov_sistema:
                if "mumu" not in merged:
                    merged["mumu"] = {}
                merged["mumu"]["timeout_carica_s"] = int(ov_sistema["timeout_carica_s"])
            # timeout_adb_s: stesso pattern — propaga da sistema a mumu
            if "timeout_adb_s" in ov_sistema:
                if "mumu" not in merged:
                    merged["mumu"] = {}
                merged["mumu"]["timeout_adb_s"] = int(ov_sistema["timeout_adb_s"])
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
    timeout_carica_s:    int = 300
    delay_carica_iniz_s: int = 45
    n_back_pulizia:      int = 5
    player_exe:          str = ""
    timeout_player_s:    int = 60


# ==============================================================================
# GlobalConfig — parametri globali tipizzati
# ==============================================================================

_NOTIFICATIONS_DEFAULT: dict = {
    "enabled":               False,
    "daily_report_enabled":  True,
    "daily_report_hour_utc": 6,
    # WU137 fase 2 — alert real-time (master toggle). Default OFF per safety.
    # Lista `alerts_disabled` permette di silenziare specifici event_type
    # (es. "cascade_adb", "heartbeat_cicli", "master_saturo_long",
    # "maintenance_long", "bot_unexpected_restart").
    "alerts_enabled":        False,
    "alerts_disabled":       [],
    # Vuoti: l'utente li configura in dashboard prima di abilitare l'invio.
    # Valori baseline iniziali in `config/global_config.json` (sovrascrivibili).
    "from_addr":             "",
    "recipients":            [],
    "smtp":                  {"host": "smtp.gmail.com", "port": 465},
}


def _merge_notifications_default(raw: dict) -> dict:
    """Merge raw config (anche parziale) con i default. Default per chiavi
    mancanti, deep-merge per `smtp`. Ritorna sempre dict completo."""
    out = dict(_NOTIFICATIONS_DEFAULT)
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if k == "smtp" and isinstance(v, dict):
            smtp_merged = dict(_NOTIFICATIONS_DEFAULT["smtp"])
            smtp_merged.update(v)
            out["smtp"] = smtp_merged
        else:
            out[k] = v
    return out


def load_effective_notifications() -> dict:
    """Ritorna config notifications EFFETTIVA (baseline + runtime_overrides).

    Priorità: `runtime_overrides.json::globali.notifications` >
              `global_config.json::notifications` > defaults.

    Tutti i consumer (daily_report, api_notifications, main.py boot) DEVONO
    usare questa per leggere config notifications, NON `load_global()` che
    legge solo il baseline. Ritorna sempre dict completo (chiavi mai mancanti).
    """
    gc = load_global()
    base = dict(gc.notifications or {})
    try:
        ov_path = _ROOT / "config" / "runtime_overrides.json"
        if ov_path.exists():
            with ov_path.open(encoding="utf-8") as f:
                ov = json.load(f) or {}
            ov_notif = (ov.get("globali") or {}).get("notifications") or {}
            if isinstance(ov_notif, dict):
                # Deep merge per smtp, shallow per resto (override > base)
                for k, v in ov_notif.items():
                    if k == "smtp" and isinstance(v, dict):
                        smtp = dict(base.get("smtp") or {})
                        smtp.update(v)
                        base["smtp"] = smtp
                    else:
                        base[k] = v
    except Exception:
        pass
    # Garantisce chiavi sempre presenti (anche se entrambi i file mancano alcune)
    return _merge_notifications_default(base)


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
    task_grafica_hq:        bool = True
    task_pulizia_cache:     bool = True
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

    # 08/05 — WU89 Skip Predictor RIMOSSO (regola "no skip istanza"). I campi
    # `skip_predictor_enabled` / `skip_predictor_shadow_only` non sono più
    # parte di GlobalConfig.

    # 08/05 — Adaptive Scheduler (flag-driven, default OFF + shadow first)
    adaptive_scheduler_enabled:     bool = False
    adaptive_scheduler_shadow_only: bool = True
    adaptive_scheduler_thresholds:  dict = field(default_factory=lambda: {
        "drl_residuo_pct":  30,
        "pct_istanze_sat":  50,
        "spedizioni_oggi":  100,
    })

    # WU115 — Debug screenshot per task (hot-reload via shared/debug_buffer.py)
    debug_tasks:            dict = field(default_factory=dict)

    # Step C Email Notifier — config notifications globale.
    # Schema: {enabled, daily_report_enabled, daily_report_hour_utc, from_addr,
    #          recipients: list[str], smtp: {host, port}}.
    # App password sempre da env var DOOMSDAY_GMAIL_APP_PASSWORD (non in config).
    notifications:          dict = field(default_factory=lambda: dict(_NOTIFICATIONS_DEFAULT))

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
    # 06/05: truppe — flag per le 4 caserme (default ON globale).
    truppe_caserme_infantry: bool = True
    truppe_caserme_rider:    bool = True
    truppe_caserme_ranged:   bool = True
    truppe_caserme_engine:   bool = True

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

        # WU155 — timeout_carica_s: priorita' sistema.timeout_carica_s (path nuovo
        # esposto in dashboard sezione sistema) > mumu.timeout_carica_s (legacy)
        # > default 300.
        _timeout_carica = int(
            s.get("timeout_carica_s",
                  m.get("timeout_carica_s", 300))
        )

        return cls(
            # MuMu
            mumu = MumuConfig(
                manager             = str(m.get("manager",
                    r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe")),
                adb                 = str(m.get("adb",
                    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe")),
                timeout_adb_s       = int(m.get("timeout_adb_s",       120)),
                timeout_carica_s    = _timeout_carica,
                delay_carica_iniz_s = int(m.get("delay_carica_iniz_s", 45)),
                n_back_pulizia      = int(m.get("n_back_pulizia",      5)),
            ),

            # Sistema (raw usa `tick_sleep_min` in minuti dal 08/05 — uniformato
            # con dynamic. Fallback alla vecchia chiave `tick_sleep` (secondi)
            # per backward compat finché tutti i file non sono migrati.)
            tick_sleep   = (int(s["tick_sleep_min"]) * 60
                            if "tick_sleep_min" in s
                            else int(s.get("tick_sleep", 300))),
            max_parallel = int(s.get("max_parallel", 2)),

            # Task
            task_grafica_hq        = bool(t.get("grafica_hq",        True)),
            task_pulizia_cache     = bool(t.get("pulizia_cache",     True)),
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

            # 08/05: WU89 Skip Predictor RIMOSSO — vedi nota dataclass.
            # 08/05 — Adaptive Scheduler flags
            adaptive_scheduler_enabled = bool(
                raw.get("adaptive_scheduler_enabled",
                        raw.get("globali", {}).get("adaptive_scheduler_enabled", False))
            ),
            adaptive_scheduler_shadow_only = bool(
                raw.get("adaptive_scheduler_shadow_only",
                        raw.get("globali", {}).get("adaptive_scheduler_shadow_only", True))
            ),
            adaptive_scheduler_thresholds = dict(
                raw.get("adaptive_scheduler_thresholds",
                        raw.get("globali", {}).get("adaptive_scheduler_thresholds",
                                                    {"drl_residuo_pct": 30,
                                                     "pct_istanze_sat": 50,
                                                     "spedizioni_oggi": 100})) or {}
            ),
            # WU115 — Debug screenshot per task (dict {task: bool}, hot-reload)
            debug_tasks = dict(
                raw.get("debug_tasks",
                        raw.get("globali", {}).get("debug_tasks", {})) or {}
            ),

            # Step C Email Notifier — config notifications.
            # Merge con default per garantire chiavi sempre presenti anche se
            # `runtime_overrides.json` ha solo override parziale (es. solo `enabled`).
            notifications = _merge_notifications_default(
                raw.get("notifications",
                        raw.get("globali", {}).get("notifications", {})) or {}
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

            # Truppe (06/05): flag per le 4 caserme (default ON globale).
            # Schema: globali.truppe.caserme.{infantry,rider,ranged,engine}: bool
            truppe_caserme_infantry = bool((tr.get("caserme") or {}).get("infantry", True)),
            truppe_caserme_rider    = bool((tr.get("caserme") or {}).get("rider",    True)),
            truppe_caserme_ranged   = bool((tr.get("caserme") or {}).get("ranged",   True)),
            truppe_caserme_engine   = bool((tr.get("caserme") or {}).get("engine",   True)),

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
        """Serializza in dict compatibile con global_config.json.
        08/05: scrittura usa `tick_sleep_min` (minuti) per uniformità con
        runtime_overrides; il campo interno resta `tick_sleep` (secondi)."""
        return {
            "sistema": {
                "tick_sleep_min":   int(self.tick_sleep // 60),
                "max_parallel":     self.max_parallel,
                # WU155 — path canonico dashboard. mumu.timeout_carica_s rimane
                # come backward compat per chi legge da quel path (V5 legacy).
                "timeout_carica_s": self.mumu.timeout_carica_s,
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
                "grafica_hq":        self.task_grafica_hq,
                "pulizia_cache":     self.task_pulizia_cache,
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
                    "pomodoro": round(self.allocazione_pomodoro * 100, 1),
                    "legno":    round(self.allocazione_legno    * 100, 1),
                    "petrolio": round(self.allocazione_petrolio * 100, 1),
                    "acciaio":  round(self.allocazione_acciaio  * 100, 1),
                },
            },
            "truppe": {
                "caserme": {
                    "infantry": self.truppe_caserme_infantry,
                    "rider":    self.truppe_caserme_rider,
                    "ranged":   self.truppe_caserme_ranged,
                    "engine":   self.truppe_caserme_engine,
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

    # Pre-calcolo flag caserme truppe (override istanza > default globale).
    # Non si può fare nella classe (nested classdef non chiude liberi).
    _truppe_ov_caserme = ((ovr.get("truppe_override") or {}).get("caserme") or {})
    def _resolve_caserma(nome_c: str, gdefault: bool) -> bool:
        v = _truppe_ov_caserme.get(nome_c)
        return bool(v) if v is not None else bool(gdefault)
    _truppe_caserme_resolved = {
        "infantry": _resolve_caserma("infantry", getattr(gcfg, "truppe_caserme_infantry", True)),
        "rider":    _resolve_caserma("rider",    getattr(gcfg, "truppe_caserme_rider",    True)),
        "ranged":   _resolve_caserma("ranged",   getattr(gcfg, "truppe_caserme_ranged",   True)),
        "engine":   _resolve_caserma("engine",   getattr(gcfg, "truppe_caserme_engine",   True)),
    }

    def _ovr(key, fallback):
        """dict.get che tratta None come chiave mancante.
        Pydantic IstanzaOverride salva campi Optional non settati come null
        esplicito nel JSON → `ovr.get(key, default)` ritorna None, non default.
        """
        v = ovr.get(key)
        return fallback if v is None else v

    # WU205 — allocazione raccolta per-istanza (override runtime > globale).
    # Normalizza a frazioni somma=1 (robusto a % o frazioni). Somma 0/assente
    # → None → fallback ai globali gcfg.allocazione_*. Retrocompatibile: nessun
    # override oggi ⇒ tutte le istanze usano il globale, comportamento invariato.
    _RIS_ALLOC = ("pomodoro", "legno", "petrolio", "acciaio")
    _alloc_ovr_raw = ovr.get("allocazione")
    _alloc_resolved = None
    if isinstance(_alloc_ovr_raw, dict):
        _av = {r: float(_alloc_ovr_raw.get(r, 0) or 0) for r in _RIS_ALLOC}
        _asum = sum(_av.values())
        if _asum > 0:
            _alloc_resolved = {r: _av[r] / _asum for r in _RIS_ALLOC}

    class _InstanceCfg:
        # ── Identità istanza ─────────────────────────────────────────────────
        # 08/05 — Regola architetturale: campi per-istanza configurabili
        # (truppe, max_squadre, livello, profilo, fascia_oraria) letti SOLO
        # da runtime (`runtime_overrides.json::istanze.<nome>.*`). Mai dal
        # static `instances.json` durante l'esecuzione: static serve solo per
        # bootstrap/reset. Bootstrap copia static→dynamic al primo avvio.
        # Default fallback: valore globale (`gcfg.*`) o costante neutra.
        # Vedi memoria `architecture_config_static_dynamic.md`.
        # `abilitata` invece resta dual-source (è anche nel filtro pre-tick di
        # `_carica_istanze_ciclo`).
        instance_name = nome
        truppe        = _ovr("truppe",      12000)
        max_squadre   = _ovr("max_squadre", 4)
        livello       = _ovr("livello",     gcfg.livello_nodo)
        # WU211 — livello edificio di trasporto (rifornimento): determina
        # capacità di trasporto per spedizione + tassa (tabella livelli 1-25).
        # Serve al calcolo deterministico dell'inviato (sostituisce l'OCR del
        # valore clampato, inaffidabile).
        # WU220 — fallback allo STATIC (instances.json), poi 20. Prima cadeva su
        # 20 costante: se il dynamic veniva azzerato (save dashboard con codice
        # vecchio → null) TUTTE le istanze finivano a 20, ignorando i livelli
        # reali (FAU_00=24, ecc.) → inviato sotto-registrato. Ora usa lo static.
        livello_trasporto = _ovr("livello_trasporto",
                                 ist.get("livello_trasporto", 20))
        profilo       = _ovr("profilo",     "full")
        fascia_oraria = _ovr("fascia_oraria", "")
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
        # LIVELLO_NODO usa il valore per-istanza (con override runtime) invece
        # del globale gcfg.livello_nodo. FAU_00 livello=7 → cerca nodi L7.
        LIVELLO_NODO         = livello
        # WU205 — override per-istanza (frazioni normalizzate) o fallback globale
        ALLOCAZIONE_POMODORO = _alloc_resolved["pomodoro"] if _alloc_resolved else gcfg.allocazione_pomodoro
        ALLOCAZIONE_LEGNO    = _alloc_resolved["legno"]    if _alloc_resolved else gcfg.allocazione_legno
        ALLOCAZIONE_PETROLIO = _alloc_resolved["petrolio"] if _alloc_resolved else gcfg.allocazione_petrolio
        ALLOCAZIONE_ACCIAIO  = _alloc_resolved["acciaio"]  if _alloc_resolved else gcfg.allocazione_acciaio
        # WU50 — modalità fuori territorio (per istanza).
        # Precedenza: override runtime > instances.json (default statico).
        RACCOLTA_FUORI_TERRITORIO_ABILITATA = bool(_ovr(
            "raccolta_fuori_territorio",
            ist.get("raccolta_fuori_territorio", False),
        ))
        # WU199 (09/07) — report_raccolta: chiamata diretta da
        # main.py::_leggi_risorse(), NON un task schedulato. Per-istanza
        # (non in instances.json — nuovo, nessun default statico) così da
        # poter testare su una sola istanza (es. FAU_00) prima di estendere.
        # Default OFF finché non abilitato esplicitamente da runtime_overrides.
        REPORT_RACCOLTA_ABILITATO  = bool(_ovr("report_raccolta_abilitato", False))
        # Fase di test corrente: limita l'operazione alla sola cancellazione
        # del report (nessuna lettura OCR) — vedi shared/report_raccolta.py.
        REPORT_RACCOLTA_SOLO_RESET = bool(_ovr("report_raccolta_solo_reset", True))
        # WU55 — Data collection OCR slot per analisi HOME vs MAPPA.
        # Flag globale (non per istanza) — attivato per 1 ciclo di analisi.
        RACCOLTA_OCR_DEBUG = bool(getattr(gcfg, "raccolta_ocr_debug", False))

        # ── Truppe — flag caserme (06/05) ──────────────────────────────────────
        # Schema: globali.truppe.caserme.{infantry,rider,ranged,engine}
        # Override istanza: istanze.<nome>.truppe_override.caserme (Optional[bool])
        # Precedenza: override istanza (se non null) > default globale.
        # I 4 valori risolti sono pre-calcolati a livello build_instance_cfg
        # (NON come metodo della classe — una nested classdef non chiude le
        # variabili libere come una def, vedi nota di scope sotto).
        TRUPPE_CASERMA_INFANTRY = _truppe_caserme_resolved["infantry"]
        TRUPPE_CASERMA_RIDER    = _truppe_caserme_resolved["rider"]
        TRUPPE_CASERMA_RANGED   = _truppe_caserme_resolved["ranged"]
        TRUPPE_CASERMA_ENGINE   = _truppe_caserme_resolved["engine"]

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
                "grafica_hq":            gcfg.task_grafica_hq,
                "pulizia_cache":         gcfg.task_pulizia_cache,
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
                f"livello={self.livello})"
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
