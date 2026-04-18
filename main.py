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
# ==============================================================================
from __future__ import annotations
import argparse, json, os, signal, sys, threading, time
from datetime import datetime, timezone
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)  # CWD = project root, indipendentemente da dove main.py è lanciato

from core.orchestrator import Orchestrator
from core.task import TaskContext, TaskResult
from core.logger import StructuredLogger, get_logger, close_all_loggers
from core.state import InstanceState
from config.config_loader import load_global, build_instance_cfg
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
    path = os.path.join(ROOT, "config", "instances.json")
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
def _build_ctx(ist: dict, gcfg, dry_run: bool) -> TaskContext:
    """
    Costruisce il TaskContext per un'istanza.
    gcfg: GlobalConfig da load_global() — letto ad ogni tick.
    """
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    cfg    = build_instance_cfg(ist, gcfg)
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

            # FIX sessione 2: firma corretta StructuredLogger.info(module, message)
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
_TASK_SETUP = [
    ("BoostTask",         5,   0.0,   "periodic"),
    ("VipTask",           10,  24.0,  "daily"),
    ("MessaggiTask",      20,  4.0,   "periodic"),
    ("AlleanzaTask",      30,  4.0,   "periodic"),
    ("StoreTask",         40,  8.0,   "periodic"),
    ("ArenaTask",         50,  24.0,  "daily"),
    ("ArenaMercatoTask",  60,  24.0,  "daily"),
    ("ZainoTask",         70,  168.0, "periodic"),
    ("RadarTask",         80,  12.0,  "periodic"),
    ("RadarCensusTask",   90,  24.0,  "periodic"),
    ("RifornimentoTask",  100, 1.0,   "periodic"),
    ("RaccoltaTask",      110, 0.0,   "always"),
]

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

    gcfg = load_global()
    ctx  = _build_ctx(ist, gcfg, dry_run)
    orc  = Orchestrator(ctx)

    for class_name, priority, interval_h, schedule in _TASK_SETUP:
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
    # Ripristina i last_run dall'ultimo stato persistito su disco.
    # Senza questo, ogni restart rieseguirebbe tutti i task immediatamente.
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
    gcfg = load_global()
    ctx  = _build_ctx(ist, gcfg, dry_run)
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
        # Sync schedule → state prima del save (restart-safe)
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
    p.add_argument("--tick-sleep", type=int, default=300)
    p.add_argument("--no-dashboard", action="store_true", default=False)
    p.add_argument("--status-interval", type=int, default=5)
    return p.parse_args()


def main():
    args = _parse_args()

    if os.path.exists(_LOG_PATH):
        try: os.replace(_LOG_PATH, _LOG_PATH + ".bak")
        except Exception: pass

    _log("MAIN", "=" * 55)
    _log("MAIN", "DOOMSDAY ENGINE V6")
    _log("MAIN", f"Root: {ROOT}  dry-run: {args.dry_run}  tick-sleep: {args.tick_sleep}s")

    filtro  = [n.strip() for n in args.istanze.split(",")] if args.istanze else None
    istanze = _carica_istanze(filtro=filtro)
    if not istanze:
        _log("MAIN", "Nessuna istanza -- uscita."); sys.exit(1)
    _log("MAIN", f"Istanze: {[i['nome'] for i in istanze]}")
    _log("MAIN", f"Modalità: SEQUENZIALE — ciclo {[i['nome'] for i in istanze]} → sleep 30min → ripeti")

    tasks_cls = _import_tasks()
    _log("MAIN", f"Task: {list(tasks_cls.keys())}")

    if not args.no_dashboard:
        try:
            from dashboard.dashboard_server import avvia as _avvia
            _avvia()
            _log("MAIN", "Dashboard avviata -> http://localhost:8080/dashboard.html")
        except Exception as exc:
            _log("MAIN", f"[WARN] Dashboard: {exc}")

    stop_event = threading.Event()

    def _on_signal(sig, frame):
        if not stop_event.is_set():
            _log("MAIN", f"Segnale {sig} -- stop...")
            stop_event.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    threading.Thread(target=_status_writer_loop, args=(stop_event, args.status_interval),
                     name="StatusWriter", daemon=True).start()

    SLEEP_CICLO = 30 * 60  # 30 minuti tra un ciclo e l'altro

    ciclo = 0
    while not stop_event.is_set():
        ciclo += 1
        _log("MAIN", f"{'=' * 55}")
        _log("MAIN", f"CICLO {ciclo} — {[i['nome'] for i in istanze]}")

        for ist in istanze:
            if stop_event.is_set():
                break
            nome = ist["nome"]
            _log("MAIN", f"--- Avvio istanza {nome} ---")
            if not args.dry_run:
                _launcher.reset_istanza(ist, lambda msg: _log(nome, msg))
            t = threading.Thread(
                target=_thread_istanza,
                args=(ist, tasks_cls, args.dry_run),
                name=nome, daemon=True
            )
            t.start()
            t.join()  # Attende che l'istanza completi il tick prima di passare alla prossima
            _log("MAIN", f"--- Istanza {nome} completata ---")

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
