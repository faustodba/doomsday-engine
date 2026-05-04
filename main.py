# ==============================================================================
#  DOOMSDAY ENGINE V6 -- main.py
#
#  FIX 12/04/2026 sessione 1:
#    - _on_signal: guard if not stop_event.is_set() — evita log multipli Ctrl+C
#    - _thread_istanza: ruota FAU_XX.jsonl all'avvio (max 1 backup .bak)
#    - _build_ctx: passa log_fn a GameNavigator per log score template matching
#  FIX 12/04/2026 sessione 2:
#    - _nav_log: logger.info(msg, module="navigator") -> logger.info("navigator", msg)
#      StructuredLogger.info(module, message) — module e' il PRIMO argomento
#  STEP B 14/04/2026 — config_loader:
#    - Rimossa classe _Cfg hardcodata — sostituita da build_instance_cfg()
#    - Rimossa _carica_runtime() — sostituita da load_global()
#    - global_config.json letto ad ogni tick → modifiche dashboard senza restart
#    - _carica_istanze() invariata — legge ancora instances.json
#  22/04/2026 — --reset-config:
#    - Azzera sezione istanze di runtime_overrides.json ripristinando instances.json
#    - Mantiene invariata la sezione globali (task flags, rifornimento, etc.)
#  23/04/2026 — task_setup.json:
#    - _TASK_SETUP non più hardcoded: letto da config/task_setup.json
#    - Schema JSON: lista di oggetti con chiavi class/priority/interval_hours/schedule
#    - Letto ad ogni avvio del processo (non hot-reload — serve restart bot)
#    - Fallback hardcoded se il file è assente/corrotto (failsafe)
# ==============================================================================
from __future__ import annotations
import argparse, json, os, signal, sys, threading, time
from datetime import datetime, timezone
from typing import Optional

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
_OVERRIDES_PATH     = os.path.join(ROOT, "config", "runtime_overrides.json")
_GLOBAL_CONFIG_PATH = os.path.join(ROOT, "config", "global_config.json")
_INSTANCES_PATH     = os.path.join(ROOT, "config", "instances.json")
_TASK_SETUP_PATH    = os.path.join(ROOT, "config", "task_setup.json")
_CHECKPOINT_PATH    = os.path.join(ROOT, "last_checkpoint.json")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)  # CWD = project root, indipendentemente da dove main.py è lanciato

from core.orchestrator import Orchestrator
from core.task import TaskContext, TaskResult
from core.logger import StructuredLogger, get_logger, close_all_loggers
from core.state import InstanceState
from config.config_loader import (
    load_global, load_overrides, merge_config,
    build_instance_cfg, GlobalConfig,
)
from core import launcher as _launcher


def _import_tasks() -> dict:
    tasks = {}
    _catalogue = [
        ("tasks.raccolta",       "RaccoltaTask"),
        ("tasks.raccolta",       "RaccoltaChiusuraTask"),  # Issue #62 — chiusura tick
        ("tasks.raccolta_fast",  "RaccoltaFastTask"),      # WU57 — variante fast (sostituisce RaccoltaTask via tipologia=raccolta_fast)
        ("tasks.rifornimento",   "RifornimentoTask"),
        ("tasks.donazione",      "DonazioneTask"),
        ("tasks.main_mission",   "MainMissionTask"),
        ("tasks.zaino",          "ZainoTask"),
        ("tasks.vip",            "VipTask"),
        ("tasks.alleanza",       "AlleanzaTask"),
        ("tasks.messaggi",       "MessaggiTask"),
        ("tasks.arena",          "ArenaTask"),
        ("tasks.arena_mercato",  "ArenaMercatoTask"),
        ("tasks.district_showdown", "DistrictShowdownTask"),
        ("tasks.boost",          "BoostTask"),
        ("tasks.truppe",         "TruppeTask"),
        ("tasks.store",          "StoreTask"),
        ("tasks.radar",          "RadarTask"),
        ("tasks.radar_census",   "RadarCensusTask"),
    ]
    for module_path, class_name in _catalogue:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            tasks[class_name] = getattr(mod, class_name)
        except (ImportError, AttributeError) as exc:
            print(f"  [WARN] Task non disponibile: {class_name} ({exc})")
    return tasks


def _carica_istanze(filtro=None) -> list[dict]:
    path = _INSTANCES_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze = json.load(f)
    except FileNotFoundError:
        print(f"  [WARN] {path} non trovato"); return []
    except json.JSONDecodeError as exc:
        print(f"  [ERRORE] {path}: {exc}"); return []
    istanze = [i for i in istanze if i.get("abilitata", False)]
    if filtro:
        istanze = [i for i in istanze if i.get("nome") in filtro]
        if not istanze:
            print(f"  [WARN] Nessuna istanza trovata per: {filtro}")
    return istanze


def _carica_istanze_ciclo(filtro=None) -> list[dict]:
    """
    Rilegge instances.json + runtime_overrides.json ad ogni ciclo.
    Merge: abilitata/truppe/tipologia/fascia_oraria da overrides
    sovrascrivono instances.json se presenti.
    Usata nel loop ciclo per recepire modifiche dashboard in tempo reale.
    """
    path = _INSTANCES_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze_base = json.load(f)
    except Exception as exc:
        _log("MAIN", f"[ERRORE] instances.json: {exc}")
        return []

    ov     = load_overrides(_OVERRIDES_PATH)
    ist_ov = ov.get("istanze", {})

    result = []
    for ist in istanze_base:
        nome   = ist.get("nome", "")
        if not nome:
            continue
        merged = dict(ist)
        override = ist_ov.get(nome, {})
        if "abilitata"    in override: merged["abilitata"]    = override["abilitata"]
        if "truppe"       in override: merged["truppe"]       = override["truppe"]
        if "tipologia"    in override: merged["profilo"]      = override["tipologia"]
        if "fascia_oraria" in override: merged["fascia_oraria"] = override["fascia_oraria"]
        if not merged.get("abilitata", True):
            continue
        result.append(merged)

    if filtro:
        result = [i for i in result if i.get("nome") in filtro]
        if not filtro or not result:
            _log("MAIN", f"[WARN] Nessuna istanza trovata per filtro: {filtro}")
    return result


# ---------------------------------------------------------------------------
# Task setup — scheduling e priorità
# ---------------------------------------------------------------------------

