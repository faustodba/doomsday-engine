"""
tests/tasks/test_daily_mission_auto.py — DailyMissionAutoTask (20/07/2026)

Copre le due fasi (trigger/claim) once/day del task custom master.
FakeDevice/FakeMatcher minimali, nessuna dipendenza ADB/emulatore.
Config con wait azzerati per test veloci.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from unittest.mock import patch

from tasks.daily_mission_auto import (
    DailyMissionAutoTask, DailyMissionClaimTask, DailyMissionAutoConfig,
)


# ── Fake infra ─────────────────────────────────────────────────────────────

class FakeScreenshot:
    frame = None   # _leggi_current_ap → -1 (nessun chest nei test)


class FakeDevice:
    def __init__(self):
        self.calls: list[tuple] = []

    def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeScreenshot()

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def swipe(self, x1, y1, x2, y2, dur=400):
        self.calls.append(("swipe", x1, y1, x2, y2))

    def taps(self):
        return [c for c in self.calls if c[0] == "tap"]


@dataclass
class _Match:
    found: bool
    score: float = 0.9
    cx: int = 850
    cy: int = 300


class FakeMatcher:
    """scores: dict {tmpl: float}. claim_count: quante volte find_one(pin_claim)
    ritorna found prima di esaurirsi (simula la lista che si svuota)."""
    def __init__(self, scores=None, claim_count=0, pin_claim="pin/pin_btn_claim_mission.png"):
        self._scores = scores or {}
        self._claim_left = claim_count
        self._pin_claim = pin_claim

    def score(self, shot, tmpl, zone=None):
        return self._scores.get(tmpl, 0.0)

    def find_one(self, shot, tmpl, threshold=0.8, zone=None):
        if tmpl == self._pin_claim:
            if self._claim_left > 0:
                self._claim_left -= 1
                return _Match(found=True, score=0.95, cx=850, cy=300)
            return _Match(found=False, score=0.0)
        s = self._scores.get(tmpl, 0.0)
        return _Match(found=s >= threshold, score=s, cx=843, cy=225)


class FakeConfig:
    def __init__(self, abilitato=True):
        self._ab = abilitato

    def task_abilitato(self, nome):
        return self._ab if nome == "daily_mission_auto" else True


class FakeNavigator:
    def vai_in_home(self):
        return True


class FakeLogger:
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass


def _make_ctx(device=None, matcher=None, abilitato=True, stato=None):
    from core.task import TaskContext
    from core.state import InstanceState
    st = InstanceState(instance_name="FauMorfeus")
    if stato is not None:
        st.daily_mission = stato
    return TaskContext(
        instance_name="FauMorfeus",
        config=FakeConfig(abilitato),
        state=st,
        log=FakeLogger(),
        device=device,
        matcher=matcher,
        navigator=FakeNavigator(),
    )


def _cfg_zero():
    return DailyMissionAutoConfig(
        wait_apri_pannello=0, wait_tab_switch=0, wait_post_auto=0,
        wait_post_claim=0, wait_post_tap=0, wait_scroll=0, wait_back=0,
    )


def _task():
    return DailyMissionAutoTask(config=_cfg_zero())


def _claim_task():
    return DailyMissionClaimTask(config=_cfg_zero())


# ── should_run ─────────────────────────────────────────────────────────────

class TestShouldRun:
    def test_device_none(self):
        ctx = _make_ctx(device=None, matcher=FakeMatcher())
        assert _task().should_run(ctx) is False

    def test_disabilitato(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=False)
        assert _task().should_run(ctx) is False

    def test_da_fare_true(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher())
        assert _task().should_run(ctx) is True

    def test_gia_completato_oggi_false(self):
        from core.state import DailyMissionState
        s = DailyMissionState()
        s.segna_trigger(); s.segna_claim()
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), stato=s)
        assert _task().should_run(ctx) is False


# ── Fase TRIGGER ───────────────────────────────────────────────────────────

class TestFaseTrigger:
    def test_trigger_pulsante_presente(self):
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher(scores={
            cfg.pin_auto_complete: 0.95,   # pulsante presente
            cfg.pin_auto_ends: 0.95,       # dopo tap, timer partito
        })
        ctx = _make_ctx(device=device, matcher=m)
        result = _task().run(ctx)

        assert result.success is True
        assert result.data.get("fase") == "trigger"
        # tap Auto Complete eseguito
        assert any(c == ("tap",) + cfg.tap_auto_complete for c in device.calls)
        # stato aggiornato
        assert ctx.state.daily_mission.trigger_fatto is True
        assert ctx.state.daily_mission.claim_fatto is False

    def test_trigger_pulsante_assente_non_disponibile(self):
        cfg = _cfg_zero()
        device = FakeDevice()
        m = FakeMatcher(scores={cfg.pin_auto_complete: 0.10})  # pulsante assente
        ctx = _make_ctx(device=device, matcher=m)
        result = _task().run(ctx)

        assert result.skipped is True
        # nessun tap su Auto Complete
        assert not any(c == ("tap",) + cfg.tap_auto_complete for c in device.calls)
        # segnato non disponibile → non riprova oggi
        assert ctx.state.daily_mission.should_run() is False


# ── Fase CLAIM ─────────────────────────────────────────────────────────────

class TestFaseClaim:
    def _stato_triggerato(self, minuti_fa=5):
        from core.state import DailyMissionState
        s = DailyMissionState()
        s.segna_trigger()
        s.trigger_ts = (datetime.now(timezone.utc) - timedelta(minutes=minuti_fa)).isoformat()
        return s

    # 21/07: il CLAIM è ora DailyMissionClaimTask (priority 199), gira nello
    # stesso ciclo del trigger. Attende SOLO il residuo dei 3 min (sleep
    # patchato nei test). should_run: trigger fatto e claim non fatto.

    def test_claim_should_run(self):
        s = self._stato_triggerato(minuti_fa=5)
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), stato=s)
        assert _claim_task().should_run(ctx) is True

    def test_claim_should_run_false_senza_trigger(self):
        from core.state import DailyMissionState
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), stato=DailyMissionState())
        assert _claim_task().should_run(ctx) is False   # trigger non fatto

    @patch("tasks.daily_mission_auto.time.sleep")
    def test_claim_attende_residuo_poi_esegue(self, mock_sleep):
        # trigger 0 min fa → attende residuo (~180s, sleep patchato) poi claim
        cfg = _cfg_zero()
        s = self._stato_triggerato(minuti_fa=0)
        device = FakeDevice()
        m = FakeMatcher(claim_count=3, pin_claim=cfg.pin_claim)
        ctx = _make_ctx(device=device, matcher=m, stato=s)
        result = _claim_task().run(ctx)
        assert mock_sleep.called            # ha atteso il residuo
        assert result.success is True
        assert result.data.get("fase") == "claim"
        assert result.data.get("daily_claim") == 3
        assert result.data.get("chest_claim") == 5
        assert ctx.state.daily_mission.claim_fatto is True

    @patch("tasks.daily_mission_auto.time.sleep")
    def test_claim_pronto_esegue(self, _sleep):
        cfg = _cfg_zero()
        s = self._stato_triggerato(minuti_fa=5)   # residuo 0
        device = FakeDevice()
        m = FakeMatcher(claim_count=3, pin_claim=cfg.pin_claim)
        ctx = _make_ctx(device=device, matcher=m, stato=s)
        result = _claim_task().run(ctx)
        assert result.success is True
        assert result.data.get("daily_claim") == 3
        assert result.data.get("chest_claim") == 5
        assert ctx.state.daily_mission.claim_fatto is True

    @patch("tasks.daily_mission_auto.time.sleep")
    def test_ritira_tutti_e_5_i_chest(self, _sleep):
        cfg = _cfg_zero()
        s = self._stato_triggerato(minuti_fa=5)
        device = FakeDevice()
        m = FakeMatcher(claim_count=1, pin_claim=cfg.pin_claim)
        ctx = _make_ctx(device=device, matcher=m, stato=s)
        _claim_task().run(ctx)
        chest_taps = [c for c in device.calls if c[0] == "tap" and (c[1], c[2]) in cfg.chest_coords]
        assert len(chest_taps) == 5

    @patch("tasks.daily_mission_auto.time.sleep")
    def test_claim_lista_vuota_scrolla_poi_stop(self, _sleep):
        cfg = _cfg_zero()
        s = self._stato_triggerato(minuti_fa=5)
        device = FakeDevice()
        m = FakeMatcher(claim_count=0, pin_claim=cfg.pin_claim)
        ctx = _make_ctx(device=device, matcher=m, stato=s)
        result = _claim_task().run(ctx)
        assert result.data.get("daily_claim") == 0
        swipes = [c for c in device.calls if c[0] == "swipe"]
        assert len(swipes) == cfg.max_scroll_vuoti
        assert ctx.state.daily_mission.claim_fatto is True
