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
from shared.template_matcher import FakeMatcher
from shared.report_raccolta import (
    HEADER_Y0,
    VALUE_Y0,
    _estrai_riga,
    _CAPACITA_MAX,
    _sort_mail_toggle_on,
    _assicura_sort_mail_off,
    _assicura_sort_mail_on,
    _seleziona_gathering_report,
    _elimina_report_letto,
    _report_vuoto_confermato,
    _tab_report_attivo,
    leggi_pagina,
    esegui_report_raccolta,
    ReportRow,
    TAP_SORT_MAIL,
    TAP_READ_CLAIM_ALL,
    TAP_DELETE_READ,
    TAP_CONFIRM_OK,
    TAP_ICONA_MESSAGGI,
    TAP_TAB_REPORT,
    TAP_TAB_ALLIANCE,
    TAP_CLOSE,
    PIN_GATHERING_REPORT,
    PIN_GATHERING_HEADER,
    PIN_REPORT_OTHER,
    PIN_CHEVRON_UP,
    MAX_TENTATIVI_GATHERING,
)


@pytest.fixture(autouse=True)
def _isola_data_dir(tmp_path, monkeypatch):
    """Isola data/report_raccolta_dataset.jsonl nella tmp_path -- senza
    questo, i test che esercitano registra_righe()/carica_chiavi_esistenti()
    scriverebbero nel vero dataset dev (pattern gia' usato in
    tests/tasks/test_raccolta.py)."""
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))


def _riga(coord, ts, tipo="petrolio", livello=7, base=264_000):
    return ReportRow(coordinata=coord, tipo=tipo, livello=livello, ts_raccolta=ts,
                      quantita_base=base, quantita_bonus=0, valore_alleanza=2640)


def _ocr_tab_e_nomail():
    """Factory (contatore isolato per-test, WU257 24/07): la 1a chiamata a
    ROI_NO_MAIL è il nuovo check "report vuoto" pre-selezione, DEVE dire
    "non vuoto" (altrimenti intercetterebbe prima ancora che il test possa
    verificare il comportamento di _seleziona_gathering_report /
    _elimina_report_letto). Le chiamate successive (es. dentro
    _elimina_report_letto, se il test arriva fin lì) dicono "vuoto" come
    da comportamento reale post-delete."""
    calls = {"n": 0}

    def _side_effect(frame, roi, cfg):
        if roi == (95, 62, 260, 82):      # ROI_TAB_LABEL
            return "Sort Mail"
        if roi == (330, 220, 950, 280):   # ROI_NO_MAIL
            calls["n"] += 1
            return "" if calls["n"] == 1 else "No mail received"
        return ""
    return _side_effect


class _FakeCtx:
    def __init__(self, device, instance_name="FAU_TEST", matcher=None):
        self.device = device
        self.instance_name = instance_name
        self.matcher = matcher if matcher is not None else FakeMatcher()


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

    # WU199... (21/07) — _assicura_sort_mail_on: mirror invertito, usato dal
    # fallback a categorie di _seleziona_gathering_report.

    def test_assicura_on_non_tocca_se_gia_on(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame_toggle(cursore_a_sinistra=False)))  # ON
        _assicura_sort_mail_on(device, log=lambda m: None)
        assert device.taps == []

    def test_assicura_on_tappa_se_off(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame_toggle(cursore_a_sinistra=True)))  # OFF
        _assicura_sort_mail_on(device, log=lambda m: None)
        assert device.taps == [TAP_SORT_MAIL]

    def test_assicura_on_screenshot_none_non_solleva(self):
        device = FakeDevice()  # nessuno screenshot in coda -> None
        _assicura_sort_mail_on(device, log=lambda m: None)
        assert device.taps == []


class _SeqMatcher:
    """Fake matcher con risultati DIVERSI a chiamate successive per lo
    stesso template — a differenza di FakeMatcher (risultato statico), serve
    a simulare stati che cambiano nel loop (es. 'Other' che passa da chiusa
    ad aperta dopo il tap). `script`: {template: [MatchResult, ...]}
    consumati in ordine; l'ultimo valore si ripete se le chiamate eccedono."""

    def __init__(self, script: dict):
        from core.device import MatchResult
        self._script = {k: list(v) for k, v in script.items()}
        self._idx = {k: 0 for k in script}
        self._MatchResult = MatchResult

    def find_one(self, screenshot, template_name: str, threshold=0.75, zone=None):
        seq = self._script.get(template_name)
        if not seq:
            return self._MatchResult(found=False, score=0.0, cx=0, cy=0)
        i = min(self._idx[template_name], len(seq) - 1)
        self._idx[template_name] += 1
        return seq[i]


