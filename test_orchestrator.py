# ==============================================================================
#  tests/unit/test_orchestrator.py — Step 22
#  Tutti i test usano FakeDevice + FakeMatcher + task stub — zero ADB reale.
# ==============================================================================

import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from core.device import FakeDevice
from core.navigator import GameNavigator
from core.task import Task, TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from core.orchestrator import (
    Orchestrator,
    _TaskEntry,
    _e_dovuto_periodic,
    _e_dovuto_daily,
    _reset_daily_corrente,
    e_dovuto,
)


# ------------------------------------------------------------------------------
# Task stub per i test
# ------------------------------------------------------------------------------

class StubTask(Task):
    """Task minimo controllabile per i test."""
    def should_run(self, ctx): return True

    def __init__(self, name: str = "stub",
                 schedule: str = "periodic",
                 interval_h: float = 4.0,
                 result: TaskResult | None = None,
                 raise_exc: Exception | None = None):
        self._name      = name
        self._schedule  = schedule
        self._interval  = interval_h
        self._result    = result or TaskResult(success=True, message="ok")
        self._raise_exc = raise_exc
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def schedule_type(self) -> str:
        return self._schedule

    @property
    def interval_hours(self) -> float:
        return self._interval

    def run(self, ctx: TaskContext) -> TaskResult:
        self.call_count += 1
        if self._raise_exc:
            raise self._raise_exc
        return self._result


# ------------------------------------------------------------------------------
# Fixture
# ------------------------------------------------------------------------------

class _FakeCfg:
    def task_abilitato(self, n): return True
    def get(self, k, default=None): return default


class _FakeNavigator:
    """Navigator che restituisce sempre True senza ADB reale."""
    def vai_in_home(self) -> bool: return True
    def vai_in_mappa(self) -> bool: return True
    def tap_barra(self, ctx, voce): return True


def make_ctx() -> TaskContext:
    from core.state import InstanceState
    device  = FakeDevice()
    matcher = FakeMatcher()
    return TaskContext(
        instance_name="FAU_00",
        config=_FakeCfg(),
        state=InstanceState("FAU_00"),
        log=None,
        device=device,
        matcher=matcher,
        navigator=_FakeNavigator(),
    )


def make_entry(task: Task, priority: int = 50,
               last_run: float = 0.0) -> _TaskEntry:
    return _TaskEntry(task=task, priority=priority, last_run=last_run)


# ==============================================================================
# 1. Helpers scheduling — periodic
# ==============================================================================

class TestEDovutoPeriodic:

    def test_mai_eseguito(self):
        entry = make_entry(StubTask(interval_h=4.0), last_run=0.0)
        assert _e_dovuto_periodic(entry) is True

    def test_appena_eseguito(self):
        entry = make_entry(StubTask(interval_h=4.0), last_run=time.time())
        assert _e_dovuto_periodic(entry) is False

    def test_scaduto(self):
        passato = time.time() - (4 * 3600 + 1)
        entry = make_entry(StubTask(interval_h=4.0), last_run=passato)
        assert _e_dovuto_periodic(entry) is True

    def test_non_ancora_scaduto(self):
        passato = time.time() - (3 * 3600)  # 3h fa, intervallo 4h
        entry = make_entry(StubTask(interval_h=4.0), last_run=passato)
        assert _e_dovuto_periodic(entry) is False

    def test_intervallo_168h(self):
        passato = time.time() - (167 * 3600)  # quasi settimanale
        entry = make_entry(StubTask(interval_h=168.0), last_run=passato)
        assert _e_dovuto_periodic(entry) is False

    def test_intervallo_168h_scaduto(self):
        passato = time.time() - (169 * 3600)
        entry = make_entry(StubTask(interval_h=168.0), last_run=passato)
        assert _e_dovuto_periodic(entry) is True


# ==============================================================================
# 2. Helpers scheduling — daily
# ==============================================================================

class TestEDovutoDaily:

    def test_mai_eseguito(self):
        entry = make_entry(StubTask(schedule="daily"), last_run=0.0)
        assert _e_dovuto_daily(entry) is True

    def test_eseguito_prima_del_reset(self):
        """Eseguito ieri (prima del reset) → dovuto."""
        reset = _reset_daily_corrente()
        prima_reset = (reset - timedelta(hours=1)).timestamp()
        entry = make_entry(StubTask(schedule="daily"), last_run=prima_reset)
        assert _e_dovuto_daily(entry) is True

    def test_eseguito_dopo_reset(self):
        """Eseguito dopo il reset di oggi → non dovuto."""
        reset = _reset_daily_corrente()
        dopo_reset = (reset + timedelta(hours=1)).timestamp()
        entry = make_entry(StubTask(schedule="daily"), last_run=dopo_reset)
        assert _e_dovuto_daily(entry) is False

    def test_reset_daily_corrente_e_utc(self):
        """Il reset deve essere alle 00:00 UTC (allineato al reset gioco)."""
        reset = _reset_daily_corrente()
        assert reset.tzinfo == timezone.utc
        assert reset.hour == 0
        assert reset.minute == 0
        assert reset.second == 0


