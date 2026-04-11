# ==============================================================================
#  tests/tasks/test_zaino.py — Step 19
#  Tutti i test usano FakeDevice + FakeMatcher — zero ADB reale.
# ==============================================================================

import time
import pytest
from unittest.mock import patch

from core.device import FakeDevice
from core.navigator import GameNavigator, Screen
from core.task import TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from tasks.zaino import (
    ZainoTask,
    _calcola_gap,
    _cfg,
    PEZZATURE,
    _DEFAULTS,
)


# ------------------------------------------------------------------------------
# Fixture base
# ------------------------------------------------------------------------------

def make_ctx(config_overrides: dict | None = None) -> TaskContext:
    device = FakeDevice()
    matcher = FakeMatcher()
    navigator = GameNavigator(device, matcher)
    config = dict(config_overrides or {})
    return TaskContext(
        device=device,
        matcher=matcher,
        navigator=navigator,
        config=config,
        instance_id="FAU_00",
        logger=None,
    )


# ==============================================================================
# 1. Proprietà del task
# ==============================================================================

class TestZainoTaskProperties:

    def test_name(self):
        assert ZainoTask().name == "zaino"

    def test_schedule_type(self):
        assert ZainoTask().schedule_type == "periodic"

    def test_interval_hours(self):
        assert ZainoTask().interval_hours == 168.0


# ==============================================================================
# 2. _cfg — lettura config con fallback
# ==============================================================================

class TestCfg:

    def test_default_abilitato(self):
        ctx = make_ctx()
        assert _cfg(ctx, "ZAINO_ABILITATO") is True

    def test_override_abilitato(self):
        ctx = make_ctx({"ZAINO_ABILITATO": False})
        assert _cfg(ctx, "ZAINO_ABILITATO") is False

    def test_default_soglia_pomodoro(self):
        ctx = make_ctx()
        assert _cfg(ctx, "ZAINO_SOGLIA_POMODORO_M") == 10.0

    def test_override_soglia_pomodoro(self):
        ctx = make_ctx({"ZAINO_SOGLIA_POMODORO_M": 5.0})
        assert _cfg(ctx, "ZAINO_SOGLIA_POMODORO_M") == 5.0

    def test_default_usa_acciaio_false(self):
        ctx = make_ctx()
        assert _cfg(ctx, "ZAINO_USA_ACCIAIO") is False

    def test_tap_apri_default(self):
        ctx = make_ctx()
        assert _cfg(ctx, "TAP_ZAINO_APRI") == (430, 18)

    def test_tap_chiudi_default(self):
        ctx = make_ctx()
        assert _cfg(ctx, "TAP_ZAINO_CHIUDI") == (783, 68)


# ==============================================================================
# 3. PEZZATURE — struttura dati
# ==============================================================================

class TestPezzature:

    def test_tutte_le_risorse_presenti(self):
        for r in ["pomodoro", "legno", "acciaio", "petrolio"]:
            assert r in PEZZATURE

    def test_pezzature_crescenti(self):
        for risorsa, vals in PEZZATURE.items():
            assert vals == sorted(vals), f"{risorsa} non ordinato"

    def test_pezzature_positive(self):
        for risorsa, vals in PEZZATURE.items():
            for v in vals:
                assert v > 0, f"{risorsa}: valore <= 0"

    def test_sei_pezzature_per_risorsa(self):
        for risorsa, vals in PEZZATURE.items():
            assert len(vals) == 6, f"{risorsa}: attese 6 pezzature"


# ==============================================================================
# 4. _calcola_gap
# ==============================================================================

class TestCalcolaGap:

    def test_gap_pomodoro_sotto_soglia(self):
        ctx = make_ctx({"ZAINO_SOGLIA_POMODORO_M": 10.0})
        dep = {"pomodoro": 4_000_000.0, "legno": 15_000_000.0,
               "acciaio": 0.0, "petrolio": 10_000_000.0}
        gaps = _calcola_gap(ctx, dep)
        assert "pomodoro" in gaps
        assert abs(gaps["pomodoro"] - 6_000_000.0) < 1

    def test_nessun_gap_sopra_soglia(self):
        ctx = make_ctx()
        dep = {"pomodoro": 15_000_000.0, "legno": 20_000_000.0,
               "acciaio": 10_000_000.0, "petrolio": 8_000_000.0}
        gaps = _calcola_gap(ctx, dep)
        assert gaps == {}

    def test_acciaio_disabilitato_per_default(self):
        ctx = make_ctx({"ZAINO_SOGLIA_ACCIAIO_M": 7.0})
        dep = {"pomodoro": 15_000_000.0, "legno": 15_000_000.0,
               "acciaio": 0.0, "petrolio": 10_000_000.0}
        gaps = _calcola_gap(ctx, dep)
        # acciaio disabilitato di default → non deve comparire nel gap
        assert "acciaio" not in gaps

    def test_acciaio_abilitato_esplicitamente(self):
        ctx = make_ctx({"ZAINO_USA_ACCIAIO": True,
                        "ZAINO_SOGLIA_ACCIAIO_M": 7.0})
        dep = {"pomodoro": 15_000_000.0, "legno": 15_000_000.0,
               "acciaio": 0.0, "petrolio": 10_000_000.0}
        gaps = _calcola_gap(ctx, dep)
        assert "acciaio" in gaps
        assert abs(gaps["acciaio"] - 7_000_000.0) < 1

    def test_ocr_non_disponibile(self):
        ctx = make_ctx()
        dep = {"pomodoro": -1.0}
        gaps = _calcola_gap(ctx, dep)
        assert "pomodoro" not in gaps

    def test_gap_multiplo(self):
        ctx = make_ctx()
        dep = {"pomodoro": 2_000_000.0, "legno": 1_000_000.0,
               "acciaio": 0.0, "petrolio": 1_000_000.0}
        gaps = _calcola_gap(ctx, dep)
        assert "pomodoro" in gaps
        assert "legno" in gaps
        assert "petrolio" in gaps
        assert "acciaio" not in gaps


