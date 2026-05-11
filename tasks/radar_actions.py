# ==============================================================================
# DOOMSDAY ENGINE V6 -- tasks/radar_actions.py
#
# Radar Actions -- orchestratore loop azioni post-apertura radar.
#
# Flusso completo (chiamato da RadarTask dopo aver aperto la mappa radar):
#   1. Tap tutti i pallini rossi visibili (_loop_pallini di RadarTask)
#   2. Wait 10s (animazioni gioco / nuovi pallini possono comparire)
#   3. Census icone -> identifica categoria di ogni pin via RadarCensusTask
#   4. Dispatch per categoria -> handler specifico (card -> GO+RESCUE)
#   5. Ripeti finche 0 pallini AND 0 record actionable (max 10 iter safety)
#
# Categorie attualmente gestite:
#   card     -> handle_card (GO + RESCUE + ritorno mappa radar)
#
# Categorie con handler placeholder (TODO):
#   skull, pedone, soldati, avatar, paracadute, camion, fiamma, bottiglia, numero, auto
#
# Coord fisse calibrate 960x540 (FAU_01 11/05/2026):
#   RADAR_GO_TAP     = (90, 465)   bottone GO sul popup Protect Survivors
#   RADAR_RESCUE_TAP = (233, 386)  bottone RESCUE sulla schermata selezione truppe
#   RADAR_ICON_TAP   = (78, 315)   icona Radar Station (riapre mappa)
# ==============================================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np

from core.task import TaskContext
from tasks.radar_census import RadarCensusTask


# Coord fisse (960x540) -- validate live su FAU_01 11/05/2026
RADAR_GO_TAP             = (90, 465)
RADAR_RESCUE_TAP         = (233, 386)
RADAR_ICON_TAP           = (78, 315)

# Timing
RADAR_POST_PALLINI_DELAY_S = 10.0   # attesa post _loop_pallini (animazioni)
RADAR_DELAY_UI_S           = 2.5    # DELAY UI vincolante CLAUDE.md

# Safety
RADAR_MAX_LOOPS = 10


def _frame_from_screenshot(screen):
    if screen is None:
        return None
    f = getattr(screen, "frame", None)
    if f is not None:
        return f
    if isinstance(screen, np.ndarray):
        return screen
    return None


# ------------------------------------------------------------------------------
# Handler per categoria
# ------------------------------------------------------------------------------

def handle_card(ctx: TaskContext, cx: int, cy: int, log_fn) -> bool:
    """
    Handler categoria 'card' (Protect Survivors).
    Sequenza: tap card -> wait -> tap GO -> wait -> tap RESCUE -> wait -> tap RADAR_ICON.
    Ritorna True se la sequenza e completata senza eccezioni.
    """
    log_fn(f"[CARD] tap card ({cx},{cy})")
    ctx.device.tap(cx, cy)
    time.sleep(RADAR_DELAY_UI_S)

    log_fn(f"[CARD] tap GO {RADAR_GO_TAP}")
    ctx.device.tap(*RADAR_GO_TAP)
    time.sleep(RADAR_DELAY_UI_S)

    log_fn(f"[CARD] tap RESCUE {RADAR_RESCUE_TAP}")
    ctx.device.tap(*RADAR_RESCUE_TAP)
    time.sleep(RADAR_DELAY_UI_S)

    log_fn(f"[CARD] tap RADAR_ICON {RADAR_ICON_TAP} (ritorno mappa)")
    ctx.device.tap(*RADAR_ICON_TAP)
    time.sleep(RADAR_DELAY_UI_S)

    return True


# Dispatcher: categoria -> handler. Solo le categorie qui presenti vengono processate.
HANDLERS: dict[str, Callable] = {
    "card": handle_card,
    # "skull":      handle_skull,      # TODO mappare azione
    # "pedone":     handle_pedone,     # TODO mappare azione
    # "soldati":    handle_soldati,    # TODO mappare azione
    # "avatar":     handle_avatar,     # TODO mappare azione
    # "paracadute": handle_paracadute, # TODO mappare azione
    # "camion":     handle_camion,     # TODO mappare azione
    # "fiamma":     handle_fiamma,     # TODO mappare azione
    # "bottiglia":  handle_bottiglia,  # TODO mappare azione
    # "numero":     handle_numero,     # TODO mappare azione
    # "auto":       handle_auto,       # TODO mappare azione
}


