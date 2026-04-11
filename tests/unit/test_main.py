"""
tests/unit/test_main.py
Test per main.py V6.

Strategia:
  - Nessun ADB, nessun MuMu — tutto dry-run con FakeDevice stub
  - Test isolati su ogni funzione pubblica/interna di main.py
  - Thread istanza testato con tick_sleep=0 e stop_event settato subito
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

# Import del modulo da testare
import main as M


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_stato():
    """Resetta lo stato globale del motore tra i test."""
    M._engine_stato["istanze"] = {}
    M._engine_stato["storico"] = []
    M._engine_stato["ciclo"]   = 0
    M._engine_stato["stato"]   = "idle"
    yield
    M._engine_stato["istanze"] = {}
    M._engine_stato["storico"] = []


@pytest.fixture()
def tmp_root(tmp_path):
    """Crea struttura minima C:\\doomsday-engine in tmp."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    instances = [
        {"nome": "FAU_00", "indice": 0, "porta": 16384,
         "truppe": 12000, "max_squadre": 4, "layout": 1,
         "lingua": "it", "abilitata": True, "livello": 6,
         "profilo": "full", "fascia_oraria": ""},
        {"nome": "FAU_01", "indice": 1, "porta": 16416,
         "truppe": 9000,  "max_squadre": 3, "layout": 1,
         "lingua": "it", "abilitata": False, "livello": 5,
         "profilo": "light", "fascia_oraria": "22:00-05:00"},
    ]
    (cfg / "instances.json").write_text(json.dumps(instances), encoding="utf-8")
    (tmp_path / "runtime.json").write_text(
        json.dumps({"globali": {"ZAINO_ABILITATO": False}, "overrides": {"mumu": {}}}),
        encoding="utf-8",
    )
    return tmp_path


# ===========================================================================
# _carica_istanze
# ===========================================================================