# ==============================================================================
# 5. ZainoTask.run — disabilitato
# ==============================================================================

class TestZainoDisabilitato:

    def test_disabilitato_skip(self):
        ctx = make_ctx({"ZAINO_ABILITATO": False})
        result = ZainoTask().run(ctx, deposito={"pomodoro": 0.0})
        assert result.success is True
        assert result.message == "disabilitato"
        assert len(ctx.device.taps) == 0

    def test_disabilitato_data_vuota(self):
        ctx = make_ctx({"ZAINO_ABILITATO": False})
        result = ZainoTask().run(ctx, deposito={"pomodoro": 0.0})
        for r in ["pomodoro", "legno", "acciaio", "petrolio"]:
            assert result.data.get(r, 0.0) == 0.0


# ==============================================================================
# 6. ZainoTask.run — deposito non fornito
# ==============================================================================

class TestZainoDeposizoNonFornito:

    def test_deposito_none_fallisce(self):
        ctx = make_ctx()
        result = ZainoTask().run(ctx, deposito=None)
        assert result.success is False
        assert "deposito" in result.message

    def test_nessun_tap_se_deposito_none(self):
        ctx = make_ctx()
        ZainoTask().run(ctx, deposito=None)
        assert len(ctx.device.device.taps if hasattr(ctx.device, 'device') else ctx.device.taps) == 0


# ==============================================================================
# 7. ZainoTask.run — tutte le risorse sopra soglia
# ==============================================================================

class TestZainoTutteSopra:

    def test_nessun_carico(self):
        ctx = make_ctx()
        dep = {"pomodoro": 20_000_000.0, "legno": 20_000_000.0,
               "acciaio": 10_000_000.0, "petrolio": 10_000_000.0}
        result = ZainoTask().run(ctx, deposito=dep)
        assert result.success is True
        assert "nessun carico" in result.message

    def test_nessun_tap_apri(self):
        ctx = make_ctx()
        dep = {"pomodoro": 20_000_000.0, "legno": 20_000_000.0,
               "acciaio": 10_000_000.0, "petrolio": 10_000_000.0}
        ZainoTask().run(ctx, deposito=dep)
        # Nessun tap sull'icona zaino
        assert (430, 18) not in ctx.device.taps


# ==============================================================================
# 8. ZainoTask.run — apertura e chiusura zaino
# ==============================================================================

class TestZainoAperturaChiusura:

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_tap_apri_eseguito(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 20_000_000.0,
               "acciaio": 0.0, "petrolio": 0.0}
        ZainoTask().run(ctx, deposito=dep)
        assert (430, 18) in ctx.device.taps

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_tap_chiudi_sempre_eseguito(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 20_000_000.0,
               "acciaio": 0.0, "petrolio": 0.0}
        ZainoTask().run(ctx, deposito=dep)
        assert (783, 68) in ctx.device.taps

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_sidebar_pomodoro_tappata(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 20_000_000.0,
               "acciaio": 0.0, "petrolio": 0.0}
        ZainoTask().run(ctx, deposito=dep)
        # sidebar pomodoro (80,130) deve essere tappata
        assert (80, 130) in ctx.device.taps


# ==============================================================================
# 9. _scarica_risorsa via run — logica gap/pezzature
# ==============================================================================