def dispatch_record(ctx: TaskContext, record: dict, log_fn) -> bool:
    """Esegue handler per un record census se categoria nota e ready=True."""
    cat = record.get("categoria", "")
    n = record.get("n", "?")
    if not record.get("ready"):
        log_fn(f"  skip n={n} ready=False (cat={cat})")
        return False
    handler = HANDLERS.get(cat)
    if handler is None:
        log_fn(f"  skip n={n} categoria '{cat}' no handler")
        return False
    cx = int(record.get("cx", 0))
    cy = int(record.get("cy", 0))
    log_fn(f"  dispatch n={n} -> {cat}({cx},{cy})")
    try:
        return handler(ctx, cx, cy, log_fn)
    except Exception as exc:
        log_fn(f"  ERRORE handler {cat}: {exc}")
        return False


# ------------------------------------------------------------------------------
# Census filtrato
# ------------------------------------------------------------------------------

def _run_census_actionable(ctx: TaskContext, log_fn) -> list[dict]:
    """Esegue RadarCensusTask e ritorna solo record ready con handler disponibile."""
    census = RadarCensusTask()
    res = census.run(ctx)
    if not res.success:
        log_fn(f"[CENSUS] fail: {res.message}")
        return []
    out_dir = res.data.get("output_dir") if res.data else None
    if not out_dir:
        log_fn("[CENSUS] no output_dir")
        return []
    cj = Path(out_dir) / "census.json"
    if not cj.is_file():
        log_fn(f"[CENSUS] census.json non trovato in {out_dir}")
        return []
    try:
        with open(cj, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as exc:
        log_fn(f"[CENSUS] errore lettura: {exc}")
        return []
    actionable = [
        r for r in records
        if r.get("ready") and r.get("categoria") in HANDLERS
    ]
    log_fn(f"[CENSUS] {len(records)} icone totali, {len(actionable)} actionable")
    return actionable


# ------------------------------------------------------------------------------
# Orchestratore loop
# ------------------------------------------------------------------------------

def process_radar_actions(ctx: TaskContext, log_fn) -> dict:
    """
    Loop principale azioni radar.

    Itera:
      1. _loop_pallini (tappa tutti i pallini rossi visibili)
      2. wait RADAR_POST_PALLINI_DELAY_S
      3. census icone -> filtra actionable
      4. dispatch ogni record -> handler categoria
      5. stop se 0 pallini AND 0 actionable in stessa iterazione

    Ritorna dict con totali per telemetria:
      {pallini_tappati: int, card_processate: int, loops: int}
    """
    from tasks.radar import RadarTask

    radar_task = RadarTask()
    totals = {
        "pallini_tappati": 0,
        "card_processate": 0,
        "loops":           0,
    }

    for i in range(1, RADAR_MAX_LOOPS + 1):
        totals["loops"] = i
        log_fn(f"\n-- ITER {i}/{RADAR_MAX_LOOPS} --")

        # Step 1: tap pallini
        try:
            n_pallini = radar_task._loop_pallini(ctx, log_fn)
        except Exception as exc:
            log_fn(f"[PALLINI] errore loop: {exc}")
            n_pallini = 0
        totals["pallini_tappati"] += n_pallini

        # Step 2: wait
        log_fn(f"[WAIT] {RADAR_POST_PALLINI_DELAY_S}s (animazioni gioco)")
        time.sleep(RADAR_POST_PALLINI_DELAY_S)

        # Step 3-4: census + dispatch
        actionable = _run_census_actionable(ctx, log_fn)
        n_processed = 0
        for record in actionable:
            if dispatch_record(ctx, record, log_fn):
                n_processed += 1
                # Conta per categoria
                if record.get("categoria") == "card":
                    totals["card_processate"] += 1

        # Step 5: stop condition
        if n_pallini == 0 and n_processed == 0:
            log_fn(f"\n[FINE] iter {i}: 0 pallini + 0 actionable -> radar pulito")
            break
    else:
        log_fn(f"\n[STOP] max_loops={RADAR_MAX_LOOPS} raggiunto (safety)")

    log_fn(f"\nTotali: loops={totals['loops']} "
           f"pallini={totals['pallini_tappati']} "
           f"card={totals['card_processate']}")
    return totals
