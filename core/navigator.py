# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/navigator.py
#
#  Navigazione delle schermate del gioco tramite template matching.
#
#  Classi:
#    Screen          — enum delle schermate riconoscibili
#    NavigatorConfig — parametri di navigazione (tentativi, attese)
#    GameNavigator   — rileva schermata corrente e naviga verso HOME o MAPPA
#
#  Design:
#    - Dipende da MuMuDevice (o FakeDevice) e TemplateMatcher
#    - Tutte le operazioni sono async
#    - Ogni azione (BACK, tap) è seguita da attesa e verifica
#    - Limite di tentativi per evitare loop infiniti
#    - La logica di escape da overlay è centralizzata qui (non nei task)
# ==============================================================================

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice, Screenshot
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# Screen — enum schermate riconoscibili
# ==============================================================================

class Screen(Enum):
    """Schermate principali del gioco."""
    HOME        = auto()   # schermata principale (rifugio)
    MAP         = auto()   # mappa mondo
    OVERLAY     = auto()   # overlay generico (popup, banner, conferma)
    LOADING     = auto()   # schermata di caricamento
    UNKNOWN     = auto()   # schermata non riconosciuta


# ==============================================================================
# NavigatorConfig
# ==============================================================================

@dataclass
class NavigatorConfig:
    """Parametri configurabili della navigazione."""

    # Attesa dopo ogni azione (BACK, tap) prima di riscattare screenshot
    wait_after_action: float = 1.5

    # Attesa aggiuntiva dopo tap su pulsante di chiusura overlay
    wait_after_overlay: float = 2.0

    # Numero massimo di tentativi per raggiungere HOME o MAP
    max_attempts: int = 8

    # Coordinate del tap "centrale" per chiudere overlay generici
    overlay_tap: tuple[int, int] = (480, 270)

    # Coordinate pulsante HOME (icona capanna) nella barra inferiore
    home_btn: tuple[int, int] = (142, 505)

    # Coordinate pulsante MAPPA (icona globo) nella barra inferiore
    map_btn: tuple[int, int] = (242, 505)

    # Soglia minima per il riconoscimento dei pin (pin_home, pin_map)
    pin_threshold: float = 0.80

    # Template names per il riconoscimento schermata
    pin_home_template: str = "pin/pin_home.png"
    pin_map_template:  str = "pin/pin_map.png"


# ==============================================================================
# GameNavigator
# ==============================================================================

class GameNavigator:
    """
    Naviga le schermate del gioco per conto di un task.

    Responsabilità:
      1. Rilevare la schermata corrente tramite template matching
      2. Portare il bot in HOME (vai_in_home) o MAPPA (vai_in_mappa)
      3. Gestire overlay e schermate sconosciute con BACK + tap di escape

    Non gestisce la logica di business dei task — si limita a garantire
    che il device sia nella schermata giusta prima che il task inizi.

    Esempio:
        nav = GameNavigator(device, matcher)
        screen = await nav.schermata_corrente()
        if screen != Screen.HOME:
            ok = await nav.vai_in_home()
    """

    def __init__(
        self,
        device: "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        config: NavigatorConfig | None = None,
    ):
        self.device  = device
        self.matcher = matcher
        self.config  = config or NavigatorConfig()

    # ── Riconoscimento schermata ──────────────────────────────────────────────

    async def schermata_corrente(self) -> Screen:
        """
        Acquisce uno screenshot e identifica la schermata corrente.

        Logica di riconoscimento (in ordine di priorità):
          1. pin_home   presente → HOME
          2. pin_map    presente → MAP
          3. nessuno dei due    → OVERLAY o UNKNOWN

        Returns:
            Screen enum
        """
        shot = await self.device.screenshot()
        return self._classifica(shot)

    def _classifica(self, shot: "Screenshot") -> Screen:
        """Classifica la schermata da uno Screenshot già acquisito."""
        cfg = self.config
        try:
            if self.matcher.exists(shot, cfg.pin_home_template,
                                   threshold=cfg.pin_threshold):
                return Screen.HOME
            if self.matcher.exists(shot, cfg.pin_map_template,
                                   threshold=cfg.pin_threshold):
                return Screen.MAP
        except FileNotFoundError:
            # Template non ancora presenti su disco → UNKNOWN
            pass
        return Screen.UNKNOWN

    # ── Navigazione verso HOME ────────────────────────────────────────────────

    async def vai_in_home(self) -> bool:
        """
        Porta il bot nella schermata HOME.

        Strategia per tentativo:
          1. Acquisisce screenshot e classifica
          2. Se HOME → ritorna True
          3. Se UNKNOWN/OVERLAY → prova tap overlay_tap poi BACK
          4. Se MAP → tap su home_btn
          5. Ripete fino a max_attempts

        Returns:
            True se HOME raggiunto, False se esauriti i tentativi.
        """
        cfg = self.config
        for attempt in range(cfg.max_attempts):
            shot  = await self.device.screenshot()
            screen = self._classifica(shot)

            if screen == Screen.HOME:
                return True

            if screen == Screen.MAP:
                # Tap sul pulsante HOME nella barra inferiore
                await self.device.tap(*cfg.home_btn)
                await asyncio.sleep(cfg.wait_after_action)
                continue

            # OVERLAY o UNKNOWN: prova tap centrale + BACK
            if attempt % 2 == 0:
                await self.device.tap(*cfg.overlay_tap)
                await asyncio.sleep(cfg.wait_after_overlay)
            else:
                await self.device.back()
                await asyncio.sleep(cfg.wait_after_action)

        return False

    # ── Navigazione verso MAPPA ───────────────────────────────────────────────

    async def vai_in_mappa(self) -> bool:
        """
        Porta il bot nella schermata MAPPA.

        Richiede di essere prima in HOME (chiama vai_in_home se necessario),
        poi tappa il pulsante MAPPA.

        Returns:
            True se MAPPA raggiunta, False se esauriti i tentativi.
        """
        cfg = self.config

        # Prima porta in HOME
        if not await self.vai_in_home():
            return False

        # Da HOME, tap sul pulsante mappa
        await self.device.tap(*cfg.map_btn)
        await asyncio.sleep(cfg.wait_after_action)

        # Verifica
        for _ in range(3):
            shot   = await self.device.screenshot()
            screen = self._classifica(shot)
            if screen == Screen.MAP:
                return True
            await asyncio.sleep(cfg.wait_after_action)

        return False

    # ── Escape da overlay ─────────────────────────────────────────────────────

    async def chiudi_overlay(self, max_tries: int = 3) -> bool:
        """
        Tenta di chiudere un overlay con tap centrale + BACK alternati.

        Ritorna True se dopo i tentativi la schermata non è più UNKNOWN,
        False se persiste.
        """
        cfg = self.config
        for i in range(max_tries):
            if i % 2 == 0:
                await self.device.tap(*cfg.overlay_tap)
            else:
                await self.device.back()
            await asyncio.sleep(cfg.wait_after_overlay)

            shot   = await self.device.screenshot()
            screen = self._classifica(shot)
            if screen != Screen.UNKNOWN:
                return True

        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    async def assicura_home(self) -> bool:
        """
        Alias di vai_in_home() — nome compatibile con V5.
        Verifica prima lo stato attuale, fa BACK solo se necessario.
        """
        return await self.vai_in_home()

    def __repr__(self) -> str:
        return (
            f"GameNavigator(device={self.device.name!r}, "
            f"max_attempts={self.config.max_attempts})"
        )
