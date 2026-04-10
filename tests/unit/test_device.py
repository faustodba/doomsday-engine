# ==============================================================================
#  tests/unit/test_device.py
#
#  Unit test per core/device.py
#
#  Nota tecnica sui test di template matching:
#    TM_CCOEFF_NORMED su template UNIFORME (varianza=0) restituisce sempre 1.0
#    perché la formula degenera in 0/0. I test usano quindi template con
#    pattern interni (gradiente, scacchiera) che hanno varianza > 0.
# ==============================================================================

import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.device import (
    FakeDevice,
    KeyCall,
    MatchResult,
    MuMuDevice,
    Screenshot,
    SwipeCall,
    TapCall,
)


# ==============================================================================
# Helpers per costruire fixture immagini con pattern reali
# ==============================================================================

def make_screenshot(width: int = 960, height: int = 540,
                    color_bgr: tuple = (50, 50, 50)) -> Screenshot:
    """Screenshot di colore uniforme (usare solo per test NON di template matching)."""
    data = np.full((height, width, 3), color_bgr, dtype=np.uint8)
    return Screenshot(data)


def make_gradient_patch(height: int, width: int, seed: int = 0) -> np.ndarray:
    """
    Crea un patch con gradiente unico — varianza > 0, non può comparire
    casualmente in uno sfondo rumoroso con range diverso.
    """
    data = np.zeros((height, width, 3), dtype=np.uint8)
    for row in range(height):
        val = 200 + (row * 50 // height)
        data[row, :] = (val, 10 + seed, 10 + seed)
    return data


def make_checker_patch(height: int, width: int, size: int = 5,
                       inverted: bool = False) -> np.ndarray:
    """
    Crea un patch a scacchiera. Versione normale e invertita danno score ~0.58
    su TM_CCOEFF_NORMED — ben al di sotto di qualunque threshold pratica.
    """
    data = np.zeros((height, width, 3), dtype=np.uint8)
    val_a, val_b = (220, 50) if not inverted else (50, 220)
    for r in range(height):
        for c in range(width):
            if (r // size + c // size) % 2 == 0:
                data[r, c] = (val_a, val_a // 2, 10)
            else:
                data[r, c] = (val_b, 10, val_b // 2)
    return data


def make_base_with_patch(
    patch_data: np.ndarray,
    patch_x: int, patch_y: int,
    width: int = 960, height: int = 540,
) -> Screenshot:
    """Crea screenshot con sfondo grigio neutro e patch inserita in posizione nota."""
    bg = np.full((height, width, 3), 128, dtype=np.uint8)
    ph, pw = patch_data.shape[:2]
    bg[patch_y:patch_y+ph, patch_x:patch_x+pw] = patch_data
    return Screenshot(bg)


# ==============================================================================
# TestMatchResult
# ==============================================================================

class TestMatchResult:

    def test_found_true(self):
        r = MatchResult(True, 0.95, 120, 80)
        assert r.found is True
        assert r.score == 0.95
        assert r.cx == 120
        assert r.cy == 80

    def test_coords_property(self):
        r = MatchResult(True, 0.8, 300, 200)
        assert r.coords == (300, 200)

    def test_not_found(self):
        r = MatchResult(False, 0.3, 0, 0)
        assert r.found is False
        assert r.coords == (0, 0)

    def test_is_named_tuple(self):
        r = MatchResult(True, 0.9, 10, 20)
        assert r[0] is True
        assert r[1] == 0.9
        assert r[2] == 10
        assert r[3] == 20


# ==============================================================================
# TestScreenshot — costruzione
# ==============================================================================

class TestScreenshotConstruction:

    def test_from_valid_array(self):
        data = np.zeros((540, 960, 3), dtype=np.uint8)
        s = Screenshot(data)
        assert s.width == 960
        assert s.height == 540

    def test_from_none_raises(self):
        with pytest.raises(ValueError, match="vuoti"):
            Screenshot(None)

    def test_from_empty_array_raises(self):
        with pytest.raises(ValueError):
            Screenshot(np.array([]))

    def test_from_bytes_valid_png(self):
        data = np.zeros((100, 100, 3), dtype=np.uint8)
        data[20:40, 20:40] = (0, 255, 0)
        _, buf = cv2.imencode(".png", data)
        s = Screenshot.from_bytes(buf.tobytes())
        assert s.width == 100
        assert s.height == 100

    def test_from_bytes_invalid_raises(self):
        with pytest.raises(ValueError, match="decodificare"):
            Screenshot.from_bytes(b"not_an_image")

    def test_timestamp_set_on_construction(self):
        import time
        before = time.monotonic()
        s = make_screenshot()
        after = time.monotonic()
        assert before <= s.timestamp <= after

    def test_repr(self):
        s = make_screenshot(960, 540)
        assert "960x540" in repr(s)

    def test_array_is_not_none(self):
        data = np.zeros((100, 100, 3), dtype=np.uint8)
        s = Screenshot(data)
        assert s.array is not None


# ==============================================================================
# TestScreenshot — template matching (con pattern reali, non template uniformi)
# ==============================================================================

class TestScreenshotTemplateMatching:

    def test_match_found(self):
        """Template con gradiente inserito in posizione nota — deve trovarlo."""
        patch = make_gradient_patch(40, 50, seed=1)
        px, py = 200, 150
        base = make_base_with_patch(patch, px, py)
        template = Screenshot(patch.copy())

        result = base.match_template(template, threshold=0.95)
        assert result.found is True
        assert result.score >= 0.95
        assert abs(result.cx - (px + 50 // 2)) <= 3
        assert abs(result.cy - (py + 40 // 2)) <= 3

    def test_match_not_found_below_threshold(self):
        """
        Scacchiera normale nel base, scacchiera INVERTITA come template.
        TM_CCOEFF_NORMED ritorna ~0.58 — ampiamente sotto la soglia 0.95.
        """
        patch_in_base = make_checker_patch(40, 50, inverted=False)
        patch_template = make_checker_patch(40, 50, inverted=True)
        base = make_base_with_patch(patch_in_base, 200, 150)
        template = Screenshot(patch_template)

        result = base.match_template(template, threshold=0.95)
        assert result.found is False

    def test_match_with_zone_found_inside(self):
        """Template trovato quando la zona copre la patch."""
        patch = make_gradient_patch(40, 40, seed=5)
        px, py = 500, 300
        base = make_base_with_patch(patch, px, py)
        template = Screenshot(patch.copy())

        result = base.match_template(template, threshold=0.95, zone=(450, 250, 600, 380))
        assert result.found is True

    def test_match_with_zone_not_found_outside(self):
        """Template non trovato quando la zona NON copre la patch."""
        patch = make_gradient_patch(40, 40, seed=5)
        px, py = 500, 300
        base = make_base_with_patch(patch, px, py)
        template = Screenshot(patch.copy())

        result = base.match_template(template, threshold=0.95, zone=(0, 0, 200, 200))
        assert result.found is False

    def test_match_all_finds_multiple(self):
        """match_template_all trova esattamente 3 patch identiche ben distanziate."""
        patch = make_gradient_patch(30, 30, seed=7)
        bg = np.full((540, 960, 3), 128, dtype=np.uint8)
        positions = [(50, 50), (400, 200), (750, 400)]
        for px, py in positions:
            bg[py:py+30, px:px+30] = patch

        base = Screenshot(bg)
        template = Screenshot(patch.copy())

        results = base.match_template_all(template, threshold=0.95)
        assert len(results) == 3

    def test_match_all_deduplication(self):
        """Patch singola produce esattamente 1 match."""
        patch = make_gradient_patch(30, 40, seed=9)
        base = make_base_with_patch(patch, 300, 200)
        template = Screenshot(patch.copy())

        results = base.match_template_all(template, threshold=0.95)
        assert len(results) == 1

    def test_match_template_too_large(self):
        """Template più grande dell'immagine ritorna not found."""
        base = make_screenshot(width=100, height=100)
        template = make_screenshot(width=200, height=200)
        result = base.match_template(template)
        assert result.found is False


# ==============================================================================
# TestScreenshot — analisi pixel
# ==============================================================================

class TestScreenshotPixelAnalysis:

    def test_pixel_color_correct(self):
        data = np.zeros((100, 100, 3), dtype=np.uint8)
        data[50, 50] = (10, 20, 30)
        s = Screenshot(data)
        b, g, r = s.pixel_color(50, 50)
        assert b == 10
        assert g == 20
        assert r == 30

    def test_count_pixels_in_zone(self):
        data = np.zeros((100, 100, 3), dtype=np.uint8)
        data[20:60, 20:60] = (0, 255, 255)
        s = Screenshot(data)
        count = s.count_pixels(
            zone=(20, 20, 60, 60),
            lower_bgr=(0, 200, 200),
            upper_bgr=(10, 255, 255),
        )
        assert count == 1600

    def test_count_pixels_empty_zone(self):
        s = make_screenshot(color_bgr=(50, 50, 50))
        count = s.count_pixels(
            zone=(0, 0, 100, 100),
            lower_bgr=(200, 200, 200),
            upper_bgr=(255, 255, 255),
        )
        assert count == 0


# ==============================================================================
# TestScreenshot — crop e conversione
# ==============================================================================

class TestScreenshotCropConvert:

    def test_crop_dimensions(self):
        s = make_screenshot(960, 540)
        cropped = s.crop((100, 50, 300, 200))
        assert cropped.width == 200
        assert cropped.height == 150

    def test_crop_preserves_content(self):
        data = np.zeros((100, 100, 3), dtype=np.uint8)
        data[10:20, 10:20] = (255, 0, 0)
        s = Screenshot(data)
        cropped = s.crop((5, 5, 25, 25))
        b, g, r = cropped.pixel_color(5, 5)
        assert b == 255

    def test_to_pil_returns_rgb(self):
        data = np.zeros((50, 50, 3), dtype=np.uint8)
        data[0, 0] = (100, 150, 200)
        s = Screenshot(data)
        pil = s.to_pil()
        r, g, b = pil.getpixel((0, 0))
        assert r == 200
        assert g == 150
        assert b == 100


# ==============================================================================
# TestFakeDevice
# ==============================================================================

class TestFakeDevice:

    def test_init_defaults(self):
        device = FakeDevice(name="TEST_00", index=0)
        assert device.name == "TEST_00"
        assert device.port == 16384
        assert device.tap_calls == []
        assert device.key_calls == []

    def test_port_calculation(self):
        d3 = FakeDevice(index=3)
        assert d3.port == 16384 + 3 * 32

    @pytest.mark.asyncio
    async def test_launch_sets_launched(self):
        device = FakeDevice()
        result = await device.launch()
        assert result is True
        assert device.launched is True

    @pytest.mark.asyncio
    async def test_shutdown_clears_launched(self):
        device = FakeDevice()
        await device.launch()
        await device.shutdown()
        assert device.launched is False

    @pytest.mark.asyncio
    async def test_tap_recorded(self):
        device = FakeDevice()
        await device.tap(100, 200)
        await device.tap(300, 400)
        assert device.tap_calls == [TapCall(100, 200), TapCall(300, 400)]

    @pytest.mark.asyncio
    async def test_swipe_recorded(self):
        device = FakeDevice()
        await device.swipe(10, 20, 30, 40, duration_ms=500)
        assert device.swipe_calls == [SwipeCall(10, 20, 30, 40, 500)]

    @pytest.mark.asyncio
    async def test_keyevent_recorded(self):
        device = FakeDevice()
        await device.keyevent("KEYCODE_BACK")
        await device.keyevent("KEYCODE_HOME")
        assert device.all_keys == ["KEYCODE_BACK", "KEYCODE_HOME"]

    @pytest.mark.asyncio
    async def test_back_shortcut(self):
        device = FakeDevice()
        await device.back()
        await device.back()
        assert device.back_count == 2

    @pytest.mark.asyncio
    async def test_input_text_recorded(self):
        device = FakeDevice()
        await device.input_text("123456")
        assert device.text_inputs == ["123456"]

    @pytest.mark.asyncio
    async def test_screenshot_sequence(self):
        s1 = make_screenshot(color_bgr=(10, 20, 30))
        s2 = make_screenshot(color_bgr=(40, 50, 60))
        device = FakeDevice(screenshots=[s1, s2])
        got1 = await device.screenshot()
        got2 = await device.screenshot()
        assert got1 is s1
        assert got2 is s2
        assert len(device.screenshots_consumed) == 2

    @pytest.mark.asyncio
    async def test_screenshot_exhausted_raises(self):
        device = FakeDevice(screenshots=[make_screenshot()])
        await device.screenshot()
        with pytest.raises(IndexError, match="fixture"):
            await device.screenshot()

    @pytest.mark.asyncio
    async def test_add_screenshot_during_test(self):
        device = FakeDevice()
        s = make_screenshot()
        device.add_screenshot(s)
        got = await device.screenshot()
        assert got is s

    def test_reset_clears_all(self):
        device = FakeDevice(screenshots=[make_screenshot(), make_screenshot()])
        asyncio.run(device.tap(1, 2))
        asyncio.run(device.keyevent("KEYCODE_BACK"))
        asyncio.run(device.screenshot())
        device.reset()
        assert device.tap_calls == []
        assert device.key_calls == []
        assert device.screenshots_consumed == []
        assert device._screen_idx == 0

    @pytest.mark.asyncio
    async def test_is_running_default_true(self):
        device = FakeDevice()
        assert await device.is_running() is True

    @pytest.mark.asyncio
    async def test_stop_game_sets_not_running(self):
        device = FakeDevice()
        await device.stop_game()
        assert await device.is_running() is False

    def test_repr(self):
        device = FakeDevice(name="FAU_TEST", index=2, screenshots=[make_screenshot()])
        r = repr(device)
        assert "FAU_TEST" in r
        assert "screenshots=1" in r


# ==============================================================================
# TestMuMuDeviceInit
# ==============================================================================

class TestMuMuDeviceInit:

    def test_port_formula(self):
        assert MuMuDevice(0, "FAU_00").port == 16384
        assert MuMuDevice(1, "FAU_01").port == 16416
        assert MuMuDevice(5, "FAU_05").port == 16544
        assert MuMuDevice(10, "FauMorfeus").port == 16704

    def test_adb_serial_format(self):
        d = MuMuDevice(2, "FAU_02")
        assert d.adb_serial == "127.0.0.1:16448"

    def test_default_paths(self):
        d = MuMuDevice(0, "FAU_00")
        assert "adb.exe" in d._adb_exe
        assert "MuMuManager.exe" in d._mgr_exe

    def test_custom_paths(self):
        d = MuMuDevice(
            0, "FAU_00",
            adb_exe=r"C:\custom\adb.exe",
            manager_exe=r"C:\custom\MuMuManager.exe",
        )
        assert d._adb_exe == r"C:\custom\adb.exe"
        assert d._mgr_exe == r"C:\custom\MuMuManager.exe"

    def test_repr(self):
        d = MuMuDevice(3, "FAU_03")
        r = repr(d)
        assert "FAU_03" in r
        assert "16480" in r
