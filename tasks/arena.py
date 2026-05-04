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
  pin/pin_arena_07_glory.png      ROI=(380,410, 570, 458)  soglia=0.80
                                  → pulsante "Continue" giallo del popup
                                    "Congratulations / Glory <Tier>" (es.
                                    Glory Silver), che appare a inizio
                                    season o al cambio di rank. NON il
                                    banner header "Arena of Glory".

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

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template


# ──────────────────────────────────────────────────────────────────────────────
# Costanti di coordinata (960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_CAMPAIGN        = (584, 486)   # bottone Campaign in home (layout 1 standard)
_TAP_ARENA_OF_DOOM   = (321, 297)   # card Arena of Doom nella schermata Campaign
_TAP_PRIMA_SFIDA     = (745, 250)   # pulsante Challenge prima riga lista (WU 04/05).
                                    # Pre-fix: TAP_ULTIMA_SFIDA=(745,482) tappava
                                    # ultima riga (5/5) — falliva quando lista <5
                                    # righe (account low-level / opponenti scarsi).
                                    # Prima riga sempre presente se la lista esiste.
_TAP_START_CHALLENGE = (730, 451)   # bottone START CHALLENGE (V5 config)
_TAP_ESAURITE_CANCEL = (334, 380)   # Cancel nel popup "sfide esaurite"
_TAP_CONGRATULATIONS = (480, 440)   # Continue nel popup Congratulations generico
_TAP_GLORY_CONTINUE  = (473, 432)   # Continue nel popup Glory <Tier> (popup tier-up:
                                    # "Congratulations / Glory Silver" e simili)

_TAP_CONTINUE_VICTORY = (457, 515)  # WU77 "Tap to Continue" Victory (era 462)
_TAP_CONTINUE_FAILURE = (457, 515)  # WU77 "Tap to Continue" Failure (era 509)
                                    # Nuovo design 30/04: stesso testo+coord
                                    # per Victory e Failure (centro basso 515)
_TAP_CENTRO           = (480, 270)  # centro schermo (fallback)
_TAP_CENTRO_PAUSE     = 0.8         # pausa tra i due tap centro
_TAP_SKIP_CHECKBOX    = (723, 488)  # checkbox Skip (salta animazione battaglia)

# WU83 (30/04 12:20) — Rebuild truppe pre-1ª sfida del giorno.
# Coord calibrate live FAU_06: 4 celle attive + 5ª lucchettata.
# Lista 5 coord — usate fino a max_squadre dell'istanza (FAU_00/FauMorfeus=5,
# altre=4). Operazione 1×/die UTC per istanza, state in
# data/arena_deploy_state.json.
_TAP_REMOVE_TRUPPA = [(80,  80), (80, 148), (80, 216), (80, 283), (80, 351)]
_TAP_OPEN_CELLA    = [(42, 100), (42, 170), (42, 240), (42, 310), (42, 380)]

# WU115 (04/05) — debug screenshot via shared/debug_buffer (hot-reload).
# Toggle config: globali.debug_tasks.arena (default False). Sostituisce il
# pattern modulo-level WU114 (_DEBUG_REBUILD_DUMP) con architettura unificata.

_TAP_READY_DEPLOY  = (723, 482)
_DELAY_REBUILD_S   = 0.8

