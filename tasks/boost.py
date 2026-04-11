# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/boost.py
#
#  Task: attivazione Gathering Speed Boost prima della raccolta.
#  SINCRONO (Step 25) — time.sleep, ctx.log_msg, navigator sincrono.
#
#  Flusso:
#    1. Assicura HOME via navigator
#    2. Screenshot + tap TAP_BOOST → apre Manage Shelter
#    3. Verifica pin_manage → popup aperto
#    4. Scroll finché pin_speed visibile (max MAX_SWIPE)
#    5. Se pin_50_ visibile → boost già attivo → chiudi popup
#    6. Tap riga Gathering Speed (coordinate dal match)
#    7. Cerca pin_speed_8h + pin_speed_use → tap USE (coordinate dal match)
#    8. Fallback: cerca pin_speed_1d + pin_speed_use → tap USE
#    9. Nessun boost → chiudi popup (non è un errore bloccante)
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from core.device import FakeDevice
    from shared.template_matcher import TemplateMatcher


@dataclass
class BoostConfig:
    tap_boost:        tuple[int, int] = (142, 47)
    n_back_chiudi:    int             = 3
    max_swipe:        int             = 8
    swipe_x:          int             = 480
    swipe_y_start:    int             = 380
    swipe_y_end:      int             = 280
    swipe_dur_ms:     int             = 400
    wait_after_tap:   float           = 1.5
    wait_after_swipe: float           = 1.5
    wait_after_use:   float           = 1.5
    wait_after_back:  float           = 0.5
    wait_after_speed_tap: float         = 2.0
    tmpl_boost:       str             = "pin/pin_boost.png"
    tmpl_manage:      str             = "pin/pin_manage.png"
    tmpl_speed:       str             = "pin/pin_speed.png"
    tmpl_50:          str             = "pin/pin_50_.png"
    tmpl_speed_8h:    str             = "pin/pin_speed_8h.png"
    tmpl_speed_1d:    str             = "pin/pin_speed_1d.png"
    tmpl_speed_use:   str             = "pin/pin_speed_use.png"
    soglia_boost:     float           = 0.80
    soglia_manage:    float           = 0.75
    soglia_speed:     float           = 0.75
    soglia_50:        float           = 0.75
    soglia_8h:        float           = 0.75
    soglia_1d:        float           = 0.75
    soglia_use:       float           = 0.75


class _Outcome:
    GIA_ATTIVO        = "boost_gia_attivo"
    ATTIVATO_8H       = "boost_attivato_8h"
    ATTIVATO_1D       = "boost_attivato_1d"
    NESSUN_BOOST      = "nessun_boost_disponibile"
    POPUP_NON_APERTO  = "popup_non_aperto"
    SPEED_NON_TROVATO = "speed_non_trovato"
    ERRORE            = "errore"


