# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_faumorfeus_setup.py
#
#  Test unitari per tasks/faumorfeus_setup.py (WU234).
#
#  Scenari coperti:
#    - should_run(): True solo per is_master_instance + device presente
#    - run(): tutti e 4 gli step invocati in ordine, best-effort (un
#      fallimento non blocca gli altri), TaskResult aggregato
#    - task_abilitato() False su grafica_hq/pulizia_cache -> skip mirato
#    - vai_in_home() chiamato fra uno step e il successivo
# ==============================================================================

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.task import TaskContext, TaskResult
from tasks.faumorfeus_setup import FauMorfeusSetupTask


# ==============================================================================
# Fake infrastructure
# ==============================================================================

class FakeConfig:
    def __init__(self, disabilitati: set[str] | None = None) -> None:
        self._disabilitati = disabilitati or set()

    def task_abilitato(self, nome: str) -> bool:
        return nome not in self._disabilitati


class FakeNavigator:
    def __init__(self) -> None:
        self.vai_in_home_calls = 0

    def vai_in_home(self) -> bool:
        self.vai_in_home_calls += 1
        return True


def _make_ctx(nome: str = "FauMorfeus", device=object(),
              disabilitati: set[str] | None = None) -> TaskContext:
    return TaskContext(
        instance_name=nome,
        config=FakeConfig(disabilitati),
        state=MagicMock(),
        log=MagicMock(),
        device=device,
        matcher=MagicMock(),
        navigator=FakeNavigator(),
    )


# ==============================================================================
# should_run()
# ==============================================================================

class TestShouldRun:
    def test_master_con_device_true(self):
        ctx = _make_ctx(nome="FauMorfeus")
        assert FauMorfeusSetupTask().should_run(ctx) is True

    def test_istanza_ordinaria_false(self):
        ctx = _make_ctx(nome="FAU_02")
        assert FauMorfeusSetupTask().should_run(ctx) is False

    def test_master_senza_device_false(self):
        ctx = _make_ctx(nome="FauMorfeus", device=None)
        assert FauMorfeusSetupTask().should_run(ctx) is False


# ==============================================================================
# run() — tutti gli step in successo
# ==============================================================================

class TestRunTuttoOk:
    def test_tutti_gli_step_invocati_in_ordine(self):
        ctx = _make_ctx()
        chiamate: list[str] = []

        def _fake_grafica(ctx_, log_fn=None):
            chiamate.append("grafica_hq")
            return True

        def _fake_cache(ctx_, log_fn=None):
            chiamate.append("pulizia_cache")
            return True

        fake_boost_task = MagicMock()
        fake_boost_task.should_run.return_value = True
        fake_boost_task.run.side_effect = lambda ctx_: (
            chiamate.append("boost") or TaskResult.ok("boost fatto")
        )

        fake_vip_task = MagicMock()
        fake_vip_task.should_run.return_value = True
        fake_vip_task.run.side_effect = lambda ctx_: (
            chiamate.append("vip") or TaskResult.ok("vip fatto")
        )

        with patch("core.settings_helper.esegui_grafica_hq", side_effect=_fake_grafica), \
             patch("core.settings_helper.esegui_pulizia_cache", side_effect=_fake_cache), \
             patch("tasks.boost.BoostTask", return_value=fake_boost_task), \
             patch("tasks.vip.VipTask", return_value=fake_vip_task):
            result = FauMorfeusSetupTask().run(ctx)

        assert chiamate == ["grafica_hq", "pulizia_cache", "boost", "vip"]
        assert result.success is True
        assert result.data["grafica_hq"] == "ok"
        assert result.data["pulizia_cache"] == "ok"
        assert result.data["boost"] == "ok"
        assert result.data["vip"] == "ok"
        # vai_in_home chiamato prima di ognuno dei 4 step
        assert ctx.navigator.vai_in_home_calls == 4


# ==============================================================================
# run() — best-effort: un fallimento non blocca gli altri
# ==============================================================================

