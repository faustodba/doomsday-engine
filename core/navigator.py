# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/navigator.py
#
#  Navigazione schermate del gioco — SINCRONO (Step 25).
#  Tutte le operazioni usano time.sleep() e metodi sync del device.
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice, Screenshot
    from shared.template_matcher import TemplateMatcher


class Screen(Enum):
    HOME    = auto()
    MAP     = auto()
    OVERLAY = auto()
    LOADING = auto()
    UNKNOWN = auto()


@dataclass
class NavigatorConfig:
    wait_after_action:  float = 1.5
    wait_after_overlay: float = 2.0
    max_attempts:       int   = 8
    overlay_tap:        tuple[int, int] = (480, 270)
    home_btn:           tuple[int, int] = (142, 505)
    map_btn:            tuple[int, int] = (242, 505)
    pin_threshold:      float = 0.80
    pin_home_template:  str   = "pin/pin_home.png"
    pin_map_template:   str   = "pin/pin_map.png"


class GameNavigator:
    """
    Naviga le schermate del gioco — SINCRONO.
    Usa device.screenshot_sync(), device.tap_sync(), device.back() sync.
    """

    def __init__(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        config:  NavigatorConfig | None = None,
    ):
        self.device  = device
        self.matcher = matcher
        self.config  = config or NavigatorConfig()

    # ── Riconoscimento schermata ──────────────────────────────────────────────

    def schermata_corrente(self) -> Screen:
        shot = self.device.screenshot_sync()
        return self._classifica(shot)

    def _classifica(self, shot: "Screenshot") -> Screen:
        cfg = self.config
        try:
            if self.matcher.exists(shot, cfg.pin_home_template,
                                   threshold=cfg.pin_threshold):
                return Screen.HOME
            if self.matcher.exists(shot, cfg.pin_map_template,
                                   threshold=cfg.pin_threshold):
                return Screen.MAP
        except FileNotFoundError:
            pass
        return Screen.UNKNOWN

    # ── Navigazione HOME ──────────────────────────────────────────────────────

    def vai_in_home(self) -> bool:
        """Porta il bot in HOME. Ritorna True se raggiunto."""
        cfg = self.config
        for attempt in range(cfg.max_attempts):
            shot   = self.device.screenshot_sync()
            screen = self._classifica(shot)

            if screen == Screen.HOME:
                return True

            if screen == Screen.MAP:
                self.device.tap_sync(cfg.home_btn)
                time.sleep(cfg.wait_after_action)
                continue

            if attempt % 2 == 0:
                self.device.tap_sync(cfg.overlay_tap)
                time.sleep(cfg.wait_after_overlay)
            else:
                self.device.back()
                time.sleep(cfg.wait_after_action)

        return False

    # ── Navigazione MAPPA ─────────────────────────────────────────────────────

    def vai_in_mappa(self) -> bool:
        """Porta il bot in MAPPA. Richiede di passare prima per HOME."""
        cfg = self.config
        if not self.vai_in_home():
            return False
        self.device.tap_sync(cfg.map_btn)
        time.sleep(cfg.wait_after_action)
        for _ in range(3):
            shot   = self.device.screenshot_sync()
            screen = self._classifica(shot)
            if screen == Screen.MAP:
                return True
            time.sleep(cfg.wait_after_action)
        return False

    # ── Escape overlay ────────────────────────────────────────────────────────

    def chiudi_overlay(self, max_tries: int = 3) -> bool:
        cfg = self.config
        for i in range(max_tries):
            if i % 2 == 0:
                self.device.tap_sync(cfg.overlay_tap)
            else:
                self.device.back()
            time.sleep(cfg.wait_after_overlay)
            shot   = self.device.screenshot_sync()
            screen = self._classifica(shot)
            if screen != Screen.UNKNOWN:
                return True
        return False

    def assicura_home(self) -> bool:
        """Alias di vai_in_home() — compatibile con V5."""
        return self.vai_in_home()

    def __repr__(self) -> str:
        return f"GameNavigator(max_attempts={self.config.max_attempts})"
