# ==============================================================================
#  tests/unit/test_calc_t_marcia_tiered.py
#
#  Unit test per core.skip_predictor._calc_t_marcia_min dopo WU223 Fase C
#  (15/07): EMPIRICO PERMANENTE. Rimossi flag `tempo_raccolta_empirico_enabled`
#  e modello statico (formula + calibrazione closed-loop). La stima viene solo
#  da stima_tempo_raccolta; ultima spiaggia = costante _FALLBACK_RACCOLTA_MIN.
# ==============================================================================

from unittest.mock import patch

from core.skip_predictor import _calc_t_marcia_min, _FALLBACK_RACCOLTA_MIN


def _invio(tipo="petrolio", livello=7, load=264_000, eta_s=120):
    return {"tipo": tipo, "livello": livello, "load_squadra": load,
            "eta_marcia_s": eta_s}


class TestCalcTMarciaFaseC:

    def test_empirico_primario_quando_cella_disponibile(self):
        """Stima disponibile → durata_s/60 + eta_ritorno (eta, non 2×eta)."""
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=9000.0):          # 150 min
            r = _calc_t_marcia_min(_invio(eta_s=120), "FAU_TEST")
        # 9000s/60 + 120s/60 = 150 + 2 = 152.0 min
        assert abs(r - 152.0) < 1e-6

    def test_fallback_costante_quando_cella_scarna(self):
        """Stima→None ma (tipo,livello) valido → costante farm + eta_ritorno
        (non più la formula statica, rimossa in Fase C)."""
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=None):
            r = _calc_t_marcia_min(_invio(eta_s=120), "FAU_TEST")
        assert abs(r - (_FALLBACK_RACCOLTA_MIN + 2.0)) < 1e-6

    def test_empirico_copre_invio_senza_load_squadra(self):
        """L'empirico non richiede load_squadra: copre gli invii pre-WU116."""
        invio_no_load = {"tipo": "petrolio", "livello": 7, "eta_marcia_s": 60}
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=7200.0):
            r = _calc_t_marcia_min(invio_no_load, "FAU_TEST")
        assert abs(r - (7200.0 / 60.0 + 1.0)) < 1e-6   # 120 + 1 = 121.0

    def test_fallback_costante_copre_invio_senza_load(self):
        """Anche senza load_squadra e senza dati empirici → costante (mai None
        per un invio con tipo+livello validi). Prima della Fase C lo statico
        ritornava None qui."""
        invio_no_load = {"tipo": "petrolio", "livello": 7, "eta_marcia_s": 0}
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=None):
            r = _calc_t_marcia_min(invio_no_load, "FAU_TEST")
        assert abs(r - _FALLBACK_RACCOLTA_MIN) < 1e-6

    def test_livello_mancante_ritorna_none(self):
        """Invio degenere (livello < 1) → None, i chiamanti lo trattano come
        'già rientrato'. Lo stimatore non viene nemmeno interpellato."""
        invio_no_lv = {"tipo": "petrolio", "load_squadra": 264_000, "eta_marcia_s": 60}
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta") as m_emp:
            assert _calc_t_marcia_min(invio_no_lv, "FAU_TEST") is None
        assert m_emp.call_count == 0

    def test_tipo_mancante_ritorna_none(self):
        """Invio senza tipo → None (nessuna stima possibile)."""
        invio_no_tipo = {"livello": 7, "load_squadra": 264_000, "eta_marcia_s": 60}
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta") as m_emp:
            assert _calc_t_marcia_min(invio_no_tipo, "FAU_TEST") is None
        assert m_emp.call_count == 0