class TestRunBestEffort:
    def test_grafica_hq_fallito_non_blocca_gli_altri(self):
        ctx = _make_ctx()

        fake_boost_task = MagicMock()
        fake_boost_task.should_run.return_value = True
        fake_boost_task.run.return_value = TaskResult.ok("boost fatto")

        fake_vip_task = MagicMock()
        fake_vip_task.should_run.return_value = True
        fake_vip_task.run.return_value = TaskResult.ok("vip fatto")

        with patch("core.settings_helper.esegui_grafica_hq", return_value=False), \
             patch("core.settings_helper.esegui_pulizia_cache", return_value=True), \
             patch("tasks.boost.BoostTask", return_value=fake_boost_task), \
             patch("tasks.vip.VipTask", return_value=fake_vip_task):
            result = FauMorfeusSetupTask().run(ctx)

        assert result.success is False  # aggregato: almeno 1 fallito
        assert result.data["grafica_hq"] == "fallito"
        assert result.data["pulizia_cache"] == "ok"
        assert result.data["boost"] == "ok"
        assert result.data["vip"] == "ok"

    def test_eccezione_in_uno_step_non_blocca_gli_altri(self):
        ctx = _make_ctx()

        fake_boost_task = MagicMock()
        fake_boost_task.should_run.return_value = True
        fake_boost_task.run.return_value = TaskResult.ok("boost fatto")

        fake_vip_task = MagicMock()
        fake_vip_task.should_run.return_value = True
        fake_vip_task.run.return_value = TaskResult.ok("vip fatto")

        with patch("core.settings_helper.esegui_grafica_hq", side_effect=RuntimeError("boom")), \
             patch("core.settings_helper.esegui_pulizia_cache", return_value=True), \
             patch("tasks.boost.BoostTask", return_value=fake_boost_task), \
             patch("tasks.vip.VipTask", return_value=fake_vip_task):
            result = FauMorfeusSetupTask().run(ctx)

        assert result.success is False
        assert "eccezione" in result.data["grafica_hq"]
        assert result.data["pulizia_cache"] == "ok"
        assert result.data["boost"] == "ok"
        assert result.data["vip"] == "ok"


# ==============================================================================
# run() — task_abilitato disabilitato -> skip mirato
# ==============================================================================

class TestRunTaskDisabilitato:
    def test_grafica_hq_disabilitato_skip_senza_chiamare_la_funzione(self):
        ctx = _make_ctx(disabilitati={"grafica_hq"})

        fake_boost_task = MagicMock()
        fake_boost_task.should_run.return_value = True
        fake_boost_task.run.return_value = TaskResult.ok("boost fatto")

        fake_vip_task = MagicMock()
        fake_vip_task.should_run.return_value = True
        fake_vip_task.run.return_value = TaskResult.ok("vip fatto")

        with patch("core.settings_helper.esegui_grafica_hq") as mock_grafica, \
             patch("core.settings_helper.esegui_pulizia_cache", return_value=True), \
             patch("tasks.boost.BoostTask", return_value=fake_boost_task), \
             patch("tasks.vip.VipTask", return_value=fake_vip_task):
            result = FauMorfeusSetupTask().run(ctx)

        mock_grafica.assert_not_called()
        assert result.data["grafica_hq"] == "skip (task disabilitato)"
        assert result.success is True  # skip non conta come fallimento

    def test_boost_should_run_false_skip_senza_chiamare_run(self):
        ctx = _make_ctx()

        fake_boost_task = MagicMock()
        fake_boost_task.should_run.return_value = False

        fake_vip_task = MagicMock()
        fake_vip_task.should_run.return_value = True
        fake_vip_task.run.return_value = TaskResult.ok("vip fatto")

        with patch("core.settings_helper.esegui_grafica_hq", return_value=True), \
             patch("core.settings_helper.esegui_pulizia_cache", return_value=True), \
             patch("tasks.boost.BoostTask", return_value=fake_boost_task), \
             patch("tasks.vip.VipTask", return_value=fake_vip_task):
            result = FauMorfeusSetupTask().run(ctx)

        fake_boost_task.run.assert_not_called()
        assert result.data["boost"] == "skip (should_run=False)"
        assert result.success is True
