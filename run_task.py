# ==============================================================================
#  DOOMSDAY ENGINE V6 — run_task.py
#
#  Runner isolato per test di singolo task su una istanza reale.
#  NON usa l'orchestrator né lo scheduler — esegue il task direttamente.
#
#  Uso:
#    cd C:\doomsday-engine
#    python run_task.py --istanza FAU_01 --task arena
#    python run_task.py --istanza FAU_00 --task zaino --force
#    python run_task.py --istanza FAU_00 --task zaino --force --dry-run
#
#  Opzioni:
#    --force     Ignora schedule (forza esecuzione anche se già eseguito oggi)
#    --dry-run   Solo simulazione: OCR + calcolo piano, nessun tap eseguito
#                Supportato da: ZainoTask (scan inventario + piano greedy)
#
#  Task disponibili:
#    boost, raccolta, rifornimento, zaino, vip, alleanza, messaggi,
#    arena, arena_mercato, store, radar, radar_census
#
#  FIX 14/04/2026:
#    - Schedule aggiornato con ISO string dopo run() OK
#    - Skip automatico se task daily già eseguito nelle ultime 24h
#    - --force ignora schedule
#    - --dry-run: solo simulazione (zaino: scan + piano, nessun tap)
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
os.chdir(ROOT)  # CWD = project root, indipendentemente da dove run_task.py è lanciato

from config.config_loader import load_global, build_instance_cfg

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

# Task con schedule daily (eseguiti una volta al giorno)
_DAILY_TASKS = {"vip", "arena", "arena_mercato", "boost", "store",
                "messaggi", "alleanza", "zaino", "radar"}

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
# Build TaskContext
# ---------------------------------------------------------------------------
def _build_ctx(ist: dict, gcfg, debug_dir: str):
    nome  = ist["nome"]
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)

    cfg = build_instance_cfg(ist, gcfg)

    try:
        from core.logger import get_logger
        logger = get_logger(nome, log_dir=debug_dir, console=False)
    except Exception as exc:
        log(f"[WARN] Logger: {exc} — logging disabilitato")
        logger = None

    try:
        from core.state import InstanceState
        state = InstanceState.load(nome, state_dir=os.path.join(ROOT, "state"))
    except Exception as exc:
        log(f"[WARN] InstanceState: {exc}")
        state = None

    try:
        from core.device import AdbDevice
        device = AdbDevice(host="127.0.0.1", port=porta)
        log(f"AdbDevice connesso: 127.0.0.1:{porta}")
    except Exception as exc:
        log(f"[ERRORE] AdbDevice: {exc}")
        device = None

    try:
        from shared.template_matcher import get_matcher
        matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
        log("TemplateMatcher OK")
    except Exception as exc:
        log(f"[ERRORE] TemplateMatcher: {exc}")
        matcher = None

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

    ctx = TaskContext(
        instance_name=nome,
        config=cfg,
        state=state,
        log=logger,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )

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
# Check schedule — emula logica orchestrator
# ---------------------------------------------------------------------------
def _check_schedule(ctx, nome_task: str, force: bool) -> bool:
    if force:
        log("[SCHEDULE] --force attivo — schedule ignorato")
        return True

    if ctx.state is None:
        return True

    ts = ctx.state.schedule.get(nome_task)
    if ts == 0.0:
        log("[SCHEDULE] Nessun run precedente registrato — procedo")
        return True

    elapsed_s = time.time() - ts
    elapsed_h = elapsed_s / 3600.0
    last_iso  = ctx.state.schedule.timestamps.get(nome_task, "?")

    if nome_task in _DAILY_TASKS:
        if elapsed_s < 86400:
            log(f"[SCHEDULE] Task daily '{nome_task}' già eseguito "
                f"{elapsed_h:.1f}h fa ({last_iso}) — SKIP")
            log(f"           Usa --force per forzare l'esecuzione")
            return False
        else:
            log(f"[SCHEDULE] Task daily '{nome_task}' ultimo run "
                f"{elapsed_h:.1f}h fa ({last_iso}) — procedo")
            return True

    log(f"[SCHEDULE] Task '{nome_task}' ultimo run "
        f"{elapsed_h:.1f}h fa ({last_iso}) — procedo")
    return True


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
    parser.add_argument("--force",   action="store_true", default=False,
                        help="Forza esecuzione ignorando lo schedule")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Simulazione: OCR + piano, nessun tap eseguito (solo zaino)")
    args = parser.parse_args()

    global _debug_dir
    _debug_dir = os.path.join(ROOT, "debug_task", args.task)
    os.makedirs(_debug_dir, exist_ok=True)

    modo = " [DRY-RUN]" if args.dry_run else ""
    separa(f"RUN TASK — {args.task.upper()} su {args.istanza}{modo}")
    log(f"Avvio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Debug dir: {_debug_dir}")
    if args.dry_run:
        log("*** MODALITÀ DRY-RUN: nessun tap verrà eseguito ***")

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
    gcfg = load_global()
    ctx  = _build_ctx(ist, gcfg, _debug_dir)
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
            log("[WARN] should_run() = False — task saltato (già eseguito, guard stato, o flag disabilitato in global_config.json)")
    except Exception as exc:
        log(f"[WARN] should_run() eccezione: {exc} — procedo comunque")

    # 4b. Schedule check
    separa("PASSO 4b — Schedule check")
    if not _check_schedule(ctx, args.task, args.force):
        log("Task saltato per schedule — uscita con codice 0")
        salva_log()
        sys.exit(0)

    # 5. Esecuzione
    separa(f"PASSO 5 — Esecuzione task '{args.task}'" +
           (" [DRY-RUN]" if args.dry_run else ""))
    t_start = time.time()
    try:
        # Passa dry_run al task se lo supporta
        if args.dry_run and hasattr(task, "run_dry"):
            result = task.run_dry(ctx)
        elif args.dry_run:
            log("[WARN] Task non supporta dry-run — esecuzione normale")
            result = task.run(ctx)
        else:
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

    # Salva state (solo se non dry-run)
    if not args.dry_run:
        try:
            if result and result.success:
                ctx.state.schedule.set(args.task, time.time())
                iso = ctx.state.schedule.timestamps.get(args.task, "?")
                log(f"Schedule aggiornato: {args.task} → {iso}")
            ctx.state.save(state_dir=os.path.join(ROOT, "state"))
            log("State salvato OK")
        except Exception as exc:
            log(f"[WARN] save state: {exc}")
    else:
        log("DRY-RUN: state non salvato")

    salva_log()

    sys.exit(0 if (result and result.success) else 1)


if __name__ == "__main__":
    main()