class TestCaricaIstanze:

    def test_carica_tutte(self, tmp_path, tmp_root, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_root))
        istanze = M._carica_istanze()
        assert len(istanze) == 2
        assert istanze[0]["nome"] == "FAU_00"
        assert istanze[1]["nome"] == "FAU_01"

    def test_filtro_nome(self, tmp_root, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_root))
        istanze = M._carica_istanze(filtro=["FAU_01"])
        assert len(istanze) == 1
        assert istanze[0]["nome"] == "FAU_01"

    def test_filtro_inesistente(self, tmp_root, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_root))
        istanze = M._carica_istanze(filtro=["NONEXIST"])
        assert istanze == []

    def test_file_assente(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        istanze = M._carica_istanze()
        assert istanze == []

    def test_json_non_valido(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "instances.json").write_text("{ non json }", encoding="utf-8")
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        istanze = M._carica_istanze()
        assert istanze == []


# ===========================================================================
# _carica_runtime
# ===========================================================================

class TestCaricaRuntime:

    def test_carica_runtime(self, tmp_root, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_root))
        rt = M._carica_runtime()
        assert rt["globali"]["ZAINO_ABILITATO"] is False

    def test_runtime_assente(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        rt = M._carica_runtime()
        assert rt == {}


# ===========================================================================
# _aggiorna_stato_istanza + _stato_globale
# ===========================================================================

class TestStatoEngine:

    def test_aggiorna_istanza_crea_entry(self):
        M._aggiorna_stato_istanza("FAU_00", {"stato": "running", "porta": 16384})
        assert M._engine_stato["istanze"]["FAU_00"]["stato"] == "running"
        assert M._engine_stato["istanze"]["FAU_00"]["porta"] == 16384

    def test_aggiorna_istanza_update_parziale(self):
        M._aggiorna_stato_istanza("FAU_00", {"stato": "running"})
        M._aggiorna_stato_istanza("FAU_00", {"errori": 3})
        assert M._engine_stato["istanze"]["FAU_00"]["stato"] == "running"
        assert M._engine_stato["istanze"]["FAU_00"]["errori"] == 3

    def test_stato_globale_running(self):
        M._aggiorna_stato_istanza("FAU_00", {"stato": "running"})
        M._aggiorna_stato_istanza("FAU_01", {"stato": "waiting"})
        assert M._stato_globale() == "running"

    def test_stato_globale_waiting(self):
        M._aggiorna_stato_istanza("FAU_00", {"stato": "waiting"})
        assert M._stato_globale() == "waiting"

    def test_stato_globale_idle(self):
        M._aggiorna_stato_istanza("FAU_00", {"stato": "idle"})
        assert M._stato_globale() == "idle"

    def test_stato_globale_vuoto(self):
        assert M._stato_globale() == "idle"


# ===========================================================================
# _aggiungi_storico
# ===========================================================================

class TestStorico:

    def test_aggiungi_e_recupera(self):
        M._aggiungi_storico({"istanza": "FAU_00", "task": "raccolta", "esito": "ok"})
        assert len(M._engine_stato["storico"]) == 1
        assert M._engine_stato["storico"][0]["task"] == "raccolta"

    def test_limite_max_storico(self):
        for i in range(M._MAX_STORICO + 50):
            M._aggiungi_storico({"i": i})
        assert len(M._engine_stato["storico"]) == M._MAX_STORICO

    def test_storico_mantiene_ultimi(self):
        for i in range(M._MAX_STORICO + 10):
            M._aggiungi_storico({"i": i})
        # L'ultimo elemento deve essere l'ultimo inserito
        assert M._engine_stato["storico"][-1]["i"] == M._MAX_STORICO + 9


# ===========================================================================
# _scrivi_status_json
# ===========================================================================

class TestScriviStatusJson:

    def test_scrive_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        M._aggiorna_stato_istanza("FAU_00", {"stato": "running"})
        M._scrivi_status_json()
        path = tmp_path / "engine_status.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == "v6"
        assert "FAU_00" in data["istanze"]
        assert "ts" in data
        assert "uptime_s" in data

    def test_stato_nel_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        M._aggiorna_stato_istanza("FAU_00", {"stato": "waiting"})
        M._scrivi_status_json()
        data = json.loads((tmp_path / "engine_status.json").read_text())
        assert data["stato"] == "waiting"

    def test_scrittura_atomica_no_tmp_rimasto(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "ROOT", str(tmp_path))
        M._scrivi_status_json()
        assert not (tmp_path / "engine_status.json.tmp").exists()


# ===========================================================================
# _build_ctx
# ===========================================================================

class TestBuildCtx:

    def test_ctx_dry_run(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        ctx = M._build_ctx(ist, {}, dry_run=True)
        assert ctx.instance_name == "FAU_00"
        assert ctx.config is not None

    def test_cfg_globali_default(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        ctx = M._build_ctx(ist, {}, dry_run=True)
        assert ctx.config.RIFUGIO_X == 684
        assert ctx.config.RIFUGIO_Y == 532
        assert ctx.config.ZAINO_ABILITATO is True

    def test_cfg_override_runtime(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        rt = {
            "globali": {"ZAINO_ABILITATO": False, "RIFUGIO_X": 700},
            "overrides": {"mumu": {"FAU_00": {"truppe": 8000}}},
        }
        ctx = M._build_ctx(ist, rt, dry_run=True)
        assert ctx.config.ZAINO_ABILITATO is False
        assert ctx.config.RIFUGIO_X == 700
        assert ctx.config.truppe == 8000

    def test_cfg_override_istanza_su_globale(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 9000, "max_squadre": 3, "layout": 2,
               "profilo": "light", "livello": 5, "fascia_oraria": "22:00-05:00"}
        ctx = M._build_ctx(ist, {}, dry_run=True)
        assert ctx.config.profilo == "light"
        assert ctx.config.layout == 2

    def test_task_abilitato(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        rt = {"globali": {"BOOST_ABILITATO": False}}
        ctx = M._build_ctx(ist, rt, dry_run=True)
        assert ctx.config.task_abilitato("boost") is False
        assert ctx.config.task_abilitato("raccolta") is True
        assert ctx.config.task_abilitato("sconosciuto") is True

    def test_log_ctx_non_crasha(self):
        ist = {"nome": "FAU_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        ctx = M._build_ctx(ist, {}, dry_run=True)
        # Non deve sollevare eccezioni
        ctx.log_msg("messaggio di test")
        ctx.log_msg("messaggio %s", "formattato")


# ===========================================================================
# _scheduler_prossimi
# ===========================================================================

class TestSchedulerProssimi:

    def _make_orc(self):
        from core.orchestrator import Orchestrator
        from core.task import Task, TaskContext, TaskResult
        from core.logger import StructuredLogger
        from core.state import InstanceState
        import tempfile, os

        class FakeTask(Task):
            def __init__(self, n, ih=4.0):
                self._n = n
                self.interval_hours = ih
                self.schedule_type = "periodic"
            def name(self): return self._n
            def should_run(self, ctx): return True
            def run(self, ctx): return TaskResult.ok()

        class _FakeCfg:
            def task_abilitato(self, n): return True

        with tempfile.TemporaryDirectory() as td:
            logger = StructuredLogger("TEST", log_dir=td, console=False)
            state  = InstanceState("TEST")

        ctx = TaskContext(
            instance_name="TEST",
            config=_FakeCfg(),
            state=state,
            log=logger,
        )
        orc = Orchestrator(ctx)
        orc.register(FakeTask("raccolta", 4.0), priority=10)
        orc.register(FakeTask("vip", 24.0), priority=20)
        return orc

    def test_task_mai_eseguito_e_adesso(self):
        orc = self._make_orc()
        sched = M._scheduler_prossimi(orc)
        assert "raccolta" in sched
        assert sched["raccolta"] == "adesso"

    def test_task_eseguito_ha_orario(self):
        orc = self._make_orc()
        orc.set_last_run("raccolta", time.time() - 100)  # eseguito 100s fa
        sched = M._scheduler_prossimi(orc)
        # Deve avere un orario futuro (non "adesso")
        assert sched["raccolta"] != "adesso"
        assert len(sched["raccolta"]) == 8  # HH:MM:SS


# ===========================================================================
# Thread istanza — smoke test con FakeTask
# ===========================================================================

class TestThreadIstanza:

    def _fake_tasks_cls(self):
        from core.task import Task, TaskResult

        class FakeRaccolta(Task):
            schedule_type = "periodic"
            interval_hours = 0.0  # sempre dovuto
            def name(self): return "raccolta"
            def should_run(self, ctx): return True
            def run(self, ctx):
                ctx.log("[FakeRaccolta] eseguita")
                return TaskResult.ok("ok raccolta")

        return {"RaccoltaTask": FakeRaccolta}

    def test_thread_si_avvia_e_ferma(self):
        ist = {"nome": "TEST_00", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        stop = threading.Event()
        t = threading.Thread(
            target=M._thread_istanza,
            args=(ist, self._fake_tasks_cls(), True, 0, stop),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)
        stop.set()
        t.join(timeout=5)
        assert not t.is_alive(), "Il thread non si è fermato entro 5s"

    def test_thread_aggiorna_stato(self):
        ist = {"nome": "TEST_01", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        stop = threading.Event()
        t = threading.Thread(
            target=M._thread_istanza,
            args=(ist, self._fake_tasks_cls(), True, 0, stop),
            daemon=True,
        )
        t.start()
        time.sleep(0.5)
        stop.set()
        t.join(timeout=5)
        # Lo stato deve essere stato scritto
        assert "TEST_01" in M._engine_stato["istanze"]

    def test_thread_no_task_disponibili(self):
        """Thread con dict task vuoto: deve avviarsi e fermarsi senza crash."""
        ist = {"nome": "TEST_02", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        stop = threading.Event()
        t = threading.Thread(
            target=M._thread_istanza,
            args=(ist, {}, True, 0, stop),
            daemon=True,
        )
        t.start()
        time.sleep(0.2)
        stop.set()
        t.join(timeout=5)
        assert not t.is_alive()

    def test_thread_task_che_crasha(self):
        """Task che lancia eccezione: il thread non deve morire."""
        from core.task import Task, TaskResult

        class CrashedTask(Task):
            schedule_type = "periodic"
            interval_hours = 0.0
            def name(self): return "raccolta"
            def should_run(self, ctx): return True
            def run(self, ctx): raise RuntimeError("crash intenzionale")

        ist = {"nome": "TEST_03", "indice": 0, "porta": 16384,
               "truppe": 12000, "max_squadre": 4, "layout": 1,
               "profilo": "full", "livello": 6, "fascia_oraria": ""}
        stop = threading.Event()
        t = threading.Thread(
            target=M._thread_istanza,
            args=(ist, {"RaccoltaTask": CrashedTask}, True, 0, stop),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)
        stop.set()
        t.join(timeout=5)
        assert not t.is_alive()