# ==============================================================================
# 3. e_dovuto — dispatch + enabled
# ==============================================================================

class TestEDovuto:

    def test_disabled_mai_dovuto(self):
        entry = make_entry(StubTask())
        entry.enabled = False
        assert e_dovuto(entry) is False

    def test_periodic_dovuto(self):
        entry = make_entry(StubTask(schedule="periodic", interval_h=4.0),
                           last_run=0.0)
        assert e_dovuto(entry) is True

    def test_daily_dovuto(self):
        entry = make_entry(StubTask(schedule="daily"), last_run=0.0)
        assert e_dovuto(entry) is True

    def test_periodic_non_dovuto(self):
        entry = make_entry(StubTask(schedule="periodic", interval_h=4.0),
                           last_run=time.time())
        assert e_dovuto(entry) is False


# ==============================================================================
# 4. Orchestrator — register e struttura
# ==============================================================================

class TestOrchestratorRegister:

    def test_register_un_task(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        assert len(orc) == 1

    def test_register_multipli(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        orc.register(StubTask("t2"))
        orc.register(StubTask("t3"))
        assert len(orc) == 3

    def test_ordine_priorita(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("alta"),  priority=10)
        orc.register(StubTask("bassa"), priority=50)
        orc.register(StubTask("media"), priority=30)
        names = orc.task_names()
        assert names == ["alta", "media", "bassa"]

    def test_task_names(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("raccolta"))
        orc.register(StubTask("zaino"))
        assert "raccolta" in orc.task_names()
        assert "zaino"    in orc.task_names()

    def test_disabled_at_register(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1")
        orc.register(t, enabled=False)
        results = orc.tick()
        assert results == []
        assert t.call_count == 0


# ==============================================================================
# 5. Orchestrator — enable / disable
# ==============================================================================

class TestOrchestratorEnableDisable:

    def test_disable(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1")
        orc.register(t)
        orc.disable("t1")
        orc.tick()
        assert t.call_count == 0

    def test_enable_dopo_disable(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1")
        orc.register(t)
        orc.disable("t1")
        orc.enable("t1")
        orc.tick()
        assert t.call_count == 1

    def test_disable_nome_inesistente_noop(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        orc.disable("nonexistent")   # non deve sollevare eccezioni
        assert len(orc) == 1


# ==============================================================================
# 6. Orchestrator — tick base
# ==============================================================================

class TestOrchestratorTick:

    def test_tick_esegue_task_dovuto(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1")
        orc.register(t)
        orc.tick()
        assert t.call_count == 1

    def test_tick_non_esegue_non_dovuto(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1", interval_h=4.0)
        orc.register(t)
        orc.set_last_run("t1", time.time())  # appena eseguito
        results = orc.tick()
        assert t.call_count == 0
        assert results == []

    def test_tick_ritorna_lista_results(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        orc.register(StubTask("t2"))
        results = orc.tick()
        assert len(results) == 2
        assert all(isinstance(r, TaskResult) for r in results)

    def test_tick_aggiorna_last_run(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        t_prima = time.time()
        orc.tick()
        t_dopo = time.time()
        stato = orc.stato()
        assert t_prima <= stato["t1"]["last_run"] <= t_dopo

    def test_tick_secondo_giro_non_riesegue(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1", interval_h=4.0)
        orc.register(t)
        orc.tick()   # primo tick → eseguito
        orc.tick()   # secondo tick → non dovuto
        assert t.call_count == 1

    def test_tick_ordine_priorita(self):
        """I task devono essere eseguiti nell'ordine di priorità."""
        eseguiti = []
        ctx = make_ctx()

        class TrackedTask(StubTask):
            def run(self, c):
                eseguiti.append(self.name)
                return super().run(c)

        orc = Orchestrator(ctx)
        orc.register(TrackedTask("bassa"), priority=50)
        orc.register(TrackedTask("alta"),  priority=10)
        orc.register(TrackedTask("media"), priority=30)
        orc.tick()
        assert eseguiti == ["alta", "media", "bassa"]

    def test_tick_risultato_success(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1", result=TaskResult(success=True, message="ok")))
        results = orc.tick()
        assert results[0].success is True
        assert results[0].message == "ok"

    def test_tick_risultato_failure(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1", result=TaskResult(success=False, message="fail")))
        results = orc.tick()
        assert results[0].success is False


# ==============================================================================
# 7. Orchestrator — gestione eccezioni nel task
# ==============================================================================

class TestOrchestratorEccezioni:

    def test_eccezione_non_propaga(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("crash", raise_exc=RuntimeError("boom")))
        results = orc.tick()   # non deve sollevare
        assert len(results) == 1
        assert results[0].success is False

    def test_eccezione_messaggio_contiene_testo(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("crash", raise_exc=ValueError("bad value")))
        results = orc.tick()
        assert "bad value" in results[0].message

    def test_eccezione_non_blocca_task_successivo(self):
        orc = Orchestrator(make_ctx())
        t_ok = StubTask("ok_after")
        orc.register(StubTask("crash", raise_exc=RuntimeError("boom")), priority=10)
        orc.register(t_ok, priority=20)
        orc.tick()
        assert t_ok.call_count == 1

    def test_last_run_aggiornato_anche_dopo_eccezione(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("crash", raise_exc=RuntimeError("boom")))
        t_prima = time.time()
        orc.tick()
        assert orc.stato()["crash"]["last_run"] >= t_prima


# ==============================================================================
# 8. Orchestrator — stato()
# ==============================================================================

class TestOrchestratorStato:

    def test_stato_vuoto(self):
        orc = Orchestrator(make_ctx())
        assert orc.stato() == {}

    def test_stato_task_mai_eseguito(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1", interval_h=4.0)
        orc.register(t, priority=10)
        s = orc.stato()
        assert "t1" in s
        assert s["t1"]["last_run"] == 0.0
        assert s["t1"]["last_success"] is None
        assert s["t1"]["priority"] == 10
        assert s["t1"]["schedule"] == "periodic"
        assert s["t1"]["interval_h"] == 4.0

    def test_stato_dopo_esecuzione(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1", result=TaskResult(success=True, message="fatto")))
        orc.tick()
        s = orc.stato()
        assert s["t1"]["last_success"] is True
        assert s["t1"]["last_message"] == "fatto"
        assert s["t1"]["last_run"] > 0.0

    def test_stato_dovuto_false_dopo_esecuzione(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1", interval_h=4.0))
        orc.tick()
        s = orc.stato()
        assert s["t1"]["dovuto"] is False

    def test_stato_enabled(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"), enabled=True)
        orc.register(StubTask("t2"), enabled=False)
        s = orc.stato()
        assert s["t1"]["enabled"] is True
        assert s["t2"]["enabled"] is False


# ==============================================================================
# 9. Orchestrator — n_dovuti
# ==============================================================================

class TestOrchestratorNDovuti:

    def test_tutti_dovuti_inizialmente(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"))
        orc.register(StubTask("t2"))
        assert orc.n_dovuti() == 2

    def test_nessuno_dopo_tick(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1", interval_h=4.0))
        orc.tick()
        assert orc.n_dovuti() == 0

    def test_disabled_non_contato(self):
        orc = Orchestrator(make_ctx())
        orc.register(StubTask("t1"), enabled=False)
        assert orc.n_dovuti() == 0


# ==============================================================================
# 10. Orchestrator — set_last_run
# ==============================================================================

class TestOrchestratorSetLastRun:

    def test_set_last_run_impedisce_esecuzione(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1", interval_h=4.0)
        orc.register(t)
        orc.set_last_run("t1", time.time())
        orc.tick()
        assert t.call_count == 0

    def test_set_last_run_passato_forza_esecuzione(self):
        orc = Orchestrator(make_ctx())
        t = StubTask("t1", interval_h=4.0)
        orc.register(t)
        orc.set_last_run("t1", time.time() - 5 * 3600)  # 5h fa
        orc.tick()
        assert t.call_count == 1

    def test_set_last_run_nome_inesistente_noop(self):
        orc = Orchestrator(make_ctx())
        orc.set_last_run("nonexistent", 0.0)  # non deve sollevare


# ==============================================================================
# 11. Orchestrator — integrazione con task V6 reali (import smoke test)
# ==============================================================================

class TestOrchestratorIntegrazione:

    @patch("tasks.zaino.time.sleep")
    def test_zaino_task_registrabile(self, mock_sleep):
        from tasks.zaino import ZainoTask
        orc = Orchestrator(make_ctx())
        orc.register(ZainoTask(), priority=30)
        assert "zaino" in orc.task_names()

    @patch("tasks.rifornimento.time.sleep")
    def test_rifornimento_task_registrabile(self, mock_sleep):
        from tasks.rifornimento import RifornimentoTask
        orc = Orchestrator(make_ctx())
        orc.register(RifornimentoTask(), priority=20)
        assert "rifornimento" in orc.task_names()

    @patch("tasks.raccolta.time.sleep")
    def test_raccolta_task_registrabile(self, mock_sleep):
        from tasks.raccolta import RaccoltaTask
        orc = Orchestrator(make_ctx())
        orc.register(RaccoltaTask(), priority=10)
        assert "raccolta" in orc.task_names()

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.raccolta.time.sleep")
    def test_tick_tre_task_registrati(self, ms_r, ms_f, ms_z):
        """Tutti e tre i task V6 coesistono e vengono eseguiti in un tick."""
        from tasks.zaino       import ZainoTask
        from tasks.rifornimento import RifornimentoTask
        from tasks.raccolta    import RaccoltaTask

        ctx = make_ctx()
        orc = Orchestrator(ctx)
        orc.register(RaccoltaTask(),     priority=10)
        orc.register(RifornimentoTask(), priority=20)
        orc.register(ZainoTask(),        priority=30)

        results = orc.tick()
        # Tutti e 3 eseguiti (disabilitati per config mancante → success=True o False)
        assert len(results) == 3
        names_eseguiti = {e.task.name() if callable(e.task.name) else e.task.name
                          for e in orc._entries if e.last_run > 0.0}
        assert names_eseguiti == {"raccolta", "rifornimento", "zaino"}


# ==============================================================================
# TestGateShouldRun — gate should_run() introdotto 16/04/2026
# ==============================================================================

class StubTaskShouldRunFalse(Task):
    """Task con should_run() sempre False."""
    def name(self): return "stub_disabled"
    def should_run(self, ctx): return False
    def run(self, ctx): return TaskResult.ok("non dovrebbe girare")
    schedule_type = "periodic"
    interval_hours = 0.0

class StubTaskShouldRunTrue(Task):
    """Task con should_run() sempre True."""
    def name(self): return "stub_enabled"
    def should_run(self, ctx): return True
    def run(self, ctx): return TaskResult.ok("eseguito")
    schedule_type = "periodic"
    interval_hours = 0.0

class StubTaskShouldRunException(Task):
    """Task con should_run() che solleva eccezione."""
    def name(self): return "stub_exc"
    def should_run(self, ctx): raise RuntimeError("errore should_run")
    def run(self, ctx): return TaskResult.ok("non dovrebbe girare")
    schedule_type = "periodic"
    interval_hours = 0.0


class TestGateShouldRun:

    def test_should_run_false_task_saltato(self):
        """Se should_run()=False il task non viene eseguito."""
        task = StubTaskShouldRunFalse()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        results = orc.tick()
        assert len(results) == 0

    def test_should_run_false_last_run_non_aggiornato(self):
        """Se should_run()=False last_run rimane 0.0 (ritenta al prossimo tick)."""
        task = StubTaskShouldRunFalse()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        orc.tick()
        entry = orc._entries[0]
        assert entry.last_run == 0.0

    def test_should_run_true_task_eseguito(self):
        """Se should_run()=True il task viene eseguito normalmente."""
        task = StubTaskShouldRunTrue()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        results = orc.tick()
        assert len(results) == 1
        assert results[0].success is True

    def test_should_run_true_last_run_aggiornato(self):
        """Se should_run()=True last_run viene aggiornato dopo run()."""
        task = StubTaskShouldRunTrue()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        orc.tick()
        entry = orc._entries[0]
        assert entry.last_run > 0.0

    def test_should_run_eccezione_task_saltato(self):
        """Se should_run() solleva eccezione il task viene saltato senza crashare."""
        task = StubTaskShouldRunException()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        results = orc.tick()
        assert len(results) == 0

    def test_should_run_eccezione_last_run_non_aggiornato(self):
        """Se should_run() solleva eccezione last_run rimane 0.0."""
        task = StubTaskShouldRunException()
        orc  = Orchestrator(make_ctx())
        orc.register(task, priority=10)
        orc.tick()
        entry = orc._entries[0]
        assert entry.last_run == 0.0

    def test_gate_ordine_should_run_prima_di_home(self):
        """should_run() viene valutato prima del gate HOME."""
        task = StubTaskShouldRunFalse()
        nav_chiamato = []

        ctx = make_ctx()
        if ctx.navigator:
            orig = ctx.navigator.vai_in_home
            def nav_spy():
                nav_chiamato.append(True)
                return orig()
            ctx.navigator.vai_in_home = nav_spy

        orc = Orchestrator(ctx)
        orc.register(task, priority=10)
        orc.tick()
        # navigator non deve essere stato chiamato per il task saltato
        assert len(nav_chiamato) == 0

    def test_mix_should_run_true_e_false(self):
        """Solo i task con should_run()=True vengono eseguiti."""
        t_enabled  = StubTaskShouldRunTrue()
        t_disabled = StubTaskShouldRunFalse()
        orc = Orchestrator(make_ctx())
        orc.register(t_disabled, priority=10)
        orc.register(t_enabled,  priority=20)
        results = orc.tick()
        assert len(results) == 1
        assert results[0].message == "eseguito"