def _mr(found, cx=0, cy=0, score=None):
    from core.device import MatchResult
    return MatchResult(found=found, score=(score if score is not None else (0.9 if found else 0.1)),
                       cx=cx, cy=cy)


class TestSelezionaGatheringReport:
    """WU199... (21/07, bug utente) — con altri eventi nel report (es. il
    master, centinaia di Battle Report), Gathering Report NON è l'unico
    elemento della lista flat (assunzione WU199sexies errata): il bot
    scrollava e leggeva la lista sbagliata (0 righe raccolta, osservato live
    sul master). Fix a 2 fasi: fast path OFF (istanze pulite, economico),
    fallback ON+categorie sotto 'Other' (istanze con altri eventi)."""

    def test_fast_path_off_trova_subito(self):
        """Istanza pulita: Gathering Report visibile subito con Sort Mail
        OFF, nessun bisogno di toggle/categorie/scroll."""
        device = FakeDevice()
        for _ in range(3):  # toggle-off check, ricerca, conferma header
            device.add_screenshot(Screenshot(_frame()))
        matcher = FakeMatcher()
        matcher.set_result(PIN_GATHERING_REPORT, (150, 300))
        matcher.set_result(PIN_GATHERING_HEADER, (400, 75))
        ctx = _FakeCtx(device, matcher=matcher)

        ok = _seleziona_gathering_report(ctx, device, lambda m: None)

        assert ok is True
        assert device.taps == [(150, 300)]   # nessun toggle (già OFF, frame nero)

    def test_fast_path_off_fallito_other_mai_trovata_abort_sicuro(self):
        """Nessun altro evento visibile MA Gathering Report introvabile
        anche a categorie ('Other' mai rilevata, es. report vuoto/anomalo)
        -> abort dopo MAX tentativi, nessuna azione distruttiva."""
        device = FakeDevice()
        # toggle-off(1) + ricerca-off(1) + toggle-on(1) + N iterazioni (1 ciascuna)
        for _ in range(3 + MAX_TENTATIVI_GATHERING):
            device.add_screenshot(Screenshot(_frame()))
        matcher = FakeMatcher()  # nulla configurato -> tutto not-found
        ctx = _FakeCtx(device, matcher=matcher)

        with patch("shared.report_raccolta.time.sleep"):   # MAX_TENTATIVI_GATHERING iterazioni, no wall-clock reale
            ok = _seleziona_gathering_report(ctx, device, lambda m: None)

        assert ok is False
        # unico tap: il toggle Sort Mail (OFF->ON, frame nero rilevato OFF)
        # per entrare nella vista a categorie — MAI un tap su Gathering o
        # Other (mai trovati): sicuro.
        assert device.taps == [TAP_SORT_MAIL]
        assert len(device.swipe_calls) == MAX_TENTATIVI_GATHERING

    def test_categorie_other_chiusa_poi_aperta_poi_gathering_trovato(self):
        """Fallback completo: fast path OFF miss -> 'Other' chiusa (tap per
        aprire) -> 'Other' aperta ma Gathering Report sotto il fold (scroll)
        -> Gathering Report trovato e confermato. Replica esatta il flusso
        osservato live sul master (screenshot reali 21/07)."""
        device = FakeDevice()
        for _ in range(7):
            device.add_screenshot(Screenshot(_frame()))
        matcher = _SeqMatcher({
            PIN_GATHERING_REPORT: [
                _mr(False),   # FASE1 (OFF): non trovato
                _mr(False),   # FASE2 iter1: non trovato
                _mr(False),   # FASE2 iter2: non trovato
                _mr(True, 204, 424),   # FASE2 iter3: trovato
            ],
            PIN_REPORT_OTHER: [
                _mr(True, 73, 298),   # iter1
                _mr(True, 73, 298),   # iter2
            ],
            PIN_CHEVRON_UP: [
                _mr(False),   # iter1: 'Other' chiusa
                _mr(True),    # iter2: 'Other' aperta
            ],
            PIN_GATHERING_HEADER: [
                _mr(True),    # conferma finale
            ],
        })
        ctx = _FakeCtx(device, matcher=matcher)

        ok = _seleziona_gathering_report(ctx, device, lambda m: None)

        assert ok is True
        # toggle Sort Mail ON + tap 'Other' (apertura, iter1) + tap
        # Gathering Report (iter3)
        assert device.taps == [TAP_SORT_MAIL, (73, 298), (204, 424)]
        assert len(device.swipe_calls) == 1   # 1 scroll (iter2, 'Other' aperta ma GR sotto il fold)


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

        nomail_calls = {"n": 0}

        def _ocr_side_effect(frame, roi, cfg):
            if roi == (95, 62, 260, 82):  # ROI_TAB_LABEL
                calls["n"] += 1
                return "" if calls["n"] == 1 else "Sort Mail"  # fallisce 1a volta, ok al retry
            if roi == (330, 220, 950, 280):  # ROI_NO_MAIL
                # WU257 (24/07): 1a chiamata = check "report vuoto" pre-
                # selezione (deve dire NON vuoto, per proseguire verso
                # _seleziona_gathering_report); 2a chiamata = dentro
                # _elimina_report_letto dopo il delete (deve dire vuoto,
                # per confermare delete_ok=True).
                nomail_calls["n"] += 1
                return "" if nomail_calls["n"] == 1 else "No mail received"
            return ""

        # screenshot in ordine: check tab iniziale (fail), check tab retry
        # (ok), check toggle Sort Mail dentro _assicura_sort_mail_off
        # (pixel, non OCR -- frame nero = toggle OFF, nessun tap), ricerca
        # Gathering Report (fast path OFF, matcher configurato -> trovato),
        # conferma header, check finale dentro _elimina_report_letto
        # ("No mail received")
        for _ in range(6):
            device.add_screenshot(Screenshot(_frame()))
        matcher = FakeMatcher()
        matcher.set_result(PIN_GATHERING_REPORT, (150, 300))
        matcher.set_result(PIN_GATHERING_HEADER, (400, 75))
        ctx = _FakeCtx(device, matcher=matcher)

        with patch("shared.report_raccolta._ocr_raw", side_effect=_ocr_side_effect):
            esito = esegui_report_raccolta(ctx, solo_reset=True)

        assert esito["errore"] is None
        assert esito["delete_ok"] is True
        assert TAP_READ_CLAIM_ALL in device.taps
        assert TAP_DELETE_READ in device.taps


