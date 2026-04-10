# ==============================================================================
#  tests/unit/test_rifornimento_base.py
#
#  Unit test per shared/rifornimento_base.py
#
#  Tutti i test usano FakeDevice e Screenshot sintetici — nessun ADB reale.
#  Le funzioni OCR vengono mockata per isolare la logica di business.
# ==============================================================================

import asyncio
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from core.device import FakeDevice, Screenshot
from shared.rifornimento_base import (
    COORD_CAMPO,
    COORD_VAI,
    QTA_DEFAULT,
    TASSA_DEFAULT,
    VAI_SOGLIA_GIALLI,
    VAI_ZONA,
    InvioResult,
    compila_e_invia,
    leggi_capacita_camion,
    leggi_eta,
    leggi_provviste,
    leggi_tassa,
    vai_abilitato,
    verifica_destinatario,
)


# ==============================================================================
# Helpers — screenshot sintetici
# ==============================================================================

def make_screenshot(width=960, height=540, color=(50, 50, 50)) -> Screenshot:
    data = np.full((height, width, 3), color, dtype=np.uint8)
    return Screenshot(data)


def make_screenshot_con_vai_giallo() -> Screenshot:
    """Screenshot con zona VAI riempita di pixel gialli (B<90, G>120, R>160)."""
    data = np.full((540, 960, 3), 50, dtype=np.uint8)
    x1, y1, x2, y2 = VAI_ZONA
    # BGR: (B=50, G=180, R=200) → giallo in RGB
    data[y1:y2, x1:x2] = (50, 180, 200)
    return Screenshot(data)


def make_screenshot_con_vai_grigio() -> Screenshot:
    """Screenshot con zona VAI riempita di grigio (non giallo)."""
    data = np.full((540, 960, 3), (100, 100, 100), dtype=np.uint8)
    return Screenshot(data)


# ==============================================================================
# TestCostanti
# ==============================================================================

class TestCostanti:

    def test_coord_campo_ha_4_risorse(self):
        assert set(COORD_CAMPO.keys()) == {"pomodoro", "legno", "acciaio", "petrolio"}

    def test_coord_campo_coordinate_valide(self):
        for risorsa, (x, y) in COORD_CAMPO.items():
            assert 0 < x < 960, f"{risorsa}: x={x} fuori range"
            assert 0 < y < 540, f"{risorsa}: y={y} fuori range"

    def test_coord_vai_valida(self):
        x, y = COORD_VAI
        assert 0 < x < 960
        assert 0 < y < 540

    def test_tassa_default(self):
        assert 0.0 < TASSA_DEFAULT < 1.0

    def test_qta_default_chiavi(self):
        assert set(QTA_DEFAULT.keys()) == {"pomodoro", "legno", "acciaio", "petrolio"}


# ==============================================================================
# TestVaiAbilitato
# ==============================================================================

class TestVaiAbilitato:

    def test_vai_giallo_abilitato(self):
        shot = make_screenshot_con_vai_giallo()
        assert vai_abilitato(shot) is True

    def test_vai_grigio_non_abilitato(self):
        shot = make_screenshot_con_vai_grigio()
        assert vai_abilitato(shot) is False

    def test_screenshot_nero_non_abilitato(self):
        shot = make_screenshot(color=(0, 0, 0))
        assert vai_abilitato(shot) is False

    def test_non_crasha_su_screenshot_piccolo(self):
        # Screenshot più piccolo della zona VAI → deve ritornare False senza crash
        data = np.zeros((10, 10, 3), dtype=np.uint8)
        shot = Screenshot(data)
        result = vai_abilitato(shot)
        assert isinstance(result, bool)


# ==============================================================================
# TestLeggiProvviste
# ==============================================================================