def _carica_task_setup() -> list[tuple]:
    """
    Carica la configurazione dei task da config/task_setup.json.
    Sostituisce _TASK_SETUP hardcodato — modificabile senza toccare main.py.
    Failsafe: se il file manca o è corrotto, il bot non si avvia (errore esplicito).
    """
    try:
        with open(_TASK_SETUP_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return [(r["class"], r["priority"], r["interval_hours"], r["schedule"]) for r in raw]
    except Exception as exc:
        print(f"[ERRORE] task_setup.json: {exc}")
        sys.exit(1)


# Caricato all'import del modulo — modifiche a task_setup.json richiedono restart.
_TASK_SETUP = _carica_task_setup()


# ---------------------------------------------------------------------------
# Cleanup emulator orfani
# ---------------------------------------------------------------------------
_MUMU_PROCESSI_KILL = [
    "MuMuManager.exe",       # CLI control
    "MuMuPlayer.exe",         # UI launcher (vecchia versione)
    "MuMuVMMSVC.exe",         # VM service
    "MuMuVMMHeadless.exe",    # VM hypervisor
    "MuMuNxMain.exe",         # UI player (versione nuova)
    "MuMuNxDevice.exe",       # istanze emulatore Android
    "adb.exe",                # server ADB
]


def _cleanup_globale_startup(log_fn=None) -> None:
    """
    Kill GLOBALE di tutti i processi MuMu+adb via `taskkill /F /IM`.
    Molto più rapido del loop `MuMuManager shutdown` per-istanza
    (~3s vs ~60s per 12 istanze).

    Usato sia all'avvio bot sia pre-ciclo (29/04/2026) — il kill secco
    è preferibile perché non dipende dal filtro `abilitata=True` delle
    istanze, quindi spazza via anche emulator orfani di istanze
    disabilitate (es. FauMorfeus) o di altri bot.

    MuMuPlayer UI viene rilanciato dal launcher (`avvia_player`) al
    primo avvio istanza del ciclo successivo.
    """
    import subprocess
    killed = []
    for proc in _MUMU_PROCESSI_KILL:
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/IM", proc, "/T"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                killed.append(proc)
        except Exception:
            pass
    if log_fn:
        log_fn(f"taskkill globale: killati {len(killed)}/{len(_MUMU_PROCESSI_KILL)} "
               f"processi ({', '.join(killed) if killed else 'nessuno'})")


def _cleanup_orfani_processi_startup(log_fn=None) -> None:
    """
    Kill processi cmd.exe + python.exe orfani da sessioni precedenti del bot,
    PRESERVANDO il bot corrente.

    Tipi di orfani gestiti:
      - cmd.exe con cmdline matching run_prod.bat o run_dashboard_prod.bat
        e PID diverso dal cmd parent del bot corrente
      - python.exe con cmdline 'main.py' e PID != current process

    Da chiamare all'avvio bot, DOPO _cleanup_globale_startup (MuMu),
    PRIMA del loop principale. Risolve il problema delle finestre cmd
    orfane accumulate (vedi WU19) e dei python.exe duplicati lasciati
    da kill brutali precedenti.

    Safe: usa CommandLine matching specifico, non killa altri python/cmd.
    """
    import subprocess
    import os as _os
    import json as _json

    current_pid = _os.getpid()
    parent_pid = None
    try:
        parent_pid = _os.getppid()
    except Exception:
        pass

    log = log_fn or (lambda _msg: None)

    # Helper: get processes via PowerShell WMI
    def _wmi_query(name: str, pattern: str) -> list[tuple[int, int, str]]:
        try:
            ps_cmd = (
                f"Get-WmiObject Win32_Process -Filter \"Name='{name}'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
                f"ForEach-Object {{ '{{0}}|{{1}}'.f($_.ProcessId, $_.ParentProcessId) }}"
            )
            # Usa formato JSON via PowerShell per evitare parsing fragile
            ps_cmd = (
                f"Get-WmiObject Win32_Process -Filter \"Name='{name}'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
                f"Select-Object ProcessId,ParentProcessId,CommandLine | "
                f"ConvertTo-Json -Compress"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return []
            data = _json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            return [(int(d["ProcessId"]), int(d.get("ParentProcessId") or 0),
                     str(d.get("CommandLine") or "")) for d in data]
        except Exception as exc:
            log(f"[CLEANUP-ORFANI] WMI query {name} errore: {exc}")
            return []

    killed_cmd = []
    killed_py = []

    # 1. cmd.exe orfani con cmdline run_prod.bat o run_dashboard_prod.bat
    for pattern in ("run_prod.bat", "run_dashboard_prod.bat"):
        for pid, ppid, cmdline in _wmi_query("cmd.exe", pattern):
            if pid in (current_pid, parent_pid):
                continue
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
                killed_cmd.append(pid)
            except Exception:
                pass

    # 2. python.exe orfani con cmdline 'main.py' (NON il bot corrente)
    for pid, ppid, cmdline in _wmi_query("python.exe", "main.py"):
        if pid == current_pid:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
            killed_py.append(pid)
        except Exception:
            pass

    log(f"cleanup orfani: cmd killed={len(killed_cmd)} {killed_cmd if killed_cmd else ''} | "
        f"python killed={len(killed_py)} {killed_py if killed_py else ''} | "
        f"current_pid={current_pid} parent={parent_pid}")


def _cleanup_tutti_emulator(istanze: list[dict], dry_run: bool) -> None:
    """
    Kill SECCO pre-ciclo di TUTTI i processi MuMu/adb via taskkill globale.

    Invocato all'inizio di ogni ciclo (prima del for istanze).

    29/04/2026 — sostituito loop `reset_istanza` per-istanza (che iterava
    SOLO le istanze in `istanze_ciclo`, già filtrate su `abilitata=True`)
    con il kill globale `_cleanup_globale_startup`. Motivazione: istanze
    disabilitate (es. FauMorfeus indice 11) non venivano spente, lasciando
    emulator orfani in vita. Il kill secco copre TUTTO indipendentemente
    dai flag dashboard.

    Effetti:
      - taskkill /F /IM su MuMuPlayer + MuMuVMMHeadless + MuMuNxMain +
        MuMuNxDevice + adb.exe (con /T per child processes)
      - MuMuPlayer UI verrà rilanciato dal launcher al primo avvio istanza
        (avvia_player gestisce process not running)

    Argomento `istanze` mantenuto per signature compat (non usato).
    """
    if dry_run:
        return
    _cleanup_globale_startup(lambda msg: _log("MAIN", msg))


# ---------------------------------------------------------------------------
# Reset configurazione
# ---------------------------------------------------------------------------
def _reset_config() -> None:
    """
    --reset-config: ripristina la sezione istanze di runtime_overrides.json
    dai valori base di instances.json.

    Comportamento:
      - Legge instances.json — fonte di verità statica
      - Per ogni istanza crea un override con i soli campi modificabili dalla dashboard:
        abilitata, truppe, tipologia (profilo), fascia_oraria
      - Sovrascrive SOLO la sezione "istanze" di runtime_overrides.json
      - Mantiene invariata la sezione "globali" (task flags, rifornimento, etc.)
      - Scrittura atomica (tmp + os.replace)
    """
    print("[RESET] Reset configurazione istanze da instances.json...")

    # Leggi instances.json
    try:
        with open(_INSTANCES_PATH, encoding="utf-8") as f:
            istanze = json.load(f)
    except Exception as exc:
        print(f"[RESET] ERRORE lettura instances.json: {exc}")
        sys.exit(1)

    # Leggi runtime_overrides.json esistente (per preservare globali)
    try:
        with open(_OVERRIDES_PATH, encoding="utf-8") as f:
            overrides = json.load(f)
    except Exception:
        overrides = {}

    # Ricostruisci sezione istanze dai valori base di instances.json
    nuove_istanze = {}
    for ist in istanze:
        nome = ist.get("nome", "")
        if not nome:
            continue
        nuove_istanze[nome] = {
            "abilitata":    ist.get("abilitata", True),
            "truppe":       ist.get("truppe", 0),
            "tipologia":    ist.get("profilo", "full"),
            "fascia_oraria": ist.get("fascia_oraria", ""),
        }
        print(f"[RESET]   {nome}: abilitata={nuove_istanze[nome]['abilitata']} "
              f"profilo={nuove_istanze[nome]['tipologia']}")

    # Mantieni globali, sostituisci solo istanze
    overrides["istanze"] = nuove_istanze

    # Scrittura atomica
    tmp = _OVERRIDES_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _OVERRIDES_PATH)
        print(f"[RESET] runtime_overrides.json aggiornato — {len(nuove_istanze)} istanze ripristinate.")
    except Exception as exc:
        print(f"[RESET] ERRORE scrittura runtime_overrides.json: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Checkpoint resume — last_checkpoint.json
# ---------------------------------------------------------------------------
def _scrivi_checkpoint(ciclo: int, istanza: str) -> None:
    """Scrive last_checkpoint.json prima di avviare ogni istanza."""
    try:
        tmp = _CHECKPOINT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "ciclo":   ciclo,
                "istanza": istanza,
                "ts":      datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }, f, indent=2)
        os.replace(tmp, _CHECKPOINT_PATH)
    except Exception as exc:
        _log("MAIN", f"[WARN] checkpoint: {exc}")


