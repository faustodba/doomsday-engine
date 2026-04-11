# ==============================================================================
#  DOOMSDAY ENGINE V6 — main.py
#
#  Entry point del bot. Avvia un thread per istanza MuMu, ognuno con il
#  proprio Orchestrator che gira in loop continuo.
#
#  ARCHITETTURA:
#    - Un thread per istanza (niente asyncio, tutto sincrono come da Step 25)
#    - Ogni thread costruisce: AdbDevice → FakeMatcher → GameNavigator → ctx
#    - L'Orchestrator del thread chiama tick() in loop con sleep tra i cicli
#    - Il loop principale scrive engine_status.json ogni STATUS_INTERVAL secondi
#    - La dashboard (Step 23) legge engine_status.json in polling
#
#  AVVIO:
#    python main.py [--istanze FAU_00,FAU_01] [--dry-run] [--tick-sleep 60]
#
#  FLAG:
#    --istanze      Sottoinsieme di istanze da avviare (default: tutte da instances.json)
#    --dry-run      Avvia senza ADB reale (usa FakeDevice — utile per CI/debug)
#    --tick-sleep   Secondi di attesa tra un tick e il successivo (default: 300)
#    --no-dashboard Non avvia il server HTTP dashboard
# ==============================================================================
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap path: permette di avviare da C:\doomsday-engine\ oppure da
# una sotto-cartella, senza dover configurare PYTHONPATH.
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.orchestrator import Orchestrator
from core.task import TaskContext, TaskResult

# ---------------------------------------------------------------------------
# Import task V6 (tutti sincroni — Step 25)
# ---------------------------------------------------------------------------
def _import_tasks():
    """
    Importa i task disponibili. Ogni import è protetto: se un modulo non è
    ancora presente (sviluppo incrementale), il task viene semplicemente
    omesso e un warning viene stampato.
    """
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


