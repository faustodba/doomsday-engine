# tasks/radar.py
"""
Step 18 — Radar Station (periodic task).

Scheduling : periodic, intervallo=12h
Dipendenza : tasks/radar_census.py (opzionale, chiamato post-pallini)

Flusso
─────────────────────────────────────────────────────────────────────────────
  1. Verifica badge rosso sull'icona Radar Station (pixel check numpy)
     Se assente → skip pulito (success=True, pallini=0)
  2. tap icona → attendi apertura mappa (2.5s) + notifiche (10s)
  3. Loop raccolta pallini:
       a. screenshot
       b. trova pallini rossi (connected components BFS, numpy puro)
       c. tap su ognuno → loop
       d. 2 scan consecutivi vuoti → exit
       e. timeout RADAR_TIMEOUT_S → exit forzato
  4. Census icone (opzionale via RadarCensusTask, se RADAR_CENSUS_ABILITATO)
  5. BACK → home

Rilevamento badge
─────────────────────────────────────────────────────────────────────────────
  Pixel check in area 55×45 attorno a tap_icona (calibrata su 960×540).
  Fail-safe: True in caso di errore (meglio tentare che saltare).

Rilevamento pallini
─────────────────────────────────────────────────────────────────────────────
  Maschera pixel rossi nella RADAR_MAPPA_ZONA.
  BFS connected components → filtro compattezza + aspect ratio + dimensione.
  Parametri: RADAR_PX_MIN, RADAR_W/H_MIN/MAX, RADAR_COMP_MIN, RADAR_ASPECT_MIN.
  Tutti i parametri letti da ctx.config (dizionario) con fallback ai default.

Coordinate di default (960×540) — override via ctx.config
─────────────────────────────────────────────────────────────────────────────
  TAP_RADAR_ICONA   = (90, 460)
  RADAR_MAPPA_ZONA  = (0, 80, 960, 490)
  RADAR_BADGE_R_MIN = 160
  RADAR_BADGE_G_MAX = 80
  RADAR_BADGE_B_MAX = 80
  RADAR_PX_MIN      = 5
  RADAR_W_MIN / MAX = 6 / 40
  RADAR_H_MIN / MAX = 6 / 40
  RADAR_COMP_MIN    = 0.45
  RADAR_ASPECT_MIN  = 0.55
  RADAR_TIMEOUT_S   = 120
  RADAR_SCAN_DELAY_S= 2.0
  RADAR_TAP_DELAY_S = 0.4
  RADAR_CENSUS_ABILITATO = False
"""

from __future__ import annotations

import time
import logging
from typing import Literal

import numpy as np

from core.task import Task, TaskContext, TaskResult
# Import a livello modulo — necessario per patch nei test
from tasks.radar_census import RadarCensusTask

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Default parametri (override via ctx.config)
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "TAP_RADAR_ICONA":       (90, 460),
    "RADAR_MAPPA_ZONA":      (0, 80, 960, 490),
    "RADAR_BADGE_R_MIN":     160,
    "RADAR_BADGE_G_MAX":     80,
    "RADAR_BADGE_B_MAX":     80,
    "RADAR_PX_MIN":          5,
    "RADAR_W_MIN":           6,
    "RADAR_W_MAX":           40,
    "RADAR_H_MIN":           6,
    "RADAR_H_MAX":           40,
    "RADAR_COMP_MIN":        0.45,
    "RADAR_ASPECT_MIN":      0.55,
    "RADAR_TIMEOUT_S":       120,
    "RADAR_SCAN_DELAY_S":    2.0,
    "RADAR_TAP_DELAY_S":     0.4,
    "RADAR_CENSUS_ABILITATO": False,
}


def _cfg(ctx: TaskContext, key: str):
    """Legge un parametro da ctx.config (dict) con fallback ai default."""
    cfg = getattr(ctx, "config", {}) or {}
    return cfg.get(key, _DEFAULTS[key])


# ──────────────────────────────────────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────────────────────────────────────