class TestZainoScaricaLogica:

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._conta_righe_visibili", return_value=1)
    @patch("tasks.zaino._riga_ha_owned", return_value=True)
    def test_skip_pezzatura_troppo_grande(self, mock_owned, mock_righe, mock_sleep):
        """Gap 500 < pezzatura minima 1000 → nessun USE."""
        ctx = make_ctx({"ZAINO_SOGLIA_POMODORO_M": 0.0005,
                        "ZAINO_USA_LEGNO": False,
                        "ZAINO_USA_PETROLIO": False})
        # deposito 0, target 500 unità → gap 500 < pezzatura min 1000
        dep = {"pomodoro": 0.0, "legno": 20_000_000.0,
               "acciaio": 0.0, "petrolio": 6_000_000.0}
        ctx.device.set_screenshot(None)
        result = ZainoTask().run(ctx, deposito=dep)
        # Nessun tap USE (722) deve essere avvenuto
        use_taps = [t for t in ctx.device.taps if t[0] == 722]
        assert len(use_taps) == 0

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    @patch("tasks.zaino._riga_ha_owned", return_value=True)
    def test_nessuna_riga_visibile_stop(self, mock_owned, mock_righe, mock_sleep):
        """Se _conta_righe_visibili=0 il loop si ferma subito."""
        ctx = make_ctx({"ZAINO_USA_LEGNO": False, "ZAINO_USA_PETROLIO": False,
                        "ZAINO_USA_ACCIAIO": False})
        dep = {"pomodoro": 0.0}
        ctx.device.set_screenshot("dummy.png")
        result = ZainoTask().run(ctx, deposito=dep)
        assert result.success is True

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._conta_righe_visibili", return_value=1)
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    def test_owned_zero_skip(self, mock_owned, mock_righe, mock_sleep):
        """Se _riga_ha_owned=False nessun USE viene tentato."""
        ctx = make_ctx({"ZAINO_USA_LEGNO": False, "ZAINO_USA_PETROLIO": False,
                        "ZAINO_USA_ACCIAIO": False})
        dep = {"pomodoro": 0.0}
        ctx.device.set_screenshot("dummy.png")
        ZainoTask().run(ctx, deposito=dep)
        use_taps = [t for t in ctx.device.taps if t[0] == 722]
        assert len(use_taps) == 0


# ==============================================================================
# 10. ZainoTask.run — result.data
# ==============================================================================

class TestZainoResultData:

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_data_contiene_tutte_le_risorse(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 0.0, "acciaio": 0.0, "petrolio": 0.0}
        result = ZainoTask().run(ctx, deposito=dep)
        for r in ["pomodoro", "legno", "acciaio", "petrolio"]:
            assert r in result.data

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_data_in_milioni(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 0.0, "acciaio": 0.0, "petrolio": 0.0}
        result = ZainoTask().run(ctx, deposito=dep)
        for r in ["pomodoro", "legno", "petrolio"]:
            assert result.data[r] >= 0.0

    def test_success_true_sopra_soglia(self):
        ctx = make_ctx()
        dep = {"pomodoro": 50_000_000.0, "legno": 50_000_000.0,
               "acciaio": 50_000_000.0, "petrolio": 50_000_000.0}
        result = ZainoTask().run(ctx, deposito=dep)
        assert result.success is True


# ==============================================================================
# 11. Configurazione coordinate personalizzate
# ==============================================================================

class TestZainoCoordCustom:

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_tap_apri_custom(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx({"TAP_ZAINO_APRI": (100, 50)})
        dep = {"pomodoro": 0.0}
        ZainoTask().run(ctx, deposito=dep)
        assert (100, 50) in ctx.device.taps

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_tap_chiudi_custom(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx({"TAP_ZAINO_CHIUDI": (900, 50)})
        dep = {"pomodoro": 0.0}
        ZainoTask().run(ctx, deposito=dep)
        assert (900, 50) in ctx.device.taps


# ==============================================================================
# 12. Multi-risorsa
# ==============================================================================

class TestZainoMultiRisorsa:

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_sidebar_legno_e_petrolio_tappate(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx({"ZAINO_USA_ACCIAIO": False})
        dep = {"pomodoro": 50_000_000.0,   # sopra soglia → skip
               "legno":    0.0,             # sotto → tap sidebar (80,200)
               "acciaio":  0.0,             # disabilitato
               "petrolio": 0.0}             # sotto → tap sidebar (80,340)
        ZainoTask().run(ctx, deposito=dep)
        assert (80, 200) in ctx.device.taps   # sidebar legno
        assert (80, 340) in ctx.device.taps   # sidebar petrolio
        assert (80, 130) not in ctx.device.taps  # sidebar pomodoro NON tappata

    @patch("tasks.zaino.time.sleep")
    @patch("tasks.zaino._riga_ha_owned", return_value=False)
    @patch("tasks.zaino._conta_righe_visibili", return_value=0)
    def test_result_data_zeroes_se_no_righe(self, mock_righe, mock_owned, mock_sleep):
        ctx = make_ctx()
        dep = {"pomodoro": 0.0, "legno": 0.0, "acciaio": 0.0, "petrolio": 0.0}
        result = ZainoTask().run(ctx, deposito=dep)
        # Nessuna riga → scaricato = 0 per tutte
        for r in ["pomodoro", "legno", "petrolio"]:
            assert result.data[r] == 0.0
