# tasks/arena.py
"""
Step 16 — Arena of Glory (daily task).

Scheduling : daily, priority=20
Template dir: templates/pin/  (prefisso "pin/")

PIN usati
─────────────────────────────────────────────────────────────────────────────
  pin/pin_arena_01_lista.png      ROI=(387,  0, 565,  43)  soglia=0.80
  pin/pin_arena_02_challenge.png  ROI=(610,434, 857, 486)  soglia=0.80
  pin/pin_arena_03_victory.png    ROI=(407, 89, 557, 156)  soglia=0.80
  pin/pin_arena_04_failure.png    ROI=(414, 94, 544, 146)  soglia=0.80
  pin/pin_arena_05_continue.png   ROI=(410,443, 547, 487)  soglia=0.80  [diagnostico]
  pin/pin_arena_06_purchase.png   ROI=(334,143, 586, 185)  soglia=0.80
  pin/pin_arena_07_glory.png      ROI=(379,418, 564, 447)  soglia=0.80

Navigazione
─────────────────────────────────────────────────────────────────────────────
  HOME → tap Campaign → tap Arena of Doom → [gestisci popup] → lista sfide
  Sfide: tap ultima sfida → [check esaurite] → START CHALLENGE → attendi
         → tap-to-continue → [check glory post-sfida] → lista
  Ritorno: doppio tap centro + 4x BACK

Logica principale
─────────────────────────────────────────────────────────────────────────────
  3 tentativi esterni.  Per ogni tentativo:
    1. Verifica HOME via navigator
    2. Naviga verso lista arena
    3. Loop sfide (MAX_SFIDE)
       - "esaurite" → break immediato (successo)
       - "ok"       → contatore++
       - "errore"   → errori_consecutivi++; se ≥ 2 → abort tentativo
    4. Successo = esaurite OR sfide_eseguite >= MAX_SFIDE
  Post-tentativo: sempre torna HOME.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from core.task import Task, TaskContext, TaskResult
from core.navigator import GameNavigator, Screen
from shared.template_matcher import TemplateMatcher

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Costanti di coordinata (960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_CAMPAIGN        = (760, 505)   # bottone Campaign in home
_TAP_ARENA_OF_DOOM   = (480, 270)   # bottone Arena of Glory nella schermata Campaign
_TAP_ULTIMA_SFIDA    = (480, 350)   # ultima voce nella lista sfide
_TAP_START_CHALLENGE = (730, 460)   # bottone START CHALLENGE
_TAP_ESAURITE_CANCEL = (334, 380)   # Cancel nel popup "sfide esaurite"
_TAP_CONGRATULATIONS = (480, 440)   # Continue nel popup Congratulations generico
_TAP_GLORY_CONTINUE  = (471, 432)   # Continue nel popup Glory Silver

_TAP_CONTINUE_VICTORY = (457, 462)  # "Tap to continue" su schermata Victory
_TAP_CONTINUE_FAILURE = (469, 509)  # "Tap to continue" su schermata Failure
_TAP_CENTRO           = (480, 270)  # centro schermo (fallback)
_TAP_CENTRO_PAUSE     = 0.8         # pausa tra i due tap centro

# Parametri pixel per popup Congratulations generico
_CONGRATS_CHECK_XY  = (480, 300)
_CONGRATS_BGR_LOW   = np.array([200, 150,  50], dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array([255, 220, 130], dtype=np.uint8)

MAX_SFIDE = 5

# Timing battaglia
_DELAY_BATTAGLIA_S = 8.0    # sleep iniziale fisso post-tap START
_POLL_BATTAGLIA_S  = 3.0    # intervallo polling
_MAX_BATTAGLIA_S   = 30.0   # timeout polling

MAX_TENTATIVI         = 3
MAX_ERRORI_CONSEC     = 2


# ──────────────────────────────────────────────────────────────────────────────
# Configurazione template
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _PinSpec:
    path:   str
    roi:    tuple[int, int, int, int]
    soglia: float


_ARENA_PIN: dict[str, _PinSpec] = {
    "lista":    _PinSpec("pin/pin_arena_01_lista.png",     (387,  0,  565,  43), 0.80),
    "challenge":_PinSpec("pin/pin_arena_02_challenge.png", (610, 434, 857, 486), 0.80),
    "victory":  _PinSpec("pin/pin_arena_03_victory.png",   (407,  89, 557, 156), 0.80),
    "failure":  _PinSpec("pin/pin_arena_04_failure.png",   (414,  94, 544, 146), 0.80),
    "continue": _PinSpec("pin/pin_arena_05_continue.png",  (410, 443, 547, 487), 0.80),
    "purchase": _PinSpec("pin/pin_arena_06_purchase.png",  (334, 143, 586, 185), 0.80),
    "glory":    _PinSpec("pin/pin_arena_07_glory.png",     (379, 418, 564, 447), 0.80),
}


# ──────────────────────────────────────────────────────────────────────────────
# Stato interno run
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _ArenaRun:
    sfide_eseguite:   int  = 0
    esaurite:         bool = False
    errore:           str | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Task principale
# ──────────────────────────────────────────────────────────────────────────────

class ArenaTask(Task):
    """
    Arena of Glory — daily, priority=20.

    Implementa Task ABC da core/task.py.
    Usa FakeDevice-compatibile via ctx.device e ctx.matcher.
    """

    # ── Task ABC ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "arena"

    @property
    def schedule_type(self) -> Literal["daily", "periodic"]:
        return "daily"

    @property
    def priority(self) -> int:
        return 20

    def run(self, ctx: TaskContext) -> TaskResult:
        run = _ArenaRun()
        self._esegui(ctx, run)
        success = run.esaurite or run.sfide_eseguite >= MAX_SFIDE
        return TaskResult(
            success=success,
            data={
                "sfide_eseguite": run.sfide_eseguite,
                "esaurite":       run.esaurite,
                "errore":         run.errore,
            },
        )

    # ── Entry point interno ───────────────────────────────────────────────────

    def _esegui(self, ctx: TaskContext, run: _ArenaRun) -> None:
        logger.info("[ARENA] Avvio Arena of Glory (max %d sfide)", MAX_SFIDE)

        for tentativo in range(1, MAX_TENTATIVI + 1):
            logger.info("[ARENA] tentativo %d/%d", tentativo, MAX_TENTATIVI)

            # 1. Verifica HOME
            if not self._assicura_home(ctx):
                logger.warning("[ARENA] impossibile confermare home (t=%d)", tentativo)
                continue

            # 2. Naviga verso lista arena
            if not self._naviga_a_arena(ctx):
                logger.warning("[ARENA] lista arena non raggiunta (t=%d) — torno home", tentativo)
                self._torna_home(ctx)
                continue

            # 3. Loop sfide
            errore_loop: str | None = None
            errori_consec = 0

            for i in range(1, MAX_SFIDE + 1):
                esito = self._esegui_sfida(ctx, run, i)

                if esito == "esaurite":
                    run.esaurite = True
                    errori_consec = 0
                    break

                if esito == "ok":
                    run.sfide_eseguite += 1
                    errori_consec = 0
                    logger.info("[ARENA] Progresso: %d/%d", run.sfide_eseguite, MAX_SFIDE)
                    continue

                # esito == "errore"
                errori_consec += 1
                logger.warning("[ARENA] errore sfida %d (%d/%d consec.)",
                               i, errori_consec, MAX_ERRORI_CONSEC)
                if errori_consec >= MAX_ERRORI_CONSEC:
                    errore_loop = f"troppi errori consecutivi alla sfida {i}"
                    break
                time.sleep(2.0)

            # 4. Valuta successo
            successo = run.esaurite or run.sfide_eseguite >= MAX_SFIDE
            logger.info("[ARENA] t=%d sfide=%d esaurite=%s successo=%s",
                        tentativo, run.sfide_eseguite, run.esaurite, successo)

            self._torna_home(ctx)

            if successo:
                logger.info("[ARENA] completato ✓ — %d sfide%s",
                            run.sfide_eseguite,
                            " (esaurite)" if run.esaurite else "")
                return

            if errore_loop:
                run.errore = errore_loop
            logger.info("[ARENA] t=%d incompleto — %s",
                        tentativo,
                        "altro tentativo" if tentativo < MAX_TENTATIVI else "fallito")

        if not (run.sfide_eseguite > 0 or run.esaurite):
            logger.error("[ARENA] fallito dopo %d tentativi", MAX_TENTATIVI)
            if not run.errore:
                run.errore = "nessuna sfida eseguita dopo tutti i tentativi"

    # ── Navigazione ──────────────────────────────────────────────────────────

    def _assicura_home(self, ctx: TaskContext) -> bool:
        """
        Porta l'istanza in HOME usando il navigator V6.
        Ritorna True se HOME confermata entro 3 cicli.
        """
        nav: GameNavigator = ctx.navigator
        for ciclo in range(3):
            for _ in range(5):
                ctx.device.back()
                time.sleep(0.4)
            time.sleep(0.8)
            screen = ctx.device.screenshot()
            if screen is not None and nav.current_screen(screen) == Screen.HOME:
                logger.debug("[ARENA] home confermata (ciclo %d)", ciclo + 1)
                return True
            logger.debug("[ARENA] non in home (ciclo %d) — riprovo", ciclo + 1)
        logger.warning("[ARENA] impossibile confermare home dopo 3 cicli")
        return False

    def _naviga_a_arena(self, ctx: TaskContext) -> bool:
        """
        HOME → Campaign → Arena of Doom.
        Gestisce popup Glory Silver e Congratulations generico.
        Verifica pin_arena_01_lista (retry=2).
        Ritorna True se lista visibile.
        """
        logger.info("[ARENA] HOME → Campaign")
        ctx.device.tap(*_TAP_CAMPAIGN)
        time.sleep(3.0)

        logger.info("[ARENA] Campaign → Arena of Doom")
        ctx.device.tap(*_TAP_ARENA_OF_DOOM)
        time.sleep(3.5)

        # Gestione popup all'ingresso
        self._gestisci_popup_glory(ctx)
        self._gestisci_popup_congratulations(ctx)

        # Verifica lista arena
        ok = self._check_pin(ctx, "lista", retry=2, retry_s=2.0)
        if ok:
            logger.info("[ARENA] [PRE-LISTA] lista aperta OK")
        else:
            logger.warning("[ARENA] [PRE-LISTA] ANOMALIA: lista non rilevata")
        return ok

    def _torna_home(self, ctx: TaskContext) -> None:
        """
        Doppio tap centro + 4x BACK.
        Il doppio tap chiude overlay/risultati persistenti (fix FAU_07).
        """
        logger.info("[ARENA] ritorno HOME — doppio tap centro + BACK×4")
        self._doppio_tap_centro(ctx)
        time.sleep(1.5)
        for _ in range(4):
            ctx.device.back()
            time.sleep(0.8)

    # ── Sfida ─────────────────────────────────────────────────────────────────

    def _esegui_sfida(self,
                      ctx: TaskContext,
                      run: _ArenaRun,
                      n: int,
                      ) -> Literal["ok", "esaurite", "errore"]:
        """
        Esegue una singola sfida arena.

        Ritorna:
          "esaurite" — popup acquisto sfide rilevato (stop loop)
          "ok"       — sfida completata (victory o failure)
          "errore"   — anomalia (lista non visibile, challenge non visibile)
        """
        logger.info("[ARENA] sfida %d/%d", n, MAX_SFIDE)

        # GUARD-GLORY: popup Glory può comparire tra sfide (cambio tier mid-session)
        screen_guard = ctx.device.screenshot()
        if screen_guard is not None and self._match(ctx, screen_guard, "glory"):
            logger.info("[ARENA] [GUARD-GLORY] popup Glory pre-sfida — chiudo")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)

        # PRE-SFIDA: lista visibile?
        if not self._check_pin(ctx, "lista", retry=1, retry_s=1.5):
            logger.warning("[ARENA] [PRE-SFIDA] lista non visibile — abort sfida")
            return "errore"

        ctx.device.tap(*_TAP_ULTIMA_SFIDA)
        time.sleep(3.0)

        # CHECK-PURCHASE: sfide esaurite?
        if self._check_pin(ctx, "purchase", retry=1, retry_s=1.0):
            logger.info("[ARENA] [CHECK-PURCHASE] sfide esaurite → Cancel")
            ctx.device.tap(*_TAP_ESAURITE_CANCEL)
            time.sleep(1.5)
            return "esaurite"

        # PRE-CHALLENGE: START CHALLENGE visibile?
        if not self._check_pin(ctx, "challenge", retry=2, retry_s=1.5):
            logger.warning("[ARENA] [PRE-CHALLENGE] START CHALLENGE non visibile — abort")
            ctx.device.back()
            time.sleep(1.5)
            return "errore"

        logger.info("[ARENA] [PRE-CHALLENGE] START CHALLENGE — tap")
        ctx.device.tap(*_TAP_START_CHALLENGE)

        # Attesa battaglia
        victory, failure = self._attendi_fine_battaglia(ctx)

        if victory:
            logger.info("[ARENA] [POST-BATTAGLIA] Victory ✓")
        elif failure:
            logger.info("[ARENA] [POST-BATTAGLIA] Failure")
        else:
            logger.warning("[ARENA] [POST-BATTAGLIA] timeout — né Victory né Failure")

        # Diagnostico: pin_continue (solo logging)
        screen_diag = ctx.device.screenshot()
        if screen_diag is not None:
            ok_cont = self._match(ctx, screen_diag, "continue")
            logger.debug("[ARENA] [PRE-CONTINUE] pin_arena_05=%s", ok_cont)

        # Tap "Tap to continue" con coordinata dipendente dal risultato
        if victory:
            logger.info("[ARENA] [CONTINUE] Victory → tap %s", _TAP_CONTINUE_VICTORY)
            ctx.device.tap(*_TAP_CONTINUE_VICTORY)
        elif failure:
            logger.info("[ARENA] [CONTINUE] Failure → tap %s", _TAP_CONTINUE_FAILURE)
            ctx.device.tap(*_TAP_CONTINUE_FAILURE)
        else:
            logger.info("[ARENA] [CONTINUE] fallback → doppio tap centro")
            self._doppio_tap_centro(ctx)
        time.sleep(2.5)

        # POST-CONTINUE: popup Glory post-vittoria (cambio tier)?
        screen_post = ctx.device.screenshot()
        if screen_post is not None and self._match(ctx, screen_post, "glory"):
            logger.info("[ARENA] [POST-CONTINUE] popup Glory — chiudo")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)

        # Verifica ritorno lista
        if not self._check_pin(ctx, "lista", retry=2, retry_s=1.5):
            logger.info("[ARENA] [POST-CONTINUE] lista non tornata — retry dopo 2s")
            time.sleep(2.0)
            if not self._check_pin(ctx, "lista", retry=2, retry_s=1.5):
                logger.warning("[ARENA] [POST-CONTINUE] lista ancora non visibile — procedo comunque")

        return "ok"

    # ── Popup helpers ─────────────────────────────────────────────────────────

    def _gestisci_popup_glory(self, ctx: TaskContext) -> bool:
        """
        Rileva e chiude popup "Congratulations / Glory Silver" (pin_arena_07_glory).
        Ritorna True se il popup era presente.
        """
        screen = ctx.device.screenshot()
        if screen is None:
            return False
        if not self._match(ctx, screen, "glory"):
            return False

        logger.info("[ARENA] popup Glory Silver — tap Continue")
        ctx.device.tap(*_TAP_GLORY_CONTINUE)
        time.sleep(2.0)

        # Riverifica
        screen2 = ctx.device.screenshot()
        if screen2 is not None and self._match(ctx, screen2, "glory"):
            logger.info("[ARENA] popup Glory ancora visibile — retry tap")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)
        return True

    def _gestisci_popup_congratulations(self, ctx: TaskContext) -> bool:
        """
        Controllo pixel per popup Congratulations generico.
        Ritorna True se il popup era presente.
        """
        screen = ctx.device.screenshot()
        if screen is None:
            return False

        import cv2
        img = ctx.device.last_frame  # numpy array BGR già in memoria
        if img is None:
            return False

        px, py = _CONGRATS_CHECK_XY
        pixel = img[py, px]
        if np.all(pixel >= _CONGRATS_BGR_LOW) and np.all(pixel <= _CONGRATS_BGR_HIGH):
            logger.info("[ARENA] popup Congratulations (pixel) — tap Continue")
            ctx.device.tap(*_TAP_CONGRATULATIONS)
            time.sleep(2.0)
            return True
        return False

    # ── Battaglia ─────────────────────────────────────────────────────────────

    def _attendi_fine_battaglia(self, ctx: TaskContext) -> tuple[bool, bool]:
        """
        Attesa fine battaglia: delay iniziale fisso + polling adattivo.

        Returns:
            (victory, failure) — entrambi False = timeout/anomalia.
        """
        logger.info("[ARENA] attesa battaglia — delay iniziale %.0fs", _DELAY_BATTAGLIA_S)
        time.sleep(_DELAY_BATTAGLIA_S)

        t_start = time.time()
        while time.time() - t_start < _MAX_BATTAGLIA_S:
            screen = ctx.device.screenshot()
            if screen is not None:
                victory = self._match(ctx, screen, "victory")
                failure = self._match(ctx, screen, "failure")
                elapsed = _DELAY_BATTAGLIA_S + (time.time() - t_start)
                if victory or failure:
                    logger.info("[ARENA] fine battaglia in %.1fs totali", elapsed)
                    return victory, failure
            time.sleep(_POLL_BATTAGLIA_S)

        totale = _DELAY_BATTAGLIA_S + _MAX_BATTAGLIA_S
        logger.warning("[ARENA] timeout battaglia dopo %.0fs", totale)
        return False, False

    # ── Primitivi template matching ───────────────────────────────────────────

    def _match(self, ctx: TaskContext, screen: object, key: str) -> bool:
        """
        Template matching su un singolo pin.
        screen può essere il path (str) o il frame numpy a seconda dell'implementazione.
        """
        spec = _ARENA_PIN[key]
        score = ctx.matcher.match(screen, spec.path, spec.roi)
        ok = score >= spec.soglia
        logger.debug("[ARENA-PIN] %s: score=%.3f → %s", key, score, "OK" if ok else "NON trovato")
        return ok

    def _check_pin(self,
                   ctx: TaskContext,
                   key: str,
                   retry: int = 1,
                   retry_s: float = 1.5,
                   ) -> bool:
        """
        Screenshot + match con retry.
        Ritorna True al primo match superato.
        """
        for tentativo in range(retry + 1):
            screen = ctx.device.screenshot()
            if screen is None:
                logger.debug("[ARENA-PIN] %s: screenshot fallito (t=%d)", key, tentativo + 1)
                time.sleep(retry_s)
                continue
            ok = self._match(ctx, screen, key)
            if ok or tentativo == retry:
                return ok
            time.sleep(retry_s)
        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    def _doppio_tap_centro(self, ctx: TaskContext) -> None:
        """Doppio tap al centro schermo per chiudere overlay/risultati persistenti."""
        ctx.device.tap(*_TAP_CENTRO)
        time.sleep(_TAP_CENTRO_PAUSE)
        ctx.device.tap(*_TAP_CENTRO)
