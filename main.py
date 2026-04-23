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
        ("tasks.rifornimento",   "RifornimentoTask"),
        ("tasks.zaino",          "ZainoTask"),
        ("tasks.vip",            "VipTask"),
        ("tasks.alleanza",       "AlleanzaTask"),
        ("tasks.messaggi",       "MessaggiTask"),
        ("tasks.arena",          "ArenaTask"),
        ("tasks.arena_mercato",  "ArenaMercatoTask"),
        ("tasks.boost",          "BoostTask"),
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
def _cleanup_tutti_emulator(istanze: list[dict], dry_run: bool) -> None:
    """
    Chiude tutti gli emulator MuMu configurati (reset_istanza per ogni istanza).

    Invocato:
      - all'avvio del bot (prima del primo ciclo)
      - all'inizio di ogni ciclo (prima del for istanze)

    Motivazione: garantisce che ogni ciclo parta da uno stato MuMu pulito,
    eliminando processi orfani rimasti da:
      - kill unclean del bot precedente (SIGKILL mid-ciclo)
      - crash/hang di un'istanza nel ciclo precedente
      - esecuzione parallela con altro bot (dry-run orfano, ecc.)

    Failsafe: ogni reset è protetto da try/except — un'istanza che fallisce
    il reset non blocca le altre.
    """
    if dry_run:
        return
    for ist in istanze:
        nome = ist.get("nome", "?")
        try:
            _launcher.reset_istanza(ist, lambda msg, n=nome: _log(n, msg))
        except Exception as exc:
            _log("MAIN", f"[WARN] cleanup orfano {nome}: {exc}")


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
        os.replace(tmp, path)
    except Exception as exc:
        print(f"  [WARN] engine_status.json: {exc}")


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

    for class_name, priority, interval_h, schedule in _carica_task_setup():
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

    results = orc.tick()

    with _contatori_lock:
        cnts = _contatori[nome]

    ultimo = None
    if results:
        last_entry = max(orc._entries, key=lambda e: e.last_run, default=None)
        if last_entry and last_entry.last_result:
            lr    = last_entry.last_result
            tname = last_entry.task.name() if callable(last_entry.task.name) else last_entry.task.name
            cnts[tname] = cnts.get(tname, 0) + 1
            ultimo = {"nome": tname, "esito": "ok" if lr.success else "err",
                      "msg": (lr.message or "")[:120], "ts": datetime.now().strftime("%H:%M:%S"), "durata_s": 0}
            _aggiungi_storico({"istanza": nome, "task": tname,
                               "esito": "ok" if lr.success else "err",
                               "ts": datetime.now().strftime("%H:%M:%S"),
                               "durata_s": 0, "msg": (lr.message or "")[:80]})

    errori = sum(1 for r in results if not r.success)
    _aggiorna_stato_istanza(nome, {"stato": "waiting", "task_eseguiti": dict(cnts),
                                   "ultimo_task": ultimo, "scheduler": _scheduler_prossimi(orc), "errori": errori})
    try:
        ctx.state.schedule.update_from_stato(orc.stato())
        ctx.state.save(state_dir=os.path.join(ROOT, "state"))
    except Exception as exc:
        _log(nome, f"[WARN] save state: {exc}")

    _log(nome, f"Tick completato ({len(results)} eseguiti)")

    # ── 4. Chiusura istanza MuMu ────────────────────────────────────
    if not dry_run:
        _launcher.chiudi_istanza(ist, porta, _log_fn)

    _aggiorna_stato_istanza(nome, {"stato": "idle"})
    _log(nome, "Thread completato.")


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
    p.add_argument("--tick-sleep", type=int, default=300,
                   help="Secondi di pausa tra un ciclo completo di istanze e il successivo")
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

    # Cleanup emulator orfani all'avvio (kill residui di sessioni precedenti)
    _log("MAIN", f"Cleanup emulator orfani (startup) — {len(istanze)} istanze")
    _cleanup_tutti_emulator(istanze, args.dry_run)

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

            # Skip istanze precedenti al punto di resume (solo ciclo 1)
            if _resume_attivo and not _resume_trovato:
                if nome != resume_da:
                    _log("MAIN", f"--- Skip {nome} (resume) ---")
                    continue
                else:
                    _resume_trovato = True  # trovata — da qui in poi esegue normalmente

            # Scrivi checkpoint PRIMA di avviare
            _scrivi_checkpoint(ciclo, nome)

            _log("MAIN", f"--- Avvio istanza {nome} ---")
            if not args.dry_run:
                _launcher.reset_istanza(ist, lambda msg: _log(nome, msg))
            t = threading.Thread(
                target=_thread_istanza,
                args=(ist, tasks_cls, args.dry_run),
                name=nome, daemon=True
            )
            t.start()
            t.join()
            _log("MAIN", f"--- Istanza {nome} completata ---")

        # Fine ciclo — cancella checkpoint solo se completato senza interruzioni
        if not stop_event.is_set():
            _cancella_checkpoint()

        if stop_event.is_set():
            break

        _log("MAIN", f"Ciclo {ciclo} completato — sleep {SLEEP_CICLO//60} minuti")
        for _ in range(SLEEP_CICLO):
            if stop_event.is_set(): break
            time.sleep(1)

    close_all_loggers()
    _log("MAIN", "Engine fermato.")


if __name__ == "__main__":
    main()
