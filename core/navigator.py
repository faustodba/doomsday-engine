# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/navigator.py
#
#  Navigazione schermate del gioco — SINCRONO (Step 25).
#
#  FIX 12/04/2026 sessione 3 — da lettura config.py V5:
#    - HOME e MAPPA si alternano con UN SOLO bottone toggle (38, 505)
#      V5: TAP_TOGGLE_HOME_MAPPA = (38, 505)
#    - home_btn e map_btn eliminati — sostituiti da toggle_btn
#    - Template corretti da V5:
#        pin_region.png  → visibile in HOME  (bottone mostra "Region")
#        pin_shelter.png → visibile in MAPPA (bottone mostra "Shelter")
#    - Logica vai_in_home / vai_in_mappa aggiornata: tap toggle se schermata sbagliata
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

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
    # V5: TAP_TOGGLE_HOME_MAPPA = (38, 505) — unico bottone che alterna HOME/MAPPA
    toggle_btn:         tuple[int, int] = (38, 505)
    pin_threshold:      float = 0.70
    # V5: pin_region.png visibile in HOME, pin_shelter.png visibile in MAPPA
    pin_home_template:  str   = "pin/pin_region.png"
    pin_map_template:   str   = "pin/pin_shelter.png"
    log_scores:         bool  = True


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
        log_fn=None,
    ):
        self.device  = device
        self.matcher = matcher
        self.config  = config or NavigatorConfig()
        self._log    = log_fn or (lambda msg: None)

    # ── Riconoscimento schermata ──────────────────────────────────────────────

    def schermata_corrente(self) -> Screen:
        shot = self.device.screenshot_sync()
        return self._classifica(shot)

    def _classifica(self, shot: "Screenshot") -> Screen:
        cfg = self.config
        if shot is None:
            self._log("[NAV] screenshot None — UNKNOWN")
            return Screen.UNKNOWN

        try:
            score_home = self.matcher.score(shot, cfg.pin_home_template)
            score_map  = self.matcher.score(shot, cfg.pin_map_template)

            if cfg.log_scores:
                self._log(
                    f"[NAV] score home={score_home:.3f} map={score_map:.3f} "
                    f"(soglia={cfg.pin_threshold})"
                )

            if score_home >= cfg.pin_threshold:
                return Screen.HOME
            if score_map >= cfg.pin_threshold:
                return Screen.MAP

        except FileNotFoundError as e:
            self._log(f"[NAV] template non trovato: {e}")
        except Exception as e:
            self._log(f"[NAV] errore classificazione: {e}")

        return Screen.UNKNOWN

    # ── Navigazione HOME ──────────────────────────────────────────────────────

    def vai_in_home(self) -> bool:
        """Porta il bot in HOME. Ritorna True se raggiunto."""
        cfg = self.config
        for attempt in range(cfg.max_attempts):
            shot   = self.device.screenshot_sync()
            screen = self._classifica(shot)

            self._log(f"[NAV] vai_in_home tentativo {attempt+1}/{cfg.max_attempts} — screen={screen.name}")

            if screen == Screen.HOME:
                return True

            if screen == Screen.MAP:
                # Toggle unico HOME/MAPPA
                self.device.tap_sync(cfg.toggle_btn)
                time.sleep(cfg.wait_after_action)
                continue

            # UNKNOWN/OVERLAY: prova tap overlay poi BACK alternati
            if attempt % 2 == 0:
                self.device.tap_sync(cfg.overlay_tap)
                time.sleep(cfg.wait_after_overlay)
            else:
                self.device.back()
                time.sleep(cfg.wait_after_action)

        self._log(f"[NAV] vai_in_home FALLITO dopo {cfg.max_attempts} tentativi")
        return False

    # ── Navigazione MAPPA ─────────────────────────────────────────────────────

    def vai_in_mappa(self) -> bool:
        """Porta il bot in MAPPA. Passa prima per HOME poi tap toggle."""
        cfg = self.config
        if not self.vai_in_home():
            return False
        # Da HOME: tap toggle → MAPPA
        self.device.tap_sync(cfg.toggle_btn)
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
