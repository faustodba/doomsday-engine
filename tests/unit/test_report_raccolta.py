# ==============================================================================
#  tests/unit/test_report_raccolta.py
#
#  Unit test per shared/report_raccolta.py — sanity check WU199quinquies:
#  quantita_base non deve mai superare la capacità nominale nota per
#  (tipo, livello), e una riga con tipo non riconosciuto va scartata.
#  _ocr_raw è mockato: nessun Tesseract richiesto.
# ==============================================================================

import numpy as np
import pytest
from unittest.mock import patch

from core.device import FakeDevice
from core.device import Screenshot
from shared.report_raccolta import (
    HEADER_Y0,
    VALUE_Y0,
    _estrai_riga,
    _CAPACITA_MAX,
    _sort_mail_toggle_on,
    _assicura_sort_mail_off,
    _elimina_report_letto,
    _report_vuoto_confermato,
    _tab_report_attivo,
    leggi_pagina,
    esegui_report_raccolta,
    TAP_SORT_MAIL,
    TAP_READ_CLAIM_ALL,
    TAP_DELETE_READ,
    TAP_CONFIRM_OK,
    TAP_ICONA_MESSAGGI,
    TAP_TAB_REPORT,
    TAP_TAB_ALLIANCE,
    TAP_CLOSE,
)


class _FakeCtx:
    def __init__(self, device, instance_name="FAU_TEST"):
        self.device = device
        self.instance_name = instance_name


def _frame():
    # dimensioni sufficienti a coprire tutte le ROI usate da _estrai_riga
    return np.zeros((540, 960, 3), dtype=np.uint8)


def _mock_ocr(coord="703 539", tipo="Field Lv.7", ts="2026/07/10 12:00",
              val_base="1,320,000", val_alleanza="13,200"):
    """Side-effect per _ocr_raw keyed sulla X di partenza della ROI —
    stesso ordine di chiamata di _estrai_riga (coord, tipo, ts, val, alleanza)."""
    def _side_effect(frame, roi, cfg):
        x0 = roi[0]
        if x0 == 330:
            return coord
        if x0 == 460:
            return tipo
        if x0 == 770:
            return ts
        if x0 == 365:
            return val_base
        if x0 == 800:
            return val_alleanza
        return ""
    return _side_effect


class TestSanityCheckCapacitaNominale:

    def test_quantita_base_entro_capacita_ok(self):
        with patch("shared.report_raccolta._ocr_raw",
                   side_effect=_mock_ocr(val_base="1,320,000")):
            row = _estrai_riga(_frame(), HEADER_Y0, VALUE_Y0)
        assert row is not None
        assert row.tipo == "campo"
        assert row.livello == 7
        assert row.quantita_base == 1_320_000

    def test_quantita_base_oltre_capacita_scartata(self):
        """Bug reale osservato 10/07: icona 'campo' bleeda nel crop valore,
        letta come cifra '5' prependuta — 51,320,000 invece di 1,320,000."""
        with patch("shared.report_raccolta._ocr_raw",
                   side_effect=_mock_ocr(val_base="51,320,000")):
            row = _estrai_riga(_frame(), HEADER_Y0, VALUE_Y0)
        assert row is not None
        assert row.tipo == "campo"
        assert row.quantita_base == -1  # scartata da registra_righe() a valle

    def test_quantita_base_oltre_capacita_segheria(self):
        """Stesso bug su segheria: cifra spuria '2' — 21,200,000 vs 1,200,000."""
        with patch("shared.report_raccolta._ocr_raw",
                   side_effect=_mock_ocr(tipo="Sawmill Lv.6",
                                          val_base="21,200,000")):
            row = _estrai_riga(_frame(), HEADER_Y0, VALUE_Y0)
        assert row is not None
        assert row.tipo == "segheria"
        assert row.quantita_base == -1

    def test_tipo_non_riconosciuto_forza_scarto(self):
        with patch("shared.report_raccolta._ocr_raw",
                   side_effect=_mock_ocr(tipo="????", val_base="1,320,000")):
            row = _estrai_riga(_frame(), HEADER_Y0, VALUE_Y0)
        assert row is not None
        assert row.tipo is None
        assert row.quantita_base == -1  # valore OCR corretto ma tipo ignoto → scartata comunque

    def test_livello_sconosciuto_non_validato(self):
        """(tipo, livello) fuori da _CAPACITA_MAX (es. Lv5) → nessun sanity
        check applicabile, il valore letto passa inalterato."""
        assert ("campo", 5) not in _CAPACITA_MAX
        with patch("shared.report_raccolta._ocr_raw",
                   side_effect=_mock_ocr(tipo="Field Lv.5", val_base="999,999,999")):
            row = _estrai_riga(_frame(), HEADER_Y0, VALUE_Y0)
        assert row is not None
        assert row.livello == 5
        assert row.quantita_base == 999_999_999

    def test_capacita_max_coerente_con_tabella_nota(self):
        """Guardrail anti-drift: la tabella deve restare quella validata
        30/04/2026 (memoria reference_capacita_nodi.md)."""
        assert _CAPACITA_MAX[("campo", 6)] == 1_200_000
        assert _CAPACITA_MAX[("campo", 7)] == 1_320_000
        assert _CAPACITA_MAX[("segheria", 6)] == 1_200_000
        assert _CAPACITA_MAX[("segheria", 7)] == 1_320_000
        assert _CAPACITA_MAX[("acciaio", 6)] == 600_000
        assert _CAPACITA_MAX[("acciaio", 7)] == 660_000
        assert _CAPACITA_MAX[("petrolio", 6)] == 240_000
        assert _CAPACITA_MAX[("petrolio", 7)] == 264_000


