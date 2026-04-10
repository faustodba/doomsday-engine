# ==============================================================================
#  tests/unit/test_ocr_helpers.py
#
#  Unit test per shared/ocr_helpers.py
#
#  Nota: i test di estrai_numero() e prepara_*() sono puri (no Tesseract).
#  I test di ocr_zona/ocr_cifre/ocr_risorse vengono saltati se Tesseract
#  non è installato nel sistema, oppure testati con mock.
# ==============================================================================

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from shared.ocr_helpers import (
    RisorseDeposito,
    ZONE_RISORSE_DEFAULT,
    estrai_numero,
    ocr_cifre,
    ocr_intero,
    ocr_risorse,
    ocr_zona,
    prepara_crema,
    prepara_otsu,
)
from core.device import Screenshot


# ==============================================================================
# Helpers
# ==============================================================================

def make_gray_screenshot(width=200, height=30, value=200) -> Screenshot:
    """Screenshot con sfondo chiaro uniforme (per preprocessing tests)."""
    data = np.full((height, width, 3), value, dtype=np.uint8)
    return Screenshot(data)


def make_screenshot_with_dark_text(width=200, height=30) -> Screenshot:
    """Screenshot con sfondo bianco e striscia scura (simula testo)."""
    data = np.full((height, width, 3), 240, dtype=np.uint8)
    data[10:20, 20:80] = (30, 30, 30)  # banda scura = "testo"
    return Screenshot(data)


# ==============================================================================
# TestEstraiNumero — parsing puro, nessun OCR
# ==============================================================================

class TestEstraiNumero:

    def test_intero_semplice(self):
        assert estrai_numero("12345") == 12345

    def test_con_spazi(self):
        assert estrai_numero("  8  ") == 8

    def test_punto_separatore_migliaia(self):
        assert estrai_numero("12.345") == 12345

    def test_virgola_separatore_migliaia(self):
        assert estrai_numero("12,345") == 12345

    def test_k_migliaia(self):
        assert estrai_numero("12K") == 12000

    def test_k_con_decimale(self):
        assert estrai_numero("12.5K") == 12500

    def test_m_milioni(self):
        assert estrai_numero("1M") == 1_000_000

    def test_m_con_decimale(self):
        assert estrai_numero("1.2M") == 1_200_000

    def test_k_minuscolo(self):
        assert estrai_numero("5k") == 5000

    def test_stringa_vuota(self):
        assert estrai_numero("") is None

    def test_solo_lettere(self):
        assert estrai_numero("abc") is None

    def test_none_input(self):
        assert estrai_numero(None) is None  # type: ignore

    def test_zero(self):
        assert estrai_numero("0") == 0

    def test_numero_grande(self):
        assert estrai_numero("1.234.567") == 1234567

    def test_virgola_decimale(self):
        # "1,5" con 1 cifra dopo virgola → non separatore migliaia → 1.5 → 2
        result = estrai_numero("1,5")
        assert result in (1, 2)  # dipende da arrotondamento float

    def test_punto_e_virgola(self):
        # "1.234,56" → il punto è separatore, virgola è decimale → 1234
        assert estrai_numero("1.234,56") == 1235  # arrotondamento di 1234.56

    def test_stringa_mista(self):
        # Testo OCR sporco come "8.542 res"
        assert estrai_numero("8.542 res") == 8542


# ==============================================================================
# TestPreparaOtsu — preprocessing puro
# ==============================================================================

class TestPreparaOtsu:

    def test_output_grayscale(self):
        s = make_gray_screenshot(200, 30, value=200)
        result = prepara_otsu(s)
        assert result.ndim == 2  # grayscale

    def test_output_binarizzato(self):
        s = make_gray_screenshot(200, 30)
        result = prepara_otsu(s)
        unique = set(result.flatten().tolist())
        assert unique <= {0, 255}  # solo bianco e nero

    def test_con_zona(self):
        s = make_gray_screenshot(960, 540)
        result = prepara_otsu(s, zone=(0, 0, 200, 30))
        assert result.shape[0] > 0
        assert result.shape[1] > 0

    def test_upscale(self):
        s = make_gray_screenshot(100, 20)
        result = prepara_otsu(s, scale=2.0)
        # Con scale=2 le dimensioni raddoppiano (circa)
        assert result.shape[1] >= 180  # ~200 * 2

    def test_accetta_array(self):
        arr = np.full((30, 200, 3), 200, dtype=np.uint8)
        result = prepara_otsu(arr)
        assert result.ndim == 2

    def test_tipo_non_supportato_solleva(self):
        with pytest.raises(TypeError):
            prepara_otsu("non_valido")


