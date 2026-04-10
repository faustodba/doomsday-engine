# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/alleanza.py             → C:\doomsday-engine\tasks\alleanza.py
#
#  Task: raccolta ricompense dalla sezione Alleanza → Dono.
#
#  Flusso (identico V5):
#    1. Assicura HOME via navigator
#    2. Tap pulsante Alleanza (menu in basso)
#    3. Tap icona Dono → apre su "Ricompense del negozio"
#    4. Tab Negozio → Tap Rivendica finché sparisce (max MAX_RIVENDICA)
#       Stop anticipato: pixel check ROI + hash no-change streak
#    5. Tab Attività → Tap Raccogli tutto
#    6. BACK×3 → torna in home
#
#  Nessun template richiesto — rilevamento Rivendica via pixel check (ROI).
#
#  Scheduling: periodic, interval_h=4, priority=40.
#  Outcome:
#    TaskResult.ok()   → completato
#    TaskResult.skip() → home non raggiungibile
#    TaskResult.fail() → errore strutturale
# ==============================================================================

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from core.task import Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice, Screenshot


# ==============================================================================
# AlleanzaConfig
# ==============================================================================

@dataclass
class AlleanzaConfig:
    """Parametri configurabili per AlleanzaTask."""

    # ── Coordinate fisse (960×540) ────────────────────────────────────────────
    coord_alleanza:    tuple[int, int] = (760, 505)
    coord_dono:        tuple[int, int] = (877, 458)
    coord_tab_negozio: tuple[int, int] = (810,  75)
    coord_tab_attivita:tuple[int, int] = (600,  75)
    coord_rivendica:   tuple[int, int] = (856, 240)
    coord_raccogli:    tuple[int, int] = (856, 505)

    # ── Rivendica — pixel check ROI ───────────────────────────────────────────
    riv_roi_half_w:    int   = 130    # semi-larghezza ROI attorno a coord_rivendica
    riv_roi_half_h:    int   = 28     # semi-altezza ROI
    riv_sat_min:       int   = 35     # saturazione minima pixel "pulsante"
    riv_bright_min:    int   = 120    # luminosità minima pixel "pulsante"
    riv_ratio_min:     float = 0.10   # frazione pixel attivi per considerare presente

    # ── Rivendica — loop ──────────────────────────────────────────────────────
    max_rivendica:     int = 20       # tap massimi su Rivendica
    no_change_limit:   int = 2        # streak no-change prima di stop

    # ── BACK chiusura ─────────────────────────────────────────────────────────
    n_back_chiudi:     int = 3

    # ── Attese ────────────────────────────────────────────────────────────────
    wait_open_alleanza: float = 2.0
    wait_open_dono:     float = 2.0
    wait_tab:           float = 0.8
    wait_rivendica:     float = 0.55
    wait_raccogli:      float = 1.0
    wait_back:          float = 0.8
    wait_back_last:     float = 1.0


# ==============================================================================
# Esiti interni
# ==============================================================================

class _Esito:
    COMPLETATO = "completato"
    NON_IN_HOME = "non_in_home"
    ERRORE      = "errore"


# ==============================================================================
# AlleanzaTask
# ==============================================================================