# ---------------------------------------------------------------------------
# Lettura configurazione istanze
# ---------------------------------------------------------------------------
def _carica_istanze(filtro: Optional[list[str]] = None) -> list[dict]:
    """
    Legge config/instances.json.
    Ritorna tutte le istanze (non filtra per abilitata=True —
    la scelta di avviarle è dell'operatore, che può usare --istanze).
    Se filtro è specificato, restituisce solo le istanze con nome in filtro.
    """
    path = os.path.join(ROOT, "config", "instances.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze = json.load(f)
    except FileNotFoundError:
        print(f"  [WARN] {path} non trovato — nessuna istanza caricata.")
        return []
    except json.JSONDecodeError as exc:
        print(f"  [ERRORE] {path} non è JSON valido: {exc}")
        return []

    if filtro:
        istanze = [i for i in istanze if i.get("nome") in filtro]
        if not istanze:
            print(f"  [WARN] Nessuna istanza trovata per: {filtro}")

    return istanze


def _carica_runtime() -> dict:
    """Legge runtime.json se esiste, altrimenti ritorna dict vuoto."""
    path = os.path.join(ROOT, "runtime.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Stato globale engine (scritto su engine_status.json per la dashboard)
# ---------------------------------------------------------------------------
_engine_stato: dict = {
    "version":  "v6",
    "ts":       "",
    "uptime_s": 0,
    "ciclo":    0,
    "stato":    "idle",
    "istanze":  {},
    "storico":  [],   # lista ultime N esecuzioni task
}
_engine_lock = threading.Lock()
_t_avvio = time.time()
_MAX_STORICO = 200   # voci massime in storico


def _aggiorna_stato_istanza(nome: str, update: dict) -> None:
    with _engine_lock:
        if nome not in _engine_stato["istanze"]:
            _engine_stato["istanze"][nome] = {
                "stato": "idle",
                "task_corrente": None,
                "task_eseguiti": {},
                "ultimo_task": None,
                "scheduler": {},
                "errori": 0,
                "porta": 0,
            }
        _engine_stato["istanze"][nome].update(update)


def _aggiungi_storico(entry: dict) -> None:
    with _engine_lock:
        _engine_stato["storico"].append(entry)
        if len(_engine_stato["storico"]) > _MAX_STORICO:
            _engine_stato["storico"] = _engine_stato["storico"][-_MAX_STORICO:]


def _scrivi_status_json() -> None:
    """Scrive engine_status.json in modo atomico (tmp + replace)."""
    path = os.path.join(ROOT, "engine_status.json")
    with _engine_lock:
        snapshot = json.loads(json.dumps(_engine_stato))  # deep copy veloce

    snapshot["ts"]       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    snapshot["uptime_s"] = int(time.time() - _t_avvio)
    snapshot["stato"]    = _stato_globale()

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        print(f"  [WARN] Impossibile scrivere engine_status.json: {exc}")


def _stato_globale() -> str:
    with _engine_lock:
        stati = [v.get("stato", "idle") for v in _engine_stato["istanze"].values()]
    if any(s == "running" for s in stati):
        return "running"
    if any(s == "waiting" for s in stati):
        return "waiting"
    return "idle"


# ---------------------------------------------------------------------------
# Logger per istanza (scrive su bot.log)
# ---------------------------------------------------------------------------
_log_lock = threading.Lock()
_LOG_PATH = os.path.join(ROOT, "bot.log")


def _log(nome: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {nome} {msg}"
    with _log_lock:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    print(line)


# ---------------------------------------------------------------------------
# Costruzione TaskContext per un'istanza
# ---------------------------------------------------------------------------
def _build_ctx(ist: dict, rt: dict, dry_run: bool) -> TaskContext:
    """
    Costruisce il TaskContext per un'istanza MuMu.

    In modalità dry-run usa FakeDevice + FakeMatcher (zero ADB).
    In modalità normale usa AdbDevice reale.
    """
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    # ── Classe config inline (porta i globali da runtime.json) ────────────
    class _Cfg:
        def __init__(self):
            g = rt.get("globali", {})
            ovr = rt.get("overrides", {}).get("mumu", {}).get(nome, {})

            # Parametri istanza (override > instances.json)
            self.truppe      = ovr.get("truppe",      ist.get("truppe",      12000))
            self.max_squadre = ovr.get("max_squadre", ist.get("max_squadre", 4))
            self.layout      = ovr.get("layout",      ist.get("layout",      1))
            self.livello     = ovr.get("livello",     ist.get("livello",     6))
            self.profilo     = ovr.get("profilo",     ist.get("profilo",     "full"))
            self.fascia_oraria = ovr.get("fascia_oraria", ist.get("fascia_oraria", ""))

            # Parametri globali
            self.RIFORNIMENTO_ABILITATO          = g.get("RIFORNIMENTO_ABILITATO",          True)
            self.RIFORNIMENTO_MAPPA_ABILITATO     = g.get("RIFORNIMENTO_MAPPA_ABILITATO",     False)
            self.RIFORNIMENTO_SOGLIA_CAMPO_M      = g.get("RIFORNIMENTO_SOGLIA_CAMPO_M",      5.0)
            self.RIFORNIMENTO_SOGLIA_LEGNO_M      = g.get("RIFORNIMENTO_SOGLIA_LEGNO_M",      5.0)
            self.RIFORNIMENTO_SOGLIA_PETROLIO_M   = g.get("RIFORNIMENTO_SOGLIA_PETROLIO_M",   3.0)
            self.RIFORNIMENTO_SOGLIA_ACCIAIO_M    = g.get("RIFORNIMENTO_SOGLIA_ACCIAIO_M",    3.0)
            self.RIFORNIMENTO_CAMPO_ABILITATO     = g.get("RIFORNIMENTO_CAMPO_ABILITATO",     True)
            self.RIFORNIMENTO_LEGNO_ABILITATO     = g.get("RIFORNIMENTO_LEGNO_ABILITATO",     True)
            self.RIFORNIMENTO_PETROLIO_ABILITATO  = g.get("RIFORNIMENTO_PETROLIO_ABILITATO",  True)
            self.RIFORNIMENTO_ACCIAIO_ABILITATO   = g.get("RIFORNIMENTO_ACCIAIO_ABILITATO",   True)
            self.RIFORNIMENTO_MAX_SPEDIZIONI_CICLO = g.get("RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5)
            self.RIFUGIO_X                        = g.get("RIFUGIO_X",                       684)
            self.RIFUGIO_Y                        = g.get("RIFUGIO_Y",                       532)
            self.ZAINO_ABILITATO                  = g.get("ZAINO_ABILITATO",                 True)
            self.ZAINO_USA_POMODORO               = g.get("ZAINO_USA_POMODORO",              True)
            self.ZAINO_USA_LEGNO                  = g.get("ZAINO_USA_LEGNO",                 True)
            self.ZAINO_USA_PETROLIO               = g.get("ZAINO_USA_PETROLIO",              True)
            self.ZAINO_USA_ACCIAIO                = g.get("ZAINO_USA_ACCIAIO",               True)
            self.ZAINO_SOGLIA_POMODORO_M          = g.get("ZAINO_SOGLIA_POMODORO_M",         10.0)
            self.ZAINO_SOGLIA_LEGNO_M             = g.get("ZAINO_SOGLIA_LEGNO_M",            10.0)
            self.ZAINO_SOGLIA_PETROLIO_M          = g.get("ZAINO_SOGLIA_PETROLIO_M",          5.0)
            self.ZAINO_SOGLIA_ACCIAIO_M           = g.get("ZAINO_SOGLIA_ACCIAIO_M",           5.0)
            self.ALLEANZA_ABILITATO               = g.get("ALLEANZA_ABILITATO",              True)
            self.MESSAGGI_ABILITATO               = g.get("MESSAGGI_ABILITATO",              True)
            self.VIP_ABILITATO                    = g.get("VIP_ABILITATO",                   True)
            self.RADAR_ABILITATO                  = g.get("RADAR_ABILITATO",                 True)
            self.RADAR_CENSUS_ABILITATO           = g.get("RADAR_CENSUS_ABILITATO",          False)
            self.ARENA_OF_GLORY_ABILITATO         = g.get("ARENA_OF_GLORY_ABILITATO",        True)
            self.ARENA_MERCATO_ABILITATO          = g.get("ARENA_MERCATO_ABILITATO",         True)
            self.BOOST_ABILITATO                  = g.get("BOOST_ABILITATO",                 True)
            self.STORE_ABILITATO                  = g.get("STORE_ABILITATO",                 True)

        def task_abilitato(self, nome_task: str) -> bool:
            mappa = {
                "raccolta":       True,   # sempre attiva
                "rifornimento":   self.RIFORNIMENTO_ABILITATO,
                "zaino":          self.ZAINO_ABILITATO,
                "vip":            self.VIP_ABILITATO,
                "alleanza":       self.ALLEANZA_ABILITATO,
                "messaggi":       self.MESSAGGI_ABILITATO,
                "arena":          self.ARENA_OF_GLORY_ABILITATO,
                "arena_mercato":  self.ARENA_MERCATO_ABILITATO,
                "boost":          self.BOOST_ABILITATO,
                "store":          self.STORE_ABILITATO,
                "radar":          self.RADAR_ABILITATO,
                "radar_census":   self.RADAR_CENSUS_ABILITATO,
            }
            return mappa.get(nome_task, True)

    cfg = _Cfg()

    # ── Device ───────────────────────────────────────────────────────────
    if dry_run:
        # FakeDevice da core/device.py (Step 25) — zero ADB
        try:
            from core.device import FakeDevice
            device = FakeDevice()
        except ImportError:
            device = None
    else:
        try:
            from core.device import AdbDevice
            device = AdbDevice(host="127.0.0.1", port=porta)
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] AdbDevice non disponibile: {exc}")
            device = None

    # ── Matcher ───────────────────────────────────────────────────────────
    matcher = None
    if not dry_run:
        try:
            from shared.template_matcher import TemplateMatcher
            matcher = TemplateMatcher(templates_dir=os.path.join(ROOT, "templates"))
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] TemplateMatcher non disponibile: {exc}")

    # ── Navigator ────────────────────────────────────────────────────────
    navigator = None
    if not dry_run:
        try:
            from core.navigator import GameNavigator
            navigator = GameNavigator(device=device, matcher=matcher)
        except (ImportError, Exception) as exc:
            _log(nome, f"[WARN] GameNavigator non disponibile: {exc}")

    # ── Logger per il context ────────────────────────────────────────────
    def log_ctx(msg: str, *args) -> None:
        if args:
            try:
                msg = msg % args
            except Exception:
                msg = f"{msg} {args}"
        _log(nome, msg)

    ctx = TaskContext(
        device=device,
        matcher=matcher,
        navigator=navigator,
        config=cfg,
        instance_id=nome,
    )
    # Sovrascriviamo log con la nostra funzione che scrive su bot.log
    ctx.log     = log_ctx
    ctx.log_msg = log_ctx
    return ctx


# ---------------------------------------------------------------------------
# Thread per singola istanza
# ---------------------------------------------------------------------------
def _thread_istanza(
    ist: dict,
    tasks_cls: dict,
    dry_run: bool,
    tick_sleep: int,
    stop_event: threading.Event,
) -> None:
    """
    Loop di una singola istanza MuMu.
    Costruisce il proprio Orchestrator con tutti i task, poi chiama tick()
    ogni tick_sleep secondi finché stop_event non viene settato.
    """
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    _log(nome, f"Thread avviato — porta ADB {porta}")
    _aggiorna_stato_istanza(nome, {"stato": "waiting", "porta": porta})

    # ── Costruisci task ───────────────────────────────────────────────────
    # Priorità: più basso = eseguito prima nel tick
    # Raccolta è la più frequente, quindi priorità massima (più bassa)
    _TASK_SETUP = [
        # (class_name,         priority, interval_h, schedule)
        ("BoostTask",          5,   8.0,  "periodic"),
        ("RaccoltaTask",       10,  4.0,  "periodic"),
        ("RifornimentoTask",   20,  1.0,  "periodic"),
        ("ZainoTask",          30,  168.0, "periodic"),  # ~settimanale
        ("VipTask",            40,  24.0, "daily"),
        ("MessaggiTask",       50,  1.0,  "periodic"),
        ("AlleanzaTask",       60,  1.0,  "periodic"),
        ("StoreTask",          70,  8.0,  "periodic"),
        ("ArenaTask",          80,  24.0, "daily"),
        ("ArenaMercatoTask",   90,  24.0, "daily"),
        ("RadarTask",          100, 12.0, "periodic"),
        ("RadarCensusTask",    110, 24.0, "periodic"),
    ]

    rt = _carica_runtime()

    ctx = _build_ctx(ist, rt, dry_run)

    # Ricostruisce ctx ad ogni tick (rilegge runtime.json → config fresca)
    # ma l'orchestrator persiste tra i tick (mantiene last_run)
    orc = Orchestrator(ctx)

    for class_name, priority, interval_h, schedule in _TASK_SETUP:
        Cls = tasks_cls.get(class_name)
        if Cls is None:
            continue
        try:
            task = Cls()
            # Imposta schedule type e interval se il task li supporta
            if hasattr(task, "schedule_type"):
                task.schedule_type   = schedule
            if hasattr(task, "interval_hours"):
                task.interval_hours  = interval_h
            orc.register(task, priority=priority)
        except Exception as exc:
            _log(nome, f"[WARN] Impossibile registrare {class_name}: {exc}")

    _log(nome, f"Orchestrator pronto — {len(orc)} task registrati: {orc.task_names()}")

    # ── Loop principale istanza ───────────────────────────────────────────
    while not stop_event.is_set():
        # Rileggi runtime ad ogni tick (configurazione hot-reload)
        rt = _carica_runtime()
        ctx = _build_ctx(ist, rt, dry_run)
        orc._ctx = ctx  # aggiorna il contesto nell'orchestrator

        _aggiorna_stato_istanza(nome, {
            "stato":     "running",
            "scheduler": _scheduler_prossimi(orc),
        })

        n_dovuti = orc.n_dovuti()
        _log(nome, f"Tick — {n_dovuti} task dovuti su {len(orc)} registrati")

        results = orc.tick()

        # Aggiorna stato dopo il tick
        stato_orc = orc.stato()
        task_eseguiti: dict[str, int] = {}
        for task_name, info in stato_orc.items():
            if info["last_run"] > 0:
                # Conta quante volte è stato eseguito (proxy: last_run != 0)
                task_eseguiti[task_name] = task_eseguiti.get(task_name, 0) + 1

        # Conta totale esecuzioni da task_eseguiti nel thread
        if not hasattr(_thread_istanza, "_contatori"):
            _thread_istanza._contatori = {}
        chiave = nome
        if chiave not in _thread_istanza._contatori:
            _thread_istanza._contatori[chiave] = {}
        cnts = _thread_istanza._contatori[chiave]

        for r in results:
            t_name = getattr(r, "task_name", None) or (
                [e.task.name() if callable(e.task.name) else e.task.name
                 for e in orc._entries if e.last_result is r] or [None]
            )[0]
            if t_name:
                cnts[t_name] = cnts.get(t_name, 0) + 1

        # Ultimo task eseguito
        ultimo = None
        if results:
            # Trova l'entry con last_run più recente
            last_entry = max(orc._entries, key=lambda e: e.last_run, default=None)
            if last_entry and last_entry.last_result:
                lr = last_entry.last_result
                tname = last_entry.task.name() if callable(last_entry.task.name) else last_entry.task.name
                ultimo = {
                    "nome":     tname,
                    "esito":    "ok" if lr.success else "err",
                    "msg":      lr.message[:120] if lr.message else "",
                    "ts":       datetime.now().strftime("%H:%M:%S"),
                    "durata_s": 0,
                }
                # Aggiungi allo storico globale
                _aggiungi_storico({
                    "istanza": nome,
                    "task":    tname,
                    "esito":   "ok" if lr.success else "err",
                    "ts":      datetime.now().strftime("%H:%M:%S"),
                    "durata_s": 0,
                    "msg":     lr.message[:80] if lr.message else "",
                })

        errori = sum(1 for r in results if not r.success)
        _aggiorna_stato_istanza(nome, {
            "stato":        "waiting",
            "task_eseguiti": cnts.copy(),
            "ultimo_task":  ultimo,
            "scheduler":    _scheduler_prossimi(orc),
            "errori":       errori,
        })

        # Sleep con check stop_event ogni secondo
        _log(nome, f"Tick completato ({len(results)} eseguiti) — pausa {tick_sleep}s")
        for _ in range(tick_sleep):
            if stop_event.is_set():
                break
            time.sleep(1)

    _aggiorna_stato_istanza(nome, {"stato": "idle"})
    _log(nome, "Thread fermato.")


def _scheduler_prossimi(orc: Orchestrator) -> dict:
    """
    Ritorna un dict {task_name: "HH:MM:SS prossimo run stimato"}
    per i task non ancora dovuti.
    """
    out = {}
    for entry in orc._entries:
        if entry.last_run == 0.0:
            out[entry.task.name() if callable(entry.task.name) else entry.task.name] = "adesso"
            continue
        if entry.task.schedule_type == "daily":
            continue  # non calcoliamo il prossimo reset giornaliero per semplicità
        secondi_rimasti = max(0.0, entry.task.interval_hours * 3600 - (time.time() - entry.last_run))
        prossimo = datetime.fromtimestamp(time.time() + secondi_rimasti).strftime("%H:%M:%S")
        tname = entry.task.name() if callable(entry.task.name) else entry.task.name
        out[tname] = prossimo
    return out


# ---------------------------------------------------------------------------
# Status writer loop (thread separato)
# ---------------------------------------------------------------------------
def _status_writer_loop(stop_event: threading.Event, interval: int = 5) -> None:
    """Scrive engine_status.json ogni `interval` secondi."""
    while not stop_event.is_set():
        _scrivi_status_json()
        for _ in range(interval):
            if stop_event.is_set():
                break
            time.sleep(1)
    # Scrittura finale con stato idle
    _scrivi_status_json()


# ---------------------------------------------------------------------------
# Argomenti CLI
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Doomsday Engine V6 — Bot farm MuMu",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--istanze", default=None,
        help="Nomi istanze separati da virgola (es. FAU_00,FAU_01). "
             "Default: tutte quelle in config/instances.json.",
    )
    p.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Avvia senza ADB reale (usa FakeDevice). Per test/CI.",
    )
    p.add_argument(
        "--tick-sleep", type=int, default=300,
        help="Secondi di pausa tra un tick e il successivo per istanza.",
    )
    p.add_argument(
        "--no-dashboard", action="store_true", default=False,
        help="Non avvia il server HTTP dashboard (porta 8080).",
    )
    p.add_argument(
        "--status-interval", type=int, default=5,
        help="Intervallo (secondi) tra aggiornamenti di engine_status.json.",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = _parse_args()

    # ── Inizializza log ───────────────────────────────────────────────────
    # Ruota bot.log: mantiene l'ultimo avvio pulito
    if os.path.exists(_LOG_PATH):
        try:
            os.replace(_LOG_PATH, _LOG_PATH + ".bak")
        except Exception:
            pass

    _log("MAIN", "=" * 55)
    _log("MAIN", "DOOMSDAY ENGINE V6")
    _log("MAIN", f"Root: {ROOT}")
    _log("MAIN", f"dry-run: {args.dry_run}  tick-sleep: {args.tick_sleep}s")

    # ── Carica istanze ────────────────────────────────────────────────────
    filtro = [n.strip() for n in args.istanze.split(",")] if args.istanze else None
    istanze = _carica_istanze(filtro=filtro)

    if not istanze:
        _log("MAIN", "Nessuna istanza configurata — uscita.")
        sys.exit(1)

    _log("MAIN", f"Istanze: {[i['nome'] for i in istanze]}")

    # ── Import task ───────────────────────────────────────────────────────
    tasks_cls = _import_tasks()
    _log("MAIN", f"Task importati: {list(tasks_cls.keys())}")

    # ── Dashboard ────────────────────────────────────────────────────────
    if not args.no_dashboard:
        try:
            from dashboard.dashboard_server import avvia as avvia_dashboard
            avvia_dashboard()
            _log("MAIN", "Dashboard avviata → http://localhost:8080/dashboard.html")
        except Exception as exc:
            _log("MAIN", f"[WARN] Dashboard non avviata: {exc}")

    # ── Stop event condiviso ─────────────────────────────────────────────
    stop_event = threading.Event()

    def _on_signal(sig, frame):
        _log("MAIN", f"Segnale {sig} ricevuto — stop in corso...")
        stop_event.set()

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # ── Status writer ─────────────────────────────────────────────────────
    sw_thread = threading.Thread(
        target=_status_writer_loop,
        args=(stop_event, args.status_interval),
        name="StatusWriter",
        daemon=True,
    )
    sw_thread.start()

    # ── Thread per istanza ────────────────────────────────────────────────
    threads: list[threading.Thread] = []
    for ist in istanze:
        t = threading.Thread(
            target=_thread_istanza,
            args=(ist, tasks_cls, args.dry_run, args.tick_sleep, stop_event),
            name=ist["nome"],
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(2)  # stagger avvio: evita burst ADB simultanei

    _log("MAIN", f"{len(threads)} thread istanza avviati.")
    _log("MAIN", "Premi Ctrl+C per fermare.")

    # ── Join ──────────────────────────────────────────────────────────────
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    _log("MAIN", "Stop richiesto — attesa thread...")
    for t in threads:
        t.join(timeout=30)

    _log("MAIN", "Engine fermato.")


if __name__ == "__main__":
    main()
