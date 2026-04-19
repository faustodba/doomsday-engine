# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_boost_live.py
#
#  Test isolato di BoostTask su FAU_00 reale.
#
#  Requisiti:
#    - FAU_00 deve essere GIA' IN HOME prima del lancio (non aggiustato dal test)
#    - ADB connesso, istanza MuMu avviata, porta da config/instances.json
#    - Python 3.14 (o compatibile), pacchetti requirements installati
#
#  Caratteristiche:
#    - Bypassa BoostTask.should_run() (esegue run() direttamente)
#    - navigator=None (nessun ensure_home → BoostTask salta il controllo HOME)
#    - Log in console con timestamp [HH:MM:SS]
#    - ctx.log_msg reindirizzato a console (niente file log)
#    - Nessuna modifica a BoostState su disco: il run() potrebbe scrivere
#      registra_attivo/registra_non_disponibile sullo stato in memoria, ma il
#      test NON salva lo state. Per una run ripetibile lo stato disco resta
#      intatto a meno di explicit state.save().
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_boost_live.py
#
#  Output:
#    Sequenza completa [BOOST] step-by-step + risultato finale.
#    Utile per isolare il problema "tap Gathering Speed non apre USE"
#    verificando il fix ricentro + polling timeout 4s in boost.py.
# ==============================================================================

from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime

# Forza UTF-8 su stdout/stderr per supportare caratteri Unicode nei log
# (es. frecce → usate in BoostState.log_stato()). Su Windows la console di
# default usa cp1252 che darebbe 'charmap' codec error.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                    errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                    errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)  # CWD = project root per path relativi

from config.config_loader import load_global, build_instance_cfg  # noqa: E402
from core.device import AdbDevice                                  # noqa: E402
from core.state import InstanceState                               # noqa: E402
from core.task import TaskContext                                  # noqa: E402
from shared.template_matcher import get_matcher                    # noqa: E402
from tasks.boost import BoostTask, BoostConfig                     # noqa: E402


ISTANZA = "FAU_00"
COUNTDOWN_SEC = 3


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def separa(titolo: str) -> None:
    print("", flush=True)
    log("=" * 62)
    log(f"  {titolo}")
    log("=" * 62)


def _carica_istanza(nome: str) -> dict | None:
    path = os.path.join(ROOT, "config", "instances.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze = json.load(f)
    except Exception as exc:
        log(f"[ERRORE] {path}: {exc}")
        return None
    for ist in istanze:
        if ist.get("nome") == nome:
            return ist
    log(f"[ERRORE] Istanza '{nome}' non trovata in instances.json")
    log(f"         Disponibili: {[i.get('nome') for i in istanze]}")
    return None


def main() -> int:
    separa(f"BOOST LIVE TEST — {ISTANZA}")

    # 1. Istanza
    ist = _carica_istanza(ISTANZA)
    if ist is None:
        return 1
    porta = ist.get("porta", 16384 + ist.get("indice", 0) * 32)
    log(f"Istanza caricata: porta=127.0.0.1:{porta}")

    # 2. Config globale + per istanza
    try:
        gcfg = load_global()
        cfg  = build_instance_cfg(ist, gcfg)
        log("Config caricata (global + instance)")
    except Exception as exc:
        log(f"[ERRORE] load_global/build_instance_cfg: {exc}")
        return 1

    # 3. Device ADB
    try:
        device = AdbDevice(host="127.0.0.1", port=porta)
        log(f"AdbDevice connesso (host=127.0.0.1 port={porta})")
    except Exception as exc:
        log(f"[ERRORE] AdbDevice: {exc}")
        return 1

    # 4. Matcher template
    try:
        matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
        log("TemplateMatcher OK")
    except Exception as exc:
        log(f"[ERRORE] TemplateMatcher: {exc}")
        return 1

    # 5. InstanceState (richiesto per BoostState)
    try:
        state = InstanceState.load(ISTANZA, state_dir=os.path.join(ROOT, "state"))
        log(f"State caricato — boost: {state.boost.log_stato()}")
    except Exception as exc:
        log(f"[ERRORE] InstanceState.load: {exc}")
        return 1

    # 6. TaskContext — navigator=None come da richiesta
    ctx = TaskContext(
        instance_name=ISTANZA,
        config=cfg,
        state=state,
        log=None,
        device=device,
        matcher=matcher,
        navigator=None,
    )

    # Reindirizza ctx.log_msg a console
    def _log_msg(msg: str, *args, level: str = "info") -> None:
        try:
            full = (msg % args) if args else msg
        except Exception:
            full = str(msg)
        log(full)

    ctx.log_msg = _log_msg  # type: ignore[assignment]

    # 7. Informativa + countdown
    separa("PRE-RUN")
    log("ATTENZIONE: FAU_00 deve essere gia' in HOME.")
    log(f"Avvio BoostTask.run() tra {COUNTDOWN_SEC}s ...")
    for i in range(COUNTDOWN_SEC, 0, -1):
        log(f"  {i}...")
        time.sleep(1)

    # 8. Bypass should_run() — esegui direttamente run()
    separa("RUN BoostTask")
    task = BoostTask(config=BoostConfig())

    t0 = time.time()
    try:
        result = task.run(ctx)
    except Exception as exc:
        log(f"[ECCEZIONE durante run()] {exc}")
        import traceback
        traceback.print_exc()
        return 2
    t1 = time.time()

    # 9. Risultato
    separa("RISULTATO")
    log(f"Durata:       {t1 - t0:.1f}s")
    log(f"Success:      {result.success}")
    log(f"Message:      {result.message}")
    log(f"Data:         {result.data}")
    log(f"Skipped:      {getattr(result, 'skipped', '?')}")
    log(f"State post:   boost: {state.boost.log_stato()}")
    log("")
    log("NOTA: lo state in memoria e' stato aggiornato da run() ma NON salvato.")
    log("Per persistenza: state.save(state_dir='state')")

    return 0 if result.success else 3


if __name__ == "__main__":
    sys.exit(main())