# ==============================================================================
# TestPreparaCrema — preprocessing puro
# ==============================================================================

class TestPreparaCrema:

    def test_output_grayscale(self):
        s = make_gray_screenshot(200, 30, value=200)
        result = prepara_crema(s)
        assert result.ndim == 2

    def test_output_binarizzato(self):
        s = make_gray_screenshot(200, 30, value=200)
        result = prepara_crema(s)
        unique = set(result.flatten().tolist())
        assert unique <= {0, 255}

    def test_pixel_luminosi_diventano_testo(self):
        # Sfondo scuro (50) → dovrebbe diventare tutto nero (sfondo) dopo inversione
        dark = np.full((30, 100, 3), 50, dtype=np.uint8)
        result = prepara_crema(dark, thresh_low=160)
        # Pixel scuri (50) < thresh(160) → 0 → dopo NOT → 255 (bianco)
        assert result.mean() > 200  # quasi tutto bianco = sfondo

    def test_con_zona(self):
        s = make_gray_screenshot(960, 540)
        result = prepara_crema(s, zone=(0, 0, 160, 25))
        assert result.shape[0] > 0


# ==============================================================================
# TestOcrZona — con mock Tesseract
# ==============================================================================

class TestOcrZona:

    def test_ritorna_stringa(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value="123"):
            result = ocr_zona(s)
        assert result == "123"

    def test_ritorna_vuoto_su_eccezione(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value=""):
            result = ocr_zona(s)
        assert result == ""

    def test_preprocessor_otsu(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value="42") as mock_t:
            ocr_zona(s, preprocessor="otsu")
            mock_t.assert_called_once()

    def test_preprocessor_crema(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value="99") as mock_t:
            ocr_zona(s, preprocessor="crema")
            mock_t.assert_called_once()

    def test_preprocessor_none(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value="7") as mock_t:
            result = ocr_zona(s, preprocessor="none")
            assert result == "7"


# ==============================================================================
# TestOcrIntero — fallback psm
# ==============================================================================

class TestOcrIntero:

    def test_ritorna_risultato_primo_tentativo(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value="500"):
            result = ocr_intero(s)
        assert result == "500"

    def test_fallback_psm13_se_primo_vuoto(self):
        s = make_gray_screenshot()
        # Primo tentativo → vuoto, secondo → "300"
        responses = iter(["", "300"])
        with patch("shared.ocr_helpers._run_tesseract", side_effect=responses):
            result = ocr_intero(s)
        assert result == "300"

    def test_ritorna_vuoto_se_entrambi_falliscono(self):
        s = make_gray_screenshot()
        with patch("shared.ocr_helpers._run_tesseract", return_value=""):
            result = ocr_intero(s)
        assert result == ""


# ==============================================================================
# TestOcrRisorse
# ==============================================================================

class TestOcrRisorse:

    def test_ritorna_risorse_deposito(self):
        s = make_gray_screenshot(960, 540)
        # Mock: restituisce valori diversi per ogni zona
        valori = iter(["12345", "8000", "2500", "500"])
        with patch("shared.ocr_helpers._run_tesseract", side_effect=valori):
            result = ocr_risorse(s)
        assert isinstance(result, RisorseDeposito)

    def test_risorse_con_fallback_cifre(self):
        s = make_gray_screenshot(960, 540)
        # Prima chiamata per ogni risorsa → vuota, seconda (cifre) → numero
        # 4 risorse × 2 tentativi = 8 chiamate totali
        side = ["", "1000", "", "2000", "", "500", "", "100"]
        with patch("shared.ocr_helpers._run_tesseract", side_effect=side):
            result = ocr_risorse(s)
        assert result.pomodoro == 1000

    def test_risorse_none_se_fallisce(self):
        s = make_gray_screenshot(960, 540)
        with patch("shared.ocr_helpers._run_tesseract", return_value=""):
            result = ocr_risorse(s)
        assert result.pomodoro is None
        assert result.legno is None
        assert result.petrolio is None
        assert result.acciaio is None

    def test_zone_custom(self):
        s = make_gray_screenshot(960, 540)
        zone_custom = {
            "pomodoro": (0, 0, 100, 20),
            "legno":    (100, 0, 200, 20),
            "petrolio": (200, 0, 300, 20),
            "acciaio":  (300, 0, 400, 20),
        }
        with patch("shared.ocr_helpers._run_tesseract", return_value="999"):
            result = ocr_risorse(s, zone_risorse=zone_custom)
        assert result.pomodoro == 999

    def test_named_tuple_accesso(self):
        r = RisorseDeposito(pomodoro=100, legno=200, petrolio=50, acciaio=10)
        assert r.pomodoro == 100
        assert r[1] == 200  # legno per indice
