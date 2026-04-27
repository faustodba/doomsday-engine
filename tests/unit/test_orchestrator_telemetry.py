# ==============================================================================
#  tests/unit/test_orchestrator_telemetry.py — Issue #53 Step 2
#
#  Verifica che l'orchestrator emetta TaskTelemetry su ogni run, con
#  outcome corretto per ok/skip/fail/abort + anomalies per ADB cascade.
# ==============================================================================

import json
import os
import shutil
import tempfile

import pytest

from core.device import FakeDevice
from core.navigator import ADBUnhealthyError
from core.task import Task, TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from core.orchestrator import Orchestrator
from core import telemetry


# ------------------------------------------------------------------------------
# Stubs e fixture
# ------------------------------------------------------------------------------

class _StubTask(Task):
    def __init__(self, name="raccolta", result=None, raise_exc=None,
                 schedule="periodic", interval_h=4.0):
        self._name      = name
        self._result    = result or TaskResult(success=True, message="ok")
        self._raise_exc = raise_exc
        self._schedule  = schedule
        self._interval  = interval_h

    @property
    def name(self): return self._name

    @property
    def schedule_type(self): return self._schedule

    @property
    def interval_hours(self): return self._interval

    def should_run(self, ctx): return True

    def run(self, ctx):
        if self._raise_exc:
            raise self._raise_exc
        return self._result


class _FakeCfg:
    def task_abilitato(self, n): return True
    def get(self, k, default=None): return default


class _FakeNav:
    def vai_in_home(self): return True
    def vai_in_mappa(self): return True
    def tap_barra(self, ctx, voce): return True


def _make_ctx(instance="FAU_TEL"):
    from core.state import InstanceState
    return TaskContext(
        instance_name=instance,
        config=_FakeCfg(),
        state=InstanceState(instance),
        log=None,
        device=FakeDevice(),
        matcher=FakeMatcher(),
        navigator=_FakeNav(),
    )


@pytest.fixture
def telemetry_root(tmp_path, monkeypatch):
    """Isola la directory data/telemetry/ in una tmp dir per ogni test."""
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    yield tmp_path


def _read_events(root):
    """Legge gli eventi dell'oggi dalla tmp root."""
    return list(telemetry.iter_events())


# ==============================================================================
# 1. Path felice — ok
# ==============================================================================

def test_ok_event_recorded(telemetry_root):
    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(result=TaskResult(success=True, message="4 squadre",
                                              data={"squadre": 4})), priority=10)

    orc.tick()

    events = _read_events(telemetry_root)
    assert len(events) == 1
    ev = events[0]
    assert ev.task     == "raccolta"
    assert ev.instance == "FAU_TEL"
    assert ev.success  is True
    assert ev.outcome  == telemetry.OUTCOME_OK
    assert ev.msg      == "4 squadre"
    assert ev.output   == {"squadre": 4}
    assert ev.anomalies == []
    assert ev.duration_s >= 0
    assert ev.event_id


# ==============================================================================
# 2. Skip
# ==============================================================================

def test_skip_event_recorded(telemetry_root):
    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(result=TaskResult.skip("nessuna squadra")), priority=10)

    orc.tick()

    events = _read_events(telemetry_root)
    assert len(events) == 1
    assert events[0].outcome == telemetry.OUTCOME_SKIP
    assert events[0].success is True   # skip è "non-fail"


# ==============================================================================
# 3. Fail
# ==============================================================================

def test_fail_event_recorded(telemetry_root):
    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(result=TaskResult.fail("errore X")), priority=10)

    orc.tick()

    events = _read_events(telemetry_root)
    assert len(events) == 1
    assert events[0].outcome == telemetry.OUTCOME_FAIL
    assert events[0].success is False
    assert events[0].msg == "errore X"


# ==============================================================================
# 4. Eccezione generica → outcome=fail con msg eccezione
# ==============================================================================

def test_exception_event_recorded(telemetry_root):
    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(raise_exc=RuntimeError("boom")), priority=10)

    orc.tick()

    events = _read_events(telemetry_root)
    assert len(events) == 1
    ev = events[0]
    assert ev.outcome == telemetry.OUTCOME_FAIL
    assert "boom" in ev.msg


# ==============================================================================
# 5. ADB UNHEALTHY → outcome=abort + anomaly tag + tick interrotto
# ==============================================================================

def test_adb_unhealthy_event_recorded_and_tick_aborted(telemetry_root):
    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(name="rifornimento",
                           raise_exc=ADBUnhealthyError("screencap None")), priority=10)
    # Secondo task NON deve essere chiamato dopo abort
    second = _StubTask(name="raccolta", result=TaskResult.ok("4 squadre"))
    orc.register(second, priority=20)

    orc.tick()

    events = _read_events(telemetry_root)
    # Deve esserci SOLO il primo evento (rifornimento, abort)
    assert len(events) == 1
    ev = events[0]
    assert ev.task    == "rifornimento"
    assert ev.outcome == telemetry.OUTCOME_ABORT
    assert ev.success is False
    assert telemetry.ANOM_ADB_UNHEALTHY in ev.anomalies


# ==============================================================================
# 6. Cycle propagato da ctx.extras
# ==============================================================================

def test_cycle_from_ctx_extras(telemetry_root):
    ctx = _make_ctx()
    ctx.extras["cycle"] = 42
    orc = Orchestrator(ctx)
    orc.register(_StubTask(), priority=10)

    orc.tick()

    events = _read_events(telemetry_root)
    assert events[0].cycle == 42


# ==============================================================================
# 7. Telemetria silenziosa: failure di record() non rompe il task
# ==============================================================================

def test_telemetry_failure_does_not_break_task(telemetry_root, monkeypatch):
    def _broken_record(_):
        raise IOError("disk full simulation")
    monkeypatch.setattr("core.orchestrator._telemetry_record", _broken_record)

    ctx = _make_ctx()
    orc = Orchestrator(ctx)
    orc.register(_StubTask(result=TaskResult.ok("ok")), priority=10)

    # Non deve sollevare
    results = orc.tick()
    assert len(results) == 1
    assert results[0].success is True