class BoostTask(Task):
    """Attiva Gathering Speed Boost. Scheduling: daily, priority=10."""

    def __init__(self, config: BoostConfig | None = None) -> None:
        self._cfg = config or BoostConfig()

    def name(self) -> str:
        return "boost"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("boost")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        def log(msg: str) -> None:
            ctx.log_msg(f"[BOOST] {msg}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="assicura_home")

        try:
            outcome = self._esegui_boost(ctx.device, ctx.matcher, log, self._cfg)
        except Exception as exc:
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_boost")

        return self._mappa_outcome(outcome, log)

    # ── Flusso principale ─────────────────────────────────────────────────────

    def _esegui_boost(self, device, matcher, log, cfg: BoostConfig) -> str:

        # STEP 1 — tap boost
        shot    = device.screenshot()
        score_b = matcher.score(shot, cfg.tmpl_boost)
        log(f"pin_boost score={score_b:.3f} → tap {cfg.tap_boost}")
        device.tap(*cfg.tap_boost)
        time.sleep(cfg.wait_after_tap)

        # STEP 2 — verifica popup Manage Shelter
        shot    = device.screenshot()
        score_m = matcher.score(shot, cfg.tmpl_manage)
        log(f"pin_manage score={score_m:.3f}")
        if score_m < cfg.soglia_manage:
            log("Popup non aperto — abort")
            self._chiudi_popup(device, cfg)
            return _Outcome.POPUP_NON_APERTO

        # STEP 3 — scroll fino a pin_speed
        speed_trovato = False
        speed_cy      = -1
        score_50_last = -1.0

        for swipe_n in range(cfg.max_swipe + 1):
            shot        = device.screenshot()
            score_speed = matcher.score(shot, cfg.tmpl_speed)
            score_50    = matcher.score(shot, cfg.tmpl_50)
            log(f"swipe {swipe_n:02d} → pin_speed={score_speed:.3f}  pin_50_={score_50:.3f}")

            if score_speed >= cfg.soglia_speed:
                match         = matcher.find(shot, cfg.tmpl_speed, threshold=cfg.soglia_speed)
                speed_cy      = match.cy if match else 270
                speed_trovato = True
                score_50_last = score_50
                log(f"pin_speed TROVATO cy={speed_cy}")
                break

            score_50_last = max(score_50_last, score_50)
            if swipe_n < cfg.max_swipe:
                self._swipe_su(device, cfg)

        if not speed_trovato:
            log(f"pin_speed non trovato dopo {cfg.max_swipe} swipe — abort")
            self._chiudi_popup(device, cfg)
            return _Outcome.SPEED_NON_TROVATO

        # STEP 4 — boost già attivo?
        if score_50_last >= cfg.soglia_50:
            log(f"Boost GIÀ ATTIVO (pin_50_ score={score_50_last:.3f}) → chiudo")
            self._chiudi_popup(device, cfg)
            return _Outcome.GIA_ATTIVO

        # STEP 5 — tap riga Gathering Speed
        tap_speed = (480, speed_cy)
        log(f"Tap Gathering Speed {tap_speed}")
        device.tap(*tap_speed)
        time.sleep(cfg.wait_after_speed_tap)

        shot = device.screenshot()
        if shot is None:
            self._chiudi_popup(device, cfg)
            return _Outcome.ERRORE

        # STEP 6 — boost 8h
        score_8h  = matcher.score(shot, cfg.tmpl_speed_8h)
        match_use = matcher.find(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)
        score_use = match_use.score if match_use else -1.0
        log(f"pin_speed_8h={score_8h:.3f}  pin_speed_use={score_use:.3f}")

        if score_8h >= cfg.soglia_8h and match_use is not None:
            log(f"Boost 8h → tap USE ({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            time.sleep(cfg.wait_after_use)
            device.back()
            time.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_8H

        # STEP 7 — fallback boost 1d
        score_1d  = matcher.score(shot, cfg.tmpl_speed_1d)
        match_use = matcher.find(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)
        score_use = match_use.score if match_use else -1.0
        log(f"pin_speed_1d={score_1d:.3f}  pin_speed_use={score_use:.3f}")

        if score_1d >= cfg.soglia_1d and match_use is not None:
            log(f"Boost 1d → tap USE ({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            time.sleep(cfg.wait_after_use)
            device.back()
            time.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_1D

        log("Nessun boost gratuito — chiudo popup")
        self._chiudi_popup(device, cfg)
        return _Outcome.NESSUN_BOOST

    # ── Helper ────────────────────────────────────────────────────────────────

    def _chiudi_popup(self, device, cfg: BoostConfig) -> None:
        for _ in range(cfg.n_back_chiudi):
            device.back()
            time.sleep(cfg.wait_after_back)

    def _swipe_su(self, device, cfg: BoostConfig) -> None:
        device.swipe(cfg.swipe_x, cfg.swipe_y_start,
                     cfg.swipe_x, cfg.swipe_y_end, cfg.swipe_dur_ms)
        time.sleep(cfg.wait_after_swipe)

    # ── Mapping outcome → TaskResult ──────────────────────────────────────────

    @staticmethod
    def _mappa_outcome(outcome: str, log) -> TaskResult:
        mapping = {
            _Outcome.GIA_ATTIVO:        TaskResult.ok("Speed boost già attivo"),
            _Outcome.ATTIVATO_8H:       TaskResult.ok("Speed boost 8h attivato",  durata="8h"),
            _Outcome.ATTIVATO_1D:       TaskResult.ok("Speed boost 1d attivato",  durata="1d"),
            _Outcome.NESSUN_BOOST:      TaskResult.skip("Nessun boost gratuito disponibile"),
            _Outcome.POPUP_NON_APERTO:  TaskResult.skip("Manage Shelter non aperto"),
            _Outcome.SPEED_NON_TROVATO: TaskResult.skip("Riga Gathering Speed non trovata"),
            _Outcome.ERRORE:            TaskResult.fail("Errore generico boost"),
        }
        result = mapping.get(outcome, TaskResult.fail(f"Outcome sconosciuto: {outcome}"))
        log(f"Outcome={outcome!r} → {result}")
        return result
