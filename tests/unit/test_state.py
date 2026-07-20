# ==============================================================================
#  tests/unit/test_state.py
#
#  Unit test per core/state.py
# ==============================================================================

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.state import (
    DAILY_TASK_KEYS,
    DailyTasksState,
    InstanceState,
    MetricsState,
    RifornimentoState,
    BoostState,
    ProduzioneBoostState,
    VipState,
    ArenaState,
    DistrictShowdownState,
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

    def test_provviste_esaurite_default_false(self):
        r = RifornimentoState()
        assert r.provviste_esaurite is False

    def test_should_run_true_per_default(self):
        r = RifornimentoState()
        assert r.should_run() is True

    def test_segna_provviste_esaurite(self):
        r = RifornimentoState()
        r.segna_provviste_esaurite()
        assert r.provviste_esaurite is True
        assert r.should_run() is False

    def test_provviste_esaurite_reset_nuovo_giorno(self):
        r = RifornimentoState(
            provviste_esaurite=True,
            data_riferimento="2020-01-01",
        )
        assert r.should_run() is True  # reset triggera
        assert r.provviste_esaurite is False

    def test_provviste_esaurite_persiste_in_giornata(self):
        r = RifornimentoState()
        r.segna_provviste_esaurite()
        d = r.to_dict()
        r2 = RifornimentoState.from_dict(d)
        assert r2.provviste_esaurite is True
        assert r2.should_run() is False

    def test_reset_forzato_azzera_provviste_esaurite(self):
        r = RifornimentoState()
        r.segna_provviste_esaurite()
        r.reset_forzato()
        assert r.provviste_esaurite is False
        assert r.should_run() is True




# ==============================================================================
# TestBoostState
# ==============================================================================

class TestBoostState:

    def test_defaults(self):
        b = BoostState()
        assert b.tipo is None
        assert b.scadenza is None
        assert b.disponibile is True

    def test_should_run_mai_attivato(self):
        """Senza scadenza → should_run=True (mai attivato)."""
        b = BoostState()
        assert b.should_run() is True

    def test_registra_attivo_8h(self):
        from datetime import datetime, timezone
        b = BoostState()
        now = datetime.now(timezone.utc)
        b.registra_attivo("8h", riferimento=now)
        assert b.tipo == "8h"
        assert b.disponibile is True
        assert b.scadenza is not None
        assert b.is_attivo is True

    def test_registra_attivo_1d(self):
        from datetime import datetime, timezone
        b = BoostState()
        now = datetime.now(timezone.utc)
        b.registra_attivo("1d", riferimento=now)
        assert b.tipo == "1d"
        assert b.is_attivo is True

    def test_should_run_false_quando_attivo(self):
        from datetime import datetime, timezone
        b = BoostState()
        b.registra_attivo("8h", riferimento=datetime.now(timezone.utc))
        assert b.should_run() is False

    def test_should_run_true_quando_scaduto(self):
        from datetime import datetime, timezone, timedelta
        b = BoostState()
        passato = datetime.now(timezone.utc) - timedelta(hours=9)
        b.registra_attivo("8h", riferimento=passato)
        assert b.is_attivo is False
        assert b.should_run() is True

    def test_registra_non_disponibile(self):
        b = BoostState()
        b.registra_non_disponibile()
        assert b.disponibile is False
        assert b.should_run() is True  # riprova sempre

    def test_should_run_true_se_non_disponibile_anche_con_scadenza(self):
        from datetime import datetime, timezone
        b = BoostState()
        b.registra_attivo("8h", riferimento=datetime.now(timezone.utc))
        b.registra_non_disponibile()
        assert b.should_run() is True

    def test_serializzazione_roundtrip(self):
        from datetime import datetime, timezone
        b = BoostState()
        b.registra_attivo("8h", riferimento=datetime.now(timezone.utc))
        d = b.to_dict()
        b2 = BoostState.from_dict(d)
        assert b2.tipo == "8h"
        assert b2.disponibile is True
        assert b2.is_attivo is True

    def test_from_dict_vuoto(self):
        b = BoostState.from_dict({})
        assert b.tipo is None
        assert b.should_run() is True

    def test_log_stato_mai_attivato(self):
        b = BoostState()
        assert "mai attivato" in b.log_stato()

    def test_log_stato_attivo(self):
        from datetime import datetime, timezone
        b = BoostState()
        b.registra_attivo("8h", riferimento=datetime.now(timezone.utc))
        assert "ATTIVO" in b.log_stato()


# ==============================================================================
# TestProduzioneBoostState — estensione BoostTask, boost produzione risorsa
# (Economic Boost, Manage Shelter) — 20/07/2026
# ==============================================================================

class TestProduzioneBoostState:

    _RISORSE = ("pomodoro", "legno", "acciaio", "petrolio")

    def test_defaults_tutti_slot_vuoti(self):
        s = ProduzioneBoostState()
        for r in self._RISORSE:
            slot = s.slot(r)
            assert isinstance(slot, BoostState)
            assert slot.tipo is None
            assert slot.should_run() is True

    def test_slot_ritorna_istanza_corretta(self):
        s = ProduzioneBoostState()
        assert s.slot("pomodoro") is s.pomodoro
        assert s.slot("legno") is s.legno
        assert s.slot("acciaio") is s.acciaio
        assert s.slot("petrolio") is s.petrolio

    def test_should_run_qualcuno_true_di_default(self):
        """Nessuna risorsa mai attivata → tutte due.run() → qualcuno True."""
        s = ProduzioneBoostState()
        assert s.should_run_qualcuno() is True

    def test_should_run_qualcuno_false_se_tutte_attive(self):
        now = datetime.now(timezone.utc)
        s = ProduzioneBoostState()
        for r in self._RISORSE:
            s.slot(r).registra_attivo("8h", riferimento=now)
        assert s.should_run_qualcuno() is False

    def test_should_run_qualcuno_true_se_una_sola_dovuta(self):
        now = datetime.now(timezone.utc)
        s = ProduzioneBoostState()
        for r in self._RISORSE:
            s.slot(r).registra_attivo("8h", riferimento=now)
        s.legno.registra_non_disponibile()   # riprova sempre
        assert s.should_run_qualcuno() is True

    def test_slot_indipendenti_tra_loro(self):
        """Attivare pomodoro non deve alterare gli altri slot."""
        now = datetime.now(timezone.utc)
        s = ProduzioneBoostState()
        s.pomodoro.registra_attivo("8h", riferimento=now)
        assert s.pomodoro.should_run() is False
        assert s.legno.should_run() is True
        assert s.acciaio.should_run() is True
        assert s.petrolio.should_run() is True

    def test_serializzazione_roundtrip(self):
        now = datetime.now(timezone.utc)
        s = ProduzioneBoostState()
        s.pomodoro.registra_attivo("8h", riferimento=now)
        s.acciaio.registra_attivo("1d", riferimento=now)
        d = s.to_dict()
        assert set(d.keys()) == set(self._RISORSE)

        s2 = ProduzioneBoostState.from_dict(d)
        assert s2.pomodoro.tipo == "8h"
        assert s2.acciaio.tipo == "1d"
        assert s2.legno.tipo is None
        assert s2.petrolio.tipo is None

    def test_from_dict_vuoto(self):
        s = ProduzioneBoostState.from_dict({})
        for r in self._RISORSE:
            assert s.slot(r).tipo is None
            assert s.slot(r).should_run() is True

    def test_instance_state_wiring(self):
        """ProduzioneBoostState è raggiungibile da InstanceState e sopravvive
        al round-trip to_dict/from_dict (pattern district_showdown 18/07)."""
        st = InstanceState(instance_name="TEST")
        st.produzione_boost.legno.registra_attivo("8h", riferimento=datetime.now(timezone.utc))
        d = st.to_dict()
        assert "produzione_boost" in d
        st2 = InstanceState.from_dict(d)
        assert st2.produzione_boost.legno.tipo == "8h"
        assert st2.produzione_boost.pomodoro.tipo is None

    def test_instance_state_from_dict_senza_chiave_produzione_boost(self):
        """File di stato pre-esistenti (senza la chiave) → default vuoto,
        nessun crash, nessuna migrazione necessaria."""
        st = InstanceState.from_dict({"instance_name": "OLD"})
        assert st.produzione_boost.pomodoro.should_run() is True


# ==============================================================================
# TestDistrictShowdownState — R-08 follow-up: throttle ven/sab (18/07/2026)
# ==============================================================================

class TestDistrictShowdownState:

    # 2026-07-17=venerdì, 07-18=sabato, 07-19=domenica, 07-13=lunedì, 07-14=martedì

    def _utc(self, y, m, d, h, mi=0):
        return datetime(y, m, d, h, mi, tzinfo=timezone.utc)

    def test_defaults(self):
        s = DistrictShowdownState()
        assert s.ultimo_dadi_esauriti is None

    def test_should_run_mai_confermato(self):
        s = DistrictShowdownState()
        assert s.should_run(self._utc(2026, 7, 17, 10)) is True   # venerdì

    def test_registra_dadi_esauriti(self):
        s = DistrictShowdownState()
        now = self._utc(2026, 7, 17, 10)
        s.registra_dadi_esauriti(riferimento=now)
        assert s.ultimo_dadi_esauriti == now.isoformat()

    def test_should_run_false_subito_dopo_venerdi(self):
        s = DistrictShowdownState()
        s.registra_dadi_esauriti(riferimento=self._utc(2026, 7, 17, 10, 0))
        assert s.should_run(self._utc(2026, 7, 17, 10, 5)) is False  # +5min < 300

    def test_should_run_true_dopo_soglia_venerdi(self):
        s = DistrictShowdownState()
        s.registra_dadi_esauriti(riferimento=self._utc(2026, 7, 17, 10, 0))
        assert s.should_run(self._utc(2026, 7, 17, 15, 0)) is True   # +300min

    def test_should_run_false_subito_dopo_sabato(self):
        s = DistrictShowdownState()
        s.registra_dadi_esauriti(riferimento=self._utc(2026, 7, 18, 10, 0))
        assert s.should_run(self._utc(2026, 7, 18, 10, 5)) is False

    def test_should_run_sempre_true_domenica_anche_subito_dopo(self):
        """Domenica: nessun gate, anche 1 minuto dopo un dadi_esauriti confermato."""
        s = DistrictShowdownState()
        s.registra_dadi_esauriti(riferimento=self._utc(2026, 7, 19, 10, 0))
        assert s.should_run(self._utc(2026, 7, 19, 10, 1)) is True

    def test_should_run_sempre_true_lunedi_anche_subito_dopo(self):
        """Fuori ven/sab/dom (qui: lunedì) → nessun gate (should_run() del task
        a monte già filtra la finestra evento; questo è solo un limite interno)."""
        s = DistrictShowdownState()
        s.registra_dadi_esauriti(riferimento=self._utc(2026, 7, 13, 10, 0))
        assert s.should_run(self._utc(2026, 7, 13, 10, 1)) is True

    def test_should_run_stato_corrotto_conservativo(self):
        s = DistrictShowdownState(ultimo_dadi_esauriti="non-una-data")
        assert s.should_run(self._utc(2026, 7, 17, 10)) is True

    def test_serializzazione_roundtrip(self):
        s = DistrictShowdownState()
        now = self._utc(2026, 7, 17, 10)
        s.registra_dadi_esauriti(riferimento=now)
        d = s.to_dict()
        s2 = DistrictShowdownState.from_dict(d)
        assert s2.ultimo_dadi_esauriti == now.isoformat()

    def test_from_dict_vuoto(self):
        s = DistrictShowdownState.from_dict({})
        assert s.ultimo_dadi_esauriti is None
        assert s.should_run() is True


# ==============================================================================
# TestVipState
# ==============================================================================

class TestVipState:

    def test_defaults(self):
        v = VipState()
        assert v.cass_ritirata is False
        assert v.free_ritirato is False

    def test_should_run_true_per_default(self):
        v = VipState()
        assert v.should_run() is True

    def test_should_run_false_quando_entrambe_ritirate(self):
        v = VipState()
        v.segna_cass()
        v.segna_free()
        assert v.should_run() is False

    def test_should_run_true_solo_cass_ritirata(self):
        v = VipState()
        v.segna_cass()
        assert v.should_run() is True  # free ancora da ritirare

    def test_should_run_true_solo_free_ritirato(self):
        v = VipState()
        v.segna_free()
        assert v.should_run() is True  # cass ancora da ritirare

    def test_segna_completato(self):
        v = VipState()
        v.segna_completato()
        assert v.cass_ritirata is True
        assert v.free_ritirato is True
        assert v.should_run() is False

    def test_reset_nuovo_giorno(self):
        v = VipState(
            cass_ritirata=True,
            free_ritirato=True,
            data_riferimento="2020-01-01",
        )
        assert v.should_run() is True
        assert v.cass_ritirata is False
        assert v.free_ritirato is False

    def test_serializzazione_roundtrip(self):
        v = VipState()
        v.segna_cass()
        d = v.to_dict()
        v2 = VipState.from_dict(d)
        assert v2.cass_ritirata is True
        assert v2.free_ritirato is False
        assert v2.should_run() is True

    def test_from_dict_vuoto(self):
        v = VipState.from_dict({})
        assert v.should_run() is True

    def test_log_stato_completato(self):
        v = VipState()
        v.segna_completato()
        assert "COMPLETATO" in v.log_stato()

    def test_log_stato_parziale(self):
        v = VipState()
        v.segna_cass()
        assert "DA RITIRARE" in v.log_stato()


# ==============================================================================
# TestDailyMissionState — auto-complete daily mission master, due fasi (20/07)
# ==============================================================================

class TestDailyMissionState:

    def _stato(self):
        from core.state import DailyMissionState
        return DailyMissionState()

    def test_defaults(self):
        s = self._stato()
        assert s.trigger_fatto is False
        assert s.trigger_ts is None
        assert s.claim_fatto is False

    def test_should_run_da_fare(self):
        assert self._stato().should_run() is True

    def test_should_run_dopo_solo_trigger(self):
        s = self._stato()
        s.segna_trigger()
        assert s.trigger_fatto is True
        assert s.trigger_ts is not None
        assert s.should_run() is True   # claim ancora da fare

    def test_should_run_false_dopo_trigger_e_claim(self):
        s = self._stato()
        s.segna_trigger()
        s.segna_claim()
        assert s.should_run() is False

    def test_claim_pronto_subito_false(self):
        s = self._stato()
        s.segna_trigger()
        assert s.claim_pronto(3.0) is False   # appena triggerato

    def test_claim_pronto_dopo_attesa(self):
        s = self._stato()
        s.segna_trigger()
        s.trigger_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert s.claim_pronto(3.0) is True

    def test_claim_pronto_false_se_non_triggerato(self):
        assert self._stato().claim_pronto(3.0) is False

    def test_claim_pronto_false_se_gia_claimato(self):
        s = self._stato()
        s.segna_trigger()
        s.segna_claim()
        assert s.claim_pronto(0.0) is False

    def test_segna_non_disponibile_chiude_giornata(self):
        s = self._stato()
        s.segna_non_disponibile()
        assert s.should_run() is False   # niente da fare oggi su questa istanza

    def test_reset_mezzanotte_utc(self):
        s = self._stato()
        s.segna_trigger()
        s.segna_claim()
        # simula giorno precedente
        s.data_riferimento = "2000-01-01"
        assert s.should_run() is True    # reset → riparte
        assert s.trigger_fatto is False
        assert s.claim_fatto is False

    def test_serializzazione_roundtrip(self):
        from core.state import DailyMissionState
        s = self._stato()
        s.segna_trigger()
        d = s.to_dict()
        assert set(d.keys()) == {"trigger_fatto", "trigger_ts", "claim_fatto", "data_riferimento"}
        s2 = DailyMissionState.from_dict(d)
        assert s2.trigger_fatto is True
        assert s2.trigger_ts == s.trigger_ts
        assert s2.claim_fatto is False

    def test_from_dict_vuoto(self):
        from core.state import DailyMissionState
        s = DailyMissionState.from_dict({})
        assert s.trigger_fatto is False
        assert s.should_run() is True

    def test_instance_state_wiring(self):
        st = InstanceState(instance_name="TEST")
        st.daily_mission.segna_trigger()
        d = st.to_dict()
        assert "daily_mission" in d
        st2 = InstanceState.from_dict(d)
        assert st2.daily_mission.trigger_fatto is True

    def test_instance_state_retrocompat_senza_chiave(self):
        st = InstanceState.from_dict({"instance_name": "OLD"})
        assert st.daily_mission.should_run() is True


# ==============================================================================
# TestArenaState
# ==============================================================================

class TestArenaState:

    def test_defaults(self):
        a = ArenaState()
        assert a.esaurite is False

    def test_should_run_true_per_default(self):
        a = ArenaState()
        assert a.should_run() is True

    def test_segna_esaurite(self):
        a = ArenaState()
        a.segna_esaurite()
        assert a.esaurite is True
        assert a.should_run() is False

    def test_reset_nuovo_giorno(self):
        a = ArenaState(
            esaurite=True,
            data_riferimento="2020-01-01",
        )
        assert a.should_run() is True
        assert a.esaurite is False

    def test_serializzazione_roundtrip(self):
        a = ArenaState()
        a.segna_esaurite()
        d = a.to_dict()
        a2 = ArenaState.from_dict(d)
        assert a2.esaurite is True
        assert a2.should_run() is False

    def test_from_dict_vuoto(self):
        a = ArenaState.from_dict({})
        assert a.should_run() is True

    def test_log_stato_esaurite(self):
        a = ArenaState()
        a.segna_esaurite()
        assert "ESAURITE" in a.log_stato()

    def test_log_stato_disponibili(self):
        a = ArenaState()
        assert "disponibili" in a.log_stato()

    def test_reset_ripristina_should_run(self):
        a = ArenaState()
        a.segna_esaurite()
        assert a.should_run() is False
        # Simula nuovo giorno
        a.data_riferimento = "2020-01-01"
        assert a.should_run() is True

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
        s.district_showdown.registra_dadi_esauriti(
            riferimento=datetime(2026, 7, 17, 10, tzinfo=timezone.utc)
        )
        d = s.to_dict()
        s2 = InstanceState.from_dict(d)
        assert s2.instance_name == "FAU_01"
        assert s2.rifornimento.spedizioni_oggi == 1
        assert s2.daily_tasks.is_completato("boost")
        assert s2.metrics.cicli_completati == 1
        assert s2.district_showdown.ultimo_dadi_esauriti == "2026-07-17T10:00:00+00:00"

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
