# tests/tasks/test_arena_mercato.py
"""
Step 17 — Test ArenaMercatoTask.

Principi (da ROADMAP):
  - Zero ADB reale: FakeDevice + FakeMatcher.
  - Ogni scenario copre un path di esecuzione distinto.

Scenari coperti
───────────────────────────────────────────────────────────────────────────
  1.  run_pack360_only           — 3 cicli pack 360, poi esaurito, pak 15 KO
  2.  run_pack15_only            — pack 360 subito esaurito, 2 cicli pack 15
  3.  run_pack360_then_pack15    — 2 cicli 360 + 2 cicli 15
  4.  run_home_fail              — HOME mai confermata
  5.  run_navigation_fail        — lista arena non rilevata
  6.  run_screenshot_fail_store  — screenshot None durante loop acquisti
  7.  run_glory_popup_dismissed  — popup Glory Silver gestito in navigazione
  8.  run_antiloop_guard         — MAX_ITER raggiunto senza stop naturale
  9.  run_360_no_clear_match     — nessun template 360 supera soglia (fallback)
  10. run_15_no_clear_match      — nessun template 15 supera soglia (fail-safe stop)
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import patch

import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Stub (identici a test_arena.py, ridefiniti per isolamento)
# ──────────────────────────────────────────────────────────────────────────────

class FakeDevice:
    def __init__(self) -> None:
        self._screenshots: list[Any] = []
        self._idx = 0
        self.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        self.taps:  list[tuple[int, int]] = []
        self.backs: int = 0

    def push(self, value: Any) -> None:
        self._screenshots.append(value)

    def screenshot(self) -> Any:
        if self._idx < len(self._screenshots):
            val = self._screenshots[self._idx]
            self._idx += 1
            return val
        return object()   # sentinel non-None

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def back(self) -> None:
        self.backs += 1


class _MatchResult:
    """Stub di shared.template_matcher.MatchResult."""
    def __init__(self, score: float, soglia: float) -> None:
        self.score = score
        self.found = score >= soglia
        self.cx    = 0
        self.cy    = 0


class FakeMatcher:
    def __init__(self) -> None:
        self._scores: dict[str, float] = {}

    def set(self, path: str, score: float) -> None:
        self._scores[path] = score

    def match(self, screen: Any, path: str, roi: tuple) -> float:
        return self._scores.get(path, 0.0)

    def find_one(self, screen: Any, path: str,
                 threshold: float = 0.0, zone: Any = None) -> _MatchResult:
        score = self.match(screen, path, ())
        return _MatchResult(score, threshold)

    def score(self, screen: Any, path: str) -> float:
        return self._scores.get(path, 0.0)


class FakeNavigator:
    def __init__(self, home: bool = True) -> None:
        self._home = home
        self.barra_taps: list[str] = []

    def current_screen(self, frame: Any):
        from enum import Enum
        class Screen(Enum):
            HOME  = "home"
            OTHER = "other"
        return Screen.HOME if self._home else Screen.OTHER

    def tap_barra(self, ctx: Any, voce: str, soglia: float = 0.80) -> bool:
        """Stub: registra la voce e tappa coordinate fittizie."""
        self.barra_taps.append(voce)
        ctx.device.tap(0, 0)
        return True


class FakeCtx:
    def __init__(self,
                 device:    FakeDevice    | None = None,
                 matcher:   FakeMatcher   | None = None,
                 navigator: FakeNavigator | None = None) -> None:
        self.device    = device    or FakeDevice()
        self.matcher   = matcher   or FakeMatcher()
        self.navigator = navigator or FakeNavigator(home=True)
        self.instance_id = "FAU_00"
        self.config      = type('Cfg', (), {'task_abilitato': lambda self, n: True})()
        self.log         = None

    def log_msg(self, *args, **kwargs) -> None:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────────────

_SENTINEL = object()   # screenshot valido non-None

def _setup_navigation_ok(matcher: FakeMatcher) -> None:
    """Configura pin minimi per navigazione riuscita verso lo store."""
    matcher.set("pin/pin_arena_01_lista.png",    0.90)  # lista visibile
    matcher.set("pin/pin_arena_07_glory.png",    0.00)  # nessun popup glory


# ──────────────────────────────────────────────────────────────────────────────
# Test suite
# ──────────────────────────────────────────────────────────────────────────────

class TestArenaMercatoTask(unittest.TestCase):

    def _make_task(self):
        from tasks.arena_mercato import ArenaMercatoTask
        return ArenaMercatoTask()

    def setUp(self):
        self._sleep_patcher = patch("tasks.arena_mercato.time.sleep")
        self._mock_sleep = self._sleep_patcher.start()
        # Fix Step 24: _assicura_home confronta Screen da core.navigator con
        # Screen inline del FakeNavigator → risultato sempre False.
        # Patch per delegare a navigator._home quando disponibile.
        def _fake_assicura_home(self_task, ctx):
            nav = ctx.navigator
            return getattr(nav, "_home", True)
        self._home_patcher = patch(
            "tasks.arena_mercato.ArenaMercatoTask._assicura_home",
            _fake_assicura_home,
        )
        self._home_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()
        self._home_patcher.stop()

    # ── Scenario 1: solo pack 360 (3 cicli, poi 15 KO) ───────────────────────

    def test_run_pack360_only(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)

        call_360 = {"n": 0}
        original = matcher.match

        def patched(screen, path, roi):
            if path == "pin/pin_360_open.png":
                call_360["n"] += 1
                return 0.80 if call_360["n"] <= 3 else 0.00
            if path == "pin/pin_360_close.png":
                return 0.80 if call_360["n"] > 3 else 0.00
            if path == "pin/pin_15_open.png":  return 0.00
            if path == "pin/pin_15_close.png": return 0.80  # esaurito subito
            return original(screen, path, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_360"], 3)
        self.assertEqual(result.data["acquisti_15"],  0)
        self.assertIsNone(result.data["errore"])

    # ── Scenario 2: solo pack 15 ──────────────────────────────────────────────

    def test_run_pack15_only(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)

        call_15 = {"n": 0}
        original = matcher.match

        def patched(screen, path, roi):
            if path == "pin/pin_360_open.png":  return 0.00
            if path == "pin/pin_360_close.png": return 0.80   # 360 subito esaurito
            if path == "pin/pin_15_open.png":
                call_15["n"] += 1
                return 0.80 if call_15["n"] <= 2 else 0.00
            if path == "pin/pin_15_close.png":
                return 0.80 if call_15["n"] > 2 else 0.00
            return original(screen, path, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_360"], 0)
        self.assertEqual(result.data["acquisti_15"],  2)

    # ── Scenario 3: 360 poi 15 ────────────────────────────────────────────────

    def test_run_pack360_then_pack15(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)

        call_360 = {"n": 0}
        call_15  = {"n": 0}
        original = matcher.match

        def patched(screen, path, roi):
            if path == "pin/pin_360_open.png":
                call_360["n"] += 1
                return 0.80 if call_360["n"] <= 2 else 0.00
            if path == "pin/pin_360_close.png":
                return 0.80 if call_360["n"] > 2 else 0.00
            if path == "pin/pin_15_open.png":
                call_15["n"] += 1
                return 0.80 if call_15["n"] <= 2 else 0.00
            if path == "pin/pin_15_close.png":
                return 0.80 if call_15["n"] > 2 else 0.00
            return original(screen, path, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_360"], 2)
        self.assertEqual(result.data["acquisti_15"],  2)

    # ── Scenario 4: HOME mai confermata ──────────────────────────────────────

    def test_run_home_fail(self):
        task = self._make_task()
        ctx  = FakeCtx(navigator=FakeNavigator(home=False))

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.data["errore"])
        self.assertIn("home", result.data["errore"])

    # ── Scenario 5: navigazione fallita ──────────────────────────────────────

    def test_run_navigation_fail(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        # lista mai visibile → _naviga_a_store → False
        matcher.set("pin/pin_arena_01_lista.png", 0.00)
        matcher.set("pin/pin_arena_07_glory.png", 0.00)

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertIn("arena", result.data["errore"])

    # ── Scenario 6: screenshot None durante acquisti ──────────────────────────

    def test_run_screenshot_fail_in_loop(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        device  = FakeDevice()
        ctx     = FakeCtx(device=device, matcher=matcher)

        _setup_navigation_ok(matcher)

        # Navigazione usa screenshot() dal device (sentinel non-None).
        # Forziamo None al primo screenshot del loop acquisti.
        # Navigazione: ~6 screenshot (home×3 + campagna + arena + lista×3)
        # Poi None al primo screenshot del loop.
        call_count = {"n": 0}
        original_screenshot = device.screenshot

        def patched_screenshot():
            call_count["n"] += 1
            # I primi 10 call sono per navigazione → sentinel
            if call_count["n"] <= 10:
                return object()
            return None   # loop acquisti → stop immediato

        device.screenshot = patched_screenshot

        result = task.run(ctx)

        # Task concludes (success=True): zero acquisti, nessun errore eccezione
        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_360"], 0)
        self.assertEqual(result.data["acquisti_15"],  0)

    # ── Scenario 7: popup Glory Silver in navigazione ─────────────────────────

    def test_run_glory_popup_dismissed(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        device  = FakeDevice()
        ctx     = FakeCtx(device=device, matcher=matcher)

        _setup_navigation_ok(matcher)

        glory_calls = {"n": 0}
        original = matcher.match

        def patched(screen, path, roi):
            if path == "pin/pin_arena_07_glory.png":
                glory_calls["n"] += 1
                # Prima comparsa: Glory visibile; poi scompare
                return 0.90 if glory_calls["n"] == 1 else 0.00
            # Pack 360 subito esaurito, pack 15 subito esaurito
            if path == "pin/pin_360_open.png":  return 0.00
            if path == "pin/pin_360_close.png": return 0.80
            if path == "pin/pin_15_open.png":   return 0.00
            if path == "pin/pin_15_close.png":  return 0.80
            return original(screen, path, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        from tasks.arena_mercato import _TAP_GLORY_CONTINUE
        self.assertIn(_TAP_GLORY_CONTINUE, device.taps)

    # ── Scenario 8: guard anti-loop MAX_ITER ─────────────────────────────────

    def test_run_antiloop_guard(self):
        """
        Pulsante 360 sempre attivo → il guard MAX_ITER (20) ferma il loop.
        Non deve andare in loop infinito.
        """
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)
        matcher.set("pin/pin_360_open.png",  0.90)  # sempre attivo
        matcher.set("pin/pin_360_close.png", 0.00)

        result = task.run(ctx)

        self.assertTrue(result.success)
        # Deve aver eseguito esattamente MAX_ITER acquisti 360
        from tasks.arena_mercato import _MERCATO_MAX_ITER
        self.assertEqual(result.data["acquisti_360"], _MERCATO_MAX_ITER)

    # ── Scenario 9: fallback pack 360 (nessun match chiaro) ──────────────────

    def test_run_360_no_clear_match_fallback(self):
        """
        Entrambi btn360_open e btn360_close sotto soglia.
        Fallback: open_score > close_score → True (acquista).
        Se open_score <= close_score → False (non acquista).
        """
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)

        # Nessuno supera soglia 0.75; open(0.50) > close(0.30) → True
        # Dopo 1 acquisto forziamo stop con pack 15 esaurito
        call_360 = {"n": 0}
        original = matcher.match

        def patched(screen, path, roi):
            if path == "pin/pin_360_open.png":
                call_360["n"] += 1
                return 0.50 if call_360["n"] == 1 else 0.00
            if path == "pin/pin_360_close.png":
                return 0.30 if call_360["n"] <= 1 else 0.80
            if path == "pin/pin_15_open.png":  return 0.00
            if path == "pin/pin_15_close.png": return 0.80
            return original(screen, path, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_360"], 1)

    # ── Scenario 10: fail-safe pack 15 (nessun match chiaro) ─────────────────

    def test_run_15_no_clear_match_failsafe(self):
        """
        btn15_open e btn15_close entrambi sotto soglia.
        Fail-safe: False → stop acquisti (non acquistare).
        """
        task    = self._make_task()
        matcher = FakeMatcher()
        ctx     = FakeCtx(matcher=matcher)

        _setup_navigation_ok(matcher)

        # 360 subito esaurito; 15: nessun match chiaro → fail-safe
        matcher.set("pin/pin_360_open.png",  0.00)
        matcher.set("pin/pin_360_close.png", 0.80)
        matcher.set("pin/pin_15_open.png",   0.40)  # sotto soglia 0.75
        matcher.set("pin/pin_15_close.png",  0.35)  # sotto soglia 0.75

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["acquisti_15"], 0)


if __name__ == "__main__":
    unittest.main()