def _frame_toggle(cursore_a_sinistra: bool) -> np.ndarray:
    """Frame sintetico 960x540 con una banda chiara nella metà sinistra o
    destra della zona toggle (simula il cursore acceso/spento)."""
    frame = np.full((540, 960, 3), 30, dtype=np.uint8)  # sfondo scuro uniforme
    if cursore_a_sinistra:
        frame[60:82, 20:47] = 220   # ROI sinistra chiara (OFF)
    else:
        frame[60:82, 60:87] = 220   # ROI destra chiara (ON)
    return frame


class TestSortMailToggle:

    def test_rileva_off_cursore_a_sinistra(self):
        assert _sort_mail_toggle_on(_frame_toggle(cursore_a_sinistra=True)) is False

    def test_rileva_on_cursore_a_destra(self):
        assert _sort_mail_toggle_on(_frame_toggle(cursore_a_sinistra=False)) is True

    def test_assicura_off_non_tocca_se_gia_off(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame_toggle(cursore_a_sinistra=True)))
        _assicura_sort_mail_off(device, log=lambda m: None)
        assert device.taps == []

    def test_assicura_off_tappa_se_on(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame_toggle(cursore_a_sinistra=False)))
        _assicura_sort_mail_off(device, log=lambda m: None)
        assert device.taps == [TAP_SORT_MAIL]

    def test_assicura_off_screenshot_none_non_solleva(self):
        device = FakeDevice()  # nessuno screenshot in coda -> None
        _assicura_sort_mail_off(device, log=lambda m: None)
        assert device.taps == []


class TestReportVuotoConfermato:
    """WU199octies: verifica POSITIVA via OCR 'No mail received', non
    assenza di righe lette (rischio falso positivo)."""

    def test_testo_no_mail_received_rilevato(self):
        with patch("shared.report_raccolta._ocr_raw", return_value="No mail received"):
            assert _report_vuoto_confermato(_frame()) is True

    def test_testo_assente_non_confermato(self):
        with patch("shared.report_raccolta._ocr_raw", return_value=""):
            assert _report_vuoto_confermato(_frame()) is False

    def test_ancora_non_rilevata_non_e_falso_positivo(self):
        """Caso critico WU199octies: se leggi_pagina() non trova righe per
        un problema di rilevazione ancora (non perche' il report e' vuoto
        davvero), il vecchio check (len==0) dava falso positivo. Il nuovo
        check testuale non ha questo problema: un frame senza il testo
        esplicito NON conferma il vuoto, anche se leggi_pagina() darebbe 0."""
        frame = _frame()  # frame nero: leggi_pagina() troverebbe 0 righe
        assert len(leggi_pagina(frame)) == 0  # comportamento vecchio: "sembra" vuoto
        with patch("shared.report_raccolta._ocr_raw", return_value=""):
            assert _report_vuoto_confermato(frame) is False  # nuovo check: non confermato


