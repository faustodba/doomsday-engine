# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/boost.py                  → C:\doomsday-engine\tasks\boost.py
#
#  Task: attivazione Gathering Speed Boost prima della raccolta.
#
#  Flusso (identico V5, portato su architettura V6):
#    1. Precondizione: assicura HOME via navigator
#    2. Tap TAP_BOOST (142, 47) → apre Manage Shelter
#    3. Verifica pin_manage → popup aperto
#    4. Scroll verso il basso finché pin_speed visibile (max MAX_SWIPE)
#    5. Verifica pin_50_ → se trovato: boost già attivo → chiudi popup
#    6. Tap riga Gathering Speed
#    7. Cerca pin_speed_8h + pin_speed_use → tap USE
#    8. Fallback: cerca pin_speed_1d + pin_speed_use → tap USE
#    9. Se nessun boost disponibile → chiudi popup (non è un errore bloccante)
#
#  Templates richiesti in <templates_dir>/pin/:
#    pin/pin_boost.png        pin/pin_manage.png      pin/pin_speed.png
#    pin/pin_50_.png          pin/pin_speed_8h.png    pin/pin_speed_1d.png
#    pin/pin_speed_use.png
#
#  Scheduling: daily, priority=10 (eseguito prima di raccolta).
#  Outcome:
#    TaskResult.ok()   → boost attivato o già attivo (raccolta può procedere)
#    TaskResult.skip() → boost non disponibile (raccolta può procedere ugualmente)
#    TaskResult.fail() → errore che impedisce di determinare lo stato del boost
# ==============================================================================

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# BoostConfig — parametri configurabili del task
# ==============================================================================

@dataclass
class BoostConfig:
    """Parametri di configurazione per BoostTask."""

    # ── Coordinate fisse (960×540) ────────────────────────────────────────────
    tap_boost:      tuple[int, int] = (142, 47)    # pulsante boost in home
    n_back_chiudi:  int             = 3             # BACK per chiudere popup

    # ── Scroll ricerca Gathering Speed ───────────────────────────────────────
    max_swipe:      int   = 8     # swipe massimi prima di dichiarare fallimento
    swipe_x:        int   = 480
    swipe_y_start:  int   = 380
    swipe_y_end:    int   = 280   # 100px verso l'alto — avanza nella lista
    swipe_dur_ms:   int   = 400

    # ── Attese ────────────────────────────────────────────────────────────────
    wait_after_tap:   float = 1.5
    wait_after_swipe: float = 1.5
    wait_after_use:   float = 1.5
    wait_after_back:  float = 0.5

    # ── Template paths (relativi a templates_dir) ────────────────────────────
    tmpl_boost:     str = "pin/pin_boost.png"
    tmpl_manage:    str = "pin/pin_manage.png"
    tmpl_speed:     str = "pin/pin_speed.png"
    tmpl_50:        str = "pin/pin_50_.png"
    tmpl_speed_8h:  str = "pin/pin_speed_8h.png"
    tmpl_speed_1d:  str = "pin/pin_speed_1d.png"
    tmpl_speed_use: str = "pin/pin_speed_use.png"

    # ── Soglie template matching ──────────────────────────────────────────────
    soglia_boost:   float = 0.80
    soglia_manage:  float = 0.75
    soglia_speed:   float = 0.75
    soglia_50:      float = 0.75
    soglia_8h:      float = 0.75
    soglia_1d:      float = 0.75
    soglia_use:     float = 0.75


# ==============================================================================
# BoostOutcome — esiti interni (non esposti all'esterno)
# ==============================================================================

class _Outcome:
    GIA_ATTIVO          = "boost_gia_attivo"
    ATTIVATO_8H         = "boost_attivato_8h"
    ATTIVATO_1D         = "boost_attivato_1d"
    NESSUN_BOOST        = "nessun_boost_disponibile"
    POPUP_NON_APERTO    = "popup_non_aperto"
    SPEED_NON_TROVATO   = "speed_non_trovato"
    ERRORE              = "errore"


# ==============================================================================
# BoostTask
# ==============================================================================

