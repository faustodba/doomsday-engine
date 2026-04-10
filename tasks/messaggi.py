# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/messaggi.py             → C:\doomsday-engine\tasks\messaggi.py
#
#  Task: raccolta ricompense dalla sezione Messaggi (tab Alliance + System).
#
#  Flusso (identico V5):
#    1. Assicura HOME via navigator
#    2. Tap icona busta messaggi
#    3. [PRE-OPEN] verifica schermata aperta (pin_msg_alliance)
#    4. Tap tab ALLIANCE → verifica attivo → tap Read and claim all se visibile
#    5. Tap tab SYSTEM   → verifica attivo → tap Read and claim all se visibile
#    6. Tap X chiudi → BACK×3 → verifica HOME finale
#
#  Templates richiesti in templates/pin/:
#    pin_msg_02_alliance.png    pin_msg_03_system.png    pin_msg_04_read.png
#
#  Scheduling: periodic, interval_h=4, priority=30.
#  Outcome:
#    TaskResult.ok()   → completato (anche senza messaggi da raccogliere)
#    TaskResult.skip() → schermata non aperta, tab anomalo
#    TaskResult.fail() → errore strutturale
# ==============================================================================

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# MessaggiConfig
# ==============================================================================

@dataclass
class MessaggiConfig:
    """Parametri configurabili per MessaggiTask."""

    # ── Coordinate UI (960×540) ───────────────────────────────────────────────
    tap_icona_messaggi: tuple[int, int] = (930, 13)   # icona busta in home
    tap_tab_alliance:   tuple[int, int] = (325, 35)   # centro ROI alliance tab
    tap_tab_system:     tuple[int, int] = (453, 36)   # centro ROI system tab
    tap_read_all:       tuple[int, int] = (108, 511)  # Read and claim all
    tap_close:          tuple[int, int] = (930, 36)   # X chiudi messaggi

    # ── ROI template matching (x1, y1, x2, y2) ───────────────────────────────
    roi_alliance: tuple[int, int, int, int] = (283,  23, 367,  47)
    roi_system:   tuple[int, int, int, int] = (417,  23, 490,  50)
    roi_read:     tuple[int, int, int, int] = ( 61, 499, 156, 523)

    # ── Soglie template matching ──────────────────────────────────────────────
    soglia_alliance: float = 0.80
    soglia_system:   float = 0.80
    soglia_read:     float = 0.85

    # ── Attese ────────────────────────────────────────────────────────────────
    wait_open:       float = 2.0   # dopo tap icona messaggi
    wait_tab:        float = 1.0   # dopo tap tab
    wait_read:       float = 2.0   # dopo tap Read and claim all
    wait_close:      float = 1.5   # dopo tap X
    wait_back:       float = 0.5   # tra BACK multipli
    n_back_close:    int   = 3     # BACK dopo chiusura per svuotare stack

    # ── Retry verifica tab ────────────────────────────────────────────────────
    retry_tab:   int   = 2
    retry_sleep: float = 1.0

    # ── Template paths (relativi a templates/) ────────────────────────────────
    tmpl_alliance: str = "pin/pin_msg_02_alliance.png"
    tmpl_system:   str = "pin/pin_msg_03_system.png"
    tmpl_read:     str = "pin/pin_msg_04_read.png"


# ==============================================================================
# Esiti interni
# ==============================================================================

class _Esito:
    COMPLETATO         = "completato"
    SCHERMATA_NON_APERTA = "schermata_non_aperta"
    ERRORE             = "errore"


# ==============================================================================
# MessaggiTask
# ==============================================================================

