# ==============================================================================
#  tests/unit/test_template_matcher.py
#
#  Unit test per shared/template_matcher.py
# ==============================================================================

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from core.device import MatchResult, Screenshot
from shared.template_matcher import (
    DEFAULT_THRESHOLDS,
    TemplateCache,
    TemplateMatcher,
    clear_matchers,
    get_matcher,
)


# ==============================================================================
# Helpers
# ==============================================================================

def make_screenshot(width=960, height=540, color=(50, 50, 50)) -> Screenshot:
    data = np.full((height, width, 3), color, dtype=np.uint8)
    return Screenshot(data)


def make_gradient_patch(h: int, w: int, seed: int = 0) -> np.ndarray:
    data = np.zeros((h, w, 3), dtype=np.uint8)
    for row in range(h):
        val = 200 + (row * 40 // h)
        data[row, :] = (val, 10 + seed, 10 + seed)
    return data


def make_screenshot_with_patch(patch: np.ndarray, px: int, py: int,
                                width=960, height=540) -> Screenshot:
    bg = np.full((height, width, 3), 128, dtype=np.uint8)
    ph, pw = patch.shape[:2]
    bg[py:py+ph, px:px+pw] = patch
    return Screenshot(bg)


def make_checker_patch(h: int, w: int, inverted: bool = False) -> np.ndarray:
    data = np.zeros((h, w, 3), dtype=np.uint8)
    va, vb = (220, 50) if not inverted else (50, 220)
    for r in range(h):
        for c in range(w):
            data[r, c] = (va, va // 2, 10) if (r // 5 + c // 5) % 2 == 0 else (vb, 10, vb // 2)
    return data


def write_png(path: Path, data: np.ndarray) -> None:
    cv2.imwrite(str(path), data)


# ==============================================================================
# TestTemplateCache
# ==============================================================================

class TestTemplateCache:

    def test_carica_template_da_disco(self):
        patch_data = make_gradient_patch(30, 40, seed=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.png"
            write_png(path, patch_data)

            cache = TemplateCache(tmpdir)
            tmpl = cache.get("test.png")
            assert isinstance(tmpl, Screenshot)
            assert tmpl.width == 40
            assert tmpl.height == 30

    def test_file_non_trovato_solleva(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TemplateCache(tmpdir)
            with pytest.raises(FileNotFoundError):
                cache.get("inesistente.png")

    def test_cache_hit_stesso_oggetto(self):
        patch_data = make_gradient_patch(20, 30)
        with tempfile.TemporaryDirectory() as tmpdir:
            write_png(Path(tmpdir) / "a.png", patch_data)
            cache = TemplateCache(tmpdir)
            t1 = cache.get("a.png")
            t2 = cache.get("a.png")
            assert t1 is t2  # stesso oggetto in cache

    def test_invalidate_forza_rilettura(self):
        patch_data = make_gradient_patch(20, 30)
        with tempfile.TemporaryDirectory() as tmpdir:
            write_png(Path(tmpdir) / "a.png", patch_data)
            cache = TemplateCache(tmpdir)
            t1 = cache.get("a.png")
            cache.invalidate("a.png")
            t2 = cache.get("a.png")
            assert t1 is not t2  # oggetto diverso dopo invalidazione

    def test_clear_svuota_cache(self):
        patch_data = make_gradient_patch(20, 30)
        with tempfile.TemporaryDirectory() as tmpdir:
            write_png(Path(tmpdir) / "a.png", patch_data)
            cache = TemplateCache(tmpdir)
            cache.get("a.png")
            assert "a.png" in cache.cached_names()
            cache.clear()
            assert cache.cached_names() == []

    def test_preload_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["a.png", "b.png"]:
                write_png(Path(tmpdir) / name, make_gradient_patch(10, 10))
            cache = TemplateCache(tmpdir)
            results = cache.preload(["a.png", "b.png"])
            assert results["a.png"] is None
            assert results["b.png"] is None

    def test_preload_errore_parziale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            write_png(Path(tmpdir) / "esiste.png", make_gradient_patch(10, 10))
            cache = TemplateCache(tmpdir)
            results = cache.preload(["esiste.png", "non_esiste.png"])
            assert results["esiste.png"] is None
            assert isinstance(results["non_esiste.png"], FileNotFoundError)

    def test_sottocartella(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "pin"
            sub.mkdir()
            write_png(sub / "pin_home.png", make_gradient_patch(15, 15))
            cache = TemplateCache(tmpdir)
            tmpl = cache.get("pin/pin_home.png")
            assert tmpl.width == 15

    def test_repr(self):
        cache = TemplateCache("templates")
        assert "TemplateCache" in repr(cache)


# ==============================================================================
# TestTemplateMatcher — find_one
# ==============================================================================

class TestTemplateMatcherFindOne:

    def _make_matcher_with_mock_cache(self, mock_template: Screenshot) -> TemplateMatcher:
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = mock_template
        return TemplateMatcher(cache)

    def test_find_one_trovato(self):
        patch_data = make_gradient_patch(40, 50, seed=3)
        base = make_screenshot_with_patch(patch_data, px=200, py=150)
        tmpl = Screenshot(patch_data.copy())

        matcher = self._make_matcher_with_mock_cache(tmpl)
        result = matcher.find_one(base, "btn/btn_ok.png")
        assert result.found is True
        assert result.score >= 0.95

    def test_find_one_non_trovato(self):
        # Scacchiera normale nella base, invertita come template → score ~0.58
        patch_data = make_checker_patch(40, 50, inverted=False)
        other_patch = make_checker_patch(40, 50, inverted=True)
        base = make_screenshot_with_patch(patch_data, px=200, py=150)
        tmpl = Screenshot(other_patch)

        matcher = self._make_matcher_with_mock_cache(tmpl)
        result = matcher.find_one(base, "btn/btn_ok.png", threshold=0.95)
        assert result.found is False

    def test_find_one_con_zona(self):
        patch_data = make_gradient_patch(40, 50, seed=5)
        base = make_screenshot_with_patch(patch_data, px=700, py=400)
        tmpl = Screenshot(patch_data.copy())

        matcher = self._make_matcher_with_mock_cache(tmpl)
        # Zona che include la patch
        r_in = matcher.find_one(base, "t.png", zone=(650, 350, 800, 480))
        assert r_in.found is True
        # Zona che esclude la patch
        r_out = matcher.find_one(base, "t.png", zone=(0, 0, 300, 300))
        assert r_out.found is False

    def test_threshold_override(self):
        patch_data = make_gradient_patch(30, 30, seed=7)
        base = make_screenshot_with_patch(patch_data, px=100, py=100)
        tmpl = Screenshot(patch_data.copy())

        matcher = self._make_matcher_with_mock_cache(tmpl)
        # Con soglia molto alta potrebbe non trovarlo, ma con 0.0 sì
        result = matcher.find_one(base, "t.png", threshold=0.0)
        assert result.found is True


# ==============================================================================
# TestTemplateMatcher — find_all, exists, find_first_of
# ==============================================================================

class TestTemplateMatcherMulti:

    def _make_matcher(self, tmpl: Screenshot) -> TemplateMatcher:
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = tmpl
        return TemplateMatcher(cache)

    def test_find_all_tre_patch(self):
        patch_data = make_gradient_patch(25, 25, seed=9)
        bg = np.full((540, 960, 3), 128, dtype=np.uint8)
        for px, py in [(50, 50), (400, 200), (750, 400)]:
            bg[py:py+25, px:px+25] = patch_data
        base = Screenshot(bg)
        tmpl = Screenshot(patch_data.copy())

        matcher = self._make_matcher(tmpl)
        results = matcher.find_all(base, "t.png", threshold=0.95)
        assert len(results) == 3

    def test_exists_true(self):
        patch_data = make_gradient_patch(30, 30, seed=11)
        base = make_screenshot_with_patch(patch_data, px=100, py=100)
        tmpl = Screenshot(patch_data.copy())

        matcher = self._make_matcher(tmpl)
        assert matcher.exists(base, "t.png") is True

    def test_not_exists_true(self):
        # Scacchiera normale nella base, invertita come template → non trovata
        patch_data = make_checker_patch(30, 30, inverted=False)
        other = make_checker_patch(30, 30, inverted=True)
        base = make_screenshot_with_patch(patch_data, px=100, py=100)
        tmpl = Screenshot(other)

        matcher = self._make_matcher(tmpl)
        assert matcher.not_exists(base, "t.png", threshold=0.95) is True

    def test_find_first_of_primo_trovato(self):
        patch_a = make_gradient_patch(30, 30, seed=13)
        base = make_screenshot_with_patch(patch_a, px=200, py=200)

        cache = MagicMock(spec=TemplateCache)
        tmpl_a = Screenshot(patch_a.copy())
        tmpl_b = Screenshot(make_gradient_patch(30, 30, seed=200))
        cache.get.side_effect = lambda name: tmpl_a if "a" in name else tmpl_b

        matcher = TemplateMatcher(cache)
        name_found, result = matcher.find_first_of(
            base, ["btn_a.png", "btn_b.png"], threshold=0.95
        )
        assert name_found == "btn_a.png"
        assert result.found is True

    def test_find_first_of_nessuno(self):
        base = make_screenshot()
        cache = MagicMock(spec=TemplateCache)
        tmpl = Screenshot(make_gradient_patch(30, 30, seed=200))
        cache.get.return_value = tmpl

        matcher = TemplateMatcher(cache)
        name_found, result = matcher.find_first_of(
            base, ["a.png", "b.png"], threshold=0.99
        )
        assert name_found is None
        assert result.found is False

    def test_find_first_of_file_not_found_skippato(self):
        patch_data = make_gradient_patch(30, 30, seed=15)
        base = make_screenshot_with_patch(patch_data, 100, 100)

        cache = MagicMock(spec=TemplateCache)
        tmpl = Screenshot(patch_data.copy())
        def side(name):
            if "missing" in name:
                raise FileNotFoundError()
            return tmpl
        cache.get.side_effect = side

        matcher = TemplateMatcher(cache)
        name_found, result = matcher.find_first_of(
            base, ["missing.png", "good.png"], threshold=0.95
        )
        assert name_found == "good.png"
        assert result.found is True


# ==============================================================================
# TestTemplateMatcher — soglie per categoria
# ==============================================================================

class TestTemplateMatcherThresholds:

    def test_soglia_default_pin(self):
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = make_screenshot(10, 10)
        matcher = TemplateMatcher(cache)
        # "pin" nel nome → soglia 0.80
        thresh = matcher._threshold_for("pin/pin_home.png", None)
        assert thresh == DEFAULT_THRESHOLDS["pin"]

    def test_soglia_default_btn(self):
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = make_screenshot(10, 10)
        matcher = TemplateMatcher(cache)
        thresh = matcher._threshold_for("btn_ok.png", None)
        assert thresh == DEFAULT_THRESHOLDS["btn"]

    def test_soglia_override(self):
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = make_screenshot(10, 10)
        matcher = TemplateMatcher(cache)
        thresh = matcher._threshold_for("pin_home.png", 0.99)
        assert thresh == 0.99

    def test_soglia_custom_categoria(self):
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = make_screenshot(10, 10)
        matcher = TemplateMatcher(cache, thresholds={"mercante": 0.60})
        thresh = matcher._threshold_for("mercante_pack.png", None)
        assert thresh == 0.60

    def test_soglia_default_fallback(self):
        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = make_screenshot(10, 10)
        matcher = TemplateMatcher(cache)
        thresh = matcher._threshold_for("qualcosa_sconosciuto.png", None)
        assert thresh == DEFAULT_THRESHOLDS["default"]


# ==============================================================================
# TestTemplateMatcher — score e log callback
# ==============================================================================

class TestTemplateMatcherExtra:

    def test_score_ritorna_float(self):
        patch_data = make_gradient_patch(30, 30, seed=17)
        base = make_screenshot_with_patch(patch_data, 100, 100)
        tmpl = Screenshot(patch_data.copy())

        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = tmpl
        matcher = TemplateMatcher(cache)

        s = matcher.score(base, "t.png")
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0

    def test_log_callback_chiamato(self):
        patch_data = make_gradient_patch(30, 30, seed=19)
        base = make_screenshot_with_patch(patch_data, 100, 100)
        tmpl = Screenshot(patch_data.copy())

        log_calls = []
        def my_log(name, op, score, found):
            log_calls.append((name, op, found))

        cache = MagicMock(spec=TemplateCache)
        cache.get.return_value = tmpl
        matcher = TemplateMatcher(cache, log_callback=my_log)
        matcher.find_one(base, "btn.png")

        assert len(log_calls) == 1
        assert log_calls[0][0] == "btn.png"
        assert log_calls[0][1] == "find_one"

    def test_repr(self):
        cache = MagicMock(spec=TemplateCache)
        matcher = TemplateMatcher(cache)
        assert "TemplateMatcher" in repr(matcher)


# ==============================================================================
# TestGetMatcher — registry globale
# ==============================================================================

class TestGetMatcher:

    def setup_method(self):
        clear_matchers()

    def teardown_method(self):
        clear_matchers()

    def test_stessa_istanza_per_stessa_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = get_matcher(tmpdir)
            m2 = get_matcher(tmpdir)
            assert m1 is m2

    def test_istanze_diverse_per_dir_diverse(self):
        with tempfile.TemporaryDirectory() as d1, \
             tempfile.TemporaryDirectory() as d2:
            m1 = get_matcher(d1)
            m2 = get_matcher(d2)
            assert m1 is not m2

    def test_clear_matchers_resetta_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = get_matcher(tmpdir)
            clear_matchers()
            m2 = get_matcher(tmpdir)
            assert m1 is not m2