class RadarTask(Task):
    """
    Radar Station — periodic, intervallo=12h.

    Raccoglie i pallini rossi dalla mappa Radar Station e,
    opzionalmente, esegue il censimento icone (RadarCensusTask).
    """

    # ── Task ABC ──────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "radar"

    def schedule_type(self) -> Literal["daily", "periodic"]:
        return "periodic"

    def interval_hours(self) -> float:
        return 12.0

    def priority(self) -> int:
        return 30

    def should_run(self, ctx) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("radar")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        pallini_tappati = 0
        census_icone    = 0
        errore: str | None = None

        tap_icona = _cfg(ctx, "TAP_RADAR_ICONA")

        # 1. Verifica badge
        screen = ctx.device.screenshot()
        if screen is None:
            errore = "screenshot fallito — skip"
            logger.warning("[RADAR] %s", errore)
            return TaskResult(success=False,
                              data=self._data(False, 0, 0, errore))

        frame = ctx.device.last_frame
        if not self._ha_badge(frame, tap_icona, ctx):
            logger.info("[RADAR] nessun badge — skip")
            return TaskResult(success=True,
                              data=self._data(True, 0, 0, None))

        # 2. Apri Radar Station
        logger.info("[RADAR] tap icona Radar Station")
        ctx.device.tap(*tap_icona)
        time.sleep(2.5)
        logger.info("[RADAR] attesa notifiche (10s)...")
        time.sleep(10.0)

        # 3. Loop pallini
        try:
            pallini_tappati = self._loop_pallini(ctx)
        except Exception as exc:
            errore = str(exc)
            logger.error("[RADAR] eccezione loop: %s", exc)

        # 4. Census opzionale
        if _cfg(ctx, "RADAR_CENSUS_ABILITATO"):
            try:
                census_task = RadarCensusTask()
                res = census_task.run(ctx)
                census_icone = res.data.get("icone_rilevate", 0)
            except Exception as exc:
                logger.warning("[RADAR] census non bloccante: %s", exc)

        # 5. Torna home
        ctx.device.back()
        time.sleep(1.0)

        logger.info("[RADAR] completato — pallini=%d census=%d",
                    pallini_tappati, census_icone)
        return TaskResult(
            success=errore is None,
            data=self._data(True, pallini_tappati, census_icone, errore),
        )

    # ── Badge detection ───────────────────────────────────────────────────────

    def _ha_badge(self,
                  frame: np.ndarray | None,
                  tap_icona: tuple[int, int],
                  ctx: TaskContext,
                  ) -> bool:
        """
        Pixel check badge rosso sull'icona Radar Station.
        Area 55×45 attorno a tap_icona (calibrata 960×540).
        Fail-safe: True in caso di errore.
        """
        if frame is None:
            return True  # fail-safe
        try:
            r_min = _cfg(ctx, "RADAR_BADGE_R_MIN")
            g_max = _cfg(ctx, "RADAR_BADGE_G_MAX")
            b_max = _cfg(ctx, "RADAR_BADGE_B_MAX")

            cx, cy = tap_icona
            # zona badge: destra e leggermente sotto il centro icona
            zona = frame[cy-25:cy+20, cx-10:cx+35, :3]   # BGR numpy
            b_ch = zona[:, :, 0].astype(int)
            g_ch = zona[:, :, 1].astype(int)
            r_ch = zona[:, :, 2].astype(int)

            rossi = (r_ch > r_min) & (g_ch < g_max) & (b_ch < b_max)
            trovati = int(rossi.sum()) >= 5
            logger.debug("[RADAR] badge pixel_rossi=%d trovato=%s",
                         int(rossi.sum()), trovati)
            return trovati
        except Exception as exc:
            logger.warning("[RADAR] _ha_badge errore (fail-safe True): %s", exc)
            return True

    # ── Loop pallini ──────────────────────────────────────────────────────────

    def _loop_pallini(self, ctx: TaskContext) -> int:
        """
        Ciclo: screenshot → trova pallini → tap → ripeti.
        Esce dopo 2 scan vuoti consecutivi o timeout.
        Ritorna il numero totale di pallini tappati.
        """
        timeout_s    = _cfg(ctx, "RADAR_TIMEOUT_S")
        scan_delay_s = _cfg(ctx, "RADAR_SCAN_DELAY_S")
        tap_delay_s  = _cfg(ctx, "RADAR_TAP_DELAY_S")

        tot_tappati = 0
        scan_vuoti  = 0
        t_inizio    = time.time()

        while True:
            if time.time() - t_inizio > timeout_s:
                logger.info("[RADAR] timeout %ds — esco", timeout_s)
                break

            screen = ctx.device.screenshot()
            if screen is None:
                logger.warning("[RADAR] screenshot fallito nel loop — esco")
                break

            frame = ctx.device.last_frame
            pallini = self._trova_pallini(frame, ctx)

            if not pallini:
                scan_vuoti += 1
                if scan_vuoti >= 2:
                    logger.info("[RADAR] %d scan vuoti consecutivi — completato",
                                scan_vuoti)
                    break
                logger.debug("[RADAR] scan vuoto %d/2 — attendo %.1fs",
                             scan_vuoti, scan_delay_s)
                time.sleep(scan_delay_s)
                continue

            scan_vuoti = 0
            logger.info("[RADAR] trovati %d pallini → tap", len(pallini))
            for cx, cy in pallini:
                ctx.device.tap(cx, cy)
                tot_tappati += 1
                time.sleep(tap_delay_s)

            time.sleep(scan_delay_s)

        logger.info("[RADAR] loop completato — tot_tappati=%d", tot_tappati)
        return tot_tappati

    # ── Pallini detection ─────────────────────────────────────────────────────

    def _trova_pallini(self,
                       frame: np.ndarray | None,
                       ctx: TaskContext,
                       ) -> list[tuple[int, int]]:
        """
        Trova pallini rossi nella zona mappa tramite connected components BFS.

        Parametri letti da ctx.config:
          RADAR_MAPPA_ZONA, RADAR_BADGE_R/G/B_*, RADAR_PX_MIN,
          RADAR_W/H_MIN/MAX, RADAR_COMP_MIN, RADAR_ASPECT_MIN.

        Ritorna lista di (cx, cy) assoluti (960×540).
        Lista vuota in caso di errore o nessun pallino.
        """
        if frame is None:
            return []
        try:
            x1, y1, x2, y2 = _cfg(ctx, "RADAR_MAPPA_ZONA")
            r_min = _cfg(ctx, "RADAR_BADGE_R_MIN")
            g_max = _cfg(ctx, "RADAR_BADGE_G_MAX")
            b_max = _cfg(ctx, "RADAR_BADGE_B_MAX")
            px_min    = _cfg(ctx, "RADAR_PX_MIN")
            w_min     = _cfg(ctx, "RADAR_W_MIN")
            w_max     = _cfg(ctx, "RADAR_W_MAX")
            h_min     = _cfg(ctx, "RADAR_H_MIN")
            h_max     = _cfg(ctx, "RADAR_H_MAX")
            comp_min  = _cfg(ctx, "RADAR_COMP_MIN")
            aspect_min= _cfg(ctx, "RADAR_ASPECT_MIN")

            # frame è BGR numpy — converti canali
            zona = frame[y1:y2, x1:x2]
            b_ch = zona[:, :, 0].astype(int)
            g_ch = zona[:, :, 1].astype(int)
            r_ch = zona[:, :, 2].astype(int)

            maschera = (r_ch > r_min) & (g_ch < g_max) & (b_ch < b_max)

            labeled, num = _label_bfs(maschera)
            pallini: list[tuple[int, int]] = []

            for i in range(1, num + 1):
                comp = np.where(labeled == i)
                ys_c, xs_c = comp
                npx = len(xs_c)
                if npx < px_min:
                    continue
                w = int(xs_c.max() - xs_c.min() + 1)
                h = int(ys_c.max() - ys_c.min() + 1)
                if not (w_min <= w <= w_max):
                    continue
                if not (h_min <= h <= h_max):
                    continue
                area       = w * h
                comp_ratio = npx / area if area > 0 else 0
                aspect     = min(w, h) / max(w, h) if max(w, h) > 0 else 0
                if comp_ratio < comp_min:
                    continue
                if aspect < aspect_min:
                    continue
                cx_abs = int(xs_c.mean()) + x1
                cy_abs = int(ys_c.mean()) + y1
                pallini.append((cx_abs, cy_abs))

            return pallini
        except Exception as exc:
            logger.warning("[RADAR] _trova_pallini errore: %s", exc)
            return []

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _data(skip_ok: bool,
              pallini: int,
              census: int,
              errore: str | None) -> dict:
        return {
            "skip_ok":        skip_ok,
            "pallini_tappati": pallini,
            "census_icone":   census,
            "errore":         errore,
        }


# ──────────────────────────────────────────────────────────────────────────────
# BFS connected components (numpy puro, no scipy)
# ──────────────────────────────────────────────────────────────────────────────

def _label_bfs(maschera: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Etichetta le componenti connesse di una maschera booleana 2D.
    Connettività 4 (su/giù/sx/dx).
    Ritorna (labeled: int32 array, n_componenti: int).
    """
    h, w = maschera.shape
    labeled = np.zeros((h, w), dtype=np.int32)
    current = 0
    for y in range(h):
        for x in range(w):
            if maschera[y, x] and labeled[y, x] == 0:
                current += 1
                queue = [(y, x)]
                labeled[y, x] = current
                while queue:
                    cy, cx = queue.pop()
                    for ny, nx in ((cy-1, cx), (cy+1, cx),
                                   (cy, cx-1), (cy, cx+1)):
                        if 0 <= ny < h and 0 <= nx < w:
                            if maschera[ny, nx] and labeled[ny, nx] == 0:
                                labeled[ny, nx] = current
                                queue.append((ny, nx))
    return labeled, current
