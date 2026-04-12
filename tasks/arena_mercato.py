# tasks/arena_mercato.py
"""
Step 17 — Arena Mercato (periodic task).

Scheduling : periodic, intervallo=12h
Template dir: templates/pin/  (prefisso "pin/")

PIN usati
─────────────────────────────────────────────────────────────────────────────
  pin/pin_360_open.png   ROI=(140,265,325,305)  soglia=0.75  [pack 360 attivo]
  pin/pin_360_close.png  ROI=(140,265,325,305)  soglia=0.75  [pack 360 esaurito]
  pin/pin_15_open.png    ROI=(620,390,870,425)  soglia=0.75  [pack 15 attivo]
  pin/pin_15_close.png   ROI=(620,390,870,425)  soglia=0.75  [pack 15 esaurito]

Navigazione
─────────────────────────────────────────────────────────────────────────────
  HOME → tap Campaign → tap Arena of Doom → tap Carrello (Arena Store)
  Acquisti → BACK → HOME

Logica acquisti (priorità)
─────────────────────────────────────────────────────────────────────────────
  FASE 1 — Pack 360 (Intermediate Resource Pack):
    loop finché btn360_open attivo:
      tap primo_acquisto → tap max_acquisto → acquisti_360++
    quando grigio → passa a FASE 2

  FASE 2 — Pack 15 (Random Resource Pack III):
    loop finché btn15_open attivo:
      tap pack15 → tap pack15_max (x34) → acquisti_15++
    quando grigio → STOP

  Guard anti-loop: max 20 iterazioni totali (FASE 1 + FASE 2).
  Fail-safe: se nessun template supera soglia → False (non acquistare).

Coordinata tap (960×540)
─────────────────────────────────────────────────────────────────────────────
  _TAP_CAMPAIGN      = (760, 505)
  _TAP_ARENA_OF_DOOM = (480, 270)
  _TAP_CARRELLO      = (905,  68)   # icona carrello in lista arena
  _TAP_PRIMO_ACQ     = (235, 283)   # pack 360: apre selettore quantità
  _TAP_MAX_ACQ       = (451, 286)   # pack 360: conferma max
  _TAP_PACK15        = (788, 408)   # pack 15: pulsante "15"
  _TAP_PACK15_MAX    = (654, 408)   # pack 15: tap x34 (max acquistabile)
  _TAP_GLORY_CONTINUE= (471, 432)   # popup Glory Silver → Continue
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from core.task import Task, TaskContext, TaskResult


# ──────────────────────────────────────────────────────────────────────────────
# Coordinata tap (960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_CAMPAIGN       = (760, 505)
_TAP_ARENA_OF_DOOM  = (480, 270)
_TAP_CARRELLO       = (905,  68)
_TAP_PRIMO_ACQ      = (235, 283)
_TAP_MAX_ACQ        = (451, 286)
_TAP_PACK15         = (788, 408)
_TAP_PACK15_MAX     = (654, 408)
_TAP_GLORY_CONTINUE = (471, 432)

_MERCATO_MAX_ITER   = 20   # guard anti-loop totale (FASE 1 + FASE 2)


# ──────────────────────────────────────────────────────────────────────────────
# Configurazione template
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _PinSpec:
    path:   str
    roi:    tuple[int, int, int, int]
    soglia: float


_MERCATO_PIN: dict[str, _PinSpec] = {
    "btn360_open":  _PinSpec("pin/pin_360_open.png",  (140, 265, 325, 305), 0.75),
    "btn360_close": _PinSpec("pin/pin_360_close.png", (140, 265, 325, 305), 0.75),
    "btn15_open":   _PinSpec("pin/pin_15_open.png",   (620, 390, 870, 425), 0.75),
    "btn15_close":  _PinSpec("pin/pin_15_close.png",  (620, 390, 870, 425), 0.75),
    # Pin arena lista — riusato per confermare navigazione
    "lista":        _PinSpec("pin/pin_arena_01_lista.png", (387, 0, 565, 43), 0.80),
    # Pin glory — gestito anche qui (può comparire entrando in arena)
    "glory":        _PinSpec("pin/pin_arena_07_glory.png", (379, 418, 564, 447), 0.80),
}


# ──────────────────────────────────────────────────────────────────────────────
# Task principale
# ──────────────────────────────────────────────────────────────────────────────

class ArenaMercatoTask(Task):
    """
    Arena Mercato — periodic, intervallo=12h.

    Acquista pack 360 (Intermediate Resource Pack) e pack 15
    (Random Resource Pack III) usando le monete arena accumulate.
    Indipendente dalle sfide giornaliere (ArenaTask).
    """

    # ── Task ABC ──────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "arena_mercato"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("arena_mercato")
        return True

    # FIX: rimosso @property — viola standard V6 (def senza decoratore)
    def interval_hours(self) -> float:
        return 12.0

    def run(self, ctx: TaskContext) -> TaskResult:
        acquisti_360 = 0
        acquisti_15  = 0
        errore: str | None = None

        # 1. HOME — FIX: usa vai_in_home() invece di current_screen()
        if not self._assicura_home(ctx):
            errore = "impossibile raggiungere home"
            ctx.log_msg("[MERCATO-ARENA] %s", errore)
            return TaskResult(success=False, data=self._data(0, 0, errore))

        # 2. Navigazione verso Arena Store
        if not self._naviga_a_store(ctx):
            errore = "impossibile raggiungere arena store"
            ctx.log_msg("[MERCATO-ARENA] %s", errore)
            self._torna_home(ctx)
            return TaskResult(success=False, data=self._data(0, 0, errore))

        # 3. Acquisti
        try:
            acquisti_360, acquisti_15 = self._loop_acquisti(ctx)
        except Exception as exc:
            errore = str(exc)
            ctx.log_msg("[MERCATO-ARENA] eccezione acquisti: %s", exc)

        # 4. Ritorno home
        self._torna_home(ctx)

        successo = errore is None
        ctx.log_msg(
            "[MERCATO-ARENA] completato — pack360=%d pack15=%d%s",
            acquisti_360, acquisti_15,
            f" errore={errore}" if errore else "",
        )
        return TaskResult(
            success=successo,
            data=self._data(acquisti_360, acquisti_15, errore),
        )

    # ── Navigazione ──────────────────────────────────────────────────────────

    def _assicura_home(self, ctx: TaskContext) -> bool:
        """
        Porta l'istanza in HOME.
        FIX: usa ctx.navigator.vai_in_home() — GameNavigator non espone current_screen().
        """
        if ctx.navigator is not None:
            ok = ctx.navigator.vai_in_home()
            if ok:
                ctx.log_msg("[MERCATO-ARENA] home confermata via navigator")
            else:
                ctx.log_msg("[MERCATO-ARENA] navigator: vai_in_home() fallito — BACK di recupero")
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
            ctx.log_msg("[MERCATO-ARENA] home fallback ciclo %d", ciclo + 1)
        return True  # ottimistico senza navigator

    def _naviga_a_store(self, ctx: TaskContext) -> bool:
        """
        HOME → Campaign → Arena of Doom → Carrello (Arena Store).
        Gestisce popup Glory Silver in ingresso.
        Verifica lista arena (pin_arena_01_lista) prima di aprire il carrello.
        """
        ctx.log_msg("[MERCATO-ARENA] HOME → Campaign")
        ctx.device.tap(*_TAP_CAMPAIGN)
        time.sleep(3.0)

        ctx.log_msg("[MERCATO-ARENA] Campaign → Arena of Doom")
        ctx.device.tap(*_TAP_ARENA_OF_DOOM)
        time.sleep(3.5)

        # Popup Glory all'ingresso (cambio tier stagionale)
        self._gestisci_popup_glory(ctx)

        # Verifica lista arena aperta
        if not self._check_pin(ctx, "lista", retry=2, retry_s=2.0):
            ctx.log_msg("[MERCATO-ARENA] lista arena non rilevata")
            return False

        ctx.log_msg("[MERCATO-ARENA] lista arena OK → tap carrello")
        ctx.device.tap(*_TAP_CARRELLO)
        time.sleep(2.0)
        return True

    def _torna_home(self, ctx: TaskContext) -> None:
        """BACK × 3 per uscire da store → lista → campaign → home."""
        ctx.log_msg("[MERCATO-ARENA] ritorno HOME — BACK×3")
        for _ in range(3):
            ctx.device.back()
            time.sleep(0.8)

    # ── Loop acquisti ─────────────────────────────────────────────────────────

    def _loop_acquisti(self, ctx: TaskContext) -> tuple[int, int]:
        """
        Ciclo principale acquisti.

        Ritorna: (acquisti_360, acquisti_15)
        """
        acquisti_360    = 0
        acquisti_15     = 0
        pack360_esaurito = False

        for iterazione in range(_MERCATO_MAX_ITER):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MERCATO-ARENA] screenshot fallito (iter=%d) — stop", iterazione)
                break

            if not pack360_esaurito:
                # ── FASE 1: Pack 360 ──────────────────────────────────────
                if self._pulsante_360_attivo(ctx, screen):
                    ctx.log_msg("[MERCATO-360] pulsante attivo — tap acquisto")
                    ctx.device.tap(*_TAP_PRIMO_ACQ)
                    time.sleep(1.0)
                    ctx.device.tap(*_TAP_MAX_ACQ)
                    time.sleep(1.5)
                    acquisti_360 += 1
                else:
                    ctx.log_msg(
                        "[MERCATO-360] esaurito (%d cicli) → passo pack 15",
                        acquisti_360,
                    )
                    pack360_esaurito = True
                    # Ri-acquisisce screen fresco per valutare subito pack 15
                    screen = ctx.device.screenshot()
                    if screen is None:
                        ctx.log_msg("[MERCATO-ARENA] screenshot fallito dopo switch — stop")
                        break
                    # Valuta pack 15 nella stessa iterazione
                    if self._pulsante_15_attivo(ctx, screen):
                        ctx.log_msg("[MERCATO-15] pulsante attivo — tap pack 15")
                        ctx.device.tap(*_TAP_PACK15)
                        time.sleep(1.0)
                        ctx.device.tap(*_TAP_PACK15_MAX)
                        time.sleep(1.5)
                        acquisti_15 += 1
                    else:
                        ctx.log_msg("[MERCATO-15] pulsante non attivo — monete esaurite, stop")
                        break
            else:
                # ── FASE 2: Pack 15 ──────────────────────────────────────
                if self._pulsante_15_attivo(ctx, screen):
                    ctx.log_msg("[MERCATO-15] pulsante attivo — tap pack 15")
                    ctx.device.tap(*_TAP_PACK15)
                    time.sleep(1.0)
                    ctx.device.tap(*_TAP_PACK15_MAX)
                    time.sleep(1.5)
                    acquisti_15 += 1
                else:
                    ctx.log_msg(
                        "[MERCATO-15] monete esaurite (%d cicli) — stop",
                        acquisti_15,
                    )
                    break

        ctx.log_msg(
            "[MERCATO-ARENA] loop completato — pack360=%d pack15=%d",
            acquisti_360, acquisti_15,
        )
        # BACK → torna alla lista arena
        ctx.device.back()
        time.sleep(1.5)
        return acquisti_360, acquisti_15

    # ── Rilevamento stato pulsanti ────────────────────────────────────────────

    def _pulsante_360_attivo(self, ctx: TaskContext, screen: object) -> bool:
        """
        True  → btn360_open supera soglia (arancione, acquistabile).
        False → btn360_close supera soglia (grigio, esaurito).
        Fallback: open > close score → True; altrimenti False (fail-safe).
        """
        spec_open  = _MERCATO_PIN["btn360_open"]
        spec_close = _MERCATO_PIN["btn360_close"]
        score_open  = ctx.matcher.match(screen, spec_open.path,  spec_open.roi)
        score_close = ctx.matcher.match(screen, spec_close.path, spec_close.roi)
        ctx.log_msg("[MERCATO] btn360 open=%.3f close=%.3f", score_open, score_close)

        if score_open  >= spec_open.soglia:  return True
        if score_close >= spec_close.soglia: return False
        # Nessun match chiaro: fallback su confronto diretto
        return score_open > score_close

    def _pulsante_15_attivo(self, ctx: TaskContext, screen: object) -> bool:
        """
        True  → btn15_open supera soglia (arancione, acquistabile).
        False → btn15_close supera soglia (grigio, esaurito).
        Fail-safe: se nessun match → False (non acquistare).
        """
        spec_open  = _MERCATO_PIN["btn15_open"]
        spec_close = _MERCATO_PIN["btn15_close"]
        score_open  = ctx.matcher.match(screen, spec_open.path,  spec_open.roi)
        score_close = ctx.matcher.match(screen, spec_close.path, spec_close.roi)
        ctx.log_msg("[MERCATO-15] btn15 open=%.3f close=%.3f", score_open, score_close)

        if score_open  >= spec_open.soglia:  return True
        if score_close >= spec_close.soglia: return False
        # Nessun match chiaro: fail-safe stop (non acquistare)
        ctx.log_msg("[MERCATO-15] nessun match chiaro — fail-safe stop")
        return False

    # ── Popup Glory ───────────────────────────────────────────────────────────

    def _gestisci_popup_glory(self, ctx: TaskContext) -> bool:
        """
        Rileva e chiude popup 'Congratulations / Glory Silver'.
        Ritorna True se il popup era presente.
        """
        screen = ctx.device.screenshot()
        if screen is None:
            return False
        spec = _MERCATO_PIN["glory"]
        score = ctx.matcher.match(screen, spec.path, spec.roi)
        if score < spec.soglia:
            return False

        ctx.log_msg("[MERCATO-ARENA] popup Glory Silver — tap Continue")
        ctx.device.tap(*_TAP_GLORY_CONTINUE)
        time.sleep(2.0)

        # Riverifica
        screen2 = ctx.device.screenshot()
        if screen2 is not None:
            score2 = ctx.matcher.match(screen2, spec.path, spec.roi)
            if score2 >= spec.soglia:
                ctx.log_msg("[MERCATO-ARENA] popup Glory ancora visibile — retry tap")
                ctx.device.tap(*_TAP_GLORY_CONTINUE)
                time.sleep(2.0)
        return True

    # ── Primitivi template matching ───────────────────────────────────────────

    def _check_pin(self,
                   ctx: TaskContext,
                   key: str,
                   retry: int = 1,
                   retry_s: float = 1.5,
                   ) -> bool:
        """Screenshot + match con retry. Ritorna True al primo match."""
        spec = _MERCATO_PIN[key]
        for tentativo in range(retry + 1):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MERCATO-PIN] %s: screenshot fallito (t=%d)", key, tentativo + 1)
                time.sleep(retry_s)
                continue
            score = ctx.matcher.match(screen, spec.path, spec.roi)
            ok = score >= spec.soglia
            ctx.log_msg("[MERCATO-PIN] %s: score=%.3f → %s", key, score, "OK" if ok else "KO")
            if ok or tentativo == retry:
                return ok
            time.sleep(retry_s)
        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _data(pack360: int, pack15: int, errore: str | None) -> dict:
        return {"acquisti_360": pack360, "acquisti_15": pack15, "errore": errore}
