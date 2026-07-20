"""
tests/tasks/test_radar_master.py — RadarMasterTask (20/07/2026)

FakeDevice/FakeMatcher minimali, nessuna dipendenza ADB/emulatore.
La saturazione stamina usa un pixel-check reale (_stamina_fill_ratio) su
frame numpy costruiti ad-hoc (non un template) — vedi _make_frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tasks.radar_master import RadarMasterTask, RadarMasterConfig, _Esito


# ── Fake infra ─────────────────────────────────────────────────────────────

def _make_frame(fill_ratio: float = 0.0, roi=(273, 147, 722, 157)) -> np.ndarray:
    """Frame numpy con la ROI barra stamina riempita di verde per la frazione
    `fill_ratio` (da sinistra), resto nero. Compatibile con _stamina_fill_ratio."""
    frame = np.zeros((300, 900, 3), dtype=np.uint8)
    x1, y1, x2, y2 = roi
    width = x2 - x1
    filled_w = int(width * fill_ratio)
    if filled_w > 0:
        frame[y1:y2, x1:x1 + filled_w] = (38, 163, 70)  # BGR verde (da screenshot reali)
    return frame


class FakeScreenshot:
    def __init__(self, frame: np.ndarray | None = None):
        self.frame = frame if frame is not None else _make_frame(0.0)


class FakeDevice:
    def __init__(self, frames=None):
        self.calls: list[tuple] = []
        self._frames = list(frames) if frames else [FakeScreenshot()]
        self._idx = 0

    def screenshot(self):
        self.calls.append(("screenshot",))
        shot = self._frames[min(self._idx, len(self._frames) - 1)]
        self._idx += 1
        return shot

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def taps(self):
        return [c for c in self.calls if c[0] == "tap"]


@dataclass
class _Match:
    found: bool
    score: float = 0.9


class FakeMatcher:
    """scores_by_tmpl_per_call: dict {tmpl: list[bool]} — sequenza di esiti
    find_one per quel template (uno per chiamata, l'ultimo si ripete)."""
    def __init__(self, sequences: dict[str, list[bool]] | None = None):
        self._seq = sequences or {}
        self._pos = {}

    def find_one(self, shot, tmpl, threshold=0.8, zone=None):
        seq = self._seq.get(tmpl)
        if not seq:
            return _Match(found=False, score=0.0)
        i = self._pos.get(tmpl, 0)
        val = seq[min(i, len(seq) - 1)]
        self._pos[tmpl] = i + 1
        return _Match(found=val, score=0.95 if val else 0.1)


class FakeConfig:
    def __init__(self, abilitato=True):
        self._ab = abilitato

    def task_abilitato(self, nome):
        return self._ab if nome == "radar_master" else True


class FakeNavigator:
    def __init__(self):
        self.calls = 0

    def vai_in_home(self):
        self.calls += 1
        return True


class FakeLogger:
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass


def _make_ctx(device=None, matcher=None, abilitato=True, navigator=None):
    from core.task import TaskContext
    from core.state import InstanceState
    return TaskContext(
        instance_name="FauMorfeus",
        config=FakeConfig(abilitato),
        state=InstanceState(instance_name="FauMorfeus"),
        log=FakeLogger(),
        device=device,
        matcher=matcher,
        navigator=navigator if navigator is not None else FakeNavigator(),
    )


def _cfg_zero():
    return RadarMasterConfig(
        wait_apertura_radar=0, wait_notifiche=0, wait_after_complete_all=0,
        wait_after_use_emergency=0, wait_after_close_stamina=0,
    )


def _task():
    return RadarMasterTask(config=_cfg_zero())


PIN_COMPLETED = "pin/pin_radar_completed.png"
PIN_STAMINA = "pin/pin_stamina_mask.png"
PIN_TITLE = "pin/pin_radar_title.png"


# ── should_run ─────────────────────────────────────────────────────────────

class TestShouldRun:
    def test_device_none(self):
        ctx = _make_ctx(device=None, matcher=FakeMatcher())
        assert _task().should_run(ctx) is False

    def test_disabilitato(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=False)
        assert _task().should_run(ctx) is False

    def test_abilitato_true(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher())
        assert _task().should_run(ctx) is True


# ── _stamina_fill_ratio (pixel-check) ──────────────────────────────────────

class TestStaminaFillRatio:
    def test_vuota(self):
        cfg = RadarMasterConfig()
        shot = FakeScreenshot(_make_frame(0.0))
        assert RadarMasterTask._stamina_fill_ratio(shot, cfg.stamina_bar_roi) < 0.05

    def test_parziale(self):
        cfg = RadarMasterConfig()
        shot = FakeScreenshot(_make_frame(0.5))
        r = RadarMasterTask._stamina_fill_ratio(shot, cfg.stamina_bar_roi)
        assert 0.4 < r < 0.6

    def test_piena(self):
        cfg = RadarMasterConfig()
        shot = FakeScreenshot(_make_frame(1.0))
        assert RadarMasterTask._stamina_fill_ratio(shot, cfg.stamina_bar_roi) > 0.97


# ── Flusso principale ──────────────────────────────────────────────────────

class TestRun:
    def test_pass_non_attivo_lucchetto_skip(self):
        """Complete All col LUCCHETTO (Radar Station Pass non attivo) → skip,
        nessun tap su Complete All."""
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher({"pin/pin_radar_lock.png": [True]})
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)
        assert result.skipped is True
        complete_taps = [c for c in device.calls
                         if c[0] == "tap" and (c[1], c[2]) == cfg.tap_complete_all]
        assert len(complete_taps) == 0

    def test_completato_al_primo_check(self):
        """pin_radar_completed trovato subito → fine immediata, nessun tap Complete All."""
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher({PIN_COMPLETED: [True]})
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.success is True
        assert result.data.get("esito") == _Esito.COMPLETATO
        complete_taps = [c for c in device.calls if c[0] == "tap" and (c[1], c[2]) == cfg.tap_complete_all]
        assert len(complete_taps) == 0

    def test_completa_dopo_un_tap(self):
        """Non completato al check iniziale, tap Complete All, poi completato."""
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher({PIN_COMPLETED: [False, True]})
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.success is True
        assert result.data.get("esito") == _Esito.COMPLETATO
        complete_taps = [c for c in device.calls if c[0] == "tap" and (c[1], c[2]) == cfg.tap_complete_all]
        assert len(complete_taps) == 1

    def test_saturazione_poi_completa(self):
        """Tap Complete All → maschera stamina → satura (barra piena subito
        col frame 1.0) → chiude maschera → ritenta → completato."""
        cfg = _cfg_zero()
        # ogni screenshot ha la barra stamina piena, cosi' un solo tap Emergency basta a saturare
        device = FakeDevice(frames=[FakeScreenshot(_make_frame(1.0))])
        m = FakeMatcher({
            PIN_COMPLETED: [False, False, True],
            PIN_STAMINA: [True],   # trovato subito dopo il tap Complete All (unica verifica)
        })
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.success is True
        assert result.data.get("esito") == _Esito.COMPLETATO
        assert result.data.get("saturazioni") == 1
        use_taps = [c for c in device.calls if c[0] == "tap" and (c[1], c[2]) == cfg.tap_use_emergency]
        assert len(use_taps) == 1   # barra già piena dal primo tap (frame 1.0)
        close_taps = [c for c in device.calls if c[0] == "tap" and (c[1], c[2]) == cfg.tap_close_stamina]
        assert len(close_taps) == 1

    def test_missione_silenziosa_riconosce_titolo_radar(self):
        """Né completato né stamina, ma pin_radar_title presente → considerato
        OK (missione completata silenziosamente), continua il loop."""
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher({
            PIN_COMPLETED: [False, False, True],
            PIN_STAMINA: [False, False],
            PIN_TITLE: [True],
        })
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.success is True
        assert result.data.get("esito") == _Esito.COMPLETATO

    def test_stato_inatteso_ripetuto_abort(self):
        """Né completato, né stamina, né titolo radar riconosciuto per
        max_stato_inatteso iterazioni consecutive → abort in sicurezza,
        navigator.vai_in_home chiamato in chiusura."""
        cfg = _cfg_zero()
        cfg.max_stato_inatteso = 2
        device = FakeDevice()
        nav = FakeNavigator()
        m = FakeMatcher({
            PIN_COMPLETED: [False] * 10,
            PIN_STAMINA: [False] * 10,
            PIN_TITLE: [False] * 10,
        })
        ctx = _make_ctx(device=device, matcher=m, navigator=nav)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.success is False
        assert result.data.get("esito") == _Esito.STATO_INATTESO
        assert nav.calls >= 1   # vai_in_home chiamato in chiusura (finally)

    def test_max_iter_raggiunto(self):
        """Mai completato, ma sempre titolo radar riconosciuto (nessun
        problema, semplicemente tante missioni) → max_iter, non crash."""
        cfg = _cfg_zero()
        cfg.max_complete_all_iter = 3
        device = FakeDevice()
        m = FakeMatcher({
            PIN_COMPLETED: [False] * 20,
            PIN_STAMINA: [False] * 20,
            PIN_TITLE: [True] * 20,
        })
        ctx = _make_ctx(device=device, matcher=m)
        result = RadarMasterTask(config=cfg).run(ctx)

        assert result.data.get("esito") == _Esito.MAX_ITER
        assert result.success is True   # non è un errore, solo tanto lavoro

    def test_chiusura_sempre_via_navigator(self):
        """In ogni caso (successo/abort/max_iter) la chiusura passa da
        navigator.vai_in_home(), mai back/tap grezzo."""
        cfg = _cfg_zero()
        device = FakeDevice()
        nav = FakeNavigator()
        m = FakeMatcher({PIN_COMPLETED: [True]})
        ctx = _make_ctx(device=device, matcher=m, navigator=nav)
        RadarMasterTask(config=cfg).run(ctx)
        # 1 volta per l'apertura iniziale + 1 in chiusura
        assert nav.calls == 2