def _cancella_checkpoint() -> None:
    """Cancella last_checkpoint.json a fine ciclo completato."""
    try:
        if os.path.exists(_CHECKPOINT_PATH):
            os.remove(_CHECKPOINT_PATH)
    except Exception as exc:
        _log("MAIN", f"[WARN] cancella checkpoint: {exc}")


def _leggi_checkpoint() -> Optional[dict]:
    """Legge last_checkpoint.json. None se non esiste o corrotto."""
    try:
        with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _prompt_resume(cp: dict) -> Optional[str]:
    """
    Mostra prompt interattivo se esiste un checkpoint.
    Restituisce nome istanza da cui riprendere, o None per ciclo normale.
    """
    istanza = cp.get("istanza", "?")
    ciclo   = cp.get("ciclo", "?")
    ts      = cp.get("ts", "?")
    print()
    print(f"  ┌─────────────────────────────────────────────────┐")
    print(f"  │  RESUME DISPONIBILE                             │")
    print(f"  │  Ultimo ciclo interrotto: ciclo {ciclo} — {istanza:<12}│")
    print(f"  │  Timestamp: {ts:<36}│")
    print(f"  └─────────────────────────────────────────────────┘")
    try:
        risposta = input(f"  Riprendere da {istanza}? [S/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        risposta = "n"
    if risposta in ("", "s", "si", "y", "yes"):
        return istanza
    return None


def _prompt_configurazione(auto_runtime: bool = False, auto_reset: bool = False) -> bool:
    """
    Chiede all'utente quale configurazione usare all'avvio.
    Restituisce True = usa runtime_overrides, False = reset a instances.json.
    auto_runtime: --use-runtime flag, accetta automaticamente runtime.
    auto_reset:   --reset-config flag, accetta automaticamente reset.
    """
    if auto_reset:
        return False
    if auto_runtime:
        return True
    print()
    print(f"  ┌─────────────────────────────────────────────────┐")
    print(f"  │  CONFIGURAZIONE ISTANZE                         │")
    print(f"  │  [1] Usa configurazione runtime (ultima salvata)│")
    print(f"  │  [2] Reset a configurazione statica             │")
    print(f"  │      (instances.json — ignora override)         │")
    print(f"  └─────────────────────────────────────────────────┘")
    try:
        risposta = input("  Scelta [1/2]: ").strip()
    except (EOFError, KeyboardInterrupt):
        risposta = "1"
    if risposta == "2":
        return False
    return True


# ---------------------------------------------------------------------------
# Stato globale engine
# ---------------------------------------------------------------------------
_engine_stato: dict = {"version":"v6","ts":"","uptime_s":0,"ciclo":0,"stato":"idle","istanze":{},"storico":[]}
_engine_lock = threading.Lock()
_t_avvio = time.time()
_MAX_STORICO = 200


def _aggiorna_stato_istanza(nome: str, update: dict) -> None:
    with _engine_lock:
        if nome not in _engine_stato["istanze"]:
            _engine_stato["istanze"][nome] = {"stato":"idle","task_corrente":None,"task_eseguiti":{},"ultimo_task":None,"scheduler":{},"errori":0,"porta":0}
        _engine_stato["istanze"][nome].update(update)


def _aggiungi_storico(entry: dict) -> None:
    with _engine_lock:
        _engine_stato["storico"].append(entry)
        if len(_engine_stato["storico"]) > _MAX_STORICO:
            _engine_stato["storico"] = _engine_stato["storico"][-_MAX_STORICO:]


def _scrivi_status_json() -> None:
    path = os.path.join(ROOT, "engine_status.json")
    with _engine_lock:
        snapshot = json.loads(json.dumps(_engine_stato))
    snapshot["ts"]       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    snapshot["uptime_s"] = int(time.time() - _t_avvio)
    snapshot["stato"]    = _stato_globale()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        # Retry os.replace — su Windows la dashboard uvicorn può tenere un
        # handle di lettura aperto momentaneamente: il replace fallisce con
        # WinError 5 anche se il processo sta solo leggendo. Backoff corto.
        last_exc = None
        for i in range(5):
            try:
                os.replace(tmp, path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.1 * (i + 1))  # 0.1, 0.2, 0.3, 0.4, 0.5s
        if last_exc is not None:
            raise last_exc
    except Exception as exc:
        print(f"  [WARN] engine_status.json: {exc}")
        # Pulizia residua del tmp se ancora presente
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _stato_globale() -> str:
    with _engine_lock:
        stati = [v.get("stato","idle") for v in _engine_stato["istanze"].values()]
    if any(s == "running" for s in stati): return "running"
    if any(s == "waiting" for s in stati): return "waiting"
    return "idle"


# ---------------------------------------------------------------------------
# Log bot.log
# ---------------------------------------------------------------------------
_log_lock = threading.Lock()
_LOG_PATH = os.path.join(ROOT, "bot.log")


def _log(nome: str, msg: str) -> None:
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {nome} {msg}"
    with _log_lock:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    print(line)


# ---------------------------------------------------------------------------
# Build TaskContext
# ---------------------------------------------------------------------------
def _build_ctx(ist: dict, gcfg, dry_run: bool, ist_overrides=None) -> TaskContext:
    """
    Costruisce il TaskContext per un'istanza.
    gcfg: GlobalConfig da load_global() — letto ad ogni tick.
    ist_overrides: dict opzionale con override per-istanza da runtime_overrides.json.
    """
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    cfg    = build_instance_cfg(ist, gcfg, overrides=ist_overrides or {})
    logger = get_logger(nome, log_dir=os.path.join(ROOT, "logs"), console=True)
    state  = InstanceState.load(nome, state_dir=os.path.join(ROOT, "state"))

    if dry_run:
        try:
            from core.device import FakeDevice
            device = FakeDevice(name=nome, index=ist.get("indice", 0))
        except ImportError:
            device = None
    else:
        try:
            from core.device import AdbDevice
            device = AdbDevice(host="127.0.0.1", port=porta)
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] AdbDevice: {exc}"); device = None

    matcher = None
    if not dry_run:
        try:
            from shared.template_matcher import get_matcher
            matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] TemplateMatcher: {exc}")

    navigator = None
    if not dry_run:
        try:
            from core.navigator import GameNavigator

            def _nav_log(msg: str) -> None:
                logger.info("navigator", msg)

            navigator = GameNavigator(device=device, matcher=matcher, log_fn=_nav_log)
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] GameNavigator: {exc}")

    return TaskContext(
        instance_name=nome,
        config=cfg,
        state=state,
        log=logger,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


class _TaskWrapper:
    def __init__(self, task, schedule_type: str, interval_hours: float):
        self._task           = task
        self._schedule_type  = schedule_type
        self._interval_hours = interval_hours

    @property
    def schedule_type(self) -> str:
        return self._schedule_type

    @property
    def interval_hours(self) -> float:
        return self._interval_hours

    def __getattr__(self, name):
        return getattr(self._task, name)


# ---------------------------------------------------------------------------
# Thread istanza
# ---------------------------------------------------------------------------

_contatori: dict[str, dict[str, int]] = {}
_contatori_lock = threading.Lock()

# WU89-Step4 — Skip Predictor: state per-istanza in-memory (guardrail tracking).
# Persiste finché il bot è vivo, reset su restart (accettabile). Vedi
# core.skip_predictor.IstanzaSkipState per i campi.
_predictor_states: dict = {}
_predictor_decisions_lock = threading.Lock()


def _append_predictor_decision(nome: str, decision, mode: str, applied: bool) -> None:
    """Append decisione predictor a data/predictor_decisions.jsonl (best-effort).

    Schema:
      {ts, instance, mode (LIVE|SHADOW), should_skip, reason, score, signals,
       growth_phase, guardrail, applied}

    `applied=True` solo se decisione `should_skip=True` AND mode=LIVE AND
    guardrail non ha bloccato. Alimenta Step 5 (dashboard precision/recall).
    Errore I/O = silent skip — il predictor non rompe il bot.
    """
    try:
        from datetime import datetime, timezone
        path = os.path.join(ROOT, "data", "predictor_decisions.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            "ts":           datetime.now(timezone.utc).isoformat(),
            "instance":     nome,
            "mode":         mode,
            "should_skip":  bool(decision.should_skip),
            "reason":       decision.reason,
            "score":        round(float(decision.score), 3),
            "signals":      decision.signals or {},
            "growth_phase": bool(decision.growth_phase),
            "guardrail":    decision.guardrail_triggered,
            "applied":      bool(applied),
        }
        with _predictor_decisions_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _thread_istanza(ist, tasks_cls, dry_run):
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    # Ruota log JSONL istanza ad ogni avvio (max 1 backup .bak)
    _jsonl_path = os.path.join(ROOT, "logs", f"{nome}.jsonl")
    if os.path.exists(_jsonl_path):
        try:
            os.replace(_jsonl_path, _jsonl_path + ".bak")
        except Exception:
            pass

    _log(nome, f"Thread avviato -- porta ADB {porta}")
    _aggiorna_stato_istanza(nome, {"stato": "waiting", "porta": porta})

    # Hook metriche per-istanza: inizio tick
    _tick_start_wall = time.time()
    try:
        from core.istanza_metrics import inizia_tick
        inizia_tick(nome, cycle_id=int(_engine_stato.get("ciclo", 0) or 0))
    except Exception:
        pass

    with _contatori_lock:
        _contatori.setdefault(nome, {})

    _ov_raw     = load_overrides(_OVERRIDES_PATH)
    with open(_GLOBAL_CONFIG_PATH, encoding="utf-8") as _f:
        _gcfg_raw = json.load(_f)
    _merged_raw = merge_config(_gcfg_raw, _ov_raw)
    gcfg        = GlobalConfig._from_raw(_merged_raw)
    _ist_ov     = _merged_raw.get("_istanze_overrides", {}).get(nome, {})
    ctx         = _build_ctx(ist, gcfg, dry_run, ist_overrides=_ist_ov)
    orc  = Orchestrator(ctx)

    # Tipologia istanza: se "raccolta_only" registra SOLO RaccoltaTask,
    # altrimenti (full) registra tutti i task definiti in task_setup.json.
    _tipologia = (
        getattr(ctx.config, "tipologia", None)
        or getattr(ctx.config, "profilo", None)
        or "full"
    )
    _solo_raccolta = str(_tipologia) == "raccolta_only"
    _raccolta_fast = str(_tipologia) == "raccolta_fast"
    if _solo_raccolta:
        _log(nome, f"Tipologia={_tipologia} — registro solo RaccoltaTask")
    if _raccolta_fast:
        _log(nome, f"Tipologia={_tipologia} — RaccoltaFastTask sostituisce RaccoltaTask (altri task attivi)")

    for class_name, priority, interval_h, schedule in _carica_task_setup():
        if _solo_raccolta and class_name not in ("RaccoltaTask", "RaccoltaChiusuraTask"):
            continue
        # WU57 — runtime swap RaccoltaTask -> RaccoltaFastTask (priority/interval/schedule preservati)
        if _raccolta_fast and class_name == "RaccoltaTask":
            class_name = "RaccoltaFastTask"
        Cls = tasks_cls.get(class_name)
        if Cls is None:
            continue
        try:
            task    = Cls()
            wrapped = _TaskWrapper(task, schedule, interval_h)
            orc.register(wrapped, priority=priority)
        except Exception as exc:
            _log(nome, f"[WARN] Impossibile registrare {class_name}: {exc}")

    _log(nome, f"Orchestrator pronto -- {len(orc)} task: {orc.task_names()}")

    # ── Ripristino scheduling dal disco (restart-safe) ────────────────────
    try:
        ctx.state.schedule.restore_to_orchestrator(orc)
        _log(nome, f"Schedule ripristinato: {dict(ctx.state.schedule.timestamps)}")
    except Exception as exc:
        _log(nome, f"[WARN] Ripristino schedule: {exc}")

    _log_fn = lambda msg: _log(nome, msg)

    # ── WU89-Step4 — Skip Predictor hook (flag-driven) ────────────────────
    # Eseguito DOPO setup orchestrator e PRIMA dell'avvio MuMu (massimo saving:
    # evita boot+settings+attendi_home se l'istanza viene skippata).
    # Stati controllati da 2 flag in `globali`:
    #   - skip_predictor_enabled (default False) → no-op, bot invariato
    #   - skip_predictor_shadow_only (default True) → predict+log, no skip
    # Failsafe try/except: errore predictor non rompe il bot.
    if getattr(gcfg, "skip_predictor_enabled", False) and not dry_run:
        try:
            from core.skip_predictor import (
                predict, IstanzaSkipState, load_metrics_history,
                COOLDOWN_POST_RETRY_CICLI,
            )
            history    = load_metrics_history(nome, last_n=20)
            skip_state = _predictor_states.setdefault(nome, IstanzaSkipState())
            decision   = predict(nome, history, state=skip_state)
            shadow     = bool(getattr(gcfg, "skip_predictor_shadow_only", True))
            mode       = "SHADOW" if shadow else "LIVE"
            applied    = bool(decision.should_skip) and not shadow

            _log(nome,
                 f"[PREDICTOR-{mode}] should_skip={decision.should_skip} "
                 f"reason={decision.reason} score={decision.score:.2f}"
                 + (f" guardrail={decision.guardrail_triggered}"
                    if decision.guardrail_triggered else "")
                 + (f" growth_phase=True" if decision.growth_phase else ""))
            _append_predictor_decision(nome, decision, mode, applied)

            if applied:
                # Skip ciclo reale: aggiorna state, chiudi metriche, early return
                skip_state.last_skip_count_consec += 1
                skip_state.cicli_totali           += 1
                _log(nome,
                     f"[PREDICTOR-LIVE] SKIP CICLO — saving stimato boot+task "
                     f"~600s (consec={skip_state.last_skip_count_consec})")
                try:
                    from core.istanza_metrics import chiudi_tick
                    chiudi_tick(nome, outcome="skipped_by_predictor")
                except Exception:
                    pass
                _aggiorna_stato_istanza(nome, {
                    "stato": "idle",
                    "ultimo_task": {
                        "nome": "predictor_skip", "esito": "skipped",
                        "msg": f"reason={decision.reason}",
                        "ts": time.strftime("%H:%M:%S"), "durata_s": 0.0,
                    },
                })
                return
            else:
                # No skip: reset counter consecutivi, incrementa totali
                skip_state.last_skip_count_consec = 0
                skip_state.cicli_totali           += 1
                # Cooldown post-retry: reset se guardrail ha forzato un retry
                # (max_skip_consec o re_eval_periodic); altrimenti incrementa
                # con clamp a COOLDOWN per uscire dal blocco.
                gr = decision.guardrail_triggered or ""
                if "max_skip_consec" in gr or "re_eval_periodic" in gr:
                    skip_state.cicli_dall_ultimo_retry = 0
                elif skip_state.cicli_dall_ultimo_retry < COOLDOWN_POST_RETRY_CICLI:
                    skip_state.cicli_dall_ultimo_retry += 1
        except Exception as exc:
            _log(nome, f"[PREDICTOR] errore best-effort: {exc}")
            # Procede con flow normale anche su errore predictor

    # ── 1. Avvio istanza MuMu + attesa HOME ─────────────────────────
    if not dry_run:
        if not _launcher.avvia_istanza(ist, _log_fn):
            _log(nome, "[ERRORE] avvia_istanza() fallito")
            _aggiorna_stato_istanza(nome, {"stato": "idle"})
            return
        if not _launcher.attendi_home(ctx, _log_fn):
            _log(nome, "[ERRORE] attendi_home() fallito")
            _launcher.chiudi_istanza(ist, porta, _log_fn)
            _aggiorna_stato_istanza(nome, {"stato": "idle"})
            return

        # auto-WU10: chiusura definitiva banner eventi HOME post-stabilizzazione
        # → maggiore zona visibile (+45px) per i task successivi.
        try:
            from shared.ui_helpers import comprimi_banner_home
            comprimi_banner_home(ctx, _log_fn)
        except Exception as exc:
            _log(nome, f"[WARN] comprimi_banner_home: {exc}")

        # auto-WU14: snapshot risorse castello + chiusura sessione precedente
        # + apertura nuova sessione produzione. Le risorse top-bar sono lette
        # qui (HOME stabile, banner chiuso) per garantire massima accuratezza.
        # auto-WU25 (27/04): retry OCR per zone fallite + skip-on-fail.
        # Pre-fix: ocr_risorse single-shot → se 1 zona fallisce ritorna -1
        # per quella sola risorsa (es. legno=-1 osservato FAU_00 27/04).
        # Post-fix: ocr_risorse_robust (3 tentativi con merge zone valide)
        # + fallback a valore precedente se tutte le retry falliscono.
        try:
            from shared.ocr_helpers import ocr_risorse_robust
            from core.state import _ts_now
            ts_now = _ts_now()
            rd = ocr_risorse_robust(
                ctx.device, max_attempts=3, sleep_s=0.5,
                log_fn=lambda m: _log(nome, m),
            )
            # Skip-on-fail: per ogni risorsa con valore -1, usa l'ultimo
            # valore valido dalla precedente sessione (risorse_iniziali del
            # produzione_corrente non ancora chiuso).
            prev_corr = ctx.state.produzione_corrente
            prev_init = (prev_corr.risorse_iniziali if prev_corr else None) or {}
            risorse_now = {}
            for r in ("pomodoro", "legno", "acciaio", "petrolio"):
                v = getattr(rd, r)
                if v == -1:
                    fallback = prev_init.get(r, -1)
                    if fallback != -1:
                        risorse_now[r] = fallback
                        _log(nome,
                             f"[PROD-FALLBACK] {r} OCR fail → uso prec valore "
                             f"{fallback/1e6:.1f}M")
                    else:
                        risorse_now[r] = -1
                        _log(nome, f"[PROD-FALLBACK] {r} OCR fail e nessun prec valore")
                else:
                    risorse_now[r] = v

            _log(nome,
                 f"[PROD] risorse castello: pom={risorse_now['pomodoro']/1e6:.1f}M "
                 f"leg={risorse_now['legno']/1e6:.1f}M "
                 f"acc={risorse_now['acciaio']/1e6:.1f}M "
                 f"pet={risorse_now['petrolio']/1e6:.1f}M dia={rd.diamanti}")

            # Chiudi sessione precedente (se esiste) calcolando produzione
            # Issue #25 fix: passa rd.diamanti per calcolare delta diamanti
            chiusa = ctx.state.chiudi_sessione_e_calcola(risorse_now, ts_now,
                                                        diamanti_finali=rd.diamanti)
            if chiusa is not None:
                po = chiusa.produzione_oraria or {}
                _log(nome,
                     f"[PROD] sessione chiusa durata={chiusa.durata_sec or 0:.0f}s "
                     f"prod/h: pom={po.get('pomodoro',0):.0f} "
                     f"leg={po.get('legno',0):.0f} "
                     f"acc={po.get('acciaio',0):.0f} "
                     f"pet={po.get('petrolio',0):.0f}")

            # Apri nuova sessione
            ctx.state.apri_sessione(risorse_now, rd.diamanti, ts_now)
            _log(nome, f"[PROD] sessione aperta @ {ts_now}")

            # auto-WU20 (27/04 fix persistenza): salva state SUBITO,
            # prima del _build_ctx (line 774) che ricarica da disco e
            # wipe `produzione_corrente`/`produzione_storico` impostati.
            # Pre-fix: sessione_aperta loggata ma mai persistita →
            # storico sempre vuoto, dashboard "in attesa" permanente.
            try:
                ctx.state.save(state_dir=os.path.join(ROOT, "state"))
            except Exception as exc:
                _log(nome, f"[WARN] save state post-apri_sessione: {exc}")
        except Exception as exc:
            _log(nome, f"[WARN] produzione snapshot: {exc}")

    # ── 2. Rebuild context (rilegge config aggiornata) ───────────────
    _ov_raw     = load_overrides(_OVERRIDES_PATH)
    with open(_GLOBAL_CONFIG_PATH, encoding="utf-8") as _f:
        _gcfg_raw = json.load(_f)
    _merged_raw = merge_config(_gcfg_raw, _ov_raw)
    gcfg        = GlobalConfig._from_raw(_merged_raw)
    _ist_ov     = _merged_raw.get("_istanze_overrides", {}).get(nome, {})
    ctx         = _build_ctx(ist, gcfg, dry_run, ist_overrides=_ist_ov)
    orc._ctx = ctx

    # ── 3. Tick ──────────────────────────────────────────────────────
    _aggiorna_stato_istanza(nome, {"stato": "running", "scheduler": _scheduler_prossimi(orc)})
    _log(nome, f"Tick -- {orc.n_dovuti()} task dovuti su {len(orc)} registrati")

    _tick_start_ts = time.time()
    results = orc.tick()

    # auto-WU14: incrementa tasks_count solo per task con last_run >= tick_start
    # (cioè eseguiti effettivamente in QUESTO tick, non quelli storici)
    try:
        if ctx.state and ctx.state.produzione_corrente and results:
            for entry in orc._entries:
                if entry.last_run and entry.last_run >= _tick_start_ts:
                    tname = entry.task.name() if callable(entry.task.name) else entry.task.name
                    ctx.state.produzione_corrente.incrementa_task(tname, 1)
    except Exception as exc:
        _log(nome, f"[PROD] hook tasks_count: {exc}")

    with _contatori_lock:
        cnts = _contatori[nome]

    ultimo = None
    if results:
        # WU87 — pre-fix: solo l'ultimo task (sempre raccolta_chiusura priority 200)
        # finiva nello storico engine_status. Storico events dashboard mostrava
        # quindi solo raccolta_chiusura con durate 0.0s, gli altri task invisibili.
        # Post-fix: itera TUTTE le entries del tick corrente (last_run >= tick_start)
        # e scrivi 1 record storico per ognuna in ordine cronologico.
        entries_tick = sorted(
            [e for e in orc._entries
             if e.last_run and e.last_run >= _tick_start_ts and e.last_result],
            key=lambda e: e.last_run,
        )
        for entry in entries_tick:
            lr    = entry.last_result
            tname = entry.task.name() if callable(entry.task.name) else entry.task.name
            cnts[tname] = cnts.get(tname, 0) + 1
            ts_str = datetime.fromtimestamp(entry.last_run).strftime("%H:%M:%S")
            esito  = "ok" if lr.success else "err"
            durata = round(float(getattr(entry, "last_duration_s", 0.0) or 0.0), 1)
            ultimo = {"nome": tname, "esito": esito,
                      "msg": (lr.message or "")[:120], "ts": ts_str, "durata_s": durata}
            _aggiungi_storico({"istanza": nome, "task": tname,
                               "esito": esito,
                               "ts": ts_str,
                               "durata_s": durata, "msg": (lr.message or "")[:80]})

    errori = sum(1 for r in results if not r.success)
    _aggiorna_stato_istanza(nome, {"stato": "waiting", "task_eseguiti": dict(cnts),
                                   "ultimo_task": ultimo, "scheduler": _scheduler_prossimi(orc), "errori": errori})
    try:
        ctx.state.schedule.update_from_stato(orc.stato())
        ctx.state.save(state_dir=os.path.join(ROOT, "state"))
    except Exception as exc:
        _log(nome, f"[WARN] save state: {exc}")

    # Issue #56 — flag adb_unhealthy: orchestrator ha abortito il tick per
    # cascata ADB persistente (reconnect cosmetico). Logga l'evento per
    # tracciamento; la chiusura istanza avviene comunque sotto.
    adb_unhealthy = bool(getattr(ctx, "adb_unhealthy", False))
    if adb_unhealthy:
        _log(nome, f"[ERRORE] reset emergenziale ADB unhealthy — tick abortito ({len(results)} task eseguiti)")
        _aggiorna_stato_istanza(nome, {"stato": "waiting", "ultimo_errore": "adb_unhealthy"})
    else:
        _log(nome, f"Tick completato ({len(results)} eseguiti)")

    # ── 4. Chiusura istanza MuMu ────────────────────────────────────
    if not dry_run:
        _launcher.chiudi_istanza(ist, porta, _log_fn)

    _aggiorna_stato_istanza(nome, {"stato": "idle"})
    _log(nome, "Thread completato.")

    # Hook metriche per-istanza: fine tick (flush record JSONL)
    try:
        from core.istanza_metrics import (
            chiudi_tick, imposta_task_duration,
        )
        # Propaga durate task dall'orchestrator
        for entry in orc._entries:
            if (entry.last_run and entry.last_run >= _tick_start_ts
                    and getattr(entry, "last_duration_s", 0) > 0):
                tname = entry.task.name() if callable(entry.task.name) else entry.task.name
                imposta_task_duration(nome, tname, entry.last_duration_s)
        # Outcome del tick (cascade ADB ha priorità)
        _tick_outcome = "cascade" if adb_unhealthy else "ok"
        _tick_total = round(time.time() - _tick_start_wall, 1)
        chiudi_tick(nome, outcome=_tick_outcome, tick_total_s=_tick_total)
    except Exception as exc:
        _log(nome, f"[WARN] istanza_metrics flush: {exc}")


def _scheduler_prossimi(orc) -> dict:
    out = {}
    for entry in orc._entries:
        tname = entry.task.name() if callable(entry.task.name) else entry.task.name
        if entry.last_run == 0.0:
            out[tname] = "adesso"; continue
        if entry.task.schedule_type == "daily": continue
        sec = max(0.0, entry.task.interval_hours * 3600 - (time.time() - entry.last_run))
        out[tname] = datetime.fromtimestamp(time.time() + sec).strftime("%H:%M:%S")
    return out


# ---------------------------------------------------------------------------
# Status writer
# ---------------------------------------------------------------------------
def _status_writer_loop(stop_event, interval=5):
    while not stop_event.is_set():
        _scrivi_status_json()
        for _ in range(interval):
            if stop_event.is_set(): break
            time.sleep(1)
    _scrivi_status_json()


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------
def _parse_args():
    p = argparse.ArgumentParser(description="Doomsday Engine V6 -- Bot farm MuMu",
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--istanze", default=None)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--tick-sleep", type=int, default=-1,
                   help="Secondi di pausa tra un ciclo completo di istanze e il successivo. "
                        "Default -1 = leggi da config (globali.sistema.tick_sleep_min × 60). "
                        "Override esplicito da CLI per test/debug.")
    p.add_argument("--no-dashboard", action="store_true", default=False)
    p.add_argument("--status-interval", type=int, default=5)
    p.add_argument("--reset-config", action="store_true", default=False,
                   help="Ripristina runtime_overrides.json (sezione istanze) dai valori base "
                        "di instances.json. Mantiene invariati i globali (task flags, etc.). "
                        "Il bot si avvia normalmente dopo il reset.")
    p.add_argument("--resume", action="store_true", default=False,
                   help="Riprende automaticamente dall'ultima istanza interrotta "
                        "senza prompt interattivo.")
    p.add_argument("--use-runtime", action="store_true", default=False,
                   help="Usa runtime_overrides.json senza prompt interattivo.")
    return p.parse_args()


def main():
    args = _parse_args()

    # ── Prompt configurazione (sempre all'avvio) ─────────────
    usa_runtime = _prompt_configurazione(
        auto_runtime=args.use_runtime,
        auto_reset=args.reset_config,
    )
    if not usa_runtime:
        _reset_config()

    if os.path.exists(_LOG_PATH):
        try: os.replace(_LOG_PATH, _LOG_PATH + ".bak")
        except Exception: pass

    _log("MAIN", "=" * 55)
    _log("MAIN", "DOOMSDAY ENGINE V6")

    # Risolve tick_sleep: priorità CLI esplicito > config (sistema.tick_sleep_min × 60)
    # > default 300s. Bug storico (03/05): il bot ignorava il config e usava
    # solo CLI, causando dashboard tick=5min vs bot reale 60s.
    if args.tick_sleep < 0:
        try:
            with open(_GLOBAL_CONFIG_PATH, encoding="utf-8") as _f:
                _gcfg_raw = json.load(_f)
            _ov_raw_main = load_overrides(_OVERRIDES_PATH)
            _merged_main = merge_config(_gcfg_raw, _ov_raw_main)
            _tick_cfg = (_merged_main.get("sistema") or {}).get("tick_sleep")
            if isinstance(_tick_cfg, int) and _tick_cfg >= 0:
                args.tick_sleep = _tick_cfg
                _log("MAIN", f"tick_sleep da config: {args.tick_sleep}s "
                             f"(={args.tick_sleep/60:.1f}min)")
            else:
                args.tick_sleep = 300
                _log("MAIN", f"tick_sleep da default: {args.tick_sleep}s (config mancante)")
        except Exception as _e:
            args.tick_sleep = 300
            _log("MAIN", f"tick_sleep da default: 300s (errore lettura config: {_e})")
    else:
        _log("MAIN", f"tick_sleep CLI esplicito: {args.tick_sleep}s")

    _log("MAIN", f"Root: {ROOT}  dry-run: {args.dry_run}  tick-sleep: {args.tick_sleep}s")
    _log("MAIN", f"Task setup: {len(_TASK_SETUP)} task da {_TASK_SETUP_PATH}")
    if usa_runtime:
        _log("MAIN", "Configurazione runtime mantenuta")
    else:
        _log("MAIN", "Config istanze ripristinata da instances.json")

    filtro  = [n.strip() for n in args.istanze.split(",")] if args.istanze else None
    istanze = _carica_istanze(filtro=filtro)
    if not istanze:
        _log("MAIN", "Nessuna istanza -- uscita."); sys.exit(1)
    _log("MAIN", f"Istanze: {[i['nome'] for i in istanze]}")
    _log("MAIN", f"Modalità: SEQUENZIALE — ciclo {[i['nome'] for i in istanze]} → sleep {args.tick_sleep}s → ripeti")

    tasks_cls = _import_tasks()
    _log("MAIN", f"Task: {list(tasks_cls.keys())}")

    if not args.no_dashboard:
        _log("MAIN", "Dashboard disponibile su http://localhost:8765 "
                     "(avvia separatamente con: uvicorn dashboard.app:app --host 0.0.0.0 --port 8765)")

    stop_event = threading.Event()

    def _on_signal(sig, frame):
        if not stop_event.is_set():
            _log("MAIN", f"Segnale {sig} -- stop...")
            stop_event.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    threading.Thread(target=_status_writer_loop, args=(stop_event, args.status_interval),
                     name="StatusWriter", daemon=True).start()

    # WU41 — telemetria live writer (rolling 24h, refresh 60s)
    # Failsafe: se core.telemetry non importa per qualche motivo, il bot
    # prosegue normalmente — la telemetria è opzionale.
    try:
        from core.telemetry import live_writer_loop
        threading.Thread(
            target=live_writer_loop,
            args=(stop_event, 60),
            name="LiveTelemetry",
            daemon=True,
        ).start()
        _log("MAIN", "Telemetria live writer avviato (refresh 60s)")
    except Exception as exc:
        _log("MAIN", f"[WARN] live writer non avviato: {exc}")

    # Cleanup emulator orfani all'avvio (kill residui di sessioni precedenti).
    # Usa taskkill globale (~3s) invece del loop MuMuManager shutdown (~60s):
    # all'avvio non ci sono istanze "buone" da preservare, kill brutale OK.
    _log("MAIN", "Cleanup emulator orfani (startup) — taskkill globale")
    if not args.dry_run:
        _cleanup_globale_startup(lambda msg: _log("MAIN", msg))

    # auto-WU22: cleanup processi orfani cmd.exe + python.exe da sessioni
    # precedenti (finestre orfane accumulate, python duplicati). Preserva
    # bot corrente via PID matching. Risolve issue WU19 e analoghi.
    _log("MAIN", "Cleanup processi orfani (cmd/python sessioni precedenti)")
    if not args.dry_run:
        try:
            _cleanup_orfani_processi_startup(lambda msg: _log("MAIN", msg))
        except Exception as exc:
            _log("MAIN", f"[WARN] cleanup orfani errore: {exc}")

    # ── Resume checkpoint ────────────────────────────────────
    resume_da: Optional[str] = None
    cp = _leggi_checkpoint()
    if cp:
        if args.resume:
            # --resume: accetta automaticamente senza prompt
            resume_da = cp.get("istanza")
            _log("MAIN", f"Resume automatico da {resume_da} (ciclo {cp.get('ciclo')})")
        else:
            # Prompt interattivo
            resume_da = _prompt_resume(cp)
            if resume_da:
                _log("MAIN", f"Resume confermato da {resume_da}")
            else:
                _log("MAIN", "Resume rifiutato — ciclo normale da inizio")

    SLEEP_CICLO = args.tick_sleep

    ciclo = 0
    while not stop_event.is_set():
        ciclo += 1
        _log("MAIN", f"{'=' * 55}")

        # Rilettura dinamica istanze (recepisce modifiche dashboard pre-ciclo)
        istanze_ciclo = _carica_istanze_ciclo(filtro=filtro)
        _log("MAIN", f"CICLO {ciclo} — {[i['nome'] for i in istanze_ciclo]}")

        # WU46 — Telemetria cicli persistenti (Issue #53 estesa).
        # Scrive data/telemetry/cicli.json con start/end/durata per ciclo +
        # per istanza. Failsafe: telemetria silenziosa.
        try:
            from core.telemetry import record_cicle_start
            record_cicle_start(ciclo)
        except Exception:
            pass

        # Cleanup orfani a inizio ciclo (robustezza contro crash mid-ciclo)
        _log("MAIN", f"Cleanup emulator orfani (pre-ciclo) — {len(istanze_ciclo)} istanze")
        _cleanup_tutti_emulator(istanze_ciclo, args.dry_run)

        # Flag resume attivo solo al primo ciclo
        _resume_attivo = resume_da is not None and ciclo == 1
        _resume_trovato = False

        for ist in istanze_ciclo:
            if stop_event.is_set():
                break

            nome = ist["nome"]

            # WU51 — modalità manutenzione: pausa tra istanze se file flag
            # data/maintenance.flag presente. Mai interrompe tick in corso.
            # Polling 5s, riprende automatico quando flag rimosso.
            try:
                from core.maintenance import wait_if_maintenance
                if wait_if_maintenance(stop_event, lambda m: _log("MAIN", m)):
                    break  # stop_event ricevuto durante manutenzione
            except Exception as exc:
                _log("MAIN", f"[WARN] check maintenance fallito: {exc}")

            # Skip istanze precedenti al punto di resume (solo ciclo 1)
            if _resume_attivo and not _resume_trovato:
                if nome != resume_da:
                    _log("MAIN", f"--- Skip {nome} (resume) ---")
                    continue
                else:
                    _resume_trovato = True  # trovata — da qui in poi esegue normalmente

            # Hot-check abilitata: rileggi override mid-ciclo per recepire
            # modifiche dashboard prima di avviare l'istanza (altrimenti il
            # flag prende effetto solo al prossimo ciclo, fino a ~2h di ritardo).
            try:
                _ov_ist = load_overrides(_OVERRIDES_PATH).get("istanze", {}).get(nome, {})
                if "abilitata" in _ov_ist and not _ov_ist["abilitata"]:
                    _log("MAIN", f"--- Skip {nome} (abilitata=False runtime) ---")
                    continue
            except Exception as exc:
                _log("MAIN", f"[WARN] hot-check abilitata {nome}: {exc}")

            # Scrivi checkpoint PRIMA di avviare
            _scrivi_checkpoint(ciclo, nome)

            _log("MAIN", f"--- Avvio istanza {nome} ---")
            if not args.dry_run:
                _launcher.reset_istanza(ist, lambda msg: _log(nome, msg))

            # WU46 — telemetria: registro start tick istanza
            try:
                from core.telemetry import record_istanza_tick_start
                record_istanza_tick_start(nome)
            except Exception:
                pass

            t = threading.Thread(
                target=_thread_istanza,
                args=(ist, tasks_cls, args.dry_run),
                name=nome, daemon=True
            )
            t.start()
            t.join()

            # WU46 — telemetria: registro end tick istanza
            try:
                from core.telemetry import record_istanza_tick_end
                record_istanza_tick_end(nome, esito="ok")
            except Exception:
                pass

            _log("MAIN", f"--- Istanza {nome} completata ---")

        # Fine ciclo — cancella checkpoint solo se completato senza interruzioni
        if not stop_event.is_set():
            _cancella_checkpoint()

        if stop_event.is_set():
            break

        # WU46 — telemetria: registro end ciclo
        try:
            from core.telemetry import record_cicle_end
            record_cicle_end(ciclo)
        except Exception:
            pass

        _log("MAIN", f"Ciclo {ciclo} completato — sleep {SLEEP_CICLO//60} minuti")
        for _ in range(SLEEP_CICLO):
            if stop_event.is_set(): break
            time.sleep(1)

    close_all_loggers()
    _log("MAIN", "Engine fermato.")


if __name__ == "__main__":
    main()