class MessaggiTask(Task):
    """
    Raccoglie le ricompense dalla sezione Messaggi (tab Alliance + System).

    Scheduling: periodic, interval_h=4, priority=30.
    Registrato in scheduler come:
        scheduler.register("messaggi", kind="periodic", interval_h=4, priority=30)

    Il task è non-bloccante: tab anomalo → log + procedi (non fail).
    Solo schermata non aperta → skip().
    """

    def __init__(self, config: MessaggiConfig | None = None) -> None:
        self._cfg = config or MessaggiConfig()

    # ── ABC: name ─────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "messaggi"

    # ── ABC: should_run ───────────────────────────────────────────────────────

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("messaggi")
        return True

    # ── ABC: run ──────────────────────────────────────────────────────────────

    async def run(self, ctx: TaskContext) -> TaskResult:
        cfg     = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            if ctx.log:
                ctx.log.info(self.name(), f"[MSG] {msg}")

        # ── Step 0: assicura HOME ─────────────────────────────────────────────
        if ctx.navigator is not None:
            if not await ctx.navigator.vai_in_home():
                return TaskResult.fail(
                    "Navigator non ha raggiunto HOME",
                    step="assicura_home",
                )
        else:
            log("Navigator non disponibile — assumo HOME corrente")

        try:
            esito, alliance_ok, system_ok = await self._esegui_messaggi(
                device, matcher, log, cfg
            )
        except Exception as exc:
            return TaskResult.fail(f"Eccezione non gestita: {exc}", step="esegui_messaggi")

        return self._mappa_esito(esito, alliance_ok, system_ok, log)

    # ── Flusso principale ─────────────────────────────────────────────────────

    async def _esegui_messaggi(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     MessaggiConfig,
    ) -> tuple[str, bool, bool]:
        """
        Flusso completo messaggi.
        Ritorna (esito, alliance_ok, system_ok).
        """

        # ── STEP 1: apri schermata messaggi ──────────────────────────────────
        log(f"Tap icona messaggi {cfg.tap_icona_messaggi}")
        await device.tap(*cfg.tap_icona_messaggi)
        await asyncio.sleep(cfg.wait_open)

        # [PRE-OPEN] verifica schermata aperta
        ok_open = await self._verifica_pin(
            device, matcher, cfg.tmpl_alliance,
            cfg.soglia_alliance, cfg.roi_alliance,
            retry=2, retry_sleep=1.5, log=log, label="PRE-OPEN"
        )
        if not ok_open:
            log("[PRE-OPEN] ANOMALIA: schermata messaggi non aperta — BACK + abort")
            await device.back()
            await asyncio.sleep(cfg.wait_back)
            return _Esito.SCHERMATA_NON_APERTA, False, False

        log("[PRE-OPEN] schermata messaggi aperta — OK")

        # ── STEP 2: tab ALLIANCE ──────────────────────────────────────────────
        alliance_ok = await self._gestisci_tab(
            device, matcher,
            tab_tap=cfg.tap_tab_alliance,
            tab_tmpl=cfg.tmpl_alliance,
            tab_soglia=cfg.soglia_alliance,
            tab_roi=cfg.roi_alliance,
            nome_tab="Alliance",
            log=log, cfg=cfg,
        )

        # ── STEP 3: tab SYSTEM ────────────────────────────────────────────────
        system_ok = await self._gestisci_tab(
            device, matcher,
            tab_tap=cfg.tap_tab_system,
            tab_tmpl=cfg.tmpl_system,
            tab_soglia=cfg.soglia_system,
            tab_roi=cfg.roi_system,
            nome_tab="System",
            log=log, cfg=cfg,
        )

        # ── STEP 4: chiudi ────────────────────────────────────────────────────
        log(f"Chiusura schermata messaggi → tap X {cfg.tap_close}")
        await device.tap(*cfg.tap_close)
        await asyncio.sleep(cfg.wait_close)

        for _ in range(cfg.n_back_close):
            await device.back()
            await asyncio.sleep(cfg.wait_back)

        log("Raccolta messaggi completata")
        return _Esito.COMPLETATO, alliance_ok, system_ok

    # ── Gestione singolo tab ──────────────────────────────────────────────────

    async def _gestisci_tab(
        self,
        device:     "MuMuDevice | FakeDevice",
        matcher:    "TemplateMatcher",
        tab_tap:    tuple[int, int],
        tab_tmpl:   str,
        tab_soglia: float,
        tab_roi:    tuple[int, int, int, int],
        nome_tab:   str,
        log,
        cfg:        MessaggiConfig,
    ) -> bool:
        """
        Seleziona un tab e clicca Read and claim all se visibile.
        Ritorna True se tab attivato correttamente, False se anomalia.
        """
        log(f"Tap tab {nome_tab} {tab_tap}")
        await device.tap(*tab_tap)
        await asyncio.sleep(cfg.wait_tab)

        # Verifica tab attivo con retry
        ok_tab = await self._verifica_pin(
            device, matcher, tab_tmpl, tab_soglia, tab_roi,
            retry=cfg.retry_tab, retry_sleep=cfg.retry_sleep,
            log=log, label=f"PRE-{nome_tab.upper()}"
        )
        if not ok_tab:
            log(f"[PRE-{nome_tab.upper()}] ANOMALIA: tab non attivo — skip tab")
            return False

        log(f"[PRE-{nome_tab.upper()}] tab attivo — OK")

        # Verifica bottone Read and claim all
        ok_read = await self._verifica_pin(
            device, matcher,
            cfg.tmpl_read, cfg.soglia_read, cfg.roi_read,
            retry=1, retry_sleep=1.0,
            log=log, label="PRE-READ"
        )
        if ok_read:
            log(f"[PRE-READ] bottone visibile — tap Read and claim all")
            await device.tap(*cfg.tap_read_all)
            await asyncio.sleep(cfg.wait_read)
        else:
            log(f"[PRE-READ] bottone non visibile — nessun messaggio su {nome_tab}")

        return True

    # ── Verifica pin con retry ────────────────────────────────────────────────

    async def _verifica_pin(
        self,
        device:      "MuMuDevice | FakeDevice",
        matcher:     "TemplateMatcher",
        tmpl:        str,
        soglia:      float,
        roi:         tuple[int, int, int, int],
        retry:       int,
        retry_sleep: float,
        log,
        label:       str,
    ) -> bool:
        """
        Verifica presenza pin con retry.
        Ritorna True se trovato entro i tentativi, False altrimenti.
        """
        for tentativo in range(retry + 1):
            shot  = await device.screenshot()
            score = matcher.score(shot, tmpl, zone=roi)
            found = score >= soglia
            log(f"[{label}] {tmpl}: score={score:.3f} → {'OK' if found else 'NON trovato'}"
                + (f" (t={tentativo+1})" if retry > 0 else ""))
            if found:
                return True
            if tentativo < retry:
                await asyncio.sleep(retry_sleep)
        return False

    # ── Mapping esito → TaskResult ────────────────────────────────────────────

    @staticmethod
    def _mappa_esito(
        esito:       str,
        alliance_ok: bool,
        system_ok:   bool,
        log,
    ) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(
                "Messaggi completati",
                alliance=alliance_ok,
                system=system_ok,
            )
        if esito == _Esito.SCHERMATA_NON_APERTA:
            log("Outcome=schermata_non_aperta → skip")
            return TaskResult.skip("Schermata messaggi non aperta")
        log(f"Outcome={esito!r} → fail")
        return TaskResult.fail(f"Errore messaggi: {esito}")

    def __repr__(self) -> str:
        return f"MessaggiTask(config={self._cfg})"