class TestLeggiProvviste:

    def test_provviste_ok(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_intero", return_value="5000000"):
            result = leggi_provviste(shot)
        assert result == 5_000_000

    def test_provviste_zero(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_intero", return_value="0"):
            result = leggi_provviste(shot)
        assert result == 0

    def test_provviste_ocr_fallisce(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_intero", return_value=""):
            result = leggi_provviste(shot)
        assert result == -1

    def test_provviste_con_virgola(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_intero", return_value="1,200,000"):
            result = leggi_provviste(shot)
        assert result == 1_200_000


# ==============================================================================
# TestLeggiTassa
# ==============================================================================

class TestLeggiTassa:

    def test_tassa_23(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="Tasse: 23.0%"):
            result = leggi_tassa(shot)
        assert abs(result - 0.23) < 0.001

    def test_tassa_default_se_ocr_fallisce(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value=""):
            result = leggi_tassa(shot)
        assert result == TASSA_DEFAULT

    def test_tassa_senza_decimale(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="Tasse: 24%"):
            result = leggi_tassa(shot)
        assert abs(result - 0.24) < 0.001

    def test_tassa_con_testo_sporco(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="Tax 20.5 %"):
            result = leggi_tassa(shot)
        assert abs(result - 0.205) < 0.001


# ==============================================================================
# TestLeggiEta
# ==============================================================================

class TestLeggiEta:

    def test_eta_hms(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="00:00:54"):
            result = leggi_eta(shot)
        assert result == 54

    def test_eta_minuti_secondi(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="01:30"):
            result = leggi_eta(shot)
        assert result == 90

    def test_eta_ore(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="01:00:00"):
            result = leggi_eta(shot)
        assert result == 3600

    def test_eta_ocr_fallisce(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value=""):
            result = leggi_eta(shot)
        assert result == 0

    def test_eta_con_spazzatura(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="ETA 00:05:30"):
            result = leggi_eta(shot)
        assert result == 330  # 5*60 + 30


# ==============================================================================
# TestLeggiCapacitaCamion
# ==============================================================================

class TestLeggiCapacitaCamion:

    def test_capacita_con_slash(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="0/1,200,000"):
            result = leggi_capacita_camion(shot)
        assert result == 1_200_000

    def test_capacita_senza_slash(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="800000"):
            result = leggi_capacita_camion(shot)
        assert result == 800_000

    def test_capacita_ocr_fallisce(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value=""):
            result = leggi_capacita_camion(shot)
        assert result == 0


# ==============================================================================
# TestVerificaDestinatario
# ==============================================================================

class TestVerificaDestinatario:

    def test_match_esatto(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="FauMorfeus"):
            ok, testo = verifica_destinatario(shot, "FauMorfeus")
        assert ok is True

    def test_match_case_insensitive(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="FAUMORFEUS"):
            ok, testo = verifica_destinatario(shot, "faumorfeus")
        assert ok is True

    def test_match_parziale(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="  FauMorfeus  "):
            ok, testo = verifica_destinatario(shot, "Morfeus")
        assert ok is True

    def test_mismatch(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="AltraPersona"):
            ok, testo = verifica_destinatario(shot, "FauMorfeus")
        assert ok is False

    def test_testo_pulito_da_pipe_e_underscore(self):
        shot = make_screenshot()
        with patch("shared.rifornimento_base.ocr_zona", return_value="|Fau_Morfeus|"):
            ok, testo = verifica_destinatario(shot, "FauMorfeus")
        assert "|" not in testo
        assert ok is True


# ==============================================================================
# TestCompilaEInvia — async, con FakeDevice
# ==============================================================================

class TestCompilaEInvia:

    def _device_con_shots(self, shots: list[Screenshot]) -> FakeDevice:
        return FakeDevice(name="FAU_TEST", index=0, screenshots=shots)

    @pytest.mark.asyncio
    async def test_invio_ok(self):
        """Flusso felice: nome ok, provviste > 0, VAI giallo."""
        shot_iniziale = make_screenshot()
        shot_post_compilazione = make_screenshot_con_vai_giallo()
        device = self._device_con_shots([shot_iniziale, shot_post_compilazione])

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(True, "FAU_00")), \
             patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=5_000_000), \
             patch("shared.rifornimento_base.leggi_eta", return_value=54), \
             patch("shared.rifornimento_base.vai_abilitato", return_value=True):

            result = await compila_e_invia(
                device,
                quantita={"pomodoro": 1_000_000},
                nome_dest="FAU_00",
            )

        assert result.ok is True
        assert result.qta_inviata == 1_000_000
        assert result.quota_esaurita is False
        assert result.mismatch_nome is False
        # Verifica che VAI sia stato tappato
        assert any(t.x == COORD_VAI[0] and t.y == COORD_VAI[1]
                   for t in device.tap_calls)

    @pytest.mark.asyncio
    async def test_mismatch_nome_ritorna_false(self):
        shot = make_screenshot()
        device = self._device_con_shots([shot, shot])

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(False, "AltraPersona")):
            result = await compila_e_invia(
                device,
                quantita={"pomodoro": 1_000_000},
                nome_dest="FAU_00",
            )

        assert result.ok is False
        assert result.mismatch_nome is True
        assert device.back_count == 1

    @pytest.mark.asyncio
    async def test_provviste_zero_quota_esaurita(self):
        shot = make_screenshot()
        device = self._device_con_shots([shot, shot])

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(True, "FAU_00")), \
             patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=0), \
             patch("shared.rifornimento_base.leggi_eta", return_value=0):

            result = await compila_e_invia(
                device,
                quantita={"pomodoro": 1_000_000},
                nome_dest="FAU_00",
            )

        assert result.ok is False
        assert result.quota_esaurita is True

    @pytest.mark.asyncio
    async def test_vai_non_abilitato_dopo_compilazione(self):
        shot = make_screenshot()
        device = self._device_con_shots([shot, shot])

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(True, "FAU_00")), \
             patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=5_000_000), \
             patch("shared.rifornimento_base.leggi_eta", return_value=54), \
             patch("shared.rifornimento_base.vai_abilitato", return_value=False):

            result = await compila_e_invia(
                device,
                quantita={"pomodoro": 1_000_000},
                nome_dest="FAU_00",
            )

        assert result.ok is False
        assert result.quota_esaurita is False

    @pytest.mark.asyncio
    async def test_nessuna_risorsa_da_inviare(self):
        shot = make_screenshot()
        device = self._device_con_shots([shot])

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(True, "FAU_00")), \
             patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=5_000_000), \
             patch("shared.rifornimento_base.leggi_eta", return_value=54):

            result = await compila_e_invia(
                device,
                quantita={"pomodoro": 0, "legno": 0},  # tutto zero
                nome_dest="FAU_00",
            )

        assert result.ok is False
        assert result.qta_inviata == 0

    @pytest.mark.asyncio
    async def test_senza_verifica_nome(self):
        """nome_dest='' salta la verifica del destinatario."""
        shot = make_screenshot()
        shot_vai = make_screenshot_con_vai_giallo()
        device = self._device_con_shots([shot, shot_vai])

        with patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=1_000_000), \
             patch("shared.rifornimento_base.leggi_eta", return_value=30), \
             patch("shared.rifornimento_base.vai_abilitato", return_value=True):

            result = await compila_e_invia(
                device,
                quantita={"legno": 500_000},
                nome_dest="",  # skip verifica
            )

        assert result.ok is True
        assert result.qta_inviata == 500_000

    @pytest.mark.asyncio
    async def test_log_fn_chiamata(self):
        """Il log_fn viene chiamato durante l'esecuzione."""
        shot = make_screenshot()
        device = self._device_con_shots([shot, shot])
        log_messages = []

        with patch("shared.rifornimento_base.verifica_destinatario", return_value=(True, "X")), \
             patch("shared.rifornimento_base.leggi_tassa", return_value=0.24), \
             patch("shared.rifornimento_base.leggi_provviste", return_value=0), \
             patch("shared.rifornimento_base.leggi_eta", return_value=0):

            await compila_e_invia(
                device,
                quantita={"pomodoro": 1_000_000},
                nome_dest="X",
                log_fn=log_messages.append,
            )

        assert len(log_messages) > 0
