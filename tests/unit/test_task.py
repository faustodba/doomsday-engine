# ==============================================================================
#  tests/unit/test_task.py
#
#  Unit test per core/task.py
#
#  Usa task concreti minimali definiti nel test stesso per verificare
#  l'interfaccia ABC senza dipendere da implementazioni reali.
# ==============================================================================

import pytest
from unittest.mock import MagicMock, AsyncMock

from core.task import Task, TaskContext, TaskResult
from core.logger import StructuredLogger
from core.state import InstanceState
from config.config import InstanceConfig


# ==============================================================================
# Task concreti minimali per i test
# ==============================================================================

class AlwaysRunTask(Task):
    """Task che esegue sempre e ritorna OK."""

    def name(self) -> str:
        return "always_run"

    def should_run(self, ctx: TaskContext) -> bool:
        return True

    async def run(self, ctx: TaskContext) -> TaskResult:
        return TaskResult.ok("completato", valore=42)


class NeverRunTask(Task):
    """Task che non esegue mai (precondizioni false)."""

    def name(self) -> str:
        return "never_run"

    def should_run(self, ctx: TaskContext) -> bool:
        return False

    async def run(self, ctx: TaskContext) -> TaskResult:
        return TaskResult.ok("non dovrebbe arrivare qui")


class FailingTask(Task):
    """Task che ritorna sempre fallimento."""

    def name(self) -> str:
        return "failing"

    def should_run(self, ctx: TaskContext) -> bool:
        return True

    async def run(self, ctx: TaskContext) -> TaskResult:
        return TaskResult.fail("errore simulato", codice=500)


class SkippingTask(Task):
    """Task che ritorna skip."""

    def name(self) -> str:
        return "skipping"

    def should_run(self, ctx: TaskContext) -> bool:
        return True

    async def run(self, ctx: TaskContext) -> TaskResult:
        return TaskResult.skip("precondizione non soddisfatta")


class CustomFailureTask(Task):
    """Task con on_failure personalizzato."""

    def __init__(self):
        self.failure_called = False
        self.last_result = None

    def name(self) -> str:
        return "custom_failure"

    def should_run(self, ctx: TaskContext) -> bool:
        return True

    async def run(self, ctx: TaskContext) -> TaskResult:
        return TaskResult.fail("errore custom")

    def on_failure(self, ctx: TaskContext, result: TaskResult) -> None:
        self.failure_called = True
        self.last_result = result


# ==============================================================================
# Fixture — TaskContext minimale per i test
# ==============================================================================

def make_context(instance_name: str = "FAU_TEST") -> TaskContext:
    """Crea un TaskContext minimale con mock per i servizi."""
    config = MagicMock(spec=InstanceConfig)
    config.task_abilitato.return_value = True

    state  = InstanceState(instance_name)
    log    = MagicMock(spec=StructuredLogger)

    return TaskContext(
        instance_name=instance_name,
        config=config,
        state=state,
        log=log,
    )


# ==============================================================================
# TestTaskResult
# ==============================================================================

class TestTaskResult:

    def test_ok_factory(self):
        r = TaskResult.ok("tutto bene", marce=3)
        assert r.success is True
        assert r.skipped is False
        assert r.message == "tutto bene"
        assert r.data["marce"] == 3

    def test_fail_factory(self):
        r = TaskResult.fail("timeout ADB", tentativi=3)
        assert r.success is False
        assert r.skipped is False
        assert r.message == "timeout ADB"
        assert r.data["tentativi"] == 3

    def test_skip_factory(self):
        r = TaskResult.skip("fuori fascia oraria")
        assert r.success is True
        assert r.skipped is True
        assert r.message == "fuori fascia oraria"

    def test_immutabilita(self):
        r = TaskResult.ok("msg")
        with pytest.raises((AttributeError, TypeError)):
            r.success = False  # type: ignore

    def test_repr_ok(self):
        r = TaskResult.ok("done")
        assert "OK" in repr(r)

    def test_repr_fail(self):
        r = TaskResult.fail("err")
        assert "FAIL" in repr(r)

    def test_repr_skip(self):
        r = TaskResult.skip("salta")
        assert "SKIP" in repr(r)

    def test_data_default_vuoto(self):
        r = TaskResult(success=True)
        assert r.data == {}

    def test_ok_senza_dati(self):
        r = TaskResult.ok()
        assert r.success is True
        assert r.data == {}

    def test_fail_senza_dati(self):
        r = TaskResult.fail()
        assert r.success is False
        assert r.data == {}


