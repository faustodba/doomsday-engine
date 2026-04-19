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
#
#  ADD 13/04/2026 — tap_barra():
#    - Barra inferiore: Campaign, Bag, Alliance, Beast, Hero
#    - Navigazione via template matching invece di coordinate fisse
#    - Necessario perché FAU_10 ha layout diverso (manca Beast → icone shiftate)
#    - ROI calibrata su screenshot reale 960×540: (546, 456, 910, 529)
#    - Score misurati: 0.993–0.995 su tutti e 5 i bottoni
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


# ──────────────────────────────────────────────────────────────────────────────
# Barra inferiore — template matching
# ──────────────────────────────────────────────────────────────────────────────
#
# ROI calibrata su screenshot reale 960×540 (home con tutti i bottoni visibili).
# Copre l'intera zona dei 5 bottoni escludendo la label "Region" a sinistra.
#
# Bottoni presenti (layout standard):  Campaign | Bag | Alliance | Beast | Hero
# Bottoni presenti (layout FAU_10):    Campaign | Bag | Alliance |        Hero
#                                      (Beast assente → Alliance e Hero shiftati)
#
# tap_barra() trova il centro del bottone richiesto via TM e lo tappa.
# Se il bottone non esiste nel layout corrente (score < soglia) → ritorna False.

_BARRA_ROI = (546, 456, 910, 529)   # (x1, y1, x2, y2) — zona 5 bottoni

_BARRA_PIN: dict[str, str] = {
    "campaign": "pin/pin_campaign.png",
    "bag":      "pin/pin_bag.png",
    "alliance": "pin/pin_alliance.png",
    "beast":    "pin/pin_beast.png",
    "hero":     "pin/pin_hero.png",
}

_BARRA_SOGLIA = 0.80   # soglia conservativa — score reali 0.993-0.995


class GameNavigator:
    """
    Naviga le schermate del gioco — SINCRONO.
    Usa device.screenshot(), device.tap(), device.back() — API AdbDevice reale.
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
        shot = self.device.screenshot()
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
        none_streak = 0
        for attempt in range(cfg.max_attempts):
            shot = self.device.screenshot()
            if shot is None:
                none_streak += 1
                if none_streak >= 3:
                    self._log(
                        f"[NAV] vai_in_home ABORT — screenshot None {none_streak}x "
                        f"consecutive (ADB unhealthy)"
                    )
                    return False
            else:
                none_streak = 0

            screen = self._classifica(shot)

            self._log(f"[NAV] vai_in_home tentativo {attempt+1}/{cfg.max_attempts} — screen={screen.name}")

            if screen == Screen.HOME:
                return True

            if screen == Screen.MAP:
                # Toggle unico HOME/MAPPA
                self.device.tap(*cfg.toggle_btn)
                time.sleep(cfg.wait_after_action)
                continue

            # UNKNOWN/OVERLAY: prova tap overlay poi BACK alternati
            if attempt % 2 == 0:
                self.device.tap(*cfg.overlay_tap)
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
        self.device.tap(*cfg.toggle_btn)
        time.sleep(cfg.wait_after_action)
        for _ in range(3):
            shot   = self.device.screenshot()
            screen = self._classifica(shot)
            if screen == Screen.MAP:
                return True
            time.sleep(cfg.wait_after_action)
        return False

    # ── Barra inferiore — template matching ───────────────────────────────────

    def tap_barra(self, ctx, voce: str, soglia: float = _BARRA_SOGLIA) -> bool:
        """
        Trova e tappa un bottone della barra inferiore via template matching.

        Parametri:
            ctx   : TaskContext — usato per device e matcher
            voce  : chiave in _BARRA_PIN ("campaign", "bag", "alliance", "beast", "hero")
            soglia: soglia minima di confidenza (default 0.80)

        Ritorna True se il bottone è stato trovato e tappato, False altrimenti.
        False indica che il bottone non esiste nel layout corrente (es. Beast su FAU_10)
        o che lo screenshot è fallito.

        Nota: usa ctx.device e ctx.matcher (non self.device/self.matcher) perché
        il TaskContext porta il dispositivo e il matcher dell'istanza corrente.
        """
        if voce not in _BARRA_PIN:
            self._log(f"[NAV-BARRA] voce sconosciuta: '{voce}'")
            return False

        pin_path = _BARRA_PIN[voce]
        screen = ctx.device.screenshot()
        if screen is None:
            self._log(f"[NAV-BARRA] screenshot fallito per '{voce}'")
            return False

        result = ctx.matcher.find_one(screen, pin_path, threshold=soglia, zone=_BARRA_ROI)
        if result.found:
            self._log(f"[NAV-BARRA] '{voce}' trovato score={result.score:.3f} → tap ({result.cx},{result.cy})")
            ctx.device.tap(result.cx, result.cy)
            return True

        self._log(f"[NAV-BARRA] '{voce}' non trovato (score={result.score:.3f} < {soglia})")
        return False

    # ── Escape overlay ────────────────────────────────────────────────────────

    def chiudi_overlay(self, max_tries: int = 3) -> bool:
        cfg = self.config
        for i in range(max_tries):
            if i % 2 == 0:
                self.device.tap(*cfg.overlay_tap)
            else:
                self.device.back()
            time.sleep(cfg.wait_after_overlay)
            shot   = self.device.screenshot()
            screen = self._classifica(shot)
            if screen != Screen.UNKNOWN:
                return True
        return False

    def assicura_home(self) -> bool:
        """Alias di vai_in_home() — compatibile con V5."""
        return self.vai_in_home()

    def __repr__(self) -> str:
        return f"GameNavigator(max_attempts={self.config.max_attempts})"
