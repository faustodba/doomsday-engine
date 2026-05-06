# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/truppe.py
#
#  Task: addestramento automatico delle 4 caserme (Infantry / Rider / Ranged /
#  Engine).
#
#  Scenario:
#    - 4 caserme fisse, una per tipologia (Fanteria, Cavalleria, Arcieri, Macchine)
#    - Sull'icona scudo+fucili nella colonna sx HOME compare il counter X/4 dove
#      X = numero caserme con addestramento in corso (0..4)
#    - Tap sull'icona pannello porta automaticamente alla prossima caserma libera
#
#  Flusso MVP:
#    1. Da HOME, leggi counter X via OCR sulla zona sotto l'icona pannello caserme
#    2. Se X == 4 → tutte impegnate → skip
#    3. Per (4 - X) volte:
#       a. tap (30, 247)  → naviga + seleziona prossima caserma libera
#       b. tap (564, 382) → cerchio "Train" del menu mappa → apre Squad Training
#       c. verifica checkbox "Fast Training" (676,497)→(699,518): se R-mean > 110
#          → tap (687, 508) per disabilitare (vincolo: SEMPRE OFF)
#       d. tap (794, 471) → pulsante TRAIN giallo → conferma addestramento
#    4. Re-leggi counter per verifica (best-effort)
#    5. Torna in HOME via tap_barra("city")
#
#  Coord (calibrate su FAU_05 — 960×540, layout standard):
#    _TAP_PANNELLO_CASERME = (30, 247)
#    _TAP_TRAIN_CIRCLE     = (564, 382)
#    _TAP_TRAIN_BUTTON     = (794, 471)
#    _TAP_CHECK_FAST       = (687, 508)
#    _BOX_CHECK_FAST       = (676, 497, 699, 518)  # sample area pixel
#    _ZONE_COUNTER_OCR     = (12, 264, 30, 282)    # zona prima cifra X
#
#  Vincoli:
#    - Checkbox "Fast Training" deve essere sempre DISABILITATO (premium-free)
#    - Le coord menu cerchio (564, 382) sono fisse: il sistema dopo (30, 247)
#      centra sempre la caserma in posizione stabile sullo schermo
#    - Counter X/4 sempre 4 al denominatore (caserme fisse 4 tipologie)
# ==============================================================================

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import numpy as np

from core.task import Task, TaskContext, TaskResult
from shared.ocr_helpers import ocr_cifre

if TYPE_CHECKING:
    pass


# ==============================================================================
# Coordinate UI (960×540)
# ==============================================================================

_TAP_PANNELLO_CASERME = (30, 247)
_TAP_TRAIN_CIRCLE     = (564, 382)
_TAP_TRAIN_BUTTON     = (794, 471)
_TAP_CHECK_FAST       = (687, 508)
_BOX_CHECK_FAST       = (676, 497, 699, 518)
_ZONE_COUNTER_OCR     = (12, 264, 30, 282)

_R_MEAN_THRESHOLD_ON  = 110     # R-mean del box checkbox: > soglia ⇒ ON

_DELAY_STEP_S         = 5.0     # delay tra tap calibrato in test FAU_05

_MAX_CASERME          = 4


# ==============================================================================
# TruppeTask
# ==============================================================================

