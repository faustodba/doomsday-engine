# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/alleanza.py
#
#  Task: raccolta ricompense Alleanza → Dono.
#  SINCRONO (Step 25) — time.sleep, ctx.log_msg, navigator sincrono.
# ==============================================================================

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import numpy as np

from core.task import Task, TaskContext, TaskResult


@dataclass
class AlleanzaConfig:
    coord_alleanza:     tuple[int, int] = (760, 505)
    coord_dono:         tuple[int, int] = (877, 458)
    coord_tab_negozio:  tuple[int, int] = (810,  75)
    coord_tab_attivita: tuple[int, int] = (600,  75)
    coord_rivendica:    tuple[int, int] = (856, 240)
    coord_raccogli:     tuple[int, int] = (856, 505)
    riv_roi_half_w:     int   = 130
    riv_roi_half_h:     int   = 28
    riv_sat_min:        int   = 35
    riv_bright_min:     int   = 120
    riv_ratio_min:      float = 0.10
    max_rivendica:      int   = 20
    no_change_limit:    int   = 2
    n_back_chiudi:      int   = 3
    wait_open_alleanza: float = 2.0
    wait_open_dono:     float = 2.0
    wait_tab:           float = 0.8
    wait_rivendica:     float = 0.55
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
        if ctx.device is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("alleanza")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg    = self._cfg
        device = ctx.device

        def log(msg: str) -> None:
            ctx.log_msg(f"[ALLEANZA] {msg}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.skip("Navigator non ha raggiunto HOME")

        coord_alleanza = cfg.coord_alleanza
        if hasattr(ctx.config, "coord_alleanza"):
            coord_alleanza = ctx.config.coord_alleanza

        try:
            esito, rivendiche, raccolti = self._esegui_alleanza(device, coord_alleanza, log, cfg)
        except Exception as exc:
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_alleanza")

        return self._mappa_esito(esito, rivendiche, raccolti, log)

    def _esegui_alleanza(self, device, coord_alleanza, log, cfg):
        log(f"Tap Alleanza {coord_alleanza}")
        device.tap(*coord_alleanza)
        time.sleep(cfg.wait_open_alleanza)

        log(f"Tap Dono {cfg.coord_dono}")
        device.tap(*cfg.coord_dono)
        time.sleep(cfg.wait_open_dono)

        log(f"Tab Negozio {cfg.coord_tab_negozio}")
        device.tap(*cfg.coord_tab_negozio)
        time.sleep(cfg.wait_tab)

        n_rivendiche     = 0
        no_change_streak = 0

        for i in range(cfg.max_rivendica):
            shot = device.screenshot()
            if not self._rivendica_presente(shot, cfg):
                log(f"Rivendica non visibile — stop a {i}")
                break
            h_before = self._roi_hash(shot, cfg)
            device.tap(*cfg.coord_rivendica)
            time.sleep(cfg.wait_rivendica)
            n_rivendiche += 1
            shot2   = device.screenshot()
            h_after = self._roi_hash(shot2, cfg)
            no_change_streak = (no_change_streak + 1) if (h_before and h_after and h_before == h_after) else 0
            if not self._rivendica_presente(shot2, cfg):
                log(f"Rivendica sparito — stop a {i+1}")
                break
            if no_change_streak >= cfg.no_change_limit:
                log(f"No-change streak={no_change_streak} — stop")
                break

        log(f"Rivendica completato: {n_rivendiche} tap")

        device.tap(*cfg.coord_tab_attivita)
        time.sleep(cfg.wait_tab)
        device.tap(*cfg.coord_raccogli)
        time.sleep(cfg.wait_raccogli)

        for i in range(cfg.n_back_chiudi):
            device.back()
            time.sleep(cfg.wait_back_last if i == cfg.n_back_chiudi - 1 else cfg.wait_back)

        return _Esito.COMPLETATO, n_rivendiche, True

    def _rivendica_presente(self, shot, cfg: AlleanzaConfig) -> bool:
        try:
            arr = self._crop_roi(shot, cfg.coord_rivendica, cfg.riv_roi_half_w, cfg.riv_roi_half_h)
            if arr is None:
                return True
            r, g, b = arr[:,:,2].astype(int), arr[:,:,1].astype(int), arr[:,:,0].astype(int)
            mx, mn  = np.maximum(np.maximum(r,g),b), np.minimum(np.minimum(r,g),b)
            mask    = ((mx - mn) > cfg.riv_sat_min) & (mx > cfg.riv_bright_min)
            return float(mask.sum()) / float(mask.size) > cfg.riv_ratio_min
        except Exception:
            return True

    def _roi_hash(self, shot, cfg: AlleanzaConfig) -> str:
        try:
            arr = self._crop_roi(shot, cfg.coord_rivendica, cfg.riv_roi_half_w, cfg.riv_roi_half_h)
            if arr is None:
                return ""
            h = hashlib.md5()
            h.update(arr.tobytes())
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _crop_roi(shot, center, half_w, half_h):
        try:
            arr = shot.array
            h_img, w_img = arr.shape[:2]
            x, y = center
            roi = arr[max(0,y-half_h):min(h_img,y+half_h), max(0,x-half_w):min(w_img,x+half_w)]
            return roi if roi.size > 0 else None
        except Exception:
            return None

    @staticmethod
    def _mappa_esito(esito, rivendiche, raccolti, log) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(f"Alleanza completata — rivendiche: {rivendiche}",
                                 rivendiche=rivendiche, raccolti=raccolti)
        if esito == _Esito.NON_IN_HOME:
            return TaskResult.skip("Home non raggiungibile")
        return TaskResult.fail(f"Errore alleanza: {esito}")