class TestEseguiReportRaccoltaAbortSuGatheringNonTrovato:
    """WU199... (21/07, bug utente) — tab OK ma Gathering Report non
    selezionabile (nessun match, né OFF né tra le categorie ON): mai
    un'azione distruttiva (Read/Delete) su una selezione non confermata —
    stesso principio di sicurezza di TestEseguiReportRaccoltaAbortSuTabSbagliato,
    applicato al passo successivo (selezione del thread, non solo il tab)."""

    def test_gathering_non_trovato_nessun_tap_distruttivo(self):
        device = FakeDevice()
        # tab ok(1) + toggle-off(1) + ricerca-off(1) + toggle-on(1)
        # + N iterazioni categorie (1 ciascuna, tutte a vuoto)
        for _ in range(4 + MAX_TENTATIVI_GATHERING):
            device.add_screenshot(Screenshot(_frame()))
        matcher = FakeMatcher()   # nulla configurato -> mai trovato
        ctx = _FakeCtx(device, matcher=matcher)

        with patch("shared.report_raccolta._ocr_raw", side_effect=_ocr_tab_e_nomail()), \
             patch("shared.report_raccolta.time.sleep"):   # MAX_TENTATIVI_GATHERING iterazioni, no wall-clock reale
            esito = esegui_report_raccolta(ctx, solo_reset=True)

        assert TAP_READ_CLAIM_ALL not in device.taps
        assert TAP_DELETE_READ not in device.taps
        assert esito["errore"] == "gathering_report_non_selezionato"
        assert esito["delete_ok"] is None
        # naviga, tenta la selezione, poi si richiude in sicurezza (Alliance + close)
        assert device.taps[-2:] == [TAP_TAB_ALLIANCE, TAP_CLOSE]


