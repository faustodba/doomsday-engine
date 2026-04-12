# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_task_base.py
#
#  Modulo di supporto per i test isolati di ogni singolo task.
#  Uso: importato da test_task_XX.py
#
#  Pattern:
#    1. Connette ADB all'istanza
#    2. Aspetta conferma manuale "sei in HOME?"
#    3. Costruisce TaskContext reale (AdbDevice + TemplateMatcher + Navigator)
#    4. Lancia il task
#    5. Stampa risultato e log
# ==============================================================================

from __future__ import annotations

import os
import sys
import time
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def build_ctx(istanza: str = "FAU_00", porta: int = 16384, dry_run: bool = False):
    """
    Costruisce un TaskContext reale per test isolato.
    Equivalente a main._build_ctx() ma standalone.
    """
    from core.task import TaskContext
    from core.logger import StructuredLogger
    from core.state import InstanceState

    log_dir = os.path.join(ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = StructuredLogger(istanza, log_dir=log_dir, console=True)
    state  = InstanceState(istanza)

    class _Cfg:
        def task_abilitato(self, n): return True
        def get(self, k, default=None): return default

    device   = None
    matcher  = None
    navigator = None

    if not dry_run:
        try:
            from core.device import AdbDevice
            device = AdbDevice(f"127.0.0.1:{porta}")
            print(f"[SETUP] ADB connesso: 127.0.0.1:{porta}")
        except Exception as exc:
            print(f"[WARN] AdbDevice non disponibile: {exc}")

        try:
            from shared.template_matcher import get_matcher
            tmpl_dir = os.path.join(ROOT, "templates")
            matcher = get_matcher(tmpl_dir)
            print(f"[SETUP] TemplateMatcher pronto: {tmpl_dir}")
        except Exception as exc:
            print(f"[WARN] TemplateMatcher non disponibile: {exc}")

        try:
            from core.navigator import GameNavigator
            navigator = GameNavigator(device=device, matcher=matcher)
            print(f"[SETUP] GameNavigator pronto")
        except Exception as exc:
            print(f"[WARN] GameNavigator non disponibile: {exc}")

    return TaskContext(
        instance_name=istanza,
        config=_Cfg(),
        state=state,
        log=logger,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


def attendi_home(task_name: str) -> None:
    """
    Pausa interattiva: chiede all'utente di portare l'istanza in HOME.
    Premere INVIO per procedere.
    """
    print()
    print("=" * 60)
    print(f"  TEST ISOLATO: {task_name.upper()}")
    print("=" * 60)
    print()
    print("  AZIONE RICHIESTA:")
    print("  1. Apri MuMu FAU_00")
    print("  2. Porta l'istanza manualmente in HOME")
    print("     (schermata principale con la mappa, icona home visibile)")
    print("  3. Premi INVIO per avviare il test")
    print()
    input("  >>> Premi INVIO quando sei in HOME: ")
    print()


def run_task_isolato(task, ctx, task_name: str) -> None:
    """
    Esegue un task singolo, stampa il risultato in modo leggibile.
    """
    print(f"[RUN] Avvio task '{task_name}'...")
    print(f"[RUN] {'─' * 50}")
    t0 = time.time()

    try:
        result = task.run(ctx)
        elapsed = time.time() - t0
        print(f"[RUN] {'─' * 50}")
        print(f"[RUN] Task completato in {elapsed:.1f}s")
        print(f"[RUN] success  = {result.success}")
        print(f"[RUN] message  = {result.message!r}")
        if result.data:
            print(f"[RUN] data     = {json.dumps(result.data, indent=2, default=str)}")
        print()
        if result.success:
            print(f"[OK] {task_name} completato con successo")
        else:
            print(f"[FAIL] {task_name} fallito: {result.message}")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"[RUN] {'─' * 50}")
        print(f"[EXCEPTION] {task_name} ha sollevato eccezione dopo {elapsed:.1f}s:")
        print(f"[EXCEPTION] {exc}")
        import traceback
        traceback.print_exc()

    print()
    print(f"[LOG] Vedi logs/{ctx.instance_name}.jsonl per il log completo")
