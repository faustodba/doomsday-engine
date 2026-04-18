# tasks/arena_mercato.py
"""
Step 17 — Arena Mercato (periodic task).

Scheduling : periodic, intervallo=12h
Template dir: templates/pin/  (prefisso "pin/")

PIN usati
─────────────────────────────────────────────────────────────────────────────
  pin/pin_arena_01_lista.png   ROI=(387,  0, 565,  43)  soglia=0.80  [lista arena confermata]
  pin/pin_arena_07_glory.png   ROI=(379,418, 564, 447)  soglia=0.80  [popup Glory Silver]
  pin/pin_360_open.png         ROI=(140,265, 325, 305)  soglia=0.75  [pack 360 attivo]
  pin/pin_360_close.png        ROI=(140,265, 325, 305)  soglia=0.75  [pack 360 esaurito]
  pin/pin_15_open.png          ROI=(620,390, 870, 425)  soglia=0.75  [pack 15 attivo]
  pin/pin_15_close.png         ROI=(620,390, 870, 425)  soglia=0.75  [pack 15 esaurito]

Navigazione (analogo a arena.py V6 + V5 arena_of_glory.py)
─────────────────────────────────────────────────────────────────────────────
  HOME → tap Campaign → tap Arena of Doom
  → [gestisci popup glory]
  → check pin_arena_01_lista (retry=2)    ← stessa logica di ArenaTask._naviga_a_arena()
  → tap Carrello (905,68)                 ← dentro _loop_acquisti, come V5 _visita_mercato_arena()
  → loop acquisti pack 360 / pack 15
  → BACK → HOME
Logica acquisti (priorità)
─────────────────────────────────────────────────────────────────────────────
  FASE 1 — Pack 360 (Intermediate Resource Pack):
    loop finché btn360_open attivo:
      tap primo_acquisto (235,283) → tap max_acquisto (451,286) → acquisti_360++
    quando grigio → passa a FASE 2

  FASE 2 — Pack 15 (Random Resource Pack III):
    loop finché btn15_open attivo:
      tap pack15 (788,408) → tap pack15_max (654,408) → acquisti_15++
    quando grigio → STOP

  Guard anti-loop: max 20 iterazioni totali (FASE 1 + FASE 2).
  Fail-safe: se nessun template supera soglia → False (non acquistare).

Coordinate tap (960×540)
─────────────────────────────────────────────────────────────────────────────
  _TAP_CAMPAIGN       = (584, 486)   # Campaign (layout standard — analogo ad arena.py V6)
  _TAP_ARENA_OF_DOOM  = (321, 297)   # card Arena of Doom in Campaign
  _TAP_CARRELLO       = (905,  68)   # icona carrello nella schermata arena → Arena Store
  _TAP_PRIMO_ACQ      = (235, 283)   # pack 360: selettore quantità
  _TAP_MAX_ACQ        = (451, 286)   # pack 360: conferma max
  _TAP_PACK15         = (788, 408)   # pack 15: pulsante "15"
  _TAP_PACK15_MAX     = (654, 408)   # pack 15: tap x34 (max acquistabile)
  _TAP_GLORY_CONTINUE = (471, 432)   # Continue popup Glory Silver
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template


# ──────────────────────────────────────────────────────────────────────────────
# Coordinate tap (960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_CAMPAIGN       = (584, 486)   # ← stesso di arena.py V6
_TAP_ARENA_OF_DOOM  = (321, 297)   # ← stesso di arena.py V6
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
    # Navigazione — stesso pin usato da ArenaTask._naviga_a_arena() in arena.py V6
    "lista":        _PinSpec("pin/pin_arena_01_lista.png",     (387,   0, 565,  43), 0.80),
    # Popup ingresso arena
    "glory":        _PinSpec("pin/pin_arena_07_glory.png",     (379, 418, 564, 447), 0.80),
    # Stato pulsanti store
    "btn360_open":  _PinSpec("pin/pin_360_open.png",           (140, 265, 325, 305), 0.75),
    "btn360_close": _PinSpec("pin/pin_360_close.png",          (140, 265, 325, 305), 0.75),
    "btn15_open":   _PinSpec("pin/pin_15_open.png",            (620, 390, 870, 425), 0.75),
    "btn15_close":  _PinSpec("pin/pin_15_close.png",           (620, 390, 870, 425), 0.75),
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

    Pattern architetturale identico ad ArenaTask (arena.py V6):
      - _assicura_home()        via navigator
      - _naviga_a_arena()       con check pin_arena_01_lista (retry=2)
      - _gestisci_popup_glory() prima del check lista
      - _match() / _check_pin() primitivi identici ad ArenaTask
      - _loop_acquisti()        apre il carrello e acquista
                                (come V5 _visita_mercato_arena — tap carrello è
                                 la prima azione del loop, non della navigazione)
      - _torna_home()           BACK×2
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

    def interval_hours(self) -> float:
        return 12.0

    def run(self, ctx: TaskContext) -> TaskResult:
        acquisti_360 = 0
        acquisti_15  = 0
        errore: str | None = None

        # 1. HOME
        if not self._assicura_home(ctx):
            errore = "impossibile raggiungere home"
            ctx.log_msg("[MERCATO-ARENA] %s", errore)
            return TaskResult(success=False, data=self._data(0, 0, errore))

        # 2. Naviga verso lista arena (verifica pin_arena_01_lista come ArenaTask)
        if not self._naviga_a_arena(ctx):
            errore = "impossibile raggiungere lista arena"
            ctx.log_msg("[MERCATO-ARENA] %s", errore)
            self._torna_home(ctx)
            return TaskResult(success=False, data=self._data(0, 0, errore))

        # 3. Acquisti (tap carrello + loop pack 360 / pack 15)
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
        Porta l'istanza in HOME usando il navigator V6.
        Identico ad ArenaTask._assicura_home().
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

        # Fallback senza navigator
        for ciclo in range(3):
            for _ in range(5):
                ctx.device.back()
                time.sleep(0.4)
            time.sleep(0.8)
            ctx.log_msg("[MERCATO-ARENA] home fallback ciclo %d", ciclo + 1)
        return True

    def _naviga_a_arena(self, ctx: TaskContext) -> bool:
        """
        HOME → Campaign → Arena of Doom.
        Gestisce popup Glory Silver, poi verifica pin_arena_01_lista (retry=2).
        Ritorna True se lista visibile.

        Identico ad ArenaTask._naviga_a_arena() — NON tappa il carrello:
        quello avviene in _loop_acquisti() come prima azione,
        speculare a V5 _visita_mercato_arena() che fa tap carrello prima del loop.
        """
        ctx.log_msg("[MERCATO-ARENA] HOME → Campaign")
        _navigato = False
        if ctx.navigator is not None and hasattr(ctx.navigator, "tap_barra"):
            _navigato = ctx.navigator.tap_barra(ctx, "campaign")
        if not _navigato:
            ctx.log_msg("[MERCATO-ARENA] tap_barra fallback → coordinate fisse %s", _TAP_CAMPAIGN)
            ctx.device.tap(*_TAP_CAMPAIGN)
        time.sleep(3.0)

        ctx.log_msg("[MERCATO-ARENA] Campaign → Arena of Doom")
        ctx.device.tap(*_TAP_ARENA_OF_DOOM)
        time.sleep(3.5)

        # Popup Glory all'ingresso (cambio tier / primo accesso)
        self._gestisci_popup_glory(ctx)

        # Verifica lista arena — stesso check di ArenaTask._naviga_a_arena()
        ok = self._check_pin(ctx, "lista", retry=2, retry_s=2.0)
        if ok:
            ctx.log_msg("[MERCATO-ARENA] [PRE-LISTA] lista aperta OK")
        else:
            ctx.log_msg("[MERCATO-ARENA] [PRE-LISTA] ANOMALIA: lista non rilevata")
        return ok

    def _torna_home(self, ctx: TaskContext) -> None:
        """BACK × 2 per uscire da store → lista → home.
        Percorso reale: Arena Store → BACK → Lista Arena → BACK → HOME.
        Campaign non costituisce schermata separata nel percorso di ritorno.
        """
        ctx.log_msg("[MERCATO-ARENA] ritorno HOME — BACK×2")
        for _ in range(2):
            ctx.device.back()
            time.sleep(0.8)

    # ── Loop acquisti ─────────────────────────────────────────────────────────

    def _loop_acquisti(self, ctx: TaskContext) -> tuple[int, int]:
        """
        Apre l'Arena Store (tap carrello) e acquista pack 360 poi pack 15.

        Speculare a V5 _visita_mercato_arena():
          - prima azione: tap carrello (905,68) → attesa 2s
          - FASE 1: loop pack 360 finché btn360_open attivo
          - FASE 2: loop pack 15 finché btn15_open attivo
          - BACK → torna lista arena

        Ritorna: (acquisti_360, acquisti_15)
        """
        # Tap carrello — prima azione (come in V5 _visita_mercato_arena)
        ctx.log_msg("[MERCATO-ARENA] tap carrello (905,68) → Arena Store")
        ctx.device.tap(*_TAP_CARRELLO)
        time.sleep(0.3)  # minimo animazione tap

        acquisti_360     = 0
        acquisti_15      = 0
        pack360_esaurito = False

        for iterazione in range(_MERCATO_MAX_ITER):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MERCATO-ARENA] screenshot fallito (iter=%d) — stop", iterazione)
                break

            if not pack360_esaurito:
                # ── FASE 1: Pack 360 ─────────────────────────────────────────
                if self._pulsante_360_attivo(ctx, screen):
                    ctx.log_msg("[MERCATO-360] pulsante attivo — tap acquisto")
                    ctx.device.tap(*_TAP_PRIMO_ACQ)
                    time.sleep(1.0)
                    ctx.device.tap(*_TAP_MAX_ACQ)
                    time.sleep(1.5)
                    acquisti_360 += 1
                else:
                    ctx.log_msg(
                        "[MERCATO-360] esaurito dopo %d cicli → passo pack 15",
                        acquisti_360,
                    )
                    pack360_esaurito = True
                    # Screen fresco per valutare subito pack 15 senza perdere un'iterazione
                    screen = ctx.device.screenshot()
                    if screen is None:
                        ctx.log_msg("[MERCATO-ARENA] screenshot fallito dopo switch — stop")
                        break
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
                # ── FASE 2: Pack 15 ──────────────────────────────────────────
                if self._pulsante_15_attivo(ctx, screen):
                    ctx.log_msg("[MERCATO-15] pulsante attivo — tap pack 15")
                    ctx.device.tap(*_TAP_PACK15)
                    time.sleep(1.0)
                    ctx.device.tap(*_TAP_PACK15_MAX)
                    time.sleep(1.5)
                    acquisti_15 += 1
                else:
                    ctx.log_msg(
                        "[MERCATO-15] monete esaurite dopo %d cicli — stop",
                        acquisti_15,
                    )
                    break

        ctx.log_msg(
            "[MERCATO-ARENA] loop completato — pack360=%d pack15=%d",
            acquisti_360, acquisti_15,
        )
        # BACK → torna alla lista arena (poi _torna_home farà altri BACK×2)
        ctx.device.back()
        time.sleep(1.5)
        return acquisti_360, acquisti_15

    # ── Rilevamento stato pulsanti ────────────────────────────────────────────

    def _pulsante_360_attivo(self, ctx: TaskContext, screen: object) -> bool:
        """
        Identico a V5 _pulsante_acquisto_attivo():
          open >= soglia  → True
          close >= soglia → False
          nessun match    → confronto score (open > close)
        """
        spec_open  = _MERCATO_PIN["btn360_open"]
        spec_close = _MERCATO_PIN["btn360_close"]
        score_open  = ctx.matcher.find_one(screen, spec_open.path,  threshold=0.0, zone=spec_open.roi).score
        score_close = ctx.matcher.find_one(screen, spec_close.path, threshold=0.0, zone=spec_close.roi).score
        ctx.log_msg("[MERCATO] btn360 open=%.3f close=%.3f", score_open, score_close)

        if score_open  >= spec_open.soglia:  return True
        if score_close >= spec_close.soglia: return False
        return score_open > score_close

    def _pulsante_15_attivo(self, ctx: TaskContext, screen: object) -> bool:
        """
        Identico a V5 _pulsante_pack15_attivo():
          open >= soglia  → True
          close >= soglia → False
          nessun match    → fail-safe False (non acquistare)
        """
        spec_open  = _MERCATO_PIN["btn15_open"]
        spec_close = _MERCATO_PIN["btn15_close"]
        score_open  = ctx.matcher.find_one(screen, spec_open.path,  threshold=0.0, zone=spec_open.roi).score
        score_close = ctx.matcher.find_one(screen, spec_close.path, threshold=0.0, zone=spec_close.roi).score
        ctx.log_msg("[MERCATO-15] btn15 open=%.3f close=%.3f", score_open, score_close)

        if score_open  >= spec_open.soglia:  return True
        if score_close >= spec_close.soglia: return False
        ctx.log_msg("[MERCATO-15] nessun match chiaro — fail-safe stop")
        return False

    # ── Popup Glory ───────────────────────────────────────────────────────────

    def _gestisci_popup_glory(self, ctx: TaskContext) -> bool:
        """
        Rileva e chiude popup Glory Silver (pin_arena_07_glory).
        Identico ad ArenaTask._gestisci_popup_glory().
        """
        screen = ctx.device.screenshot()
        if screen is None:
            return False
        if not self._match(ctx, screen, "glory"):
            return False

        ctx.log_msg("[MERCATO-ARENA] popup Glory Silver — tap Continue")
        ctx.device.tap(*_TAP_GLORY_CONTINUE)
        time.sleep(2.0)

        screen2 = ctx.device.screenshot()
        if screen2 is not None and self._match(ctx, screen2, "glory"):
            ctx.log_msg("[MERCATO-ARENA] popup Glory ancora visibile — retry tap")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(2.0)
        return True

    # ── Primitivi template matching ───────────────────────────────────────────

    def _match(self, ctx: TaskContext, screen: object, key: str) -> bool:
        """
        Template matching su un singolo pin.
        Identico ad ArenaTask._match().
        """
        spec = _MERCATO_PIN[key]
        result = ctx.matcher.find_one(screen, spec.path, threshold=spec.soglia, zone=spec.roi)
        ok = result.found
        ctx.log_msg("[MERCATO-PIN] %s: score=%.3f → %s", key, result.score, "OK" if ok else "NON trovato")
        return ok

    def _check_pin(self,
                   ctx: TaskContext,
                   key: str,
                   retry: int = 1,
                   retry_s: float = 1.5,
                   ) -> bool:
        """
        Screenshot + match con retry. Ritorna True al primo match.
        Identico ad ArenaTask._check_pin().
        """
        for tentativo in range(retry + 1):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MERCATO-PIN] %s: screenshot fallito (t=%d)", key, tentativo + 1)
                time.sleep(retry_s)
                continue
            ok = self._match(ctx, screen, key)
            if ok or tentativo == retry:
                return ok
            time.sleep(retry_s)
        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _data(pack360: int, pack15: int, errore: str | None) -> dict:
        return {"acquisti_360": pack360, "acquisti_15": pack15, "errore": errore}