# Parametri pixel per popup Congratulations generico
_CONGRATS_CHECK_XY  = (480, 300)
_CONGRATS_BGR_LOW   = np.array([200, 150,  50], dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array([255, 220, 130], dtype=np.uint8)

MAX_SFIDE = 5

# Timing battaglia
_DELAY_BATTAGLIA_S = 5.0    # sleep iniziale fisso post-tap START (8.0 → 5.0 WU82)
_POLL_BATTAGLIA_S  = 3.0    # intervallo polling (legacy, non usato post-WU75)
_MAX_BATTAGLIA_S   = 10.0   # WU82 (30/04 11:30): 52→10. Battaglie con
                            # skip ON + driver DirectX durano <10s in pratica.
                            # Totale wait WU75 ora 15s (era 60s).

MAX_TENTATIVI         = 3
MAX_ERRORI_CONSEC     = 2
ARENA_TIMEOUT_S       = 300  # Hard timeout globale task (fix #F2)


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
    # WU77+WU80 (30/04 10:42) — template + ROI aggiornati per nuovo design.
    # Victory: testo "Victory" giallo/oro centro alto su sfondo dorato.
    # Estratto live FAU_00 30/04 (rank 81→53). Self-match score 1.000.
    # WU81 (30/04 10:45): soglia 0.80→0.90 — su Failure il victory matchava
    # 0.847 (falso positivo strutturale font/dim simili). Soglia 0.90 evita
    # confusione: Victory reale ~1.0, Failure reale ~0.84.
    "victory":  _PinSpec("pin/pin_arena_03_victory.png",   (370,  35, 545,  95), 0.90),
    # Failure: testo "Failure" bianco grande su sfondo magenta in (380,42,535,88).
    # Validazione live FAU_10: score 0.998. Soglia 0.90 (WU81) per simmetria.
    "failure":  _PinSpec("pin/pin_arena_04_failure.png",   (370,  35, 545,  95), 0.90),
    # Vecchio "Tap to Continue" pulsante in (410,443,547,487); nuovo testo
    # "Tap to Continue" corsivo bianco in basso a (380,503,535,530). Score 0.996.
    "continue": _PinSpec("pin/pin_arena_05_continue.png",  (370, 495, 545, 540), 0.80),
    "purchase": _PinSpec("pin/pin_arena_06_purchase.png",  (334, 143, 586, 185), 0.80),
    # "glory" = pulsante "Continue" giallo del popup tier-up
    # "Congratulations / Glory <Tier>". Template attuale 225×35 px,
    # ROI deve essere ≥ template (constraint cv2.matchTemplate).
    # Fix 29/04 sera: ROI 190×48 → 270×60 (centro 480, span ±135, y 405-465)
    # per accogliere template 225×35 con margine. Bug: template > ROI →
    # match sempre impossibile, popup Glory mai chiuso.
    "glory":    _PinSpec("pin/pin_arena_07_glory.png",     (345, 405, 615, 465), 0.80),
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
    skip_verificato:  bool = False  # WU74 deprecato — check skip ora ad ogni sfida


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
        msg = (f"{run.sfide_eseguite} sfide" if not run.errore
               else f"{run.sfide_eseguite} sfide ({run.errore})")
        return TaskResult(
            success=success,
            message=msg,
            data={
                "sfide_eseguite": int(run.sfide_eseguite),
                "esaurite":       bool(run.esaurite),
                "errore":         run.errore or "",
            },
        )

    # ── Entry point interno ───────────────────────────────────────────────────

    def _esegui(self, ctx: TaskContext, run: _ArenaRun) -> None:
        ctx.log_msg("[ARENA] Avvio Arena of Glory (max %d sfide)", MAX_SFIDE)
        deadline = time.time() + ARENA_TIMEOUT_S

        for tentativo in range(1, MAX_TENTATIVI + 1):
            if time.time() > deadline:
                run.errore = f"timeout globale {ARENA_TIMEOUT_S}s"
                ctx.log_msg("[ARENA] %s — abort tentativi", run.errore)
                break
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
        time.sleep(1.0)  # animazione minima

        ctx.log_msg("[ARENA] Campaign → Arena of Doom")
        ctx.device.tap(*_TAP_ARENA_OF_DOOM)
        time.sleep(1.0)  # animazione minima

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

        ctx.device.tap(*_TAP_PRIMA_SFIDA)
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

        # WU83 (30/04 12:20) — Rebuild truppe pre-1ª sfida del giorno.
        # Eseguito SOLO alla prima sfida del primo tentativo del giorno.
        # State persistito in data/arena_deploy_state.json (granularità UTC).
        # Operation: rimuovi N squadre + tap cella + READY (auto-deploy).
        # READY auto-seleziona la migliore composizione disponibile (es. test
        # FAU_06: power 431k → 685k post-rebuild, +59% truppe nuove).
        if run.sfide_eseguite == 0 and not _deploy_done_today(ctx.instance_name):
            try:
                n_celle = int(ctx.config.get("max_squadre", 4))
                self._rebuild_truppe(ctx, n_celle)
                _mark_deploy_done(ctx.instance_name)
                ctx.log_msg(f"[ARENA] [WU83] rebuild OK ({n_celle} celle) — marcato per oggi")
            except Exception as exc:
                ctx.log_msg(f"[ARENA] [WU83] rebuild errore: {exc}")
            # Re-verifica START CHALLENGE post-rebuild
            if not self._check_pin(ctx, "challenge", retry=2, retry_s=1.5):
                ctx.log_msg("[ARENA] [WU83] START CHALLENGE non visibile post-rebuild — abort")
                ctx.device.back()
                time.sleep(1.5)
                return "errore"

        # SKIP-CHECKBOX: verifica ad ogni sfida.
        # WU74 (30/04 mattina) — pre-fix: solo 1×/sessione. Bug osservato: la
        # pulizia cache giornaliera (WU64) reset checkbox al default e in
        # alcune istanze il template `skip_on` matcha falso positivo dopo
        # cache pulita → bot crede skip ON ma è OFF → battaglie >60s →
        # timeout 5/5 (es. FAU_05 30/04). Costo: ~1.5s/sfida × 5 = +7.5s/ciclo
        # arena. Beneficio: skip sempre realmente attivo, eliminazione timeout.
        self._assicura_skip(ctx)

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

        # WU80 (30/04 10:25) — tap DINAMICO su loc match "continue" invece
        # di coord fisse. Motivo: pulsante "Tap to Continue" può essere in
        # posizione diversa tra Victory e Failure (UI ridisegnata 30/04).
        # Match dinamico template `pin_arena_05_continue.png` → tap (cx, cy)
        # dal MatchResult. Fallback coord fissa (457,515) se match fallisce.
        screen_diag = ctx.device.screenshot()
        cont_result = None
        if screen_diag is not None:
            spec_c = _ARENA_PIN["continue"]
            cont_result = ctx.matcher.find_one(
                screen_diag, spec_c.path,
                threshold=spec_c.soglia, zone=spec_c.roi,
            )
            ctx.log_msg("[ARENA] [PRE-CONTINUE] continue score=%.3f", cont_result.score)

        if victory or failure:
            esito = "Victory" if victory else "Failure"
            if cont_result is not None and cont_result.found:
                cx, cy = cont_result.cx, cont_result.cy
                ctx.log_msg("[ARENA] [CONTINUE] %s → tap dinamico (%d,%d) score=%.3f",
                            esito, cx, cy, cont_result.score)
                ctx.device.tap(cx, cy)
            else:
                # Fallback su coord fissa unificata (457,515)
                fallback = _TAP_CONTINUE_VICTORY if victory else _TAP_CONTINUE_FAILURE
                ctx.log_msg("[ARENA] [CONTINUE] %s → match fail, fallback coord %s",
                            esito, fallback)
                ctx.device.tap(*fallback)
        else:
            ctx.log_msg("[ARENA] [CONTINUE] timeout → doppio tap centro")
            self._doppio_tap_centro(ctx)
        time.sleep(0.5)  # minimo animazione tap

        # POST-CONTINUE: popup Glory post-vittoria (cambio tier)?
        screen_post = ctx.device.screenshot()
        if screen_post is not None and self._match(ctx, screen_post, "glory"):
            ctx.log_msg("[ARENA] [POST-CONTINUE] popup Glory — chiudo")
            ctx.device.tap(*_TAP_GLORY_CONTINUE)
            time.sleep(0.5)  # minimo animazione tap

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
        WU74 (30/04 mattina) — chiamato ad ogni sfida (era 1×/sessione).
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
        Rileva e chiude popup tier-up "Congratulations / Glory <Tier>"
        (es. Glory Silver) via match del pulsante "Continue" giallo.

        Template: pin/pin_arena_07_glory.png (il bottone Continue, NON il
        banner header). Tap fisso su _TAP_GLORY_CONTINUE = (473, 432).

        Hook: chiamato post-tap "Arena of Doom" (vedi `_naviga_a_arena`)
        e re-controllato in `_esegui_sfida` (GUARD-GLORY pre-sfida e
        POST-CONTINUE post-vittoria) — il popup può comparire mid-session
        al cambio rank.

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
        Attesa fine battaglia: sleep passivo totale + 1 check final.

        WU75 (30/04 mattina) — refactor da polling adattivo a sleep+single-check.
        Pre-fix: 17 screenshot/battaglia (polling ogni 3.5s × 60s) causavano
        cascade ADB nelle transizioni post-battaglia (8/11 istanze 30/04 con
        cascade da 6-17 screenshot fallito).

        Strategia (con skip checkbox attivo da WU74 ad ogni sfida):
          1. Sleep passivo totale (delay_iniziale + max_battaglia)
          2. 1 screenshot finale → match victory + failure
          3. Return esito o False/False se fallisce

        Saving: ~94% screencap durante battaglia (17→1).
        Trade-off: se skip è OFF reale (template false positive), battaglia
        può durare >60s → single check fallisce → timeout normale (uguale al
        comportamento pre-fix in caso di timeout).

        Returns:
            (victory, failure) — entrambi False = timeout/anomalia.
        """
        total_wait = _DELAY_BATTAGLIA_S + _MAX_BATTAGLIA_S
        ctx.log_msg("[ARENA] attesa battaglia passiva %.0fs (WU75 no polling)",
                    total_wait)
        time.sleep(total_wait)

        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[ARENA] screenshot post-battaglia fallito — assumo timeout")
            return False, False

        victory = self._match(ctx, screen, "victory")
        failure = self._match(ctx, screen, "failure")

        if victory or failure:
            ctx.log_msg("[ARENA] fine battaglia rilevata dopo %.0fs", total_wait)
        else:
            ctx.log_msg("[ARENA] timeout battaglia dopo %.0fs — né Victory né Failure",
                        total_wait)
        return victory, failure

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

    # WU83 — Rebuild truppe pre-1ª sfida (ad ogni avvio nuovo giorno UTC)
    def _rebuild_truppe(self, ctx: TaskContext, n_celle: int) -> None:
        """
        Rimuove tutte le truppe schierate + ricarica via READY auto-deploy.

        Sequenza:
          1. Tap N pulsanti "−" rimozione (colonna sx coord 80,y_remove[i])
          2. Per ogni cella vuota:
             - Tap centro cella (apre selettore truppe)
             - Tap READY (723,482) → auto-deploy migliore composizione
          3. Ritorna alla pre-battle screen con N truppe schierate

        n_celle: 4 (default) o 5 (FAU_00, FauMorfeus). 5ª cella >= max disponibili
                 sarà ignorata silenziosamente se lucchettata.

        Test live FAU_06 30/04 (4 celle): power 431k → 685k post-rebuild (+59%).

        WU114 (04/05): debug screenshot buffer per analisi rebuild non completo.
        Snap a punti chiave (pre/post rimozione, per ogni cella pre/post tap+READY,
        post-rebuild). Flush in `data/arena_debug/{ist}_{ts}_{idx}_{label}.png`.
        """
        ctx.log_msg(f"[ARENA] [WU83] rebuild truppe — {n_celle} celle")
        n = max(1, min(5, int(n_celle)))

        # WU115 — debug buffer via shared/debug_buffer (hot-reload via config)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("arena", getattr(ctx, "instance_name", "_unknown"))
        debug.snap("00_pre_rebuild", ctx.device.screenshot())

        # Step 1: rimuovi N truppe correnti
        for i in range(n):
            x, y = _TAP_REMOVE_TRUPPA[i]
            ctx.device.tap(x, y)
            time.sleep(_DELAY_REBUILD_S)
        time.sleep(2.0)  # stabilizzazione UI post-rimozione
        debug.snap("01_post_rimozione", ctx.device.screenshot())

        # Step 2: riempi N celle con auto-deploy
        for i in range(n):
            x, y = _TAP_OPEN_CELLA[i]
            ctx.log_msg(f"[ARENA] [WU83] cella {i+1}/{n} — tap ({x},{y}) + READY")
            ctx.device.tap(x, y)
            time.sleep(2.5)  # apertura selettore truppe
            debug.snap(f"02_cella{i+1}_open_selettore", ctx.device.screenshot())
            ctx.device.tap(*_TAP_READY_DEPLOY)
            time.sleep(2.5)  # ready + chiusura pannello
            debug.snap(f"03_cella{i+1}_post_ready", ctx.device.screenshot())

        debug.snap("04_post_rebuild_complete", ctx.device.screenshot())
        # WU115: rebuild è always-flush quando debug enabled (force=True).
        # Saving disco gestito dal toggle config + cleanup automatico 7gg.
        debug.flush(success=True, force=True, log_fn=ctx.log_msg)


# ──────────────────────────────────────────────────────────────────────────────
# WU83 — State helper: 1×/die UTC per istanza
# ──────────────────────────────────────────────────────────────────────────────

def _deploy_state_path() -> Path:
    """Path data/arena_deploy_state.json (rispetta DOOMSDAY_ROOT)."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "arena_deploy_state.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _deploy_done_today(nome: str) -> bool:
    """True se rebuild già fatto oggi (UTC) per `nome`. Failsafe → False."""
    if not nome:
        return False
    try:
        path = _deploy_state_path()
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get(nome) == _today_utc()
    except Exception:
        return False


def _mark_deploy_done(nome: str) -> None:
    """Aggiorna data/arena_deploy_state.json[nome] = oggi UTC. Atomic write."""
    if not nome:
        return
    try:
        path = _deploy_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data[nome] = _today_utc()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass
