# ==============================================================================
#  tests/unit/test_state.py
#
#  Unit test per core/state.py
# ==============================================================================

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.state import (
    DAILY_TASK_KEYS,
    DailyTasksState,
    InstanceState,
    MetricsState,
    RifornimentoState,
    _today_utc,
)


# ==============================================================================
# TestRifornimentoState
# ==============================================================================

class TestRifornimentoState:

    def test_defaults(self):
        r = RifornimentoState()
        assert r.spedizioni_oggi == 0
        assert r.quota_max == 5
        assert r.ultima_spedizione is None
        assert not r.quota_esaurita

    def test_registra_spedizione(self):
        r = RifornimentoState()
        r.registra_spedizione()
        assert r.spedizioni_oggi == 1
        assert r.ultima_spedizione is not None

    def test_quota_esaurita_dopo_max(self):
        r = RifornimentoState(quota_max=3)
        for _ in range(3):
            r.registra_spedizione()
        assert r.quota_esaurita is True
        assert r.spedizioni_rimaste == 0

    def test_spedizioni_rimaste(self):
        r = RifornimentoState(quota_max=5)
        r.registra_spedizione()
        r.registra_spedizione()
        assert r.spedizioni_rimaste == 3

    def test_reset_automatico_nuovo_giorno(self):
        r = RifornimentoState(
            spedizioni_oggi=5,
            quota_max=5,
            data_riferimento="2020-01-01",  # data passata
        )
        # Accedere alla proprietà triggera il reset
        assert not r.quota_esaurita
        assert r.spedizioni_oggi == 0

    def test_reset_forzato(self):
        r = RifornimentoState(spedizioni_oggi=4, quota_max=5)
        r.reset_forzato()
        assert r.spedizioni_oggi == 0
        assert r.ultima_spedizione is None

    def test_serializzazione_roundtrip(self):
        r = RifornimentoState(spedizioni_oggi=3, quota_max=5)
        r.registra_spedizione()
        d = r.to_dict()
        r2 = RifornimentoState.from_dict(d)
        assert r2.spedizioni_oggi == r.spedizioni_oggi
        assert r2.quota_max == r.quota_max
        assert r2.ultima_spedizione == r.ultima_spedizione

    def test_from_dict_valori_mancanti(self):
        """from_dict con dict vuoto usa i valori di default."""
        r = RifornimentoState.from_dict({})
        assert r.spedizioni_oggi == 0
        assert r.quota_max == 5


# ==============================================================================
# TestDailyTasksState
# ==============================================================================

class TestDailyTasksState:

    def test_defaults_tutti_false(self):
        dt = DailyTasksState()
        for key in DAILY_TASK_KEYS:
            assert not dt.is_completato(key)

    def test_segna_completato(self):
        dt = DailyTasksState()
        dt.segna_completato("boost")
        assert dt.is_completato("boost")
        assert dt.timestamps["boost"] is not None

    def test_task_pendenti_tutti(self):
        dt = DailyTasksState()
        pendenti = dt.task_pendenti()
        assert set(pendenti) == DAILY_TASK_KEYS

    def test_task_pendenti_con_filtro(self):
        dt = DailyTasksState()
        dt.segna_completato("boost")
        dt.segna_completato("vip")
        pendenti = dt.task_pendenti(task_abilitati={"boost", "vip", "store"})
        assert "boost" not in pendenti
        assert "vip" not in pendenti
        assert "store" in pendenti

    def test_tutti_completati(self):
        dt = DailyTasksState()
        assert not dt.tutti_completati
        for key in DAILY_TASK_KEYS:
            dt.segna_completato(key)
        assert dt.tutti_completati

    def test_reset_automatico_nuovo_giorno(self):
        dt = DailyTasksState(data_riferimento="2020-01-01")
        # Segna manualmente prima del reset
        dt.completati["boost"] = True
        # Accedere a is_completato triggera reset
        assert not dt.is_completato("boost")

    def test_chiavi_canoniche_sempre_presenti(self):
        """from_dict con dict parziale integra le chiavi mancanti."""
        dt = DailyTasksState.from_dict({
            "data_riferimento": _today_utc(),
            "completati": {"boost": True},
            "timestamps": {"boost": "2024-01-01T00:00:00+00:00"},
        })
        for key in DAILY_TASK_KEYS:
            assert key in dt.completati
            assert key in dt.timestamps

    def test_serializzazione_roundtrip(self):
        dt = DailyTasksState()
        dt.segna_completato("arena")
        dt.segna_completato("store")
        d = dt.to_dict()
        dt2 = DailyTasksState.from_dict(d)
        assert dt2.is_completato("arena")
        assert dt2.is_completato("store")
        assert not dt2.is_completato("boost")


# ==============================================================================
# TestMetricsState
# ==============================================================================

