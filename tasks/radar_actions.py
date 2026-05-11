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

def _is_card_popup_open(ctx: TaskContext, log_fn) -> bool:
    """
    Detect popup card (Protect Survivors / Assist Ally / ...) gia' aperto.
    Pixel test su ROI (90,465) bottone GO arancione/giallo brillante.
    Su mappa radar pulita quell'area e' terreno marrone scuro.
    Fail-safe False (no false-positive sui ritorni).
    """
    try:
        screen = ctx.device.screenshot()
        frame = _frame_from_screenshot(screen)
        if frame is None:
            return False
        gx, gy = RADAR_GO_TAP
        # ROI piccola 11x11 attorno a GO_TAP
        y1 = max(0, gy - 5)
        y2 = min(frame.shape[0], gy + 6)
        x1 = max(0, gx - 5)
        x2 = min(frame.shape[1], gx + 6)
        roi = frame[y1:y2, x1:x2, :3]
        if roi.size == 0:
            return False
        b_mean = float(roi[:, :, 0].mean())
        g_mean = float(roi[:, :, 1].mean())
        r_mean = float(roi[:, :, 2].mean())
        # Bottone GO: arancione/giallo brillante (R molto alto, B basso, R>>B)
        is_button = (r_mean > 140 and (r_mean - b_mean) > 50)
        if is_button:
            log_fn(f"[POPUP-CHECK] GO ROI BGR=({b_mean:.0f},{g_mean:.0f},{r_mean:.0f}) -> popup OPEN")
        return is_button
    except Exception as exc:
        log_fn(f"[POPUP-CHECK] errore (fail-safe False): {exc}")
        return False


def _resolve_card_popup(ctx: TaskContext, log_fn) -> bool:
    """
    Risolve popup card gia' aperto: GO -> RESCUE -> tap RADAR_ICON.
    Step da chiamare DOPO che il popup e' stato aperto (manualmente o via tap card).
    """
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


def handle_card(ctx: TaskContext, cx: int, cy: int, log_fn) -> bool:
    """
    Handler categoria 'card' (Protect Survivors / Assist Ally / ...).
    Sequenza: tap card -> wait -> _resolve_card_popup (GO + RESCUE + RADAR_ICON).
    Ritorna True se la sequenza e' completata senza eccezioni.
    """
    log_fn(f"[CARD] tap card ({cx},{cy})")
    ctx.device.tap(cx, cy)
    time.sleep(RADAR_DELAY_UI_S)
    return _resolve_card_popup(ctx, log_fn)


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

    Pre-step: detect popup card aperto (residuo ciclo precedente) -> risolvi.

    Itera:
      1. _loop_pallini (tappa tutti i pallini rossi visibili)
      2. wait RADAR_POST_PALLINI_DELAY_S
      3. census icone -> filtra actionable
      4. dispatch ogni record -> handler categoria
      5. stop se 0 pallini AND 0 actionable in stessa iterazione
      6. safety break se N iter consecutivi con pallini>0 ma 0 processed (loop sterile)

    Ritorna dict con totali per telemetria:
      {pallini_tappati: int, card_processate: int, loops: int, popup_pre_resolved: bool, stagnant_abort: bool}
    """
    from tasks.radar import RadarTask

    radar_task = RadarTask()
    totals = {
        "pallini_tappati":     0,
        "card_processate":     0,
        "loops":               0,
        "popup_pre_resolved":  False,
        "stagnant_abort":      False,
    }

    # FIX A: pre-check popup card (residuo da ciclo precedente o stato iniziale)
    log_fn("[FIX-A] pre-check popup card aperto...")
    if _is_card_popup_open(ctx, log_fn):
        log_fn("[FIX-A] popup card aperto - risolvo prima del loop")
        try:
            _resolve_card_popup(ctx, log_fn)
            totals["popup_pre_resolved"] = True
            totals["card_processate"] += 1
        except Exception as exc:
            log_fn(f"[FIX-A] errore resolve popup: {exc}")
    else:
        log_fn("[FIX-A] no popup aperto, procedo con loop normale")

    # FIX B safety state
    last_pallini = -1
    stagnant_iter = 0
    MAX_STAGNANT = 2

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
                if record.get("categoria") == "card":
                    totals["card_processate"] += 1

        # Step 5: stop normale
        if n_pallini == 0 and n_processed == 0:
            log_fn(f"\n[FINE] iter {i}: 0 pallini + 0 actionable -> radar pulito")
            break

        # FIX B: safety break loop sterile (pallini>0 ma 0 card processate, ripetuto)
        if n_pallini > 0 and n_processed == 0:
            if n_pallini == last_pallini:
                stagnant_iter += 1
                log_fn(f"[SAFETY] iter stagnante {stagnant_iter}/{MAX_STAGNANT} "
                       f"(pallini={n_pallini} repeat, no card)")
                if stagnant_iter >= MAX_STAGNANT:
                    log_fn(f"[SAFETY] abort: {MAX_STAGNANT} iter consecutivi senza progresso "
                           f"-> probabile popup intercetta tap")
                    totals["stagnant_abort"] = True
                    # Tentativo recovery: se popup aperto, risolvilo
                    if _is_card_popup_open(ctx, log_fn):
                        log_fn("[SAFETY] popup detected post-abort - tentativo resolve")
                        try:
                            _resolve_card_popup(ctx, log_fn)
                            totals["card_processate"] += 1
                        except Exception as exc:
                            log_fn(f"[SAFETY] resolve fallito: {exc}")
                    break
            else:
                stagnant_iter = 0
        else:
            stagnant_iter = 0
        last_pallini = n_pallini
    else:
        log_fn(f"\n[STOP] max_loops={RADAR_MAX_LOOPS} raggiunto (safety)")

    log_fn(f"\nTotali: loops={totals['loops']} "
           f"pallini={totals['pallini_tappati']} "
           f"card={totals['card_processate']} "
           f"popup_pre={totals['popup_pre_resolved']} "
           f"stagnant_abort={totals['stagnant_abort']}")
    return totals
