# ==============================================================================
#  tests/tasks/test_rifornimento.py — Step 20
#  Tutti i test usano FakeDevice + FakeMatcher — zero ADB reale.
# ==============================================================================

import time
import pytest
from collections import deque
from unittest.mock import patch, MagicMock

from core.device import FakeDevice
from core.navigator import GameNavigator
from core.task import TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from tasks.rifornimento import (
    RifornimentoTask,
    _cfg,
    _aggiorna_coda,
    _attesa_prima_spedizione,
    _attesa_ultima_spedizione,
    _seleziona_risorsa,
    _build_risorse_config,
    _DEFAULTS,
)


# ------------------------------------------------------------------------------
# Fixture base
# ------------------------------------------------------------------------------

class _DictCfg:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, k, default=None):
        return self._d.get(k, default)
    def task_abilitato(self, n):
        return self._d.get(f"task_{n}", True)
    def __getattr__(self, k):
        return self._d.get(k, None)

class _FakeNavigator:
    """Navigator che registra le chiamate senza ADB reale."""
    def __init__(self):
        self.home_calls = 0
        self.mappa_calls = 0
    def vai_in_home(self) -> bool:
        self.home_calls += 1
        return True
    def vai_in_mappa(self) -> bool:
        self.mappa_calls += 1
        return True
    def tap_barra(self, ctx, voce): return True