class TestMetricsState:

    def test_defaults(self):
        m = MetricsState()
        assert m.pomodoro_per_ora == 0.0
        assert m.marce_inviate_totali == 0
        assert m.cicli_completati == 0
        assert m.errori_totali == 0

    def test_aggiorna_risorse(self):
        m = MetricsState()
        m.aggiorna_risorse(pomodoro=12.5, legno=8.0)
        assert m.pomodoro_per_ora == 12.5
        assert m.legno_per_ora == 8.0
        assert m.ultimo_aggiornamento is not None

    def test_incrementa_contatori(self):
        m = MetricsState()
        m.incrementa_marce(3)
        m.incrementa_cicli()
        m.incrementa_errori()
        assert m.marce_inviate_totali == 3
        assert m.cicli_completati == 1
        assert m.errori_totali == 1

    def test_serializzazione_roundtrip(self):
        m = MetricsState()
        m.aggiorna_risorse(pomodoro=5.5, legno=3.2, petrolio=1.1)
        m.incrementa_marce(10)
        d = m.to_dict()
        m2 = MetricsState.from_dict(d)
        assert m2.pomodoro_per_ora == 5.5
        assert m2.marce_inviate_totali == 10

    def test_from_dict_valori_mancanti(self):
        m = MetricsState.from_dict({})
        assert m.pomodoro_per_ora == 0.0
        assert m.errori_totali == 0


# ==============================================================================
# TestInstanceState
# ==============================================================================

class TestInstanceState:

    def test_costruzione_default(self):
        s = InstanceState("FAU_00")
        assert s.instance_name == "FAU_00"
        assert not s.attivo
        assert s.ultimo_errore is None

    def test_segna_avvio(self):
        s = InstanceState("FAU_00")
        s.segna_avvio()
        assert s.attivo is True
        assert s.ultimo_avvio is not None

    def test_segna_errore(self):
        s = InstanceState("FAU_00")
        s.segna_errore("timeout ADB")
        assert "timeout ADB" in s.ultimo_errore
        assert s.metrics.errori_totali == 1

    def test_repr(self):
        s = InstanceState("FAU_03")
        r = repr(s)
        assert "FAU_03" in r
        assert "rif=" in r

    def test_serializzazione_roundtrip(self):
        s = InstanceState("FAU_01")
        s.rifornimento.registra_spedizione()
        s.daily_tasks.segna_completato("boost")
        s.metrics.incrementa_cicli()
        d = s.to_dict()
        s2 = InstanceState.from_dict(d)
        assert s2.instance_name == "FAU_01"
        assert s2.rifornimento.spedizioni_oggi == 1
        assert s2.daily_tasks.is_completato("boost")
        assert s2.metrics.cicli_completati == 1

    def test_from_dict_valori_mancanti(self):
        """from_dict con dict minimo non crasha."""
        s = InstanceState.from_dict({"instance_name": "FAU_X"})
        assert s.instance_name == "FAU_X"
        assert s.rifornimento.spedizioni_oggi == 0

    # ── Test persistenza su disco ─────────────────────────────────────────────

    def test_save_e_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = InstanceState("FAU_00")
            s.rifornimento.registra_spedizione()
            s.rifornimento.registra_spedizione()
            s.daily_tasks.segna_completato("arena")
            s.metrics.aggiorna_risorse(pomodoro=9.9)
            s.save(tmpdir)

            s2 = InstanceState.load("FAU_00", tmpdir)
            assert s2.rifornimento.spedizioni_oggi == 2
            assert s2.daily_tasks.is_completato("arena")
            assert s2.metrics.pomodoro_per_ora == 9.9

    def test_load_file_non_esistente(self):
        """Se il file non esiste, load ritorna stato fresco."""
        with tempfile.TemporaryDirectory() as tmpdir:
            s = InstanceState.load("FAU_NUOVO", tmpdir)
            assert s.instance_name == "FAU_NUOVO"
            assert s.rifornimento.spedizioni_oggi == 0

    def test_load_file_corrotto(self):
        """Se il file JSON è corrotto, load ritorna stato fresco senza crashare."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "FAU_00.json"
            path.write_text("{ INVALID JSON !!!", encoding="utf-8")
            s = InstanceState.load("FAU_00", tmpdir)
            assert s.instance_name == "FAU_00"
            assert s.rifornimento.spedizioni_oggi == 0

    def test_save_crea_directory(self):
        """save() crea la directory state/ se non esiste."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested", "state")
            s = InstanceState("FAU_05")
            s.save(subdir)
            assert os.path.exists(os.path.join(subdir, "FAU_05.json"))

    def test_json_leggibile(self):
        """Il file salvato è JSON valido e leggibile a mano."""
        with tempfile.TemporaryDirectory() as tmpdir:
            s = InstanceState("FAU_02")
            s.daily_tasks.segna_completato("boost")
            s.save(tmpdir)
            path = Path(tmpdir) / "FAU_02.json"
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["instance_name"] == "FAU_02"
            assert data["daily_tasks"]["completati"]["boost"] is True