class TestScrollFermoConfermaFineLista:
    """WU199duodecies: idea utente 11/07 -- se lo scroll produce la stessa
    pagina di prima (stesso giro di lettura), è un segnale locale e
    affidabile che siamo in fondo alla lista (il gioco non scrolla oltre).
    Sostituisce il vecchio check contro lo storico globale (poteva
    scattare a metà lista rileggendo una riga nota da tempo)."""

    def _righe_full_page(self, prefix, ts_base):
        return [
            _riga(f"70{i}_50{i}", f"2026-07-11T0{ts_base}:0{i}:00+00:00")
            for i in range(4)
        ]

    def _matcher_fast_path(self) -> FakeMatcher:
        """Matcher configurato per far succedere il fast path OFF di
        _seleziona_gathering_report al primo colpo (nessuno swipe/tap
        aggiuntivo rispetto al comportamento pre-fix — questi test coprono
        la logica dedup/scroll della LETTURA pagine, non la selezione)."""
        matcher = FakeMatcher()
        matcher.set_result(PIN_GATHERING_REPORT, (150, 300))
        matcher.set_result(PIN_GATHERING_HEADER, (400, 75))
        return matcher

    def test_pagina_identica_dopo_scroll_conferma_fine_lista(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame()))  # tab check
        device.add_screenshot(Screenshot(_frame()))  # toggle-off check
        device.add_screenshot(Screenshot(_frame()))  # ricerca Gathering Report (fast path)
        device.add_screenshot(Screenshot(_frame()))  # conferma header
        device.add_screenshot(Screenshot(_frame()))  # pagina 1
        device.add_screenshot(Screenshot(_frame()))  # pagina 2 (identica)
        device.add_screenshot(Screenshot(_frame()))  # finale _elimina_report_letto
        ctx = _FakeCtx(device, matcher=self._matcher_fast_path())

        pagina = self._righe_full_page("70", 1)

        with patch("shared.report_raccolta._ocr_raw", side_effect=_ocr_tab_e_nomail()), \
             patch("shared.report_raccolta.leggi_pagina", side_effect=[pagina, pagina]):
            esito = esegui_report_raccolta(ctx, solo_reset=False)

        assert esito["pagine"] == 2
        assert esito["fine_lista_raggiunta"] is True
        assert esito["delete_ok"] is True
        assert esito["nuove"] == 4  # solo dalla prima pagina, la seconda è tutta dedup
        # 1 solo swipe: quello tra pagina 1 e 2 (il fast path OFF non scrolla)
        assert len(device.swipe_calls) == 1

    def test_pagine_diverse_non_scattano_falso_positivo(self):
        device = FakeDevice()
        device.add_screenshot(Screenshot(_frame()))  # tab check
        device.add_screenshot(Screenshot(_frame()))  # toggle-off check
        device.add_screenshot(Screenshot(_frame()))  # ricerca Gathering Report (fast path)
        device.add_screenshot(Screenshot(_frame()))  # conferma header
        device.add_screenshot(Screenshot(_frame()))  # pagina 1
        device.add_screenshot(Screenshot(_frame()))  # pagina 2 (diversa)
        ctx = _FakeCtx(device, matcher=self._matcher_fast_path())

        pagina1 = self._righe_full_page("70", 1)
        pagina2 = [
            _riga(f"71{i}_51{i}", f"2026-07-11T0{2}:0{i}:00+00:00")
            for i in range(4)
        ]

        with patch("shared.report_raccolta._ocr_raw", side_effect=_ocr_tab_e_nomail()), \
             patch("shared.report_raccolta.leggi_pagina", side_effect=[pagina1, pagina2]):
            esito = esegui_report_raccolta(ctx, solo_reset=False)

        assert esito["fine_lista_raggiunta"] is False
        assert esito["delete_ok"] is None
        assert esito["pagine"] == 2
        assert esito["nuove"] == 8