class BoostTask(Task):
    """
    Attiva il Gathering Speed Boost prima della raccolta risorse.

    Task di tipo DAILY (priority=10) — registrato in scheduler come:
        scheduler.register("boost", kind="daily", priority=10)

    Il task è non-bloccante: anche se il boost non è disponibile o il
    popup non si apre, ritorna skip() invece di fail(), permettendo
    alla raccolta di procedere comunque.

    Solo errori strutturali (device None, navigator non raggiunge HOME)
    producono TaskResult.fail().
    """

    def __init__(self, config: BoostConfig | None = None) -> None:
        self._cfg = config or BoostConfig()

    # ── ABC: name ─────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "boost"

    # ── ABC: should_run ───────────────────────────────────────────────────────

    def should_run(self, ctx: TaskContext) -> bool:
        """
        Precondizioni (puro, no I/O):
          - task abilitato in config
          - device disponibile
        La verifica dello stato daily (già eseguito oggi) è delegata
        allo scheduler — qui non la duplichiamo.
        """
        if ctx.device is None:
            return False
        if ctx.matcher is None:
            return False
        # Controllo config: se InstanceConfig espone task_abilitato()
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("boost")
        return True

    # ── ABC: run ──────────────────────────────────────────────────────────────

    async def run(self, ctx: TaskContext) -> TaskResult:
        """
        Esegue il flusso completo di attivazione boost.

        Struttura:
          1. Assicura HOME via navigator (se disponibile)
          2. Delega a _esegui_boost() per il flusso UI
          3. Mappa l'outcome interno in TaskResult

        Returns:
            TaskResult.ok()   → boost attivato o già attivo
            TaskResult.skip() → nessun boost disponibile, popup non aperto,
                                 riga speed non trovata (non è errore bloccante)
            TaskResult.fail() → errore strutturale (device, navigator)
        """
        cfg = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            if ctx.log:
                ctx.log.info(self.name(), f"[BOOST] {msg}")

        # ── Step 0: assicura HOME ─────────────────────────────────────────────
        if ctx.navigator is not None:
            log("Verifica HOME prima del boost")
            in_home = await ctx.navigator.vai_in_home()
            if not in_home:
                return TaskResult.fail(
                    "Navigator non ha raggiunto HOME",
                    step="assicura_home",
                )
        else:
            log("Navigator non disponibile — assumo schermata corrente corretta")

        # ── Step 1–9: flusso UI boost ─────────────────────────────────────────
        try:
            outcome = await self._esegui_boost(device, matcher, log, cfg)
        except Exception as exc:
            return TaskResult.fail(f"Eccezione non gestita: {exc}", step="esegui_boost")

        # ── Mappa outcome → TaskResult ────────────────────────────────────────
        return self._mappa_outcome(outcome, log)

    # ── Flusso UI interno ─────────────────────────────────────────────────────

    async def _esegui_boost(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     BoostConfig,
    ) -> str:
        """
        Flusso UI completo. Ritorna una stringa _Outcome.
        Separato da run() per testabilità indipendente.
        """

        # ── STEP 1 — Tap pulsante boost ───────────────────────────────────────
        shot = await device.screenshot()
        score_b = matcher.score(shot, cfg.tmpl_boost)
        if score_b >= cfg.soglia_boost:
            log(f"pin_boost visibile (score={score_b:.3f}) → tap {cfg.tap_boost}")
        else:
            log(f"pin_boost score={score_b:.3f} → tap fisso {cfg.tap_boost}")

        await device.tap(*cfg.tap_boost)
        await asyncio.sleep(cfg.wait_after_tap)

        # ── STEP 2 — Verifica popup Manage Shelter ────────────────────────────
        shot = await device.screenshot()
        score_m = matcher.score(shot, cfg.tmpl_manage)
        log(f"pin_manage: score={score_m:.3f} → {'OK' if score_m >= cfg.soglia_manage else 'NON TROVATO'}")

        if score_m < cfg.soglia_manage:
            log("Popup non aperto — chiudo e abort")
            await self._chiudi_popup(device, cfg)
            return _Outcome.POPUP_NON_APERTO

        # ── STEP 3 — Scroll fino a pin_speed ─────────────────────────────────
        log(f"Ricerca Gathering Speed (max {cfg.max_swipe} swipe)")

        speed_trovato = False
        speed_cy      = -1
        score_50_last = -1.0

        for swipe_n in range(cfg.max_swipe + 1):
            shot = await device.screenshot()

            score_speed = matcher.score(shot, cfg.tmpl_speed)
            score_50    = matcher.score(shot, cfg.tmpl_50)
            log(f"swipe {swipe_n:02d} → pin_speed={score_speed:.3f}  pin_50_={score_50:.3f}")

            if score_speed >= cfg.soglia_speed:
                # Recupera coordinate centro match
                match = matcher.find(shot, cfg.tmpl_speed, threshold=cfg.soglia_speed)
                speed_cy      = match.cy if match else 270
                speed_trovato = True
                score_50_last = score_50
                log(f"pin_speed TROVATO cy={speed_cy}")
                break

            # Aggiorna l'ultimo score_50 osservato (potrebbe essere visibile
            # nello stesso frame in cui speed non è ancora emerso)
            score_50_last = max(score_50_last, score_50)

            if swipe_n < cfg.max_swipe:
                await self._swipe_su(device, cfg)

        if not speed_trovato:
            log(f"pin_speed non trovato dopo {cfg.max_swipe} swipe — abort")
            await self._chiudi_popup(device, cfg)
            return _Outcome.SPEED_NON_TROVATO

        # ── STEP 4 — Boost già attivo? ────────────────────────────────────────
        if score_50_last >= cfg.soglia_50:
            log(f"Boost GIÀ ATTIVO (pin_50_ score={score_50_last:.3f}) → chiudo")
            await self._chiudi_popup(device, cfg)
            return _Outcome.GIA_ATTIVO

        log(f"Nessun boost attivo (pin_50_ score={score_50_last:.3f}) → procedo")

        # ── STEP 5 — Tap riga Gathering Speed ────────────────────────────────
        tap_speed = (480, speed_cy)
        log(f"Tap Gathering Speed {tap_speed}")
        await device.tap(*tap_speed)
        await asyncio.sleep(2.0)   # attesa popup selezione

        shot = await device.screenshot()
        if shot is None:
            log("Screenshot fallito dopo tap speed — abort")
            await self._chiudi_popup(device, cfg)
            return _Outcome.ERRORE

        # ── STEP 6 — Cerca boost 8h ───────────────────────────────────────────
        score_8h  = matcher.score(shot, cfg.tmpl_speed_8h)
        match_use = matcher.find(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)
        score_use = match_use.score if match_use else -1.0
        log(f"pin_speed_8h={score_8h:.3f}  pin_speed_use={score_use:.3f}")

        if score_8h >= cfg.soglia_8h and match_use is not None:
            log(f"Boost 8h → tap USE ({match_use.cx},{match_use.cy})")
            await device.tap(match_use.cx, match_use.cy)
            await asyncio.sleep(cfg.wait_after_use)
            await device.back()
            await asyncio.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_8H

        # ── STEP 7 — Fallback boost 1d ────────────────────────────────────────
        log("Boost 8h non disponibile — cerco 1d")
        score_1d  = matcher.score(shot, cfg.tmpl_speed_1d)
        match_use = matcher.find(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)
        score_use = match_use.score if match_use else -1.0
        log(f"pin_speed_1d={score_1d:.3f}  pin_speed_use={score_use:.3f}")

        if score_1d >= cfg.soglia_1d and match_use is not None:
            log(f"Boost 1d → tap USE ({match_use.cx},{match_use.cy})")
            await device.tap(match_use.cx, match_use.cy)
            await asyncio.sleep(cfg.wait_after_use)
            await device.back()
            await asyncio.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_1D

        # ── STEP 8 — Nessun boost gratuito ────────────────────────────────────
        log("Nessun boost gratuito disponibile — chiudo popup")
        await self._chiudi_popup(device, cfg)
        return _Outcome.NESSUN_BOOST

    # ── Helper: chiudi popup ──────────────────────────────────────────────────

    async def _chiudi_popup(
        self,
        device: "MuMuDevice | FakeDevice",
        cfg:    BoostConfig,
    ) -> None:
        """Invia N_BACK_CHIUDI BACK per chiudere il popup Manage Shelter."""
        for _ in range(cfg.n_back_chiudi):
            await device.back()
            await asyncio.sleep(cfg.wait_after_back)

    # ── Helper: swipe su ─────────────────────────────────────────────────────

    async def _swipe_su(
        self,
        device: "MuMuDevice | FakeDevice",
        cfg:    BoostConfig,
    ) -> None:
        """
        Scorre verso il basso nel popup (il dito sale, la lista avanza).
        Usa device.swipe() se disponibile, altrimenti device.scroll().
        """
        if hasattr(device, "swipe"):
            await device.swipe(
                cfg.swipe_x, cfg.swipe_y_start,
                cfg.swipe_x, cfg.swipe_y_end,
                duration_ms=cfg.swipe_dur_ms,
            )
        else:
            await device.scroll(
                cfg.swipe_x, cfg.swipe_y_start,
                cfg.swipe_x, cfg.swipe_y_end,
                durata_ms=cfg.swipe_dur_ms,
            )
        await asyncio.sleep(cfg.wait_after_swipe)

    # ── Mapping outcome → TaskResult ─────────────────────────────────────────

    @staticmethod
    def _mappa_outcome(outcome: str, log) -> TaskResult:
        """
        Converte la stringa _Outcome in TaskResult V6.

        Filosofia:
          - ok()   → boost applicato o già attivo (raccolta può procedere)
          - skip()  → nessun boost disponibile o popup non aperto
                      (non è un errore bloccante per la raccolta)
          - fail()  → errore strutturale che non dovrebbe accadere
        """
        mapping = {
            _Outcome.ATTIVATO_8H:      TaskResult.ok("Speed boost 8h attivato",  durata="8h"),
            _Outcome.ATTIVATO_1D:      TaskResult.ok("Speed boost 1d attivato",  durata="1d"),
            _Outcome.GIA_ATTIVO:       TaskResult.ok("Speed boost già attivo"),
            _Outcome.NESSUN_BOOST:     TaskResult.skip("Nessun boost gratuito disponibile"),
            _Outcome.POPUP_NON_APERTO: TaskResult.skip("Manage Shelter non aperto"),
            _Outcome.SPEED_NON_TROVATO:TaskResult.skip("Riga Gathering Speed non trovata"),
            _Outcome.ERRORE:           TaskResult.fail("Errore generico nel flusso boost"),
        }
        result = mapping.get(outcome, TaskResult.fail(f"Outcome sconosciuto: {outcome}"))
        log(f"Outcome={outcome!r} → {result}")
        return result

    def __repr__(self) -> str:
        return f"BoostTask(config={self._cfg})"
