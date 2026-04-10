# ==============================================================================
#  tests/unit/test_scheduler.py
#
#  Unit test per core/scheduler.py
# ==============================================================================

import time
import pytest

from core.scheduler import TaskEntry, TaskScheduler


# ==============================================================================
# Helpers
# ==============================================================================

def make_scheduler(fascia=None) -> TaskScheduler:
    return TaskScheduler(fascia_oraria=fascia)


def register_daily(s: TaskScheduler, name: str, priority: int = 50) -> None:
    s.register(name, kind="daily", priority=priority)


def register_periodic(
    s: TaskScheduler, name: str, interval_h: float = 4.0, priority: int = 50
) -> None:
    s.register(name, kind="periodic", interval_h=interval_h, priority=priority)


# ==============================================================================
# TestTaskEntry
# ==============================================================================

class TestTaskEntry:

    def test_elapsed_mai_eseguito(self):
        e = TaskEntry("boost", "daily")
        assert e.elapsed_secs() == float("inf")

    def test_elapsed_dopo_mark_done(self):
        e = TaskEntry("boost", "daily")
        e.mark_done()
        assert e.elapsed_secs() < 1.0

    def test_mark_done_aggiorna_ts(self):
        e = TaskEntry("x", "periodic")
        assert e.last_run_ts is None
        e.mark_done()
        assert e.last_run_ts is not None

    def test_repr(self):
        e = TaskEntry("boost", "daily", enabled=True)
        r = repr(e)
        assert "boost" in r
        assert "daily" in r


# ==============================================================================
# TestTaskScheduler — registrazione
# ==============================================================================

class TestTaskSchedulerRegistration:

    def test_register_daily(self):
        s = make_scheduler()
        register_daily(s, "boost")
        assert "boost" in s.registered_names()
        assert s.entry("boost").kind == "daily"

    def test_register_periodic(self):
        s = make_scheduler()
        register_periodic(s, "raccolta", interval_h=0.5)
        e = s.entry("raccolta")
        assert e.kind == "periodic"
        assert e.interval_secs == 0.5 * 3600

    def test_register_kind_non_valido_solleva(self):
        s = make_scheduler()
        with pytest.raises(ValueError, match="kind"):
            s.register("x", kind="mensile")

    def test_register_many(self):
        s = make_scheduler()
        s.register_many([
            {"name": "boost",    "kind": "daily",    "priority": 10},
            {"name": "raccolta", "kind": "periodic", "interval_h": 0.5},
        ])
        assert "boost" in s.registered_names()
        assert "raccolta" in s.registered_names()

    def test_set_enabled_false(self):
        s = make_scheduler()
        register_daily(s, "boost")
        s.set_enabled("boost", False)
        assert not s.entry("boost").enabled

    def test_set_enabled_task_inesistente_non_crasha(self):
        s = make_scheduler()
        s.set_enabled("inesistente", False)  # deve passare silenziosamente

    def test_entries_lista(self):
        s = make_scheduler()
        register_daily(s, "a")
        register_daily(s, "b")
        assert len(s.entries()) == 2

    def test_repr(self):
        s = make_scheduler(fascia=(8, 22))
        register_daily(s, "boost")
        r = repr(s)
        assert "TaskScheduler" in r
        assert "tasks=1" in r


# ==============================================================================
# TestInFascia
# ==============================================================================

class TestInFascia:

    def test_nessuna_fascia_sempre_true(self):
        s = make_scheduler(fascia=None)
        for h in range(24):
            assert s.in_fascia(h) is True

    def test_fascia_normale(self):
        s = make_scheduler(fascia=(8, 22))
        assert s.in_fascia(8)  is True
        assert s.in_fascia(15) is True
        assert s.in_fascia(21) is True
        assert s.in_fascia(22) is False  # end esclusivo
        assert s.in_fascia(7)  is False
        assert s.in_fascia(0)  is False

    def test_fascia_mezzanotte(self):
        # 22→6: attivo dalle 22 alle 6 del mattino
        s = make_scheduler(fascia=(22, 6))
        assert s.in_fascia(22) is True
        assert s.in_fascia(23) is True
        assert s.in_fascia(0)  is True
        assert s.in_fascia(5)  is True
        assert s.in_fascia(6)  is False
        assert s.in_fascia(12) is False

    def test_fascia_ora_singola(self):
        s = make_scheduler(fascia=(10, 11))
        assert s.in_fascia(10) is True
        assert s.in_fascia(11) is False
        assert s.in_fascia(9)  is False


# ==============================================================================
# TestShouldRun — daily
# ==============================================================================

