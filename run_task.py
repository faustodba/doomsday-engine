# ==============================================================================
#  DOOMSDAY ENGINE V6 — run_task.py
#
#  Runner isolato per test di singolo task su una istanza reale.
#  NON usa l'orchestrator né lo scheduler — esegue il task direttamente.
#
#  Uso:
#    cd C:\doomsday-engine
#    python run_task.py --istanza FAU_01 --task arena
#    python run_task.py --istanza FAU_01 --task arena_mercato
#    python run_task.py --istanza FAU_00 --task raccolta
#
#  Task disponibili:
#    boost, raccolta, rifornimento, zaino, vip, alleanza, messaggi,
#    arena, arena_mercato, store, radar, radar_census
#
#  Output:
#    - Log a schermo con timestamp
#    - Screenshot di debug salvati in C:\doomsday-engine\debug_task\<task>\
#    - Esito finale: OK / FAIL
#
#  Prerequisiti:
#    - Istanza MuMu avviata con Doomsday aperto sulla HOME del gioco
#    - ADB connesso (verificare con: adb devices)
# ==============================================================================

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Catalogo task: nome_task → (modulo, classe)
# ---------------------------------------------------------------------------
_TASK_CATALOGUE = {
    "boost":          ("tasks.boost",          "BoostTask"),
    "raccolta":       ("tasks.raccolta",        "RaccoltaTask"),
    "rifornimento":   ("tasks.rifornimento",    "RifornimentoTask"),
    "zaino":          ("tasks.zaino",           "ZainoTask"),
    "vip":            ("tasks.vip",             "VipTask"),
    "alleanza":       ("tasks.alleanza",        "AlleanzaTask"),
    "messaggi":       ("tasks.messaggi",        "MessaggiTask"),
    "arena":          ("tasks.arena",           "ArenaTask"),
    "arena_mercato":  ("tasks.arena_mercato",   "ArenaMercatoTask"),
    "store":          ("tasks.store",           "StoreTask"),
    "radar":          ("tasks.radar",           "RadarTask"),
    "radar_census":   ("tasks.radar_census",    "RadarCensusTask"),
}

# ---------------------------------------------------------------------------
# Helpers log
# ---------------------------------------------------------------------------
_log_lines: list[str] = []
_debug_dir: str = ""


def log(msg: str) -> None:
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_lines.append(line)


def separa(titolo: str) -> None:
    log("")
    log("=" * 60)
    log(f"  {titolo}")
    log("=" * 60)


def salva_log() -> None:
    if not _debug_dir:
        return
    path = os.path.join(_debug_dir, "run_task.log")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(_log_lines))
        log(f"Log salvato: {path}")
    except Exception as exc:
        log(f"[WARN] salvataggio log fallito: {exc}")


