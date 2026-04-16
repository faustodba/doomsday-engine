# tests/tasks/test_arena.py
"""
Step 16 — Test ArenaTask.

Principi (da ROADMAP):
  - Zero ADB reale: FakeDevice + FakeMatcher.
  - Ogni scenario copre un path di esecuzione distinto.
  - Nessun import da config.py o device reale.

Scenari coperti
───────────────────────────────────────────────────────────────────────────
  1. run_success_all_fights        — 5 sfide completate, tutte Victory
  2. run_success_esaurite          — popup "esaurite" al 3° tentativo sfida
  3. run_partial_then_esaurite     — 2 sfide OK, poi esaurite
  4. run_home_fail                 — navigator non trova HOME → 3 tentativi falliti
  5. run_navigation_fail           — lista arena non rilevata → 3 tentativi falliti
  6. run_too_many_consecutive_err  — 2 errori consecutivi → abort tentativo
  7. run_glory_popup_dismissed     — popup Glory Silver gestito prima della sfida
  8. run_failure_result            — sfida con esito Failure (cammino alternativo)
  9. run_battle_timeout            — timeout battaglia → fallback doppio tap centro
 10. run_recovery_second_attempt   — 1° tentativo fallisce (navigation), 2° riesce
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch, call

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# Stub minimi (FakeDevice, FakeMatcher, FakeNavigator, TaskContext)
# compatibili con l'interfaccia usata da ArenaTask senza import reali
# ──────────────────────────────────────────────────────────────────────────────

class FakeDevice:
    """
    Emula core.device.MuMuDevice senza ADB.

    screenshot() → ritorna None oppure un sentinel object non-None.
    last_frame   → numpy array BGR 540×960 (nero).
    back()       → registra la chiamata.
    tap(x, y)    → registra la chiamata.
    """

    def __init__(self) -> None:
        self._screenshot_results: list[Any] = []
        self._screenshot_idx = 0
        self.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        self.taps:  list[tuple[int, int]] = []
        self.backs: int = 0

    def push_screenshot(self, value: Any) -> None:
        """Accoda un valore che verrà restituito dalla prossima chiamata screenshot()."""
        self._screenshot_results.append(value)

    def screenshot(self) -> Any:
        if self._screenshot_idx < len(self._screenshot_results):
            val = self._screenshot_results[self._screenshot_idx]
            self._screenshot_idx += 1
            return val
        # Default: ritorna sempre un sentinel non-None
        return object()

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
    """
    Emula shared.template_matcher.TemplateMatcher.

    match(screen, template_path, roi) ritorna il valore configurato
    via set_score(template_path, score).
    find_one(screen, path, threshold, zone) ritorna _MatchResult.
    Default: 0.0 (nessun match).
    """

    def __init__(self) -> None:
        self._scores: dict[str, float] = {}

    def set_score(self, template_path: str, score: float) -> None:
        self._scores[template_path] = score

    def match(self, screen: Any, template_path: str, roi: tuple) -> float:
        return self._scores.get(template_path, 0.0)

    def find_one(self, screen: Any, template_path: str,
                 threshold: float = 0.0, zone: Any = None) -> _MatchResult:
        score = self.match(screen, template_path, ())
        return _MatchResult(score, threshold)

    def score(self, screen: Any, template_path: str) -> float:
        return self._scores.get(template_path, 0.0)


class FakeNavigator:
    """Emula core.navigator.GameNavigator."""

    def __init__(self, home: bool = True) -> None:
        self._home = home
        self._call_count = 0
        self.barra_taps: list[str] = []

    def current_screen(self, frame: Any):
        from enum import Enum

        class Screen(Enum):
            HOME = "home"
            OTHER = "other"

        self._call_count += 1
        return Screen.HOME if self._home else Screen.OTHER

    def tap_barra(self, ctx: Any, voce: str, soglia: float = 0.80) -> bool:
        """Stub: registra la voce e tappa coordinate fittizie."""
        self.barra_taps.append(voce)
        ctx.device.tap(0, 0)
        return True


class FakeTaskContext:
    """
    Costruisce un TaskContext minimale compatibile con ArenaTask.
    """

    def __init__(self,
                 device: FakeDevice | None = None,
                 matcher: FakeMatcher | None = None,
                 navigator: FakeNavigator | None = None) -> None:
        self.device    = device    or FakeDevice()
        self.matcher   = matcher   or FakeMatcher()
        self.navigator = navigator or FakeNavigator(home=True)
        self.instance_id = "FAU_00"
        self.config      = type('Cfg', (), {'task_abilitato': lambda self, n: True})()
        self.log         = None

    def log_msg(self, *args, **kwargs) -> None:
        pass  # silenzioso nei test


# ──────────────────────────────────────────────────────────────────────────────
# Helper: configura matcher per una singola sfida riuscita (Victory)
# ──────────────────────────────────────────────────────────────────────────────

def _setup_victory_fight(matcher: FakeMatcher) -> None:
    """Configura i pin per un ciclo sfida → Victory completo."""
    matcher.set_score("pin/pin_arena_01_lista.png",     0.90)  # lista visibile
    matcher.set_score("pin/pin_arena_06_purchase.png",  0.00)  # NON esaurite
    matcher.set_score("pin/pin_arena_02_challenge.png", 0.90)  # START CHALLENGE
    matcher.set_score("pin/pin_arena_03_victory.png",   0.90)  # Victory
    matcher.set_score("pin/pin_arena_04_failure.png",   0.00)
    matcher.set_score("pin/pin_arena_07_glory.png",     0.00)  # nessun popup glory


# ──────────────────────────────────────────────────────────────────────────────
# Test suite
# ──────────────────────────────────────────────────────────────────────────────

class TestArenaTask(unittest.TestCase):

    def _make_task(self):
        """Importa e istanzia ArenaTask (importazione lazy per isolamento)."""
        from tasks.arena import ArenaTask
        return ArenaTask()

    # ── patch time.sleep per velocizzare i test ────────────────────────────

    def setUp(self):
        self._sleep_patcher = patch("tasks.arena.time.sleep")
        self._mock_sleep = self._sleep_patcher.start()
        # Fix Step 24: _assicura_home confronta Screen da core.navigator con
        # Screen inline del FakeNavigator → risultato sempre False.
        def _fake_assicura_home(self_task, ctx):
            nav = ctx.navigator
            return getattr(nav, "_home", True)
        self._home_patcher = patch(
            "tasks.arena.ArenaTask._assicura_home",
            _fake_assicura_home,
        )
        self._home_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()
        self._home_patcher.stop()

    # ── Scenario 1: 5 sfide Victory ──────────────────────────────────────────

    def test_run_success_all_fights(self):
        task    = self._make_task()
        device  = FakeDevice()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(device, matcher, nav)

        _setup_victory_fight(matcher)

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["sfide_eseguite"], 5)
        self.assertFalse(result.data["esaurite"])
        self.assertIsNone(result.data["errore"])

    # ── Scenario 2: popup esaurite al 1° sfida ────────────────────────────────

    def test_run_success_esaurite(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(matcher=matcher, navigator=nav)

        matcher.set_score("pin/pin_arena_01_lista.png",    0.90)
        matcher.set_score("pin/pin_arena_06_purchase.png", 0.95)  # esaurite!
        matcher.set_score("pin/pin_arena_07_glory.png",    0.00)

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertTrue(result.data["esaurite"])
        self.assertEqual(result.data["sfide_eseguite"], 0)

    # ── Scenario 3: 2 sfide OK poi esaurite ──────────────────────────────────

    def test_run_partial_then_esaurite(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(matcher=matcher, navigator=nav)

        # Configurazione base Victory
        _setup_victory_fight(matcher)

        # Alla 3ª sfida simuliamo esaurite: usiamo side_effect su matcher.match
        call_count = {"lista_check": 0}
        original_match = matcher.match

        def patched_match(screen, tmpl, roi):
            if tmpl == "pin/pin_arena_06_purchase.png":
                call_count["lista_check"] += 1
                # _check_pin("purchase", retry=1) chiama match 2 volte per sfida.
                # Sfida 1: call 1-2 → not esaurite. Sfida 2: call 3-4 → not esaurite.
                # Sfida 3: call 5 → esaurite. Threshold = 5.
                return 0.95 if call_count["lista_check"] >= 5 else 0.00
            return original_match(screen, tmpl, roi)

        matcher.match = patched_match

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertTrue(result.data["esaurite"])
        self.assertEqual(result.data["sfide_eseguite"], 2)

    # ── Scenario 4: HOME mai confermata ──────────────────────────────────────

    def test_run_home_fail(self):
        task = self._make_task()
        nav  = FakeNavigator(home=False)  # navigator non conferma mai home
        ctx  = FakeTaskContext(navigator=nav)

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertEqual(result.data["sfide_eseguite"], 0)

    # ── Scenario 5: navigazione verso arena fallita ───────────────────────────

    def test_run_navigation_fail(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(matcher=matcher, navigator=nav)

        # Lista mai rilevata (score 0): _naviga_a_arena → False
        matcher.set_score("pin/pin_arena_01_lista.png", 0.00)

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertEqual(result.data["sfide_eseguite"], 0)
        self.assertIsNotNone(result.data["errore"])

    # ── Scenario 6: troppi errori consecutivi ────────────────────────────────

    def test_run_too_many_consecutive_errors(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(matcher=matcher, navigator=nav)

        # Lista navigazione: OK per _naviga_a_arena, ma NON visibile in _esegui_sfida
        call_count = {"n": 0}
        original_match = matcher.match

        def patched(screen, tmpl, roi):
            call_count["n"] += 1
            # Prima chiamata (navigazione): lista OK
            if tmpl == "pin/pin_arena_01_lista.png" and call_count["n"] <= 3:
                return 0.90
            # Poi sempre KO → errore consecutivo
            if tmpl == "pin/pin_arena_01_lista.png":
                return 0.00
            return 0.00

        matcher.match = patched

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.data["errore"])
        self.assertIn("consecutivi", result.data["errore"])

    # ── Scenario 7: popup Glory Silver all'ingresso ───────────────────────────

    def test_run_glory_popup_dismissed(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        device  = FakeDevice()
        ctx     = FakeTaskContext(device, matcher, nav)

        _setup_victory_fight(matcher)
        # Glory visibile UNA volta all'ingresso (primo check) poi scompare
        call_count = {"glory": 0}
        original_match = matcher.match

        def patched(screen, tmpl, roi):
            if tmpl == "pin/pin_arena_07_glory.png":
                call_count["glory"] += 1
                return 0.90 if call_count["glory"] == 1 else 0.00
            return original_match(screen, tmpl, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        # Verifica che il tap Glory Continue sia stato emesso
        from tasks.arena import _TAP_GLORY_CONTINUE
        self.assertIn(_TAP_GLORY_CONTINUE, device.taps)

    # ── Scenario 8: sfida con esito Failure ──────────────────────────────────

    def test_run_failure_result(self):
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        device  = FakeDevice()
        ctx     = FakeTaskContext(device, matcher, nav)

        matcher.set_score("pin/pin_arena_01_lista.png",     0.90)
        matcher.set_score("pin/pin_arena_06_purchase.png",  0.00)
        matcher.set_score("pin/pin_arena_02_challenge.png", 0.90)
        matcher.set_score("pin/pin_arena_03_victory.png",   0.00)  # nessuna Victory
        matcher.set_score("pin/pin_arena_04_failure.png",   0.90)  # Failure
        matcher.set_score("pin/pin_arena_07_glory.png",     0.00)

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["sfide_eseguite"], 5)  # 5 Failure = 5 "ok"

        from tasks.arena import _TAP_CONTINUE_FAILURE
        self.assertIn(_TAP_CONTINUE_FAILURE, device.taps)

    # ── Scenario 9: timeout battaglia → fallback doppio tap ──────────────────

    def test_run_battle_timeout(self):
        """
        Victory e Failure restituiscono score 0 → timeout → doppio tap centro.
        Il task deve comunque completare come "ok" (best-effort).

        Fix Step 24: patchiamo _assicura_home per evitare la dipendenza dal
        confronto Screen.HOME tra enum diversi (FakeNavigator locale vs
        core.navigator.Screen), e time.time per simulare il timeout rapido.
        """
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        device  = FakeDevice()
        ctx     = FakeTaskContext(device, matcher, nav)

        matcher.set_score("pin/pin_arena_01_lista.png",     0.90)
        matcher.set_score("pin/pin_arena_06_purchase.png",  0.00)
        matcher.set_score("pin/pin_arena_02_challenge.png", 0.90)
        matcher.set_score("pin/pin_arena_03_victory.png",   0.00)  # timeout
        matcher.set_score("pin/pin_arena_04_failure.png",   0.00)  # timeout
        matcher.set_score("pin/pin_arena_07_glory.png",     0.00)

        import tasks.arena as arena_mod
        # time.time() ritorna valori crescenti: ogni call aumenta di 40s
        # così t_start e il while check escono sempre al primo giro
        _t = [0.0]
        def fake_time():
            _t[0] += 40.0
            return _t[0]

        with patch.object(arena_mod.time, "time",  side_effect=fake_time), \
             patch.object(arena_mod.time, "sleep", return_value=None):
            result = task.run(ctx)

        self.assertTrue(result.success)
        # Doppio tap centro deve essere nelle taps (×5 sfide × 2 = 10 tap centro)
        from tasks.arena import _TAP_CENTRO
        centro_count = device.taps.count(_TAP_CENTRO)
        self.assertGreaterEqual(centro_count, 2)  # almeno un doppio tap

    # ── Scenario 10: recovery al 2° tentativo ────────────────────────────────

    def test_run_recovery_second_attempt(self):
        """
        1° tentativo: _naviga_a_arena fallisce (lista non visibile).
        2° tentativo: tutto OK → 5 sfide Victory.
        """
        task    = self._make_task()
        matcher = FakeMatcher()
        nav     = FakeNavigator(home=True)
        ctx     = FakeTaskContext(matcher=matcher, navigator=nav)

        attempt = {"n": 0}
        original_match = matcher.match
        _setup_victory_fight(matcher)

        def patched(screen, tmpl, roi):
            if tmpl == "pin/pin_arena_01_lista.png":
                attempt["n"] += 1
                # Primo gruppo di check (tentativo 1): fallisce
                return 0.00 if attempt["n"] <= 3 else 0.90
            return original_match(screen, tmpl, roi)

        matcher.match = patched

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["sfide_eseguite"], 5)


if __name__ == "__main__":
    unittest.main()


# ==============================================================================
# Test: ArenaState integration — guard sfide esaurite
# ==============================================================================

class TestArenaStateIntegration(unittest.TestCase):

    def _make_ctx_with_state(self, esaurite=False):
        """Costruisce ctx con InstanceState e ArenaState configurato."""
        from core.state import InstanceState
        ctx = _make_ctx()
        ctx.state = InstanceState("FAKE_00")
        if esaurite:
            ctx.state.arena.segna_esaurite()
        return ctx

    def test_should_run_false_se_esaurite(self):
        """ArenaTask.should_run() → False se sfide già esaurite."""
        from tasks.arena import ArenaTask
        ctx = self._make_ctx_with_state(esaurite=True)
        task = ArenaTask()
        self.assertFalse(task.should_run(ctx))

    def test_should_run_true_se_non_esaurite(self):
        """ArenaTask.should_run() → True se sfide non ancora esaurite."""
        from tasks.arena import ArenaTask
        ctx = self._make_ctx_with_state(esaurite=False)
        task = ArenaTask()
        self.assertTrue(task.should_run(ctx))

    def test_segna_esaurite_dopo_purchase_popup(self):
        """ArenaState.segna_esaurite() persiste correttamente."""
        from core.state import InstanceState
        state = InstanceState("FAKE_00")
        self.assertTrue(state.arena.should_run())
        state.arena.segna_esaurite()
        self.assertFalse(state.arena.should_run())

    def test_arena_state_reset_nuovo_giorno(self):
        """ArenaState si resetta automaticamente a mezzanotte UTC."""
        from core.state import ArenaState
        a = ArenaState(esaurite=True, data_riferimento="2020-01-01")
        self.assertTrue(a.should_run())  # nuovo giorno → reset
        self.assertFalse(a.esaurite)
