# tasks/arena.py
"""
Step 16 — Arena of Glory.

Scheduling : always-run (interval=0.0), priority=50
Guard      : ctx.state.arena.should_run() — skip se sfide esaurite oggi
Reset      : automatico a mezzanotte UTC via ArenaState._controlla_reset()
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
    1. Verifica HOME via navigator.vai_in_home()
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
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from core.task import Task, TaskContext, TaskResult


# ──────────────────────────────────────────────────────────────────────────────
# Costanti di coordinata (960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_CAMPAIGN        = (584, 486)   # bottone Campaign in home (layout 1 standard)
_TAP_ARENA_OF_DOOM   = (321, 297)   # card Arena of Doom nella schermata Campaign
_TAP_ULTIMA_SFIDA    = (745, 482)   # pulsante Challenge ultima riga lista (V5 config)
_TAP_START_CHALLENGE = (730, 451)   # bottone START CHALLENGE (V5 config)
_TAP_ESAURITE_CANCEL = (334, 380)   # Cancel nel popup "sfide esaurite"
_TAP_CONGRATULATIONS = (480, 440)   # Continue nel popup Congratulations generico
_TAP_GLORY_CONTINUE  = (471, 432)   # Continue nel popup Glory Silver

_TAP_CONTINUE_VICTORY = (457, 462)  # "Tap to continue" su schermata Victory
_TAP_CONTINUE_FAILURE = (469, 509)  # "Tap to continue" su schermata Failure
_TAP_CENTRO           = (480, 270)  # centro schermo (fallback)
_TAP_CENTRO_PAUSE     = 0.8         # pausa tra i due tap centro
_TAP_SKIP_CHECKBOX    = (723, 488)  # checkbox Skip (salta animazione battaglia)

# Parametri pixel per popup Congratulations generico
_CONGRATS_CHECK_XY  = (480, 300)
_CONGRATS_BGR_LOW   = np.array([200, 150,  50], dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array([255, 220, 130], dtype=np.uint8)

MAX_SFIDE = 5

# Timing battaglia
_DELAY_BATTAGLIA_S = 8.0    # sleep iniziale fisso post-tap START
_POLL_BATTAGLIA_S  = 3.0    # intervallo polling
_MAX_BATTAGLIA_S   = 15.0   # timeout polling

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
    "skip_on":  _PinSpec("pin/pin_arena_check.png",        (700, 470, 760, 510), 0.75),
    "skip_off": _PinSpec("pin/pin_arena_no_check.png",     (700, 470, 760, 510), 0.75),
}


# ──────────────────────────────────────────────────────────────────────────────
# Stato interno run
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _ArenaRun:
    sfide_eseguite:   int  = 0
    esaurite:         bool = False
    errore:           str | None = None
    skip_verificato:  bool = False


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

    def name(self) -> str:
        return "arena"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("arena"):
                return False
        # Guard ArenaState: skip se sfide già esaurite oggi
        stato = ctx.state.arena.log_stato()
        if not ctx.state.arena.should_run():
            ctx.log_msg("[ARENA] %s → skip", stato)
            return False
        ctx.log_msg("[ARENA] %s → eseguo", stato)
        return True

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
        ctx.log_msg("[ARENA] Avvio Arena of Glory (max %d sfide)", MAX_SFIDE)

        for tentativo in range(1, MAX_TENTATIVI + 1):
            ctx.log_msg("[ARENA] tentativo %d/%d", tentativo, MAX_TENTATIVI)

            # 1. Verifica HOME — FIX: usa vai_in_home() invece di current_screen()
            if not self._assicura_home(ctx):
                ctx.log_msg("[ARENA] impossibile confermare home (t=%d)", tentativo)
                continue

            # 2. Naviga verso lista arena
            if not self._naviga_a_arena(ctx):
                ctx.log_msg("[ARENA] lista arena non raggiunta (t=%d) — torno home", tentativo)
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
                    ctx.state.arena.segna_esaurite()
                    ctx.log_msg("[ARENA] sfide esaurite → ArenaState aggiornato")
                    break

                if esito == "ok":
                    run.sfide_eseguite += 1
                    errori_consec = 0
                    ctx.log_msg("[ARENA] Progresso: %d/%d", run.sfide_eseguite, MAX_SFIDE)
                    continue

                # esito == "errore"
                errori_consec += 1
                ctx.log_msg("[ARENA] errore sfida %d (%d/%d consec.)",
                               i, errori_consec, MAX_ERRORI_CONSEC)
                if errori_consec >= MAX_ERRORI_CONSEC:
                    errore_loop = f"troppi errori consecutivi alla sfida {i}"
                    break
                time.sleep(2.0)

            # 4. Valuta successo
            successo = run.esaurite or run.sfide_eseguite >= MAX_SFIDE
            ctx.log_msg("[ARENA] t=%d sfide=%d esaurite=%s successo=%s",
                        tentativo, run.sfide_eseguite, run.esaurite, successo)

            self._torna_home(ctx)

            if successo:
                ctx.log_msg("[ARENA] completato ✓ — %d sfide%s",
                            run.sfide_eseguite,
                            " (esaurite)" if run.esaurite else "")
                return

            if errore_loop:
                run.errore = errore_loop
            ctx.log_msg("[ARENA] t=%d incompleto — %s",
                        tentativo,
                        "altro tentativo" if tentativo < MAX_TENTATIVI else "fallito")

        if not (run.sfide_eseguite > 0 or run.esaurite):
            ctx.log_msg("[ARENA] fallito dopo %d tentativi", MAX_TENTATIVI)
            if not run.errore:
                run.errore = "nessuna sfida eseguita dopo tutti i tentativi"

    # ── Navigazione ──────────────────────────────────────────────────────────

    def _assicura_home(self, ctx: TaskContext) -> bool:
        """
        Porta l'istanza in HOME usando il navigator V6.
        FIX: usa ctx.navigator.vai_in_home() — GameNavigator non espone current_screen().
        """
        if ctx.navigator is not None:
            ok = ctx.navigator.vai_in_home()
            if ok:
                ctx.log_msg("[ARENA] home confermata via navigator")
            else:
                ctx.log_msg("[ARENA] navigator: vai_in_home() fallito — BACK di recupero")
                for _ in range(5):
                    ctx.device.back()
                    time.sleep(0.4)
            return ok

        # Fallback senza navigator: sequenza BACK
        for ciclo in range(3):
            for _ in range(5):
                ctx.device.back()
                time.sleep(0.4)
            time.sleep(0.8)
            ctx.log_msg("[ARENA] home fallback ciclo %d", ciclo + 1)
        return True  # ottimistico senza navigator

    def _naviga_a_arena(self, ctx: TaskContext) -> bool:
        """
        HOME → Campaign → Arena of Doom.
        Gestisce popup Glory Silver e Congratulations generico.
        Verifica pin_arena_01_lista (retry=2).
        Ritorna True se lista visibile.

        FIX 13/04/2026: tap Campaign via template matching (tap_barra) invece di
        coordinate fisse (_TAP_CAMPAIGN=584,486). FAU_10 ha layout diverso
        (bottone Beast assente → icone shiftate). Fallback su _TAP_CAMPAIGN se
        navigator non disponibile o tap_barra fallisce.
        """
        ctx.log_msg("[ARENA] HOME → Campaign")
        _navigato = False
        if ctx.navigator is not None and hasattr(ctx.navigator, "tap_barra"):
            _navigato = ctx.navigator.tap_barra(ctx, "campaign")
        if not _navigato:
            ctx.log_msg("[ARENA] tap_barra fallback → coordinate fisse %s", _TAP_CAMPAIGN)
            ctx.device.tap(*_TAP_CAMPAIGN)
        time.sleep(3.0)

        ctx.log_msg("[ARENA] Campaign → Arena of Doom")
        ctx.device.tap(*_TAP_ARENA_OF_DOOM)
        time.sleep(3.5)

        # Gestione popup all'ingresso
        self._gestisci_popup_glory(ctx)
        self._gestisci_popup_congratulations(ctx)

        # Verifica lista arena
        ok = self._check_pin(ctx, "lista", retry=2, retry_s=2.0)
        if ok:
            ctx.log_msg("[ARENA] [PRE-LISTA] lista aperta OK")
        else:
            ctx.log_msg("[ARENA] [PRE-LISTA] ANOMALIA: lista non rilevata")
        return ok

    def _torna_home(self, ctx: TaskContext) -> None:
        """
        Doppio tap centro + 4x BACK + vai_in_home() come verifica finale.
        Il doppio tap chiude overlay/risultati persistenti (fix FAU_07).
        vai_in_home() garantisce il ritorno effettivo in HOME anche quando
        la sequenza BACK non è sufficiente.
        """
        ctx.log_msg("[ARENA] ritorno HOME — doppio tap centro + BACK×4")
        self._doppio_tap_centro(ctx)
        time.sleep(1.5)
        for _ in range(4):
            ctx.device.back()
            time.sleep(0.8)

        if ctx.navigator is not None:
            ok = ctx.navigator.vai_in_home()
            ctx.log_msg("[ARENA] vai_in_home() post-BACK → %s", "OK" if ok else "FALLITO")

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
        ctx.log_msg("[ARENA] sfida %d/%d", n, MAX_SFIDE)

        # GUARD-GLORY: popup Glory può comparire tra sfide (cambio tier mid-session)
        screen_guard = ctx.device.screenshot()
        if screen_guard is not None and self._match(ctx, screen_guard, "glory"):
            ctx.log_msg("[ARENA] [GUARD-GLORY] popup Glory pre-sfida — chiudo")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)

        # PRE-SFIDA: lista visibile?
        if not self._check_pin(ctx, "lista", retry=1, retry_s=1.5):
            ctx.log_msg("[ARENA] [PRE-SFIDA] lista non visibile — abort sfida")
            return "errore"

        ctx.device.tap(*_TAP_ULTIMA_SFIDA)
        time.sleep(3.0)

        # CHECK-PURCHASE: sfide esaurite?
        if self._check_pin(ctx, "purchase", retry=1, retry_s=1.0):
            ctx.log_msg("[ARENA] [CHECK-PURCHASE] sfide esaurite → Cancel")
            ctx.device.tap(*_TAP_ESAURITE_CANCEL)
            time.sleep(1.5)
            return "esaurite"

        # PRE-CHALLENGE: START CHALLENGE visibile?
        if not self._check_pin(ctx, "challenge", retry=2, retry_s=1.5):
            ctx.log_msg("[ARENA] [PRE-CHALLENGE] START CHALLENGE non visibile — abort")
            ctx.device.back()
            time.sleep(1.5)
            return "errore"

        # SKIP-CHECKBOX: verifica una volta per sessione
        if not run.skip_verificato:
            self._assicura_skip(ctx)
            run.skip_verificato = True

        ctx.log_msg("[ARENA] [PRE-CHALLENGE] START CHALLENGE — tap")
        ctx.device.tap(*_TAP_START_CHALLENGE)

        # Attesa battaglia
        victory, failure = self._attendi_fine_battaglia(ctx)

        if victory:
            ctx.log_msg("[ARENA] [POST-BATTAGLIA] Victory ✓")
        elif failure:
            ctx.log_msg("[ARENA] [POST-BATTAGLIA] Failure")
        else:
            ctx.log_msg("[ARENA] [POST-BATTAGLIA] timeout — né Victory né Failure")

        # Diagnostico: pin_continue (solo logging)
        screen_diag = ctx.device.screenshot()
        if screen_diag is not None:
            ok_cont = self._match(ctx, screen_diag, "continue")
            ctx.log_msg("[ARENA] [PRE-CONTINUE] pin_arena_05=%s", ok_cont)

        # Tap "Tap to continue" con coordinata dipendente dal risultato
        if victory:
            ctx.log_msg("[ARENA] [CONTINUE] Victory → tap %s", _TAP_CONTINUE_VICTORY)
            ctx.device.tap(*_TAP_CONTINUE_VICTORY)
        elif failure:
            ctx.log_msg("[ARENA] [CONTINUE] Failure → tap %s", _TAP_CONTINUE_FAILURE)
            ctx.device.tap(*_TAP_CONTINUE_FAILURE)
        else:
            ctx.log_msg("[ARENA] [CONTINUE] fallback → doppio tap centro")
            self._doppio_tap_centro(ctx)
        time.sleep(2.5)

        # POST-CONTINUE: popup Glory post-vittoria (cambio tier)?
        screen_post = ctx.device.screenshot()
        if screen_post is not None and self._match(ctx, screen_post, "glory"):
            ctx.log_msg("[ARENA] [POST-CONTINUE] popup Glory — chiudo")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)

        # Verifica ritorno lista
        if not self._check_pin(ctx, "lista", retry=2, retry_s=1.5):
            ctx.log_msg("[ARENA] [POST-CONTINUE] lista non tornata — retry dopo 2s")
            time.sleep(2.0)
            if not self._check_pin(ctx, "lista", retry=2, retry_s=1.5):
                ctx.log_msg("[ARENA] [POST-CONTINUE] lista ancora non visibile — procedo comunque")

        return "ok"

    # ── Popup helpers ─────────────────────────────────────────────────────────

    def _assicura_skip(self, ctx: TaskContext) -> None:
        """
        Verifica che Skip sia attivo nella schermata START CHALLENGE.
        Se non spuntato esegue il tap su (723,488) per attivarlo.
        Chiamato una sola volta per sessione (run.skip_verificato).
        """
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[ARENA] [SKIP] screenshot fallito — skip check")
            return
        on  = self._match(ctx, screen, "skip_on")
        off = self._match(ctx, screen, "skip_off")
        ctx.log_msg("[ARENA] [SKIP] check=%s  no_check=%s", on, off)
        if on:
            ctx.log_msg("[ARENA] [SKIP] Skip già attivo ✓")
        else:
            ctx.log_msg("[ARENA] [SKIP] Skip non attivo — tap %s", _TAP_SKIP_CHECKBOX)
            ctx.device.tap(*_TAP_SKIP_CHECKBOX)
            time.sleep(0.8)
            screen2 = ctx.device.screenshot()
            if screen2 is not None:
                ok = self._match(ctx, screen2, "skip_on")
                ctx.log_msg("[ARENA] [SKIP] post-tap skip_on=%s", ok)

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

        ctx.log_msg("[ARENA] popup Glory Silver — tap Continue")
        ctx.device.tap(*_TAP_GLORY_CONTINUE)
        time.sleep(2.0)

        # Riverifica
        screen2 = ctx.device.screenshot()
        if screen2 is not None and self._match(ctx, screen2, "glory"):
            ctx.log_msg("[ARENA] popup Glory ancora visibile — retry tap")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)
        return True

    def _gestisci_popup_congratulations(self, ctx: TaskContext) -> bool:
        """
        Controllo pixel per popup Congratulations generico.
        FIX: usa device.screenshot().frame invece di device.last_frame.
        Ritorna True se il popup era presente.
        """
        screen = ctx.device.screenshot()
        if screen is None:
            return False

        # FIX: Screenshot.frame invece di device.last_frame (non esiste in AdbDevice)
        img = getattr(screen, "frame", None)
        if img is None:
            return False

        px, py = _CONGRATS_CHECK_XY
        pixel = img[py, px]
        if np.all(pixel >= _CONGRATS_BGR_LOW) and np.all(pixel <= _CONGRATS_BGR_HIGH):
            ctx.log_msg("[ARENA] popup Congratulations (pixel) — tap Continue")
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
        ctx.log_msg("[ARENA] attesa battaglia — delay iniziale %.0fs", _DELAY_BATTAGLIA_S)
        time.sleep(_DELAY_BATTAGLIA_S)

        t_start = time.time()
        while time.time() - t_start < _MAX_BATTAGLIA_S:
            screen = ctx.device.screenshot()
            if screen is not None:
                victory = self._match(ctx, screen, "victory")
                failure = self._match(ctx, screen, "failure")
                elapsed = _DELAY_BATTAGLIA_S + (time.time() - t_start)
                if victory or failure:
                    ctx.log_msg("[ARENA] fine battaglia in %.1fs totali", elapsed)
                    return victory, failure
            time.sleep(_POLL_BATTAGLIA_S)

        totale = _DELAY_BATTAGLIA_S + _MAX_BATTAGLIA_S
        ctx.log_msg("[ARENA] timeout battaglia dopo %.0fs", totale)
        return False, False

    # ── Primitivi template matching ───────────────────────────────────────────

    def _match(self, ctx: TaskContext, screen: object, key: str) -> bool:
        """
        Template matching su un singolo pin.
        API V6: find_one(screenshot, name, zone=roi) — non esiste match().
        """
        spec = _ARENA_PIN[key]
        result = ctx.matcher.find_one(screen, spec.path, threshold=spec.soglia, zone=spec.roi)
        ok = result.found
        ctx.log_msg("[ARENA-PIN] %s: score=%.3f → %s", key, result.score, "OK" if ok else "NON trovato")
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
                ctx.log_msg("[ARENA-PIN] %s: screenshot fallito (t=%d)", key, tentativo + 1)
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