# ---------------------------------------------------------------------------
# Carica istanza da instances.json
# ---------------------------------------------------------------------------
def _carica_istanza(nome: str) -> dict | None:
    path = os.path.join(ROOT, "config", "instances.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze = json.load(f)
    except FileNotFoundError:
        log(f"[ERRORE] {path} non trovato")
        return None
    except json.JSONDecodeError as exc:
        log(f"[ERRORE] {path}: {exc}")
        return None

    for ist in istanze:
        if ist.get("nome") == nome:
            return ist

    log(f"[ERRORE] Istanza '{nome}' non trovata in instances.json")
    log(f"  Istanze disponibili: {[i.get('nome') for i in istanze]}")
    return None


# ---------------------------------------------------------------------------
# Carica runtime.json (opzionale)
# ---------------------------------------------------------------------------
def _carica_runtime() -> dict:
    try:
        with open(os.path.join(ROOT, "runtime.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Build config istanza (speculare a main.py _build_cfg)
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
        RIFORNIMENTO_MAPPA_ABILITATO     = g.get("RIFORNIMENTO_MAPPA_ABILITATO",     False)
        RIFORNIMENTO_SOGLIA_CAMPO_M      = g.get("RIFORNIMENTO_SOGLIA_CAMPO_M",      5.0)
        RIFORNIMENTO_SOGLIA_LEGNO_M      = g.get("RIFORNIMENTO_SOGLIA_LEGNO_M",      5.0)
        RIFORNIMENTO_SOGLIA_PETROLIO_M   = g.get("RIFORNIMENTO_SOGLIA_PETROLIO_M",   3.0)
        RIFORNIMENTO_SOGLIA_ACCIAIO_M    = g.get("RIFORNIMENTO_SOGLIA_ACCIAIO_M",    3.0)
        RIFORNIMENTO_CAMPO_ABILITATO     = g.get("RIFORNIMENTO_CAMPO_ABILITATO",     True)
        RIFORNIMENTO_LEGNO_ABILITATO     = g.get("RIFORNIMENTO_LEGNO_ABILITATO",     True)
        RIFORNIMENTO_PETROLIO_ABILITATO  = g.get("RIFORNIMENTO_PETROLIO_ABILITATO",  True)
        RIFORNIMENTO_ACCIAIO_ABILITATO   = g.get("RIFORNIMENTO_ACCIAIO_ABILITATO",   True)
        RIFORNIMENTO_MAX_SPEDIZIONI_CICLO= g.get("RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5)
        RIFUGIO_X                        = g.get("RIFUGIO_X",  684)
        RIFUGIO_Y                        = g.get("RIFUGIO_Y",  532)
        ZAINO_ABILITATO                  = g.get("ZAINO_ABILITATO",     True)
        ZAINO_USA_POMODORO               = g.get("ZAINO_USA_POMODORO",  True)
        ZAINO_USA_LEGNO                  = g.get("ZAINO_USA_LEGNO",     True)
        ZAINO_USA_PETROLIO               = g.get("ZAINO_USA_PETROLIO",  True)
        ZAINO_USA_ACCIAIO                = g.get("ZAINO_USA_ACCIAIO",   True)
        ZAINO_SOGLIA_POMODORO_M          = g.get("ZAINO_SOGLIA_POMODORO_M",  10.0)
        ZAINO_SOGLIA_LEGNO_M             = g.get("ZAINO_SOGLIA_LEGNO_M",     10.0)
        ZAINO_SOGLIA_PETROLIO_M          = g.get("ZAINO_SOGLIA_PETROLIO_M",   5.0)
        ZAINO_SOGLIA_ACCIAIO_M           = g.get("ZAINO_SOGLIA_ACCIAIO_M",    5.0)
        ALLEANZA_ABILITATO               = g.get("ALLEANZA_ABILITATO",   True)
        MESSAGGI_ABILITATO               = g.get("MESSAGGI_ABILITATO",   True)
        VIP_ABILITATO                    = g.get("VIP_ABILITATO",        True)
        RADAR_ABILITATO                  = g.get("RADAR_ABILITATO",      True)
        RADAR_CENSUS_ABILITATO           = g.get("RADAR_CENSUS_ABILITATO", False)
        ARENA_OF_GLORY_ABILITATO         = g.get("ARENA_OF_GLORY_ABILITATO",  True)
        ARENA_MERCATO_ABILITATO          = g.get("ARENA_MERCATO_ABILITATO",   True)
        BOOST_ABILITATO                  = g.get("BOOST_ABILITATO",  True)
        STORE_ABILITATO                  = g.get("STORE_ABILITATO",  True)

        def get(self, key: str, default=None):
            return getattr(self, key, default)

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
# Build TaskContext (speculare a main.py _build_ctx)
# ---------------------------------------------------------------------------
def _build_ctx(ist: dict, rt: dict, debug_dir: str):
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    cfg = _build_cfg(ist, rt, nome)

    # Logger — scrive su file in debug_dir
    try:
        from core.logger import get_logger
        logger = get_logger(nome, log_dir=debug_dir, console=False)
    except Exception as exc:
        log(f"[WARN] Logger: {exc} — logging disabilitato")
        logger = None

    # State
    try:
        from core.state import InstanceState
        state = InstanceState.load(nome, state_dir=os.path.join(ROOT, "state"))
    except Exception as exc:
        log(f"[WARN] InstanceState: {exc}")
        state = None

    # Device ADB
    try:
        from core.device import AdbDevice
        device = AdbDevice(host="127.0.0.1", port=porta)
        log(f"AdbDevice connesso: 127.0.0.1:{porta}")
    except Exception as exc:
        log(f"[ERRORE] AdbDevice: {exc}")
        device = None

    # TemplateMatcher
    try:
        from shared.template_matcher import get_matcher
        matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
        log("TemplateMatcher OK")
    except Exception as exc:
        log(f"[ERRORE] TemplateMatcher: {exc}")
        matcher = None

    # Navigator
    navigator = None
    try:
        from core.navigator import GameNavigator

        def _nav_log(msg: str) -> None:
            log(f"[NAV] {msg}")
            if logger:
                logger.info("navigator", msg)

        navigator = GameNavigator(device=device, matcher=matcher, log_fn=_nav_log)
        log("GameNavigator OK")
    except Exception as exc:
        log(f"[WARN] GameNavigator: {exc}")

    from core.task import TaskContext

    # TaskContext con log_msg che scrive anche a schermo
    ctx = TaskContext(
        instance_name=nome,
        config=cfg,
        state=state,
        log=logger,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )

    # Patch log_msg per stampare a schermo durante il test
    _orig_log_msg = ctx.log_msg
    def _log_msg_verbose(msg: str, *args, level: str = "info") -> None:
        try:
            full = (msg % args) if args else msg
        except Exception:
            full = msg
        log(f"[CTX] {full}")
        _orig_log_msg(msg, *args, level=level)

    ctx.log_msg = _log_msg_verbose

    return ctx


# ---------------------------------------------------------------------------
# Carica classe task
# ---------------------------------------------------------------------------
def _carica_task(nome_task: str):
    if nome_task not in _TASK_CATALOGUE:
        log(f"[ERRORE] Task '{nome_task}' non nel catalogo.")
        log(f"  Disponibili: {', '.join(sorted(_TASK_CATALOGUE.keys()))}")
        return None

    modulo_path, class_name = _TASK_CATALOGUE[nome_task]
    try:
        mod = __import__(modulo_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        log(f"Task caricato: {class_name} da {modulo_path}")
        return cls
    except (ImportError, AttributeError) as exc:
        log(f"[ERRORE] Impossibile caricare {class_name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Doomsday Engine V6 — Runner isolato singolo task",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--istanza", required=True,
                        help="Nome istanza (es. FAU_01)")
    parser.add_argument("--task",    required=True,
                        help=f"Task da eseguire: {', '.join(sorted(_TASK_CATALOGUE.keys()))}")
    args = parser.parse_args()

    # Debug dir
    global _debug_dir
    _debug_dir = os.path.join(ROOT, "debug_task", args.task)
    os.makedirs(_debug_dir, exist_ok=True)

    separa(f"RUN TASK — {args.task.upper()} su {args.istanza}")
    log(f"Avvio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Debug dir: {_debug_dir}")

    # 1. Carica istanza
    separa("PASSO 1 — Carica istanza")
    ist = _carica_istanza(args.istanza)
    if ist is None:
        log("FAIL: istanza non trovata — uscita")
        salva_log()
        sys.exit(1)
    log(f"Istanza: {ist.get('nome')} — porta {ist.get('porta')} — profilo {ist.get('profilo')}")

    # 2. Build context
    separa("PASSO 2 — Build TaskContext")
    rt  = _carica_runtime()
    ctx = _build_ctx(ist, rt, _debug_dir)
    if ctx.device is None:
        log("FAIL: device ADB non disponibile — uscita")
        salva_log()
        sys.exit(1)
    if ctx.matcher is None:
        log("FAIL: TemplateMatcher non disponibile — uscita")
        salva_log()
        sys.exit(1)

    # 3. Carica task
    separa("PASSO 3 — Carica task")
    TaskCls = _carica_task(args.task)
    if TaskCls is None:
        log("FAIL: task non caricato — uscita")
        salva_log()
        sys.exit(1)

    task = TaskCls()
    log(f"Task istanziato: {task}")

    # 4. should_run check
    separa("PASSO 4 — should_run()")
    try:
        ok = task.should_run(ctx)
        log(f"should_run() → {ok}")
        if not ok:
            log("[WARN] should_run() = False — il task potrebbe essere disabilitato")
            log("       Verifica flag in runtime.json (sezione globali) o instances.json")
    except Exception as exc:
        log(f"[WARN] should_run() eccezione: {exc} — procedo comunque")

    # 5. Esecuzione
    separa(f"PASSO 5 — Esecuzione task '{args.task}'")
    t_start = time.time()
    try:
        result = task.run(ctx)
        durata = time.time() - t_start
    except Exception as exc:
        durata = time.time() - t_start
        log(f"[ERRORE] Eccezione durante run(): {exc}")
        import traceback
        traceback.print_exc()
        result = None

    # 6. Riepilogo
    separa("RIEPILOGO")
    log(f"Durata: {durata:.1f}s")

    if result is None:
        log("ESITO: FAIL — eccezione durante esecuzione")
    elif result.success:
        log(f"ESITO: OK — {result.message or '(nessun messaggio)'}")
        if result.data:
            for k, v in result.data.items():
                log(f"  {k}: {v}")
    else:
        log(f"ESITO: FAIL — {result.message or '(nessun messaggio)'}")
        if result.data:
            for k, v in result.data.items():
                log(f"  {k}: {v}")

    # Salva state
    try:
        ctx.state.save(state_dir=os.path.join(ROOT, "state"))
        log("State salvato OK")
    except Exception as exc:
        log(f"[WARN] save state: {exc}")

    salva_log()

    sys.exit(0 if (result and result.success) else 1)


if __name__ == "__main__":
    main()
