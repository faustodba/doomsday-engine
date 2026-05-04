# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/alleanza.py
#
#  Task: raccolta ricompense Alleanza → Dono.
#  SINCRONO (Step 25) — time.sleep, ctx.log_msg, navigator sincrono.
#
#  MIGLIORAMENTO: loop Rivendica usa template matching su pin_claim.png
#  invece di coordinate fisse + heuristica cromatica. Il tap avviene sulla
#  posizione dinamica rilevata dal matcher → nessun click a vuoto.
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template


@dataclass
class AlleanzaConfig:
    coord_alleanza:     tuple[int, int] = (760, 505)
    coord_dono:         tuple[int, int] = (877, 458)
    coord_tab_negozio:  tuple[int, int] = (810,  75)
    coord_tab_attivita: tuple[int, int] = (600,  75)
    coord_raccogli:     tuple[int, int] = (856, 505)
    tmpl_claim:         str   = "pin/pin_claim.png"
    soglia_claim:       float = 0.75
    max_rivendica:      int   = 30   # auto-WU13: 20 → 30 (alleanza con molti claim disponibili)
    n_back_chiudi:      int   = 3
    wait_open_alleanza: float = 2.0
    wait_open_dono:     float = 2.0
    wait_tab:           float = 1.5   # Slow-PC: 0.8 → 1.5 (pre-match pin_claim)
    wait_rivendica:     float = 1.0   # Slow-PC: 0.55 → 1.0 (stabilizza UI post-claim)
    wait_raccogli:      float = 1.0
    wait_back:          float = 0.8
    wait_back_last:     float = 1.0


class _Esito:
    COMPLETATO  = "completato"
    NON_IN_HOME = "non_in_home"
    ERRORE      = "errore"


class AlleanzaTask(Task):
    """Raccoglie ricompense Alleanza → Dono. Scheduling: periodic 4h."""

    def __init__(self, config: AlleanzaConfig | None = None) -> None:
        self._cfg = config or AlleanzaConfig()

    def name(self) -> str:
        return "alleanza"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("alleanza")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg     = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            ctx.log_msg(f"[ALLEANZA] {msg}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.skip("Navigator non ha raggiunto HOME")

        coord_alleanza = cfg.coord_alleanza
        if hasattr(ctx.config, "coord_alleanza"):
            coord_alleanza = ctx.config.coord_alleanza

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.alleanza)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("alleanza", getattr(ctx, "instance_name", "_unknown"))
        self._dbg = debug

        try:
            esito, rivendiche, raccolti = self._esegui_alleanza(
                ctx, device, matcher, coord_alleanza, log, cfg
            )
        except Exception as exc:
            debug.snap("99_exception", device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_alleanza")

        # Anomalia: 0 rivendiche (cosa rara, normalmente alleanza ha 5-10 claim/run)
        anomalia = (esito == _Esito.COMPLETATO and rivendiche == 0)
        debug.flush(
            success=(esito == _Esito.COMPLETATO),
            force=anomalia,
            log_fn=log,
        )

        return self._mappa_esito(esito, rivendiche, raccolti, log)

    def _esegui_alleanza(self, ctx, device, matcher, coord_alleanza, log, cfg):
        _dbg = getattr(self, "_dbg", None)
        if _dbg is not None:
            _dbg.snap("00_pre_tap_alleanza", device.screenshot())

        # Issue #5 fix (03/05): tap_barra("alliance") con template matching
        # dinamico (pattern standard V6 — vedi donazione.py, rifornimento.py).
        nav = getattr(ctx, "navigator", None)
        if nav is not None and hasattr(nav, "tap_barra"):
            log("Tap Alleanza via tap_barra (template matching)")
            ok = nav.tap_barra(ctx, "alliance")
            if not ok:
                log(f"tap_barra alliance fallito — fallback coord fissa {coord_alleanza}")
                device.tap(*coord_alleanza)
        else:
            log(f"Tap Alleanza coord-fallback {coord_alleanza} (no navigator)")
            device.tap(*coord_alleanza)
        time.sleep(0.3)  # minimo animazione tap

        log(f"Tap Dono {cfg.coord_dono}")
        device.tap(*cfg.coord_dono)
        time.sleep(0.3)  # minimo animazione tap
        if _dbg is not None:
            _dbg.snap("01_post_tap_dono", device.screenshot())

        log(f"Tab Negozio {cfg.coord_tab_negozio}")
        device.tap(*cfg.coord_tab_negozio)
        time.sleep(cfg.wait_tab)
        if _dbg is not None:
            _dbg.snap("02_pre_claim_loop", device.screenshot())

        n_rivendiche = 0
        # auto-WU15: scroll lista quando pin_claim esce viewport (claims sotto).
        # Reset dopo ogni tap success: se la lista cambia, rivaluta scroll.
        scroll_used = False

        for i in range(cfg.max_rivendica):
            shot   = device.screenshot()
            result = matcher.find_one(shot, cfg.tmpl_claim)
            if not result.found or result.score < cfg.soglia_claim:
                if not scroll_used:
                    log(
                        f"pin_claim non trovato (score={result.score:.3f}) "
                        f"— scroll lista per claims sotto viewport"
                    )
                    device.swipe(480, 400, 480, 180, duration_ms=400)
                    time.sleep(cfg.wait_tab)
                    scroll_used = True
                    continue
                log(
                    f"pin_claim non trovato post-scroll (score={result.score:.3f}) "
                    f"— stop a {i}/{cfg.max_rivendica}"
                )
                break
            cx, cy = result.cx, result.cy
            log(f"Claim tap {i+1}/{cfg.max_rivendica} → ({cx},{cy}) score={result.score:.3f}")
            device.tap(cx, cy)
            time.sleep(cfg.wait_rivendica)
            n_rivendiche += 1
            scroll_used = False  # reset: lista aggiornata, riconsidera scroll
        else:
            log(f"Claim completato: raggiunto limite {cfg.max_rivendica}")

        log(f"Claim totale: {n_rivendiche} tap")
        if _dbg is not None:
            _dbg.snap("03_post_claim_loop", device.screenshot())

        log(f"Tab Attivita {cfg.coord_tab_attivita}")
        device.tap(*cfg.coord_tab_attivita)
        time.sleep(cfg.wait_tab)
        log(f"Raccogli tutto {cfg.coord_raccogli}")
        device.tap(*cfg.coord_raccogli)
        time.sleep(cfg.wait_raccogli)
        if _dbg is not None:
            _dbg.snap("04_post_raccogli", device.screenshot())

        for i in range(cfg.n_back_chiudi):
            device.back()
            time.sleep(cfg.wait_back_last if i == cfg.n_back_chiudi - 1 else cfg.wait_back)

        return _Esito.COMPLETATO, n_rivendiche, True

    @staticmethod
    def _mappa_esito(esito, rivendiche, raccolti, log) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(f"Alleanza completata — rivendiche: {rivendiche}",
                                 rivendiche=rivendiche, raccolti=raccolti)
        if esito == _Esito.NON_IN_HOME:
            return TaskResult.skip("Home non raggiungibile")
        return TaskResult.fail(f"Errore alleanza: {esito}")
