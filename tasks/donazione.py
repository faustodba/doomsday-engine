"""
tasks/donazione.py — DonazioneTask V6
======================================
Dona risorse alla tecnologia dell'alleanza marcata come "Marked!".

Flusso:
  HOME → tap_barra("alliance") → Technology → cerca pin_marked
  → tap marked → verifica pin_donate (giallo)
  → se donate presente: tappa (max 30 volte) → back×3
  → se research o donate assente: back×1 → exit

Scheduling: always (analogo a RaccoltaTask)
  - e_dovuto() → True sempre
  - Gate reale: presenza/assenza pin_donate nella UI
  - Flag abilitato: globali.task.donazione (runtime_overrides.json)

Priority: 105 (dopo RifornimentoTask=100, prima RaccoltaTask=110)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from core.task import Task as BaseTask, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DonazioneConfig:
    # --- Navigazione ---
    tap_technology: tuple[int, int] = (753, 446)   # bottone Technology nel menu Alliance
    tap_donate_giallo: tuple[int, int] = (739, 434) # bottone Donate giallo (risorse)
    tap_close_x: tuple[int, int] = (844, 57)        # X chiusura popup tecnologia

    # --- Template ---
    pin_marked: str = "pin/pin_marked.png"       # badge "Marked!" sulla tecnologia
    pin_donate: str = "pin/pin_donate.png"       # bottone Donate giallo attivo (file da creare)
    pin_research: str = "pin/pin_research.png"   # bottone Research (skip — tecnologia in upgrade)

    # --- Soglie TM ---
    score_marked: float = 0.75
    score_donate: float = 0.75
    score_research: float = 0.75

    # --- Delay ---
    wait_alliance_open: float = 2.0   # dopo tap_barra alliance
    wait_technology_open: float = 4.0 # dopo tap Technology (prima di scan pin_marked)
    wait_marked_tap: float = 2.0      # dopo tap sulla tecnologia marked
    wait_donate_tap: float = 1.5      # dopo ogni tap Donate
    wait_back: float = 1.0            # dopo ogni device.back()

    # --- Safety ---
    max_donate_tap: int = 30          # cap tap per esecuzione (sicurezza)
    max_marked_scan: int = 10         # max ricerche pin_marked per evitare loop


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class DonazioneTask(BaseTask):
    """
    Dona risorse alla tecnologia dell'alleanza con badge Marked!.
    Scheduling: always — e_dovuto() restituisce True ad ogni tick.
    Il gate reale è la presenza del bottone Donate nella UI.
    """

    def __init__(self) -> None:
        # Nota: V6 Task ABC non ha __init__ da chiamare via super().
        self.cfg = DonazioneConfig()

    # ------------------------------------------------------------------
    # V6 Task ABC — name + should_run (richiesti)
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "donazione"

    def should_run(self, ctx: TaskContext) -> bool:
        # Gate device/matcher + flag abilitazione globale
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("donazione")
        return True

    # ------------------------------------------------------------------
    # Scheduling always — analogo a RaccoltaTask (metodo storico V5)
    # ------------------------------------------------------------------

    def e_dovuto(self, ctx: TaskContext) -> bool:  # noqa: ARG002
        return True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        # Guard flag abilitato — V6 API _InstanceCfg.task_abilitato()
        # Nota: in V6 should_run() gia' esegue questo check prima di run(),
        # ma conserviamo il guard interno per robustezza anche in test/dev.
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("donazione"):
                ctx.log_msg("[DONAZIONE] disabilitato — skip")
                return TaskResult(success=True, skipped=True)

        ctx.log_msg("[DONAZIONE] avvio")

        try:
            # 1. Naviga ad Alliance → Technology
            if not self._naviga_technology(ctx):
                return TaskResult(success=False, message="navigazione fallita")

            # 2. Cerca marked e dona
            donate_count = self._cerca_e_dona(ctx)

            # 3. Torna in home
            ctx.navigator.vai_in_home()

            ctx.log_msg(f"[DONAZIONE] completato — donate={donate_count}")
            return TaskResult(success=True, message=f"donate={donate_count}")

        except Exception as exc:  # pylint: disable=broad-except
            ctx.log_msg(f"[DONAZIONE] errore imprevisto: {exc}")
            ctx.navigator.vai_in_home()
            return TaskResult(success=False, message=str(exc))

    # ------------------------------------------------------------------
    # Step 1 — Navigazione
    # ------------------------------------------------------------------

    def _naviga_technology(self, ctx: TaskContext) -> bool:
        """HOME → Alliance (tap_barra) → Technology."""

        # Alliance via tap_barra (standard V6 — no coordinate hardcoded)
        ctx.log_msg("[DONAZIONE] tap_barra alliance")
        ctx.navigator.tap_barra(ctx, "alliance")
        time.sleep(self.cfg.wait_alliance_open)

        # Technology
        ctx.log_msg("[DONAZIONE] tap Technology")
        ctx.device.tap(*self.cfg.tap_technology)
        time.sleep(self.cfg.wait_technology_open)

        # Verifica: schermata Technology aperta (pin_marked visibile o assente — non blocchiamo)
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[DONAZIONE] screenshot fallito dopo Technology")
            return False

        ctx.log_msg("[DONAZIONE] Technology aperta")
        return True

    # ------------------------------------------------------------------
    # Step 2 — Cerca pin_marked e dona
    # ------------------------------------------------------------------

    def _cerca_e_dona(self, ctx: TaskContext) -> int:
        """
        Cerca pin_marked nella schermata Technology.
        Se trovato: apre popup → verifica donate → dona (max cfg.max_donate_tap volte).
        Ritorna il numero di donate eseguiti.
        """
        donate_count = 0

        # Auto-WU6 (25/04): retry vero su scan pin_marked (era break al primo).
        # Pattern: 86% donate=0 (38/44) vs solo 6 successi → sospetto timing/loading.
        # Ora: scan fino a 3 volte con sleep 1s tra retry. Log dello score
        # effettivo per diagnosi (prima diceva solo "non trovato").
        SCAN_RETRY_MAX = 3
        not_found_score = 0.0
        for scan_idx in range(self.cfg.max_marked_scan):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[DONAZIONE] screenshot fallito durante scan marked")
                break

            result = ctx.matcher.find_one(screen, self.cfg.pin_marked)

            if result is None or result.score < self.cfg.score_marked:
                actual_score = result.score if result is not None else 0.0
                not_found_score = max(not_found_score, actual_score)
                ctx.log_msg(
                    f"[DONAZIONE] pin_marked NON trovato (scan {scan_idx + 1}) "
                    f"score={actual_score:.3f} (soglia={self.cfg.score_marked:.2f})"
                )
                if scan_idx + 1 < SCAN_RETRY_MAX:
                    time.sleep(1.0)
                    continue
                # Esauriti retry → conferma assenza tech donabile
                ctx.log_msg(
                    f"[DONAZIONE] {SCAN_RETRY_MAX} scan falliti — best score "
                    f"{not_found_score:.3f}. Nessuna tecnologia donabile."
                )
                # Chiudi Technology + menu Alliance prima del break, così
                # vai_in_home() successivo trova HOME e non si stucca su 8
                # retry falliti (bloccando il gate HOME delle task successive).
                # Back x3 coerente con i rami research/non_riconosciuto.
                for _ in range(3):
                    ctx.device.back()
                    time.sleep(self.cfg.wait_back)
                break

            cx, cy = result.cx, result.cy
            ctx.log_msg(
                f"[DONAZIONE] pin_marked trovato score={result.score:.3f} "
                f"pos=({cx},{cy}) — tap"
            )

            # Tap sulla tecnologia marked
            ctx.device.tap(cx, cy)
            time.sleep(self.cfg.wait_marked_tap)

            # Verifica popup: Research o Donate?
            n = self._gestisci_popup(ctx)
            donate_count += n

            # Se abbiamo già raggiunto il cap di sicurezza, usciamo
            if donate_count >= self.cfg.max_donate_tap:
                ctx.log_msg(f"[DONAZIONE] cap max_donate_tap={self.cfg.max_donate_tap} raggiunto")
                # Chiudi popup e torna alla Technology
                ctx.device.back()
                time.sleep(self.cfg.wait_back)
                break

            # Dopo _gestisci_popup siamo già tornati alla schermata Technology
            # (back×1 dal popup). Se n==0 il popup era Research o donate esaurito:
            # non ha senso continuare a cercare altri marked in questa esecuzione.
            if n == 0:
                ctx.log_msg("[DONAZIONE] donate non disponibile — exit scan")
                break

        return donate_count

    # ------------------------------------------------------------------
    # Step 3 — Gestione popup tecnologia
    # ------------------------------------------------------------------

    def _gestisci_popup(self, ctx: TaskContext) -> int:
        """
        Analizza il popup aperto dopo tap su tecnologia marked.

        Casi:
          A) pin_research visibile → skip (back×1)
          B) pin_donate visibile   → dona in loop (max 30 tap totali)
                                     poi back×3
          C) nessuno dei due       → back×1 (sicurezza)

        Ritorna il numero di donate eseguiti (0 nei casi A e C).
        """
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[DONAZIONE] screenshot fallito nel popup — back×3")
            for i in range(3):
                ctx.device.back()
                time.sleep(self.cfg.wait_back)
                ctx.log_msg(f"[DONAZIONE] back {i + 1}/3")
            return 0

        # --- Caso A: Research (tecnologia in upgrade attivo) ---
        res_research = ctx.matcher.find_one(screen, self.cfg.pin_research)
        if res_research is not None and res_research.score >= self.cfg.score_research:
            ctx.log_msg(
                f"[DONAZIONE] pin_research rilevato score={res_research.score:.3f} "
                f"— tecnologia in upgrade, skip"
            )
            # back×3 per chiudere popup + Technology + menu Alliance → HOME
            for i in range(3):
                ctx.device.back()
                time.sleep(self.cfg.wait_back)
                ctx.log_msg(f"[DONAZIONE] back {i + 1}/3")
            return 0

        # --- Caso B: Donate disponibile ---
        res_donate = ctx.matcher.find_one(screen, self.cfg.pin_donate)
        if res_donate is not None and res_donate.score >= self.cfg.score_donate:
            ctx.log_msg(
                f"[DONAZIONE] pin_donate rilevato score={res_donate.score:.3f} — inizio donazione"
            )
            count = self._loop_donate(ctx)
            # Chiudi popup: back×3
            for i in range(3):
                ctx.device.back()
                time.sleep(self.cfg.wait_back)
                ctx.log_msg(f"[DONAZIONE] back {i + 1}/3")
            return count

        # --- Caso C: nessun pin riconosciuto ---
        ctx.log_msg("[DONAZIONE] popup non riconosciuto (né research né donate) — back×3")
        # back×3 per chiudere popup + Technology + menu Alliance → HOME
        for i in range(3):
            ctx.device.back()
            time.sleep(self.cfg.wait_back)
            ctx.log_msg(f"[DONAZIONE] back {i + 1}/3")
        return 0

    # ------------------------------------------------------------------
    # Step 4 — Loop donate
    # ------------------------------------------------------------------

    def _loop_donate(self, ctx: TaskContext) -> int:
        """
        Tappa il bottone Donate giallo fino a:
          - pin_donate non più visibile (slot esauriti)
          - raggiunto max_donate_tap (safety cap)

        Nota: il tap viene eseguito sempre su coordinate fisse (cfg.tap_donate_giallo).
        In assenza di donazioni disponibili, il tap non produce eventi UI —
        il gate è il TM su pin_donate dopo ogni tap.

        Ritorna il numero di tap eseguiti.
        """
        count = 0

        for tap_idx in range(self.cfg.max_donate_tap):
            # Tap donate giallo
            ctx.device.tap(*self.cfg.tap_donate_giallo)
            time.sleep(self.cfg.wait_donate_tap)
            count += 1

            ctx.log_msg(f"[DONAZIONE] tap donate #{count}")

            # Verifica se donate è ancora disponibile
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[DONAZIONE] screenshot fallito durante loop donate — stop")
                break

            res = ctx.matcher.find_one(screen, self.cfg.pin_donate)
            if res is None or res.score < self.cfg.score_donate:
                ctx.log_msg(
                    f"[DONAZIONE] pin_donate non più visibile dopo tap #{count} "
                    f"— slot esauriti, stop"
                )
                break

            ctx.log_msg(
                f"[DONAZIONE] pin_donate ancora visibile score={res.score:.3f} "
                f"— continua"
            )

        else:
            # Loop completato senza break = cap raggiunto
            ctx.log_msg(
                f"[DONAZIONE] safety cap raggiunto ({self.cfg.max_donate_tap} tap)"
            )

        return count