# ==============================================================================
# TestTaskContext
# ==============================================================================

class TestTaskContext:

    def test_costruzione_minimale(self):
        ctx = make_context("FAU_00")
        assert ctx.instance_name == "FAU_00"
        assert ctx.device is None
        assert ctx.navigator is None
        assert ctx.matcher is None

    def test_extras_dict(self):
        ctx = make_context()
        ctx.extras["screenshot"] = "fake"
        assert ctx.extras["screenshot"] == "fake"

    def test_repr(self):
        ctx = make_context("FAU_05")
        r = repr(ctx)
        assert "FAU_05" in r
        assert "TaskContext" in r

    def test_con_device(self):
        ctx = make_context()
        ctx.device = MagicMock()
        assert ctx.device is not None


# ==============================================================================
# TestTask — interfaccia ABC
# ==============================================================================

class TestTaskABC:

    def test_non_istanziabile_direttamente(self):
        """Task è ABC — non può essere istanziata direttamente."""
        with pytest.raises(TypeError):
            Task()  # type: ignore

    def test_name(self):
        task = AlwaysRunTask()
        assert task.name() == "always_run"

    def test_should_run_true(self):
        task = AlwaysRunTask()
        ctx = make_context()
        assert task.should_run(ctx) is True

    def test_should_run_false(self):
        task = NeverRunTask()
        ctx = make_context()
        assert task.should_run(ctx) is False

    @pytest.mark.asyncio
    async def test_run_ok(self):
        task = AlwaysRunTask()
        ctx = make_context()
        result = await task.run(ctx)
        assert result.success is True
        assert result.data["valore"] == 42

    @pytest.mark.asyncio
    async def test_run_fail(self):
        task = FailingTask()
        ctx = make_context()
        result = await task.run(ctx)
        assert result.success is False
        assert result.data["codice"] == 500

    @pytest.mark.asyncio
    async def test_run_skip(self):
        task = SkippingTask()
        ctx = make_context()
        result = await task.run(ctx)
        assert result.skipped is True

    def test_on_failure_default_loga(self):
        task = AlwaysRunTask()
        ctx = make_context()
        result = TaskResult.fail("errore test")
        task.on_failure(ctx, result)
        ctx.log.error.assert_called_once()

    def test_on_failure_custom_override(self):
        task = CustomFailureTask()
        ctx = make_context()
        result = TaskResult.fail("errore custom")
        task.on_failure(ctx, result)
        assert task.failure_called is True
        assert task.last_result is result

    def test_repr(self):
        task = AlwaysRunTask()
        r = repr(task)
        assert "AlwaysRunTask" in r
        assert "always_run" in r


# ==============================================================================
# TestTask — pattern di utilizzo corretto
# ==============================================================================

class TestTaskPattern:
    """
    Verifica che il pattern di utilizzo raccomandato funzioni:
    1. should_run() viene chiamato prima di run()
    2. on_failure() viene chiamato se run() ritorna fail
    """

    @pytest.mark.asyncio
    async def test_pattern_completo_successo(self):
        task = AlwaysRunTask()
        ctx = make_context()

        if task.should_run(ctx):
            result = await task.run(ctx)
            if not result.success and not result.skipped:
                task.on_failure(ctx, result)

        assert True  # nessuna eccezione

    @pytest.mark.asyncio
    async def test_pattern_completo_fallimento(self):
        task = CustomFailureTask()
        ctx = make_context()

        if task.should_run(ctx):
            result = await task.run(ctx)
            if not result.success and not result.skipped:
                task.on_failure(ctx, result)

        assert task.failure_called is True

    @pytest.mark.asyncio
    async def test_pattern_should_run_false_non_chiama_run(self):
        """Se should_run è False, run non deve essere chiamato."""
        task = NeverRunTask()
        ctx = make_context()
        run_called = False

        if task.should_run(ctx):
            run_called = True
            await task.run(ctx)

        assert run_called is False

    @pytest.mark.asyncio
    async def test_pattern_skip_non_chiama_on_failure(self):
        """Un risultato skipped non deve triggerare on_failure."""
        task = SkippingTask()
        ctx = make_context()
        on_failure_called = False

        result = await task.run(ctx)
        if not result.success and not result.skipped:
            on_failure_called = True

        assert on_failure_called is False