class TruppeTask(Task):
    """
    Addestra le 4 caserme libere dell'istanza.
    Schedule: periodic (default 1h) — il guard `should_run` interno gestisce
    lo skip quando counter == 4/4.
    """

    def name(self) -> str:
        return "truppe"

    def should_run(self, ctx: TaskContext) -> bool:
        # Flag dashboard (`globali.task.truppe`). Lo scheduler valuta
        # poi anche il timing (interval_hours=4h). Il guard counter==4
        # è valutato in run() per evitare doppia screenshot.
        try:
            if not ctx.config.task_abilitato("truppe"):
                return False
        except Exception:
            pass
        return True

    # --------------------------------------------------------------------------
    # run
    # --------------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        # Pre: HOME stabile
        if ctx.navigator is not None:
            try:
                ctx.navigator.vai_in_home()
            except Exception as exc:
                ctx.log_msg("[TRUPPE] vai_in_home errore: %s", exc)
                return TaskResult.fail("vai_in_home fallito")

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.truppe)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("truppe", getattr(ctx, "instance_name", "_unknown"))
        self._dbg = debug   # accessibile da _esegui_ciclo per snap intermedi
        debug.snap("00_pre_counter_read", ctx.device.screenshot())

        # Lettura counter iniziale
        x = self._leggi_counter(ctx)
        if x is None:
            ctx.log_msg("[TRUPPE] counter X/4 non leggibile — skip")
            # Anomalia: counter non leggibile
            debug.flush(success=True, force=True, log_fn=ctx.log_msg)
            return TaskResult.skip("counter non leggibile")

        ctx.log_msg("[TRUPPE] counter iniziale = %d/%d", x, _MAX_CASERME)

        if x >= _MAX_CASERME:
            debug.clear()  # tutte impegnate, no anomalia
            return TaskResult.skip(f"tutte le caserme già impegnate ({x}/{_MAX_CASERME})")

        iterazioni = _MAX_CASERME - x
        ok = 0
        for i in range(iterazioni):
            ctx.log_msg("[TRUPPE] === ciclo %d/%d ===", i + 1, iterazioni)
            self._dbg_iter = i + 1   # passato a _esegui_ciclo via attributo
            esito = self._esegui_ciclo(ctx)
            if not esito:
                ctx.log_msg("[TRUPPE] ciclo %d FALLITO — interrompo", i + 1)
                debug.snap(f"99_ciclo{i+1}_fail", ctx.device.screenshot())
                break
            ok += 1

        debug.snap("01_post_loop", ctx.device.screenshot())

        # Lettura counter finale (best effort, no fail se OCR perde)
        x_final = self._leggi_counter(ctx)
        if x_final is not None:
            ctx.log_msg("[TRUPPE] counter finale = %d/%d (avviati %d)",
                        x_final, _MAX_CASERME, ok)

        # Ritorno HOME
        if ctx.navigator is not None:
            try:
                ctx.navigator.tap_barra(ctx, "city")
                time.sleep(1.5)
            except Exception:
                pass

        if ok == 0:
            debug.flush(success=False, log_fn=ctx.log_msg)
            return TaskResult.fail("nessuna caserma avviata")
        # Anomalia: avviate < target (interruzione mid-loop) OR debug toggle
        # attivato dalla dashboard (forza flush su success per analisi).
        anomalia = (ok < iterazioni)
        debug.flush(success=True, force=anomalia or debug.enabled, log_fn=ctx.log_msg)
        return TaskResult.ok(f"avviate {ok}/{iterazioni} caserme",
                             avviate=ok, target=iterazioni)

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _leggi_counter(self, ctx: TaskContext) -> int | None:
        """
        Legge la prima cifra X dal counter X/4 sotto l'icona pannello caserme.
        Tenta 2 preprocessor in cascata:
          - 'otsu'   → funziona per X ∈ {1,2,3,4}
          - 'binary' → fallback per X == 0 (otsu lo perde)
        Ritorna None se nessuno dei due legge una cifra valida.
        """
        if ctx.device is None:
            return None
        screen = ctx.device.screenshot()
        if screen is None:
            return None
        frame = screen.frame

        for preproc in ("otsu", "binary"):
            try:
                testo = ocr_cifre(frame, zone=_ZONE_COUNTER_OCR, preprocessor=preproc).strip()
            except Exception as exc:
                ctx.log_msg("[TRUPPE] OCR errore (%s): %s", preproc, exc)
                continue
            m = re.search(r"(\d)", testo)
            if not m:
                continue
            x = int(m.group(1))
            if 0 <= x <= _MAX_CASERME:
                return x
        return None

    def _checkbox_fast_training_on(self, ctx: TaskContext) -> bool:
        """True se il checkbox "Fast Training" è ON (R-mean del box > soglia)."""
        if ctx.device is None:
            return False
        screen = ctx.device.screenshot()
        if screen is None:
            return False
        frame = screen.frame
        x0, y0, x1, y1 = _BOX_CHECK_FAST
        try:
            patch = frame[y0:y1, x0:x1, :3]
            r_mean = float(patch[:, :, 0].mean())
        except Exception:
            return False
        return r_mean > _R_MEAN_THRESHOLD_ON

    def _esegui_ciclo(self, ctx: TaskContext) -> bool:
        """Un ciclo: tap pannello → tap cerchio Train → verifica check → tap TRAIN."""
        if ctx.device is None:
            return False
        dbg = getattr(self, "_dbg", None)
        idx = getattr(self, "_dbg_iter", 0)

        # 1. Tap icona pannello caserme — sistema centra prossima libera
        ctx.log_msg("[TRUPPE] tap pannello caserme %s", _TAP_PANNELLO_CASERME)
        ctx.device.tap(*_TAP_PANNELLO_CASERME)
        time.sleep(_DELAY_STEP_S)
        if dbg and dbg.enabled:
            dbg.snap(f"02_iter{idx}_post_pannello_caserme", ctx.device.screenshot())

        # 2. Tap cerchio "Train" del menu mappa → apre Squad Training
        ctx.log_msg("[TRUPPE] tap cerchio Train %s", _TAP_TRAIN_CIRCLE)
        ctx.device.tap(*_TAP_TRAIN_CIRCLE)
        time.sleep(_DELAY_STEP_S)
        # Snap maschera Squad Training: qui sono visibili le risorse consumate
        # per l'addestramento (target del consumo per scorporo prod_ora)
        if dbg and dbg.enabled:
            dbg.snap(f"03_iter{idx}_squad_training_panel", ctx.device.screenshot())

        # 3. Verifica checkbox Fast Training: se ON → tap per disabilitare
        if self._checkbox_fast_training_on(ctx):
            ctx.log_msg("[TRUPPE] checkbox Fast Training ON — disabilito %s",
                        _TAP_CHECK_FAST)
            ctx.device.tap(*_TAP_CHECK_FAST)
            time.sleep(_DELAY_STEP_S)
        else:
            ctx.log_msg("[TRUPPE] checkbox Fast Training OFF — ok")
        if dbg and dbg.enabled:
            dbg.snap(f"04_iter{idx}_pre_train_button", ctx.device.screenshot())

        # 4. Tap TRAIN giallo → conferma addestramento
        ctx.log_msg("[TRUPPE] tap TRAIN %s", _TAP_TRAIN_BUTTON)
        ctx.device.tap(*_TAP_TRAIN_BUTTON)
        time.sleep(_DELAY_STEP_S)

        return True