class AlleanzaTask(Task):
    """
    Raccoglie le ricompense dalla sezione Alleanza → Dono.

    Scheduling: periodic, interval_h=4, priority=40.
    Registrato in scheduler come:
        scheduler.register("alleanza", kind="periodic", interval_h=4, priority=40)

    Il rilevamento del pulsante Rivendica usa pixel check sulla ROI
    (stesso approccio di V5) — nessun template PNG richiesto.
    """

    def __init__(self, config: AlleanzaConfig | None = None) -> None:
        self._cfg = config or AlleanzaConfig()

    # ── ABC: name ─────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "alleanza"

    # ── ABC: should_run ───────────────────────────────────────────────────────

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("alleanza")
        return True

    # ── ABC: run ──────────────────────────────────────────────────────────────

    async def run(self, ctx: TaskContext) -> TaskResult:
        cfg    = self._cfg
        device = ctx.device

        def log(msg: str) -> None:
            if ctx.log:
                ctx.log.info(self.name(), f"[ALLEANZA] {msg}")

        # ── Step 0: assicura HOME ─────────────────────────────────────────────
        if ctx.navigator is not None:
            if not await ctx.navigator.vai_in_home():
                return TaskResult.skip("Navigator non ha raggiunto HOME")
        else:
            log("Navigator non disponibile — assumo HOME corrente")

        # ── Coordinata Alleanza: può variare per layout istanza ───────────────
        coord_alleanza = cfg.coord_alleanza
        if hasattr(ctx.config, "coord_alleanza"):
            coord_alleanza = ctx.config.coord_alleanza

        try:
            esito, rivendiche, raccolti = await self._esegui_alleanza(
                device, coord_alleanza, log, cfg
            )
        except Exception as exc:
            return TaskResult.fail(f"Eccezione non gestita: {exc}", step="esegui_alleanza")

        return self._mappa_esito(esito, rivendiche, raccolti, log)

    # ── Flusso principale ─────────────────────────────────────────────────────

    async def _esegui_alleanza(
        self,
        device:         "MuMuDevice | FakeDevice",
        coord_alleanza: tuple[int, int],
        log,
        cfg:            AlleanzaConfig,
    ) -> tuple[str, int, bool]:
        """
        Flusso completo alleanza.
        Ritorna (esito, n_rivendiche, raccolti).
        """

        # ── STEP 1: apri menu Alleanza ────────────────────────────────────────
        log(f"Tap Alleanza {coord_alleanza}")
        await device.tap(*coord_alleanza)
        await asyncio.sleep(cfg.wait_open_alleanza)

        # ── STEP 2: apri sezione Dono ─────────────────────────────────────────
        log(f"Tap Dono {cfg.coord_dono}")
        await device.tap(*cfg.coord_dono)
        await asyncio.sleep(cfg.wait_open_dono)

        # ── STEP 3: tab Negozio → Rivendica ──────────────────────────────────
        log(f"Tab Negozio {cfg.coord_tab_negozio}")
        await device.tap(*cfg.coord_tab_negozio)
        await asyncio.sleep(cfg.wait_tab)

        n_rivendiche   = 0
        no_change_streak = 0

        for i in range(cfg.max_rivendica):
            shot = await device.screenshot()

            if not self._rivendica_presente(shot, cfg):
                log(f"Rivendica non visibile — stop a {i}/{cfg.max_rivendica}")
                break

            h_before = self._roi_hash(shot, cfg)
            await device.tap(*cfg.coord_rivendica)
            await asyncio.sleep(cfg.wait_rivendica)
            n_rivendiche += 1

            shot2    = await device.screenshot()
            h_after  = self._roi_hash(shot2, cfg)

            if h_before and h_after and h_before == h_after:
                no_change_streak += 1
            else:
                no_change_streak = 0

            if not self._rivendica_presente(shot2, cfg):
                log(f"Rivendica sparito dopo tap — stop a {i + 1}/{cfg.max_rivendica}")
                break

            if no_change_streak >= cfg.no_change_limit:
                log(f"No-change streak={no_change_streak} — stop a {i + 1}/{cfg.max_rivendica}")
                break

        log(f"Rivendica completato: {n_rivendiche} tap")

        # ── STEP 4: tab Attività → Raccogli tutto ────────────────────────────
        log(f"Tab Attività {cfg.coord_tab_attivita}")
        await device.tap(*cfg.coord_tab_attivita)
        await asyncio.sleep(cfg.wait_tab)

        log(f"Raccogli tutto {cfg.coord_raccogli}")
        await device.tap(*cfg.coord_raccogli)
        await asyncio.sleep(cfg.wait_raccogli)
        raccolti = True

        # ── STEP 5: BACK×3 ───────────────────────────────────────────────────
        log(f"Chiusura → BACK×{cfg.n_back_chiudi}")
        for i in range(cfg.n_back_chiudi):
            await device.back()
            wait = cfg.wait_back_last if i == cfg.n_back_chiudi - 1 else cfg.wait_back
            await asyncio.sleep(wait)

        log("Raccolta Alleanza completata")
        return _Esito.COMPLETATO, n_rivendiche, raccolti

    # ── Pixel check Rivendica ─────────────────────────────────────────────────

    def _rivendica_presente(self, shot: "Screenshot", cfg: AlleanzaConfig) -> bool:
        """
        True se il pulsante Rivendica sembra presente.
        Analizza la saturazione/luminosità della ROI attorno a coord_rivendica.
        Fail-safe: ritorna True se non riesce a leggere l'immagine.
        """
        try:
            arr = self._crop_roi(shot, cfg.coord_rivendica,
                                 cfg.riv_roi_half_w, cfg.riv_roi_half_h)
            if arr is None:
                return True
            r = arr[:, :, 2].astype(int)   # BGR: indice 2 = R
            g = arr[:, :, 1].astype(int)
            b = arr[:, :, 0].astype(int)
            mx = np.maximum(np.maximum(r, g), b)
            mn = np.minimum(np.minimum(r, g), b)
            sat    = mx - mn
            bright = mx
            mask   = (sat > cfg.riv_sat_min) & (bright > cfg.riv_bright_min)
            ratio  = float(mask.sum()) / float(mask.size)
            return ratio > cfg.riv_ratio_min
        except Exception:
            return True

    def _roi_hash(self, shot: "Screenshot", cfg: AlleanzaConfig) -> str:
        """Hash MD5 della ROI del pulsante Rivendica (per no-change detection)."""
        try:
            arr = self._crop_roi(shot, cfg.coord_rivendica,
                                 cfg.riv_roi_half_w, cfg.riv_roi_half_h)
            if arr is None:
                return ""
            h = hashlib.md5()
            h.update(arr.tobytes())
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _crop_roi(
        shot:   "Screenshot",
        center: tuple[int, int],
        half_w: int,
        half_h: int,
    ):
        """
        Ritorna array BGR della ROI attorno al punto center.
        Usa shot.array (numpy BGR) disponibile su Screenshot V6.
        Ritorna None se fallisce.
        """
        try:
            arr = shot.array   # shape (H, W, 3) BGR
            h_img, w_img = arr.shape[:2]
            x, y = center
            x1 = max(0, x - half_w)
            y1 = max(0, y - half_h)
            x2 = min(w_img, x + half_w)
            y2 = min(h_img, y + half_h)
            roi = arr[y1:y2, x1:x2]
            if roi.size == 0:
                return None
            return roi
        except Exception:
            return None

    # ── Mapping esito → TaskResult ────────────────────────────────────────────

    @staticmethod
    def _mappa_esito(
        esito:      str,
        rivendiche: int,
        raccolti:   bool,
        log,
    ) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(
                f"Alleanza completata — rivendiche: {rivendiche}",
                rivendiche=rivendiche,
                raccolti=raccolti,
            )
        if esito == _Esito.NON_IN_HOME:
            return TaskResult.skip("Home non raggiungibile")
        log(f"Outcome={esito!r} → fail")
        return TaskResult.fail(f"Errore alleanza: {esito}")

    def __repr__(self) -> str:
        return f"AlleanzaTask(config={self._cfg})"
