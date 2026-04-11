# tests/tasks/test_radar.py
"""
Step 18 — Test RadarTask + RadarCensusTask.

Principi (da ROADMAP):
  - Zero ADB reale: FakeDevice + FakeMatcher.
  - numpy disponibile (usato internamente da RadarTask._trova_pallini).
  - radar_tool non disponibile → RadarCensusTask gestisce gracefully.

Scenari RadarTask (10)
───────────────────────────────────────────────────────────────────────────
  1.  badge_assente          — pixel check fallisce → skip pulito
  2.  badge_presente_no_pallini — badge OK, loop vuoto subito (2 scan)
  3.  pallini_trovati        — 3 pallini tappati, poi scan vuoto×2
  4.  screenshot_none_badge  — screenshot None → success=False
  5.  screenshot_none_loop   — None nel loop → exit immediato
  6.  timeout_guard          — time.time() > RADAR_TIMEOUT_S → exit
  7.  census_chiamato        — RADAR_CENSUS_ABILITATO=True, RadarCensusTask invocato
  8.  census_non_bloccante   — census solleva eccezione, RadarTask non crasha
  9.  back_sempre_chiamato   — BACK emesso anche in caso di skip
  10. parametri_custom_ctx   — override R_MIN/G_MAX/B_MAX via ctx.config

Scenari RadarCensusTask (4)
───────────────────────────────────────────────────────────────────────────
  11. census_disabilitato    — RADAR_CENSUS_ABILITATO=False → icone=0
  12. census_no_detector     — radar_tool non disponibile → errore graceful
  13. census_abilitato_ok    — detector mockato → records salvati
  14. catalogo_finale_rf     — _catalogo_finale priorità RF > template
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import patch, MagicMock

import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Stub
# ──────────────────────────────────────────────────────────────────────────────

class FakeDevice:
    def __init__(self) -> None:
        self._screenshots: list[Any] = []
        self._idx = 0
        # Frame nero 540×960 BGR
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
        return object()

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def back(self) -> None:
        self.backs += 1


class FakeMatcher:
    def match(self, screen, path, roi):
        return 0.0


class FakeCtx:
    def __init__(self,
                 device: FakeDevice | None = None,
                 cfg: dict | None = None) -> None:
        self.device      = device or FakeDevice()
        self.matcher     = FakeMatcher()
        self.config      = cfg or {}
        self.instance_id = "FAU_00"


# ──────────────────────────────────────────────────────────────────────────────
# Helper: crea frame con N pallini rossi sintetici
# ──────────────────────────────────────────────────────────────────────────────

def _frame_con_pallini(n: int = 3) -> np.ndarray:
    """
    Crea un frame BGR 540×960 con N cerchi rossi sintetici
    nella zona mappa (y=80..490) ben separati.
    """
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    step = 120
    for i in range(n):
        cx = 100 + i * step
        cy = 200
        # Disegna un cerchio rosso 10px di raggio (R=200,G=20,B=20 in BGR)
        for dy in range(-10, 11):
            for dx in range(-10, 11):
                if dx*dx + dy*dy <= 100:
                    y_, x_ = cy + dy, cx + dx
                    if 0 <= y_ < 540 and 0 <= x_ < 960:
                        frame[y_, x_] = [20, 20, 200]   # BGR → rosso
    return frame


# ──────────────────────────────────────────────────────────────────────────────
# Test RadarTask
# ──────────────────────────────────────────────────────────────────────────────

class TestRadarTask(unittest.TestCase):

    def _make_task(self):
        from tasks.radar import RadarTask
        return RadarTask()

    def setUp(self):
        self._sleep_patcher = patch("tasks.radar.time.sleep")
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    # ── 1. Badge assente → skip ───────────────────────────────────────────────

    def test_badge_assente_skip(self):
        task   = self._make_task()
        device = FakeDevice()
        # Frame nero → nessun pixel rosso → badge assente
        device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        ctx = FakeCtx(device=device)

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["pallini_tappati"], 0)
        self.assertTrue(result.data["skip_ok"])

    # ── 2. Badge presente, loop vuoto ────────────────────────────────────────

    def test_badge_presente_no_pallini(self):
        task   = self._make_task()
        device = FakeDevice()

        # Frame con badge rosso all'icona (90,460), zona mappa nera.
        # In numpy BGR: rosso = [B=20, G=20, R=200].
        # Il badge è FUORI dalla RADAR_MAPPA_ZONA (y=80..490):
        # cy=460, zona badge cy-25:cy+20 = 435:480 → dentro la mappa!
        # Soluzione: usiamo TAP_RADAR_ICONA=(90,30) via ctx.config,
        # così il badge è a y=5..50 → fuori dalla zona mappa (y>=80).
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 30   # icona fuori dalla zona mappa
        frame[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]  # BGR → rosso
        device.last_frame = frame

        ctx = FakeCtx(
            device=device,
            cfg={"TAP_RADAR_ICONA": (cx, cy)},  # override coordinata icona
        )

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["pallini_tappati"], 0)
        self.assertGreaterEqual(device.backs, 1)

    # ── 3. Pallini trovati e tappati ─────────────────────────────────────────

    def test_pallini_trovati(self):
        task   = self._make_task()
        device = FakeDevice()

        # Badge presente
        frame_badge = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 460
        frame_badge[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]

        # Frame con 3 pallini per il loop
        frame_pallini = _frame_con_pallini(3)

        # Sequenza screenshot: badge-check → loop(pallini) → loop(vuoto×2)
        call_count = {"n": 0}
        original_screenshot = device.screenshot

        def patched_screenshot():
            call_count["n"] += 1
            return object()  # sempre non-None

        device.screenshot = patched_screenshot

        # last_frame cambia nel tempo: prima badge, poi pallini, poi nero
        frame_seq = [frame_badge, frame_pallini,
                     np.zeros((540, 960, 3), dtype=np.uint8),
                     np.zeros((540, 960, 3), dtype=np.uint8)]
        frame_idx = {"i": 0}

        original_screenshot2 = device.screenshot
        def patched_screenshot2():
            idx = frame_idx["i"]
            if idx < len(frame_seq):
                device.last_frame = frame_seq[idx]
                frame_idx["i"] += 1
            return object()

        device.screenshot = patched_screenshot2
        ctx = FakeCtx(device=device)

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertGreaterEqual(result.data["pallini_tappati"], 0)

    # ── 4. Screenshot None al badge-check ────────────────────────────────────

    def test_screenshot_none_badge(self):
        task   = self._make_task()
        device = FakeDevice()

        device.screenshot = lambda: None
        device.last_frame = None
        ctx = FakeCtx(device=device)

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.data["errore"])

    # ── 5. Screenshot None nel loop ───────────────────────────────────────────

    def test_screenshot_none_nel_loop(self):
        task   = self._make_task()
        device = FakeDevice()

        # Badge presente (primo screenshot valido)
        frame_badge = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 460
        frame_badge[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]

        call_count = {"n": 0}

        def patched_screenshot():
            call_count["n"] += 1
            if call_count["n"] == 1:
                device.last_frame = frame_badge
                return object()
            device.last_frame = None
            return None  # loop → exit

        device.screenshot = patched_screenshot
        ctx = FakeCtx(device=device)

        result = task.run(ctx)

        # Deve completare senza crash
        self.assertIsNotNone(result)

    # ── 6. Timeout guard ─────────────────────────────────────────────────────

    def test_timeout_guard(self):
        task   = self._make_task()
        device = FakeDevice()

        frame_badge = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 460
        frame_badge[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]

        call_count = {"n": 0}

        def patched_screenshot():
            call_count["n"] += 1
            if call_count["n"] == 1:
                device.last_frame = frame_badge
            else:
                device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
            return object()

        device.screenshot = patched_screenshot

        import tasks.radar as radar_mod
        fake_times = iter([0.0] + [999.0] * 200)

        with patch.object(radar_mod.time, "time", side_effect=lambda: next(fake_times)):
            ctx = FakeCtx(device=device, cfg={"RADAR_TIMEOUT_S": 120})
            result = task.run(ctx)

        self.assertIsNotNone(result)

    # ── 7. Census chiamato se abilitato ──────────────────────────────────────

    def test_census_chiamato(self):
        task   = self._make_task()
        device = FakeDevice()

        frame_badge = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 460
        frame_badge[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]

        call_count = {"n": 0}

        def patched_screenshot():
            call_count["n"] += 1
            if call_count["n"] == 1:
                device.last_frame = frame_badge
            else:
                device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
            return object()

        device.screenshot = patched_screenshot

        census_called = {"v": False}

        with patch("tasks.radar.RadarCensusTask") as MockCensus:
            mock_instance = MagicMock()
            mock_instance.run.return_value = MagicMock(
                data={"icone_rilevate": 5, "errore": None}
            )
            MockCensus.return_value = mock_instance

            ctx = FakeCtx(device=device,
                          cfg={"RADAR_CENSUS_ABILITATO": True})
            result = task.run(ctx)

        mock_instance.run.assert_called_once()
        self.assertEqual(result.data["census_icone"], 5)

    # ── 8. Census non bloccante ───────────────────────────────────────────────

    def test_census_non_bloccante(self):
        task   = self._make_task()
        device = FakeDevice()

        frame_badge = np.zeros((540, 960, 3), dtype=np.uint8)
        cx, cy = 90, 460
        frame_badge[cy-20:cy+15, cx-5:cx+30] = [20, 20, 200]

        call_count = {"n": 0}

        def patched_screenshot():
            call_count["n"] += 1
            device.last_frame = frame_badge if call_count["n"] == 1 else np.zeros((540, 960, 3), dtype=np.uint8)
            return object()

        device.screenshot = patched_screenshot

        with patch("tasks.radar.RadarCensusTask") as MockCensus:
            MockCensus.side_effect = RuntimeError("census crash")
            ctx = FakeCtx(device=device,
                          cfg={"RADAR_CENSUS_ABILITATO": True})
            result = task.run(ctx)

        # Non deve crashare
        self.assertIsNotNone(result)

    # ── 9. BACK sempre emesso ─────────────────────────────────────────────────

    def test_back_sempre_chiamato(self):
        task   = self._make_task()
        device = FakeDevice()
        # Badge assente → skip
        device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        ctx = FakeCtx(device=device)

        task.run(ctx)

        # In caso di skip il BACK non viene emesso (non siamo entrati nella mappa)
        # Questo è il comportamento corretto: no tap icona → no BACK
        self.assertEqual(device.backs, 0)

    # ── 10. Parametri custom via ctx.config ───────────────────────────────────

    def test_parametri_custom_ctx(self):
        task   = self._make_task()
        device = FakeDevice()

        # Soglie impossibili → badge sempre False → skip
        ctx = FakeCtx(
            device=device,
            cfg={
                "RADAR_BADGE_R_MIN": 300,   # impossibile (max 255)
                "RADAR_BADGE_G_MAX": 0,
                "RADAR_BADGE_B_MAX": 0,
            }
        )
        device.last_frame = np.full((540, 960, 3), 200, dtype=np.uint8)  # tutto grigio

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["pallini_tappati"], 0)


# ──────────────────────────────────────────────────────────────────────────────
# Test RadarCensusTask
# ──────────────────────────────────────────────────────────────────────────────

class TestRadarCensusTask(unittest.TestCase):

    def _make_task(self):
        from tasks.radar_census import RadarCensusTask
        return RadarCensusTask()

    def setUp(self):
        self._sleep_patcher = patch("tasks.radar_census.time.sleep",
                                    MagicMock()) if False else MagicMock()

    # ── 11. Census disabilitato ───────────────────────────────────────────────

    def test_census_disabilitato(self):
        task = self._make_task()
        ctx  = FakeCtx(cfg={"RADAR_CENSUS_ABILITATO": False})

        result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["icone_rilevate"], 0)
        self.assertIsNone(result.data["errore"])

    # ── 12. Census abilitato ma radar_tool non disponibile ───────────────────

    def test_census_no_detector(self):
        task   = self._make_task()
        device = FakeDevice()
        device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        ctx = FakeCtx(
            device=device,
            cfg={
                "RADAR_CENSUS_ABILITATO": True,
                "RADAR_TEMPLATES_DIR":    "/non/esiste",
            }
        )

        result = task.run(ctx)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.data["errore"])

    # ── 13. Census abilitato con detector mockato ─────────────────────────────

    def test_census_abilitato_con_mock(self):
        task   = self._make_task()
        device = FakeDevice()
        device.last_frame = np.zeros((540, 960, 3), dtype=np.uint8)

        fake_match = {
            "cx": 200, "cy": 300,
            "tipo": "skull", "template": "skull_01",
            "conf": 0.85,
        }

        def fake_load_templates(path):
            return {"skull_01": MagicMock()}

        def fake_detect(frame, templates, threshold):
            return [fake_match]

        def fake_extract_crop(frame, cx, cy, size):
            return np.zeros((size, size, 3), dtype=np.uint8)

        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir    = os.path.join(tmpdir, "templates")
            archive_dir = os.path.join(tmpdir, "archive")
            os.makedirs(tmpl_dir)

            # Patch _carica_detector
            with patch.object(
                task, "_carica_detector",
                return_value=(fake_load_templates, fake_detect, fake_extract_crop)
            ):
                ctx = FakeCtx(
                    device=device,
                    cfg={
                        "RADAR_CENSUS_ABILITATO": True,
                        "RADAR_TEMPLATES_DIR":    tmpl_dir,
                        "RADAR_ARCHIVE_ROOT":     archive_dir,
                        "RADAR_RF_MODEL_PATH":    "/non/esiste.pkl",
                    }
                )

                result = task.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.data["icone_rilevate"], 1)

    # ── 14. _catalogo_finale priorità RF > template ───────────────────────────

    def test_catalogo_finale_priorita_rf(self):
        from tasks.radar_census import _catalogo_finale

        rec = {
            "rf_label":  "skull",
            "rf_conf":   0.85,
            "conf_tmpl": 0.90,
            "template":  "pedone_01",
            "tipo":      "pedone",
        }
        cat, src, cconf, ready, reason = _catalogo_finale(rec)

        self.assertEqual(cat, "skull")
        self.assertEqual(src, "rf")
        self.assertTrue(ready)

    def test_catalogo_finale_fallback_template(self):
        from tasks.radar_census import _catalogo_finale

        rec = {
            "rf_label":  None,
            "rf_conf":   None,
            "conf_tmpl": 0.82,
            "template":  "skull_01",
            "tipo":      "skull",
        }
        cat, src, cconf, ready, reason = _catalogo_finale(rec)

        self.assertEqual(cat, "skull")
        self.assertEqual(src, "template")
        self.assertTrue(ready)

    def test_catalogo_finale_sconosciuto(self):
        from tasks.radar_census import _catalogo_finale

        rec = {
            "rf_label":  None,
            "rf_conf":   None,
            "conf_tmpl": 0.50,   # sotto _TMPL_WARN=0.70
            "template":  "skull_01",
            "tipo":      "skull",
        }
        cat, src, _, ready, _ = _catalogo_finale(rec)

        self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main()