class TestEliminaReportLetto:

    def test_sequenza_tap_read_claim_delete_read_ok(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(np.zeros((540, 960, 3), dtype=np.uint8)))
        with patch("shared.report_raccolta._ocr_raw", return_value="No mail received"):
            ok = _elimina_report_letto(device)
        assert device.taps == [TAP_READ_CLAIM_ALL, TAP_DELETE_READ, TAP_CONFIRM_OK]
        assert ok is True

    def test_testo_non_confermato_ritorna_false(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(np.zeros((540, 960, 3), dtype=np.uint8)))
        with patch("shared.report_raccolta._ocr_raw", return_value=""):
            ok = _elimina_report_letto(device)
        assert ok is False

    def test_screenshot_finale_none_ritorna_false(self):
        device = FakeDevice()  # nessuno screenshot in coda -> None dopo i tap
        ok = _elimina_report_letto(device)
        assert ok is False


class TestTabReportAttivo:
    """WU199nonies: sentinella OCR 'Sort Mail', presente solo sul tab Report."""

    def test_testo_sort_mail_presente_confermato(self):
        with patch("shared.report_raccolta._ocr_raw", return_value="Sort Mail"):
            assert _tab_report_attivo(_frame()) is True

    def test_testo_assente_non_confermato(self):
        with patch("shared.report_raccolta._ocr_raw", return_value=""):
            assert _tab_report_attivo(_frame()) is False


class TestEseguiReportRaccoltaAbortSuTabSbagliato:
    """WU199nonies: bug reale osservato live 10/07 su FAU_03 -- il tap su
    TAP_TAB_REPORT non veniva mai verificato, e Read-claim-all+Delete-read
    hanno colpito il tab Alliance (rimasto attivo dal run precedente,
    WU199bis) invece del report raccolta. Questi test verificano che,
    senza conferma del tab, NESSUNA azione distruttiva venga eseguita."""

    def _ocr_sempre_vuoto(self, frame, roi, cfg):
        return ""  # nessun tab riconosciuto, né al primo tentativo né al retry

    def test_tab_mai_confermato_nessun_tap_distruttivo(self):
        device = FakeDevice()
        # 2 screenshot: check iniziale + check dopo retry, entrambi "senza testo"
        device.add_screenshot(Screenshot(_frame()))
        device.add_screenshot(Screenshot(_frame()))
        ctx = _FakeCtx(device)

        with patch("shared.report_raccolta._ocr_raw", side_effect=self._ocr_sempre_vuoto):
            esito = esegui_report_raccolta(ctx, solo_reset=True)

        assert TAP_READ_CLAIM_ALL not in device.taps
        assert TAP_DELETE_READ not in device.taps
        assert TAP_CONFIRM_OK not in device.taps
        assert esito["errore"] == "tab_report_non_confermato"
        assert esito["delete_ok"] is None
        # naviga e si richiude in sicurezza: apri messaggi, tab Report x2
        # (primo tentativo + retry), ripristina Alliance, chiudi
        assert device.taps == [
            TAP_ICONA_MESSAGGI, TAP_TAB_REPORT, TAP_TAB_REPORT,
            TAP_TAB_ALLIANCE, TAP_CLOSE,
        ]

    def test_tab_confermato_al_retry_procede_normalmente(self):
        device = FakeDevice()
        calls = {"n": 0}

        def _ocr_side_effect(frame, roi, cfg):
            if roi == (95, 62, 260, 82):  # ROI_TAB_LABEL
                calls["n"] += 1
                return "" if calls["n"] == 1 else "Sort Mail"  # fallisce 1a volta, ok al retry
            if roi == (330, 220, 950, 280):  # ROI_NO_MAIL
                return "No mail received"
            return ""

        # screenshot in ordine: check tab iniziale (fail), check tab retry
        # (ok), check toggle Sort Mail dentro _assicura_sort_mail_off
        # (pixel, non OCR -- frame nero = toggle OFF, nessun tap), check
        # finale dentro _elimina_report_letto ("No mail received")
        device.add_screenshot(Screenshot(_frame()))
        device.add_screenshot(Screenshot(_frame()))
        device.add_screenshot(Screenshot(_frame()))
        device.add_screenshot(Screenshot(_frame()))
        ctx = _FakeCtx(device)

        with patch("shared.report_raccolta._ocr_raw", side_effect=_ocr_side_effect):
            esito = esegui_report_raccolta(ctx, solo_reset=True)

        assert esito["errore"] is None
        assert esito["delete_ok"] is True
        assert TAP_READ_CLAIM_ALL in device.taps
        assert TAP_DELETE_READ in device.taps
