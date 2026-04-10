# ==============================================================================
#  tests/unit/test_navigator.py
#
#  Unit test per core/navigator.py
#
#  Tutti i test usano FakeDevice + mock TemplateMatcher — nessun ADB reale.
#  La sequenza di screenshot restituiti da FakeDevice controlla il flusso
#  di navigazione e permette di testare ogni ramo della logica.
# ==============================================================================

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.device import FakeDevice, MatchResult, Screenshot
from core.navigator import (
    GameNavigator,
    NavigatorConfig,
    Screen,
)
from shared.template_matcher import TemplateMatcher


# ==============================================================================
# Helpers
# ==============================================================================

def make_screenshot(color=(50, 50, 50)) -> Screenshot:
    data = np.full((540, 960, 3), color, dtype=np.uint8)
    return Screenshot(data)


def make_matcher(
    home_found: bool = False,
    map_found: bool = False,
) -> TemplateMatcher:
    """
    Crea un TemplateMatcher mock che risponde in modo fisso.
    home_found / map_found controllano cosa restituisce exists().
    """
    matcher = MagicMock(spec=TemplateMatcher)

    def mock_exists(shot, name, threshold=None, zone=None):
        if "home" in name:
            return home_found
        if "map" in name:
            return map_found
        return False

    matcher.exists.side_effect = mock_exists
    return matcher


