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
    max_rivendica:      int   = 20
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

        try:
            esito, rivendiche, raccolti = self._esegui_alleanza(
                device, matcher, coord_alleanza, log, cfg
            )
        except Exception as exc:
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_alleanza")

        return self._mappa_esito(esito, rivendiche, raccolti, log)

    def _esegui_alleanza(self, device, matcher, coord_alleanza, log, cfg):
        log(f"Tap Alleanza {coord_alleanza}")
        device.tap(*coord_alleanza)
        time.sleep(0.3)  # minimo animazione tap

        log(f"Tap Dono {cfg.coord_dono}")
        device.tap(*cfg.coord_dono)
        time.sleep(0.3)  # minimo animazione tap

        log(f"Tab Negozio {cfg.coord_tab_negozio}")
        device.tap(*cfg.coord_tab_negozio)
        time.sleep(cfg.wait_tab)

        n_rivendiche = 0

        for i in range(cfg.max_rivendica):
            shot   = device.screenshot()
            result = matcher.find_one(shot, cfg.tmpl_claim)
            if not result.found or result.score < cfg.soglia_claim:
                log(f"pin_claim non trovato (score={result.score:.3f}) — stop a {i}/{cfg.max_rivendica}")
                break
            cx, cy = result.cx, result.cy
            log(f"Claim tap {i+1}/{cfg.max_rivendica} → ({cx},{cy}) score={result.score:.3f}")
            device.tap(cx, cy)
            time.sleep(cfg.wait_rivendica)
            n_rivendiche += 1
        else:
            log(f"Claim completato: raggiunto limite {cfg.max_rivendica}")

        log(f"Claim totale: {n_rivendiche} tap")

        log(f"Tab Attivita {cfg.coord_tab_attivita}")
        device.tap(*cfg.coord_tab_attivita)
        time.sleep(cfg.wait_tab)
        log(f"Raccogli tutto {cfg.coord_raccogli}")
        device.tap(*cfg.coord_raccogli)
        time.sleep(cfg.wait_raccogli)

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