def make_ctx(config_overrides: dict | None = None) -> TaskContext:
    from core.state import InstanceState
    device = FakeDevice()
    matcher = FakeMatcher()
    navigator = _FakeNavigator()
    return TaskContext(
        instance_name="FAU_00",
        config=_DictCfg(config_overrides or {}),
        state=InstanceState("FAU_00"),
        log=None,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


def ctx_abilitato(**overrides) -> TaskContext:
    """TaskContext con rifornimento abilitato e DOOMS_ACCOUNT configurato."""
    base = {
        "RIFORNIMENTO_MAPPA_ABILITATO": True,
        "DOOMS_ACCOUNT": "MioRifugio",
        "RIFORNIMENTO_QTA_POMODORO": 1_000_000,
        "RIFORNIMENTO_QTA_LEGNO":    1_000_000,
        "RIFORNIMENTO_QTA_ACCIAIO":  0,
        "RIFORNIMENTO_QTA_PETROLIO": 0,
        "RIFORNIMENTO_CAMPO_ABILITATO":    True,
        "RIFORNIMENTO_LEGNO_ABILITATO":    True,
        "RIFORNIMENTO_ACCIAIO_ABILITATO":  False,
        "RIFORNIMENTO_PETROLIO_ABILITATO": False,
        "RIFORNIMENTO_SOGLIA_CAMPO_M":    5.0,
        "RIFORNIMENTO_SOGLIA_LEGNO_M":    5.0,
        "RIFORNIMENTO_SOGLIA_ACCIAIO_M":  3.5,
        "RIFORNIMENTO_SOGLIA_PETROLIO_M": 2.5,
        "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 3,
        "TEMPLATE_RESOURCE_SUPPLY": "pin/btn_resource_supply_map.png",
        "TEMPLATE_RESOURCE_SUPPLY_SOGLIA": 0.75,
        "MARGINE_ATTESA": 0,  # zero nei test per non aspettare
    }
    base.update(overrides)
    return make_ctx(base)


DEP_OK = {
    "pomodoro": 10_000_000.0,
    "legno":    10_000_000.0,
    "acciaio":  0.0,
    "petrolio": 0.0,
}

DEP_SOTTO = {
    "pomodoro": 1_000_000.0,  # sotto soglia 5M
    "legno":    1_000_000.0,  # sotto soglia 5M
    "acciaio":  0.0,
    "petrolio": 0.0,
}


# ==============================================================================
# 1. Proprietà del task
# ==============================================================================

class TestRifornimentoProperties:

    def test_name(self):
        assert RifornimentoTask().name() == "rifornimento"

    def test_schedule_type(self):
        task = RifornimentoTask()
        st = task.schedule_type() if callable(task.schedule_type) else task.schedule_type
        assert st == "periodic"

    def test_interval_hours(self):
        task = RifornimentoTask()
        ih = task.interval_hours() if callable(task.interval_hours) else task.interval_hours
        assert ih == 4.0


# ==============================================================================
# 2. _cfg — lettura config con fallback
# ==============================================================================

class TestCfg:

    def test_default_disabilitato(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RIFORNIMENTO_MAPPA_ABILITATO") is False

    def test_override_abilitato(self):
        ctx = make_ctx({"RIFORNIMENTO_MAPPA_ABILITATO": True})
        assert _cfg(ctx, "RIFORNIMENTO_MAPPA_ABILITATO") is True

    def test_default_rifugio_x(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RIFUGIO_X") == 684

    def test_default_rifugio_y(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RIFUGIO_Y") == 532

    def test_default_soglia_campo(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RIFORNIMENTO_SOGLIA_CAMPO_M") == 5.0

    def test_default_acciaio_disabilitato(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RIFORNIMENTO_ACCIAIO_ABILITATO") is False

    def test_override_max_spedizioni(self):
        ctx = make_ctx({"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 10})
        assert _cfg(ctx, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO") == 10


# ==============================================================================
# 3. Logica coda_volo
# ==============================================================================

class TestCodaVolo:

    def test_aggiorna_coda_rimuove_scadute(self):
        coda = deque()
        coda.append((time.time() - 100, 60.0))  # già scaduta
        coda.append((time.time() - 10,  120.0)) # ancora in volo
        _aggiorna_coda(coda)
        assert len(coda) == 1

    def test_aggiorna_coda_vuota(self):
        coda = deque()
        _aggiorna_coda(coda)
        assert len(coda) == 0

    def test_aggiorna_coda_nessuna_scaduta(self):
        coda = deque()
        coda.append((time.time(), 300.0))
        _aggiorna_coda(coda)
        assert len(coda) == 1

    def test_attesa_prima_coda_vuota(self):
        assert _attesa_prima_spedizione(deque(), margine=0) == 0.0

    def test_attesa_prima_scaduta(self):
        coda = deque()
        coda.append((time.time() - 200, 100.0))  # già rientrata
        # (time.time() - ts) >= eta_ar → residuo negativo → max(0, negativo) = 0
        assert _attesa_prima_spedizione(coda, margine=0) == 0.0

    def test_attesa_prima_in_volo(self):
        coda = deque()
        coda.append((time.time(), 60.0))  # partita adesso, ETA 60s
        att = _attesa_prima_spedizione(coda, margine=0)
        assert att > 50.0  # circa 60s

    def test_attesa_ultima_coda_vuota(self):
        assert _attesa_ultima_spedizione(deque(), margine=0) == 0.0

    def test_attesa_ultima_ultima_in_volo(self):
        coda = deque()
        coda.append((time.time() - 10, 60.0))   # prima
        coda.append((time.time(),       120.0))  # ultima, 120s A/R
        att = _attesa_ultima_spedizione(coda, margine=0)
        assert att > 100.0


# ==============================================================================
# 4. _seleziona_risorsa
# ==============================================================================

class TestSelezionaRisorsa:

    def test_seleziona_sopra_soglia(self):
        risorse_reali  = {"pomodoro": 10_000_000.0, "legno": 10_000_000.0}
        risorse_config = {"pomodoro": 1_000_000, "legno": 1_000_000}
        soglie = {"pomodoro": 5.0, "legno": 5.0}
        r, _ = _seleziona_risorsa(risorse_reali, risorse_config, soglie, 0)
        assert r == "pomodoro"

    def test_nessuna_sotto_soglia(self):
        risorse_reali  = {"pomodoro": 1_000_000.0, "legno": 1_000_000.0}
        risorse_config = {"pomodoro": 1_000_000, "legno": 1_000_000}
        soglie = {"pomodoro": 5.0, "legno": 5.0}
        r, _ = _seleziona_risorsa(risorse_reali, risorse_config, soglie, 0)
        assert r is None

    def test_round_robin(self):
        risorse_reali  = {"pomodoro": 10_000_000.0, "legno": 10_000_000.0}
        risorse_config = {"pomodoro": 1_000_000, "legno": 1_000_000}
        soglie = {"pomodoro": 5.0, "legno": 5.0}
        r, nuovo_idx = _seleziona_risorsa(risorse_reali, risorse_config, soglie, 0)
        assert r == "pomodoro"
        assert nuovo_idx == 1
        r2, nuovo_idx2 = _seleziona_risorsa(risorse_reali, risorse_config, soglie, nuovo_idx)
        assert r2 == "legno"

    def test_skip_sotto_soglia_e_prende_successiva(self):
        risorse_reali  = {"pomodoro": 1_000_000.0, "legno": 10_000_000.0}
        risorse_config = {"pomodoro": 1_000_000, "legno": 1_000_000}
        soglie = {"pomodoro": 5.0, "legno": 5.0}
        r, _ = _seleziona_risorsa(risorse_reali, risorse_config, soglie, 0)
        assert r == "legno"


# ==============================================================================
# 5. _build_risorse_config
# ==============================================================================

class TestBuildRisorseConfig:

    def test_acciaio_escluso_per_default(self):
        ctx = make_ctx()
        rc, soglie, ab = _build_risorse_config(ctx)
        assert "acciaio" not in rc

    def test_pomodoro_incluso_per_default(self):
        ctx = make_ctx()
        rc, _, _ = _build_risorse_config(ctx)
        assert "pomodoro" in rc

    def test_qta_zero_esclude_risorsa(self):
        ctx = make_ctx({"RIFORNIMENTO_QTA_POMODORO": 0})
        rc, _, _ = _build_risorse_config(ctx)
        assert "pomodoro" not in rc

    def test_acciaio_incluso_se_abilitato(self):
        ctx = make_ctx({"RIFORNIMENTO_ACCIAIO_ABILITATO": True,
                        "RIFORNIMENTO_QTA_ACCIAIO": 500_000})
        rc, _, _ = _build_risorse_config(ctx)
        assert "acciaio" in rc

    def test_soglie_corrette(self):
        ctx = make_ctx({"RIFORNIMENTO_SOGLIA_CAMPO_M": 7.5})
        _, soglie, _ = _build_risorse_config(ctx)
        assert soglie["pomodoro"] == 7.5


# ==============================================================================
# 6. RifornimentoTask.run — disabilitato
# ==============================================================================

class TestRifornimentoDisabilitato:

    def test_disabilitato_skip(self):
        ctx = make_ctx({"RIFORNIMENTO_MAPPA_ABILITATO": False})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK)
        assert result.success is True
        assert result.message == "disabilitato"
        assert len(ctx.device.taps) == 0

    def test_disabilitato_data(self):
        ctx = make_ctx({"RIFORNIMENTO_MAPPA_ABILITATO": False})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK)
        assert result.data["spedizioni"] == 0


# ==============================================================================
# 7. RifornimentoTask.run — DOOMS_ACCOUNT mancante
# ==============================================================================

class TestRifornimentoNoAccount:

    def test_no_account_fallisce(self):
        ctx = make_ctx({"RIFORNIMENTO_MAPPA_ABILITATO": True,
                        "DOOMS_ACCOUNT": ""})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK)
        assert result.success is False
        assert "DOOMS_ACCOUNT" in result.message

    def test_no_account_nessun_tap(self):
        ctx = make_ctx({"RIFORNIMENTO_MAPPA_ABILITATO": True,
                        "DOOMS_ACCOUNT": ""})
        RifornimentoTask().run(ctx, deposito=DEP_OK)
        assert len(ctx.device.taps) == 0


# ==============================================================================
# 8. RifornimentoTask.run — deposito non fornito
# ==============================================================================

class TestRifornimentoDeposizoNone:

    def test_deposito_none_fallisce(self):
        ctx = ctx_abilitato()
        result = RifornimentoTask().run(ctx, deposito=None)
        assert result.success is False
        assert "deposito" in result.message


# ==============================================================================
# 9. RifornimentoTask.run — nessuna risorsa configurata
# ==============================================================================

class TestRifornimentoNessunaRisorsa:

    def test_qta_tutte_zero(self):
        ctx = ctx_abilitato(**{
            "RIFORNIMENTO_QTA_POMODORO": 0,
            "RIFORNIMENTO_QTA_LEGNO":    0,
            "RIFORNIMENTO_QTA_ACCIAIO":  0,
            "RIFORNIMENTO_QTA_PETROLIO": 0,
        })
        result = RifornimentoTask().run(ctx, deposito=DEP_OK)
        assert result.success is True
        assert "configurata" in result.message


# ==============================================================================
# 10. RifornimentoTask.run — slot == 0 → stop immediato
# ==============================================================================

class TestRifornimentoSlotZero:

    @patch("tasks.rifornimento.time.sleep")
    def test_slot_zero_stop(self, mock_sleep):
        ctx = ctx_abilitato()
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=0)
        assert result.data["spedizioni"] == 0

    @patch("tasks.rifornimento.time.sleep")
    def test_slot_zero_home_key(self, mock_sleep):
        ctx = ctx_abilitato()
        RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=0)
        # Il ritorno HOME avviene via navigator.vai_in_home() — non via device.key()
        assert ctx.navigator.home_calls >= 1


# ==============================================================================
# 11. RifornimentoTask.run — risorse sotto soglia → stop dopo mappa
# ==============================================================================

class TestRifornimentoSottoSoglia:

    @patch("tasks.rifornimento.time.sleep")
    def test_risorse_sotto_soglia_zero_spedizioni(self, mock_sleep):
        ctx = ctx_abilitato()
        result = RifornimentoTask().run(ctx, deposito=DEP_SOTTO, slot_liberi=3)
        assert result.data["spedizioni"] == 0
        assert result.success is True

    @patch("tasks.rifornimento.time.sleep")
    def test_mappa_key_inviato(self, mock_sleep):
        """Anche con risorse sotto, il bot entra in mappa (prima verifica slot)."""
        ctx = ctx_abilitato()
        RifornimentoTask().run(ctx, deposito=DEP_SOTTO, slot_liberi=3)
        # KEYCODE_MAP deve essere inviato (navigazione in mappa)
        # La navigazione mappa avviene via navigator.vai_in_mappa() — non via device.key()
        assert ctx.navigator.mappa_calls >= 1


# ==============================================================================
# 12. RifornimentoTask.run — RESOURCE SUPPLY non trovato → stop
# ==============================================================================

class TestRifornimentoSupplyNonTrovato:

    @patch("tasks.rifornimento.time.sleep")
    def test_supply_non_trovato_zero_sped(self, mock_sleep):
        ctx = ctx_abilitato()
        ctx.device.add_screenshot(None)
        # FakeMatcher di default non trova nulla → _apri_resource_supply ritorna False
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert result.data["spedizioni"] == 0

    @patch("tasks.rifornimento.time.sleep")
    def test_tap_lente_eseguito(self, mock_sleep):
        ctx = ctx_abilitato()
        ctx.device.add_screenshot(None)
        RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        # La centratura mappa deve avvenire
        assert _DEFAULTS["TAP_LENTE_MAPPA"] in ctx.device.taps


# ==============================================================================
# 13. RifornimentoTask.run — spedizione OK simulata
# ==============================================================================

class TestRifornimentoSpedizioneOK:

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 54, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_una_spedizione(self, mock_centra, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert result.data["spedizioni"] == 1
        assert result.success is True

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 60, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_tre_spedizioni(self, mock_centra, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 3})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=5)
        assert result.data["spedizioni"] == 3

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 54, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_result_message_contiene_spedizioni(self,
           mock_centra, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert "1" in result.message

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 54, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_home_key_finale(self, mock_centra, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1})
        RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        # Il ritorno HOME avviene via navigator.vai_in_home() — non via device.key()
        assert ctx.navigator.home_calls >= 1


# ==============================================================================
# 14. RifornimentoTask.run — quota esaurita
# ==============================================================================

class TestRifornimentoQuotaEsaurita:

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(False, 0, True, 0, 0))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_quota_esaurita_stop(self, mock_centra, mock_apri,
                                  mock_compila, mock_sleep):
        ctx = ctx_abilitato()
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert result.data["spedizioni"] == 0
        assert result.success is True


# ==============================================================================
# 15. RifornimentoTask.run — eta_residua nel result
# ==============================================================================

class TestRifornimentoEtaResidua:

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 60, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    @patch("tasks.rifornimento._centra_mappa")
    def test_eta_residua_presente(self, mock_centra, mock_apri,
                                   mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{"RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1,
                               "MARGINE_ATTESA": 0})
        result = RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert "eta_residua" in result.data
        assert result.data["eta_residua"] >= 0.0


# ==============================================================================
# 16. Coordinate personalizzate via config
# ==============================================================================

class TestRifornimentoCoordCustom:

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 54, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    def test_lente_custom(self, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{
            "TAP_LENTE_MAPPA": (200, 20),
            "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1,
        })
        RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        assert (200, 20) in ctx.device.taps

    @patch("tasks.rifornimento.time.sleep")
    @patch("tasks.rifornimento._compila_e_invia",
           return_value=(True, 54, False, 1_000_000, -1))
    @patch("tasks.rifornimento._apri_resource_supply", return_value=True)
    def test_rifugio_xy_custom(self, mock_apri, mock_compila, mock_sleep):
        ctx = ctx_abilitato(**{
            "RIFUGIO_X": 100,
            "RIFUGIO_Y": 200,
            "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 1,
        })
        RifornimentoTask().run(ctx, deposito=DEP_OK, slot_liberi=3)
        # Il testo "100" deve essere inviato come input
        assert ("TEXT", "100") in ctx.device.taps
        assert ("TEXT", "200") in ctx.device.taps


# ==============================================================================
# Test: RifornimentoState.provviste_esaurite — guard persistente
# ==============================================================================

class TestRifornimentoStateShouldRun:

    def _make_ctx_with_state(self, provviste_esaurite=False):
        from core.state import InstanceState
        ctx = make_ctx()
        ctx.state = InstanceState("FAKE_00")
        if provviste_esaurite:
            ctx.state.rifornimento.segna_provviste_esaurite()
        return ctx

    def test_should_run_true_per_default(self):
        ctx = self._make_ctx_with_state(provviste_esaurite=False)
        task = RifornimentoTask()
        assert task.should_run(ctx) is True

    def test_should_run_false_se_provviste_esaurite(self):
        """Se provviste_esaurite=True → should_run=False."""
        ctx = self._make_ctx_with_state(provviste_esaurite=True)
        task = RifornimentoTask()
        assert task.should_run(ctx) is False

    def test_should_run_true_dopo_reset_giornaliero(self):
        """provviste_esaurite si resetta a mezzanotte UTC."""
        from core.state import RifornimentoState
        r = RifornimentoState(
            provviste_esaurite=True,
            data_riferimento="2020-01-01",
        )
        assert r.should_run() is True

    def test_provviste_esaurite_persiste_dopo_serializzazione(self):
        """provviste_esaurite persiste in to_dict/from_dict."""
        from core.state import RifornimentoState
        r = RifornimentoState()
        r.segna_provviste_esaurite()
        d = r.to_dict()
        r2 = RifornimentoState.from_dict(d)
        assert r2.provviste_esaurite is True
        assert r2.should_run() is False

    def test_device_none_ritorna_false(self):
        """Guard tecnica: device None → should_run=False."""
        from core.task import TaskContext
        from core.state import InstanceState
        ctx = TaskContext(
            instance_name="FAKE_00",
            config=_DictCfg({}),
            state=InstanceState("FAKE_00"),
            log=None,
            device=None,
            matcher=None,
        )
        assert RifornimentoTask().should_run(ctx) is False