def make_seq_matcher(responses: list[dict]) -> TemplateMatcher:
    """
    Matcher che risponde in sequenza: ogni chiamata a exists() consuma
    un elemento della lista responses.
    responses: [{"home": bool, "map": bool}, ...]
    """
    matcher = MagicMock(spec=TemplateMatcher)
    call_count = [0]

    def mock_exists(shot, name, threshold=None, zone=None):
        idx = min(call_count[0] // 2, len(responses) - 1)
        call_count[0] += 1
        resp = responses[idx]
        if "home" in name:
            return resp.get("home", False)
        if "map" in name:
            return resp.get("map", False)
        return False

    matcher.exists.side_effect = mock_exists
    return matcher


def fast_config() -> NavigatorConfig:
    """Config con attese azzerate per velocizzare i test."""
    return NavigatorConfig(
        wait_after_action=0.0,
        wait_after_overlay=0.0,
        max_attempts=6,
    )


# ==============================================================================
# TestScreen
# ==============================================================================

class TestScreen:

    def test_valori_distinti(self):
        values = [s.value for s in Screen]
        assert len(values) == len(set(values))

    def test_nomi(self):
        assert Screen.HOME.name == "HOME"
        assert Screen.MAP.name == "MAP"
        assert Screen.UNKNOWN.name == "UNKNOWN"


# ==============================================================================
# TestNavigatorConfig
# ==============================================================================

class TestNavigatorConfig:

    def test_defaults(self):
        cfg = NavigatorConfig()
        assert cfg.max_attempts == 8
        assert cfg.wait_after_action == 1.5
        assert cfg.pin_threshold == 0.80

    def test_override(self):
        cfg = NavigatorConfig(max_attempts=3, wait_after_action=0.5)
        assert cfg.max_attempts == 3
        assert cfg.wait_after_action == 0.5


# ==============================================================================
# TestGameNavigatorSchermataCorrente
# ==============================================================================

class TestGameNavigatorSchermataCorrente:

    @pytest.mark.asyncio
    async def test_riconosce_home(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(home_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        screen = await nav.schermata_corrente()
        assert screen == Screen.HOME

    @pytest.mark.asyncio
    async def test_riconosce_map(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(map_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        screen = await nav.schermata_corrente()
        assert screen == Screen.MAP

    @pytest.mark.asyncio
    async def test_unknown_se_nessun_pin(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(home_found=False, map_found=False)
        nav     = GameNavigator(device, matcher, fast_config())

        screen = await nav.schermata_corrente()
        assert screen == Screen.UNKNOWN

    @pytest.mark.asyncio
    async def test_unknown_se_file_not_found(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = MagicMock(spec=TemplateMatcher)
        matcher.exists.side_effect = FileNotFoundError("template mancante")
        nav = GameNavigator(device, matcher, fast_config())

        screen = await nav.schermata_corrente()
        assert screen == Screen.UNKNOWN

    def test_classifica_usa_screenshot_fornito(self):
        device  = FakeDevice()
        matcher = make_matcher(home_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        shot    = make_screenshot()
        screen  = nav._classifica(shot)
        assert screen == Screen.HOME


# ==============================================================================
# TestVaiInHome
# ==============================================================================

class TestVaiInHome:

    @pytest.mark.asyncio
    async def test_gia_in_home_ritorna_true(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(home_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        result = await nav.vai_in_home()
        assert result is True
        # Nessun BACK o tap necessario
        assert device.back_count == 0
        assert len(device.tap_calls) == 0

    @pytest.mark.asyncio
    async def test_da_map_tap_home_btn(self):
        # Prima schermata: MAP; seconda: HOME
        shots = [make_screenshot(), make_screenshot()]
        device = FakeDevice(screenshots=shots)

        responses = [
            {"home": False, "map": True},   # prima iterazione: MAP
            {"home": True,  "map": False},  # seconda: HOME
        ]
        matcher = make_seq_matcher(responses)
        nav = GameNavigator(device, matcher, fast_config())

        result = await nav.vai_in_home()
        assert result is True
        # Deve aver tappato home_btn
        cfg = fast_config()
        assert any(
            t.x == cfg.home_btn[0] and t.y == cfg.home_btn[1]
            for t in device.tap_calls
        )

    @pytest.mark.asyncio
    async def test_overlay_usa_back_e_tap(self):
        # UNKNOWN per 3 tentativi, poi HOME
        shots = [make_screenshot()] * 5
        device = FakeDevice(screenshots=shots)

        call_n = [0]
        matcher = MagicMock(spec=TemplateMatcher)
        def mock_exists(shot, name, threshold=None, zone=None):
            # Dopo 3 coppie di chiamate restituisce HOME
            idx = call_n[0] // 2
            call_n[0] += 1
            if idx >= 3 and "home" in name:
                return True
            return False
        matcher.exists.side_effect = mock_exists

        nav = GameNavigator(device, matcher, fast_config())
        result = await nav.vai_in_home()
        assert result is True

    @pytest.mark.asyncio
    async def test_esaurisce_tentativi_ritorna_false(self):
        cfg = fast_config()
        cfg.max_attempts = 4
        shots = [make_screenshot()] * cfg.max_attempts
        device = FakeDevice(screenshots=shots)
        matcher = make_matcher(home_found=False, map_found=False)
        nav = GameNavigator(device, matcher, cfg)

        result = await nav.vai_in_home()
        assert result is False

    @pytest.mark.asyncio
    async def test_non_esegue_back_se_gia_in_home(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(home_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        await nav.vai_in_home()
        assert device.back_count == 0


# ==============================================================================
# TestVaiInMappa
# ==============================================================================

class TestVaiInMappa:

    @pytest.mark.asyncio
    async def test_da_home_va_in_mappa(self):
        # Screenshot 1: HOME (per vai_in_home)
        # Screenshot 2-4: verifica MAP (max 3 tentativi)
        shots = [make_screenshot()] * 4
        device = FakeDevice(screenshots=shots)

        responses = [
            {"home": True, "map": False},   # HOME
            {"home": False, "map": True},   # MAP al primo tentativo verifica
            {"home": False, "map": True},   # (extra, nel caso servisse)
        ]
        matcher = make_seq_matcher(responses)
        nav = GameNavigator(device, matcher, fast_config())

        result = await nav.vai_in_mappa()
        assert result is True

        # Deve aver tappato map_btn
        cfg = fast_config()
        assert any(
            t.x == cfg.map_btn[0] and t.y == cfg.map_btn[1]
            for t in device.tap_calls
        )

    @pytest.mark.asyncio
    async def test_fallisce_se_home_non_raggiungibile(self):
        cfg = fast_config()
        cfg.max_attempts = 2
        shots = [make_screenshot()] * 10
        device = FakeDevice(screenshots=shots)
        matcher = make_matcher(home_found=False, map_found=False)
        nav = GameNavigator(device, matcher, cfg)

        result = await nav.vai_in_mappa()
        assert result is False

    @pytest.mark.asyncio
    async def test_fallisce_se_mappa_non_raggiungibile(self):
        # HOME raggiunto, ma mappa non appare mai
        shots = [make_screenshot()] * 8
        device = FakeDevice(screenshots=shots)

        call_n = [0]
        matcher = MagicMock(spec=TemplateMatcher)
        def mock_exists(shot, name, threshold=None, zone=None):
            call_n[0] += 1
            # Sempre HOME, mai MAP
            return "home" in name
        matcher.exists.side_effect = mock_exists

        cfg = fast_config()
        nav = GameNavigator(device, matcher, cfg)
        result = await nav.vai_in_mappa()
        assert result is False


# ==============================================================================
# TestChiudiOverlay
# ==============================================================================

class TestChiudiOverlay:

    @pytest.mark.asyncio
    async def test_chiude_al_primo_tentativo(self):
        shots = [make_screenshot(), make_screenshot()]
        device = FakeDevice(screenshots=shots)

        responses = [
            {"home": False, "map": False},  # UNKNOWN prima
            {"home": True,  "map": False},  # HOME dopo tap
        ]
        matcher = make_seq_matcher(responses)
        nav = GameNavigator(device, matcher, fast_config())

        result = await nav.chiudi_overlay()
        assert result is True

    @pytest.mark.asyncio
    async def test_ritorna_false_se_overlay_persiste(self):
        shots = [make_screenshot()] * 5
        device = FakeDevice(screenshots=shots)
        matcher = make_matcher(home_found=False, map_found=False)
        nav = GameNavigator(device, matcher, fast_config())

        result = await nav.chiudi_overlay(max_tries=3)
        assert result is False


# ==============================================================================
# TestGameNavigatorMisc
# ==============================================================================

class TestGameNavigatorMisc:

    def test_repr(self):
        device  = FakeDevice(name="FAU_02", index=2)
        matcher = MagicMock(spec=TemplateMatcher)
        nav     = GameNavigator(device, matcher)
        r = repr(nav)
        assert "FAU_02" in r
        assert "GameNavigator" in r

    @pytest.mark.asyncio
    async def test_assicura_home_alias(self):
        device  = FakeDevice(screenshots=[make_screenshot()])
        matcher = make_matcher(home_found=True)
        nav     = GameNavigator(device, matcher, fast_config())

        result = await nav.assicura_home()
        assert result is True