class TestShouldRunDaily:

    def test_daily_non_completato_pronto(self):
        s = make_scheduler()
        register_daily(s, "boost")
        assert s.should_run("boost", daily_completed={"boost": False})

    def test_daily_completato_non_pronto(self):
        s = make_scheduler()
        register_daily(s, "boost")
        assert not s.should_run("boost", daily_completed={"boost": True})

    def test_daily_senza_completed_dict_pronto(self):
        s = make_scheduler()
        register_daily(s, "boost")
        assert s.should_run("boost", daily_completed=None)

    def test_daily_disabilitato_non_pronto(self):
        s = make_scheduler()
        register_daily(s, "boost")
        s.set_enabled("boost", False)
        assert not s.should_run("boost", daily_completed={"boost": False})

    def test_daily_fuori_fascia_non_pronto(self):
        s = make_scheduler(fascia=(8, 22))
        register_daily(s, "boost")
        # ora=3 → fuori fascia
        assert not s.should_run("boost", daily_completed={"boost": False}, utc_hour=3)

    def test_daily_in_fascia_pronto(self):
        s = make_scheduler(fascia=(8, 22))
        register_daily(s, "boost")
        assert s.should_run("boost", daily_completed={"boost": False}, utc_hour=10)

    def test_task_non_registrato_false(self):
        s = make_scheduler()
        assert not s.should_run("inesistente")


# ==============================================================================
# TestShouldRun — periodic
# ==============================================================================

class TestShouldRunPeriodic:

    def test_periodic_mai_eseguito_pronto(self):
        s = make_scheduler()
        register_periodic(s, "raccolta", interval_h=4.0)
        assert s.should_run("raccolta")

    def test_periodic_appena_eseguito_non_pronto(self):
        s = make_scheduler()
        register_periodic(s, "raccolta", interval_h=4.0)
        s.mark_done("raccolta")
        # Appena eseguito → elapsed ~0 < 4h
        assert not s.should_run("raccolta")

    def test_periodic_intervallo_zero_sempre_pronto(self):
        s = make_scheduler()
        register_periodic(s, "x", interval_h=0.0)
        s.mark_done("x")
        assert s.should_run("x")

    def test_periodic_disabilitato_non_pronto(self):
        s = make_scheduler()
        register_periodic(s, "raccolta", interval_h=4.0)
        s.set_enabled("raccolta", False)
        assert not s.should_run("raccolta")


# ==============================================================================
# TestNextTasks
# ==============================================================================

class TestNextTasks:

    def test_ordine_per_priority(self):
        s = make_scheduler()
        register_daily(s, "arena",   priority=30)
        register_daily(s, "boost",   priority=10)
        register_daily(s, "raccolta", priority=20)

        tasks = s.next_tasks(daily_completed={})
        assert tasks == ["boost", "raccolta", "arena"]

    def test_solo_task_pronti(self):
        s = make_scheduler()
        register_daily(s, "boost")
        register_daily(s, "arena")

        # "boost" già completato, "arena" no
        tasks = s.next_tasks(daily_completed={"boost": True, "arena": False})
        assert "boost" not in tasks
        assert "arena" in tasks

    def test_mix_daily_e_periodic(self):
        s = make_scheduler()
        register_daily(s, "boost", priority=10)
        register_periodic(s, "raccolta", interval_h=0.0, priority=20)

        tasks = s.next_tasks(daily_completed={"boost": False})
        assert "boost" in tasks
        assert "raccolta" in tasks
        assert tasks.index("boost") < tasks.index("raccolta")

    def test_nessun_task_pronto(self):
        s = make_scheduler()
        register_daily(s, "boost")
        tasks = s.next_tasks(daily_completed={"boost": True})
        assert tasks == []

    def test_lista_vuota_se_nessun_task_registrato(self):
        s = make_scheduler()
        assert s.next_tasks() == []

    def test_fuori_fascia_nessun_task(self):
        s = make_scheduler(fascia=(8, 22))
        register_daily(s, "boost")
        register_periodic(s, "raccolta", interval_h=0.0)
        tasks = s.next_tasks(daily_completed={}, utc_hour=3)
        assert tasks == []

    def test_task_disabilitato_escluso(self):
        s = make_scheduler()
        register_daily(s, "boost")
        register_daily(s, "vip")
        s.set_enabled("boost", False)
        tasks = s.next_tasks(daily_completed={})
        assert "boost" not in tasks
        assert "vip" in tasks


# ==============================================================================
# TestMarkDone
# ==============================================================================

class TestMarkDone:

    def test_mark_done_aggiorna_ts(self):
        s = make_scheduler()
        register_periodic(s, "raccolta", interval_h=4.0)
        assert s.entry("raccolta").last_run_ts is None
        s.mark_done("raccolta")
        assert s.entry("raccolta").last_run_ts is not None

    def test_mark_done_task_inesistente_non_crasha(self):
        s = make_scheduler()
        s.mark_done("inesistente")  # silenzioso

    def test_mark_all_done(self):
        s = make_scheduler()
        register_periodic(s, "a", interval_h=4.0)
        register_periodic(s, "b", interval_h=4.0)
        s.mark_all_done(["a", "b"])
        assert s.entry("a").last_run_ts is not None
        assert s.entry("b").last_run_ts is not None

    def test_periodic_non_pronto_dopo_mark_done(self):
        s = make_scheduler()
        register_periodic(s, "store", interval_h=4.0)
        s.mark_done("store")
        assert not s.should_run("store")
