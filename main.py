# ==============================================================================
#  DOOMSDAY ENGINE V6 -- main.py
# ==============================================================================
from __future__ import annotations
import argparse, json, os, signal, sys, threading, time
from datetime import datetime, timezone
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.orchestrator import Orchestrator
from core.task import TaskContext, TaskResult
from core.logger import StructuredLogger, get_logger, close_all_loggers
from core.state import InstanceState


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
    if filtro:
        istanze = [i for i in istanze if i.get("nome") in filtro]
        if not istanze:
            print(f"  [WARN] Nessuna istanza trovata per: {filtro}")
    return istanze


def _carica_runtime() -> dict:
    try:
        with open(os.path.join(ROOT, "runtime.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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
# Config istanza
# ---------------------------------------------------------------------------
def _build_cfg(ist: dict, rt: dict, nome: str):
    g   = rt.get("globali", {})
    ovr = rt.get("overrides", {}).get("mumu", {}).get(nome, {})

    class _Cfg:
        instance_name = nome
        truppe        = ovr.get("truppe",      ist.get("truppe",      12000))
        max_squadre   = ovr.get("max_squadre", ist.get("max_squadre", 4))
        layout        = ovr.get("layout",      ist.get("layout",      1))
        livello       = ovr.get("livello",     ist.get("livello",     6))
        profilo       = ovr.get("profilo",     ist.get("profilo",     "full"))
        fascia_oraria = ovr.get("fascia_oraria", ist.get("fascia_oraria", ""))
        lingua        = ist.get("lingua", "en")
        RIFORNIMENTO_ABILITATO           = g.get("RIFORNIMENTO_ABILITATO",           True)
        RIFORNIMENTO_MAPPA_ABILITATO      = g.get("RIFORNIMENTO_MAPPA_ABILITATO",     False)
        RIFORNIMENTO_SOGLIA_CAMPO_M       = g.get("RIFORNIMENTO_SOGLIA_CAMPO_M",      5.0)
        RIFORNIMENTO_SOGLIA_LEGNO_M       = g.get("RIFORNIMENTO_SOGLIA_LEGNO_M",      5.0)
        RIFORNIMENTO_SOGLIA_PETROLIO_M    = g.get("RIFORNIMENTO_SOGLIA_PETROLIO_M",   3.0)
        RIFORNIMENTO_SOGLIA_ACCIAIO_M     = g.get("RIFORNIMENTO_SOGLIA_ACCIAIO_M",    3.0)
        RIFORNIMENTO_CAMPO_ABILITATO      = g.get("RIFORNIMENTO_CAMPO_ABILITATO",     True)
        RIFORNIMENTO_LEGNO_ABILITATO      = g.get("RIFORNIMENTO_LEGNO_ABILITATO",     True)
        RIFORNIMENTO_PETROLIO_ABILITATO   = g.get("RIFORNIMENTO_PETROLIO_ABILITATO",  True)
        RIFORNIMENTO_ACCIAIO_ABILITATO    = g.get("RIFORNIMENTO_ACCIAIO_ABILITATO",   True)
        RIFORNIMENTO_MAX_SPEDIZIONI_CICLO = g.get("RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5)
        RIFUGIO_X                         = g.get("RIFUGIO_X",  684)
        RIFUGIO_Y                         = g.get("RIFUGIO_Y",  532)
        ZAINO_ABILITATO                   = g.get("ZAINO_ABILITATO",     True)
        ZAINO_USA_POMODORO                = g.get("ZAINO_USA_POMODORO",  True)
        ZAINO_USA_LEGNO                   = g.get("ZAINO_USA_LEGNO",     True)
        ZAINO_USA_PETROLIO                = g.get("ZAINO_USA_PETROLIO",  True)
        ZAINO_USA_ACCIAIO                 = g.get("ZAINO_USA_ACCIAIO",   True)
        ZAINO_SOGLIA_POMODORO_M           = g.get("ZAINO_SOGLIA_POMODORO_M",  10.0)
        ZAINO_SOGLIA_LEGNO_M              = g.get("ZAINO_SOGLIA_LEGNO_M",     10.0)
        ZAINO_SOGLIA_PETROLIO_M           = g.get("ZAINO_SOGLIA_PETROLIO_M",   5.0)
        ZAINO_SOGLIA_ACCIAIO_M            = g.get("ZAINO_SOGLIA_ACCIAIO_M",    5.0)
        ALLEANZA_ABILITATO                = g.get("ALLEANZA_ABILITATO",   True)
        MESSAGGI_ABILITATO                = g.get("MESSAGGI_ABILITATO",   True)
        VIP_ABILITATO                     = g.get("VIP_ABILITATO",        True)
        RADAR_ABILITATO                   = g.get("RADAR_ABILITATO",      True)
        RADAR_CENSUS_ABILITATO            = g.get("RADAR_CENSUS_ABILITATO", False)
        ARENA_OF_GLORY_ABILITATO          = g.get("ARENA_OF_GLORY_ABILITATO",  True)
        ARENA_MERCATO_ABILITATO           = g.get("ARENA_MERCATO_ABILITATO",   True)
        BOOST_ABILITATO                   = g.get("BOOST_ABILITATO",  True)
        STORE_ABILITATO                   = g.get("STORE_ABILITATO",  True)

        def task_abilitato(self, nome_task: str) -> bool:
            mappa = {
                "raccolta":      True,
                "rifornimento":  self.RIFORNIMENTO_ABILITATO,
                "zaino":         self.ZAINO_ABILITATO,
                "vip":           self.VIP_ABILITATO,
                "alleanza":      self.ALLEANZA_ABILITATO,
                "messaggi":      self.MESSAGGI_ABILITATO,
                "arena":         self.ARENA_OF_GLORY_ABILITATO,
                "arena_mercato": self.ARENA_MERCATO_ABILITATO,
                "boost":         self.BOOST_ABILITATO,
                "store":         self.STORE_ABILITATO,
                "radar":         self.RADAR_ABILITATO,
                "radar_census":  self.RADAR_CENSUS_ABILITATO,
            }
            return mappa.get(nome_task, True)

    return _Cfg()


# ---------------------------------------------------------------------------
# Build TaskContext (firma allineata a core/task.py Step 25)
# ---------------------------------------------------------------------------
def _build_ctx(ist: dict, rt: dict, dry_run: bool) -> TaskContext:
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    cfg    = _build_cfg(ist, rt, nome)
    logger = get_logger(nome, log_dir=os.path.join(ROOT, "logs"), console=False)
    state  = InstanceState.load(nome, state_dir=os.path.join(ROOT, "state"))

    if dry_run:
        try:
            from core.device import FakeDevice
            device = FakeDevice(name=nome, index=ist.get("indice", 0))
        except ImportError:
            device = None
    else:
        try:
            from core.device import AdbDevice  # type: ignore
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
            navigator = GameNavigator(device=device, matcher=matcher)
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


# ---------------------------------------------------------------------------
# Thread istanza
# ---------------------------------------------------------------------------
_TASK_SETUP = [
    ("BoostTask",         5,   8.0,   "periodic"),
    ("RaccoltaTask",      10,  4.0,   "periodic"),
    ("RifornimentoTask",  20,  1.0,   "periodic"),
    ("ZainoTask",         30,  168.0, "periodic"),
    ("VipTask",           40,  24.0,  "daily"),
    ("MessaggiTask",      50,  1.0,   "periodic"),
    ("AlleanzaTask",      60,  1.0,   "periodic"),
    ("StoreTask",         70,  8.0,   "periodic"),
    ("ArenaTask",         80,  24.0,  "daily"),
    ("ArenaMercatoTask",  90,  24.0,  "daily"),
    ("RadarTask",         100, 12.0,  "periodic"),
    ("RadarCensusTask",   110, 24.0,  "periodic"),
]

_contatori: dict[str, dict[str, int]] = {}
_contatori_lock = threading.Lock()


def _thread_istanza(ist, tasks_cls, dry_run, tick_sleep, stop_event):
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    _log(nome, f"Thread avviato -- porta ADB {porta}")
    _aggiorna_stato_istanza(nome, {"stato": "waiting", "porta": porta})

    with _contatori_lock:
        _contatori.setdefault(nome, {})

    rt  = _carica_runtime()
    ctx = _build_ctx(ist, rt, dry_run)
    orc = Orchestrator(ctx)

    for class_name, priority, interval_h, schedule in _TASK_SETUP:
        Cls = tasks_cls.get(class_name)
        if Cls is None:
            continue
        try:
            task = Cls()
            if hasattr(task, "schedule_type"):  task.schedule_type  = schedule
            if hasattr(task, "interval_hours"): task.interval_hours = interval_h
            orc.register(task, priority=priority)
        except Exception as exc:
            _log(nome, f"[WARN] Impossibile registrare {class_name}: {exc}")

    _log(nome, f"Orchestrator pronto -- {len(orc)} task: {orc.task_names()}")

    while not stop_event.is_set():
        rt  = _carica_runtime()
        ctx = _build_ctx(ist, rt, dry_run)
        orc._ctx = ctx

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
            ctx.state.save(state_dir=os.path.join(ROOT, "state"))
        except Exception as exc:
            _log(nome, f"[WARN] save state: {exc}")

        _log(nome, f"Tick completato ({len(results)} eseguiti) -- pausa {tick_sleep}s")
        for _ in range(tick_sleep):
            if stop_event.is_set(): break
            time.sleep(1)

    _aggiorna_stato_istanza(nome, {"stato": "idle"})
    _log(nome, "Thread fermato.")


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
        _log("MAIN", f"Segnale {sig} -- stop..."); stop_event.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    threading.Thread(target=_status_writer_loop, args=(stop_event, args.status_interval),
                     name="StatusWriter", daemon=True).start()

    threads = []
    for ist in istanze:
        t = threading.Thread(target=_thread_istanza,
                             args=(ist, tasks_cls, args.dry_run, args.tick_sleep, stop_event),
                             name=ist["nome"], daemon=True)
        t.start(); threads.append(t); time.sleep(2)

    _log("MAIN", f"{len(threads)} thread avviati. Premi Ctrl+C per fermare.")

    try:
        while not stop_event.is_set(): time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    _log("MAIN", "Attesa thread...")
    for t in threads: t.join(timeout=30)
    close_all_loggers()
    _log("MAIN", "Engine fermato.")


if __name__ == "__main__":
    main()
