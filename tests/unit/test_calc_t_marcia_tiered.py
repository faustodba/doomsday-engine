# ==============================================================================
#  tests/unit/test_calc_t_marcia_tiered.py
#
#  Unit test per la logica TIERED di core.skip_predictor._calc_t_marcia_min
#  (WU200 Fase B, 12/07): stima empirica primaria (flag ON + cella con dati),
#  fallback alla formula statica (flag OFF, o cella sotto soglia). Verifica
#  il vincolo cardine: con flag OFF il comportamento è byte-identico alla
#  versione pre-Fase B (zero regressione).
# ==============================================================================

from unittest.mock import patch

from core.skip_predictor import _calc_t_marcia_min


def _invio(tipo="petrolio", livello=7, load=264_000, eta_s=120):
    return {"tipo": tipo, "livello": livello, "load_squadra": load,
            "eta_marcia_s": eta_s}


class TestCalcTMarciaTiered:

    def test_flag_off_usa_formula_statica(self):
        """Flag OFF → percorso statico (nessun uso dello stimatore empirico)."""
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=False), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta") as m_emp:
            r = _calc_t_marcia_min(_invio(), "FAU_TEST")
        assert m_emp.call_count == 0          # lo stimatore NON viene interpellato
        assert r is not None and r > 0

    def test_fallback_identico_allo_statico_quando_cella_scarna(self):
        """Flag ON ma cella senza abbastanza campioni (stima→None): il
        risultato deve essere IDENTICO al percorso statico (flag OFF)."""
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=False):
            r_static = _calc_t_marcia_min(_invio(), "FAU_TEST")
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=True), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=None):
            r_fallback = _calc_t_marcia_min(_invio(), "FAU_TEST")
        assert r_fallback == r_static

    def test_empirico_primario_quando_cella_disponibile(self):
        """Flag ON + stima disponibile → durata_s/60 + eta_ritorno (eta, non 2×eta)."""
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=True), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=9000.0):          # 150 min
            r = _calc_t_marcia_min(_invio(eta_s=120), "FAU_TEST")
        # 9000s/60 + 120s/60 = 150 + 2 = 152.0 min
        assert abs(r - 152.0) < 1e-6

    def test_empirico_copre_invio_senza_load_squadra(self):
        """L'empirico non richiede load_squadra: copre invii pre-WU116 dove
        il fallback statico ritornerebbe None."""
        invio_no_load = {"tipo": "petrolio", "livello": 7, "eta_marcia_s": 60}
        # flag OFF: statico senza load → None
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=False):
            assert _calc_t_marcia_min(invio_no_load, "FAU_TEST") is None
        # flag ON con stima: ritorna il valore empirico (non None)
        with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                   return_value=True), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                   return_value=7200.0):
            r = _calc_t_marcia_min(invio_no_load, "FAU_TEST")
        assert abs(r - (7200.0 / 60.0 + 1.0)) < 1e-6   # 120 + 1 = 121.0

    def test_livello_mancante_ritorna_none_in_entrambe_le_modalita(self):
        invio_no_lv = {"tipo": "petrolio", "load_squadra": 264_000, "eta_marcia_s": 60}
        for flag in (True, False):
            with patch("core.skip_predictor._tempo_raccolta_empirico_attivo",
                       return_value=flag), \
                 patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                       return_value=7200.0):
                assert _calc_t_marcia_min(invio_no_lv, "FAU_TEST") is None

    def test_flag_default_off_da_config(self):
        """Sanity: senza mock, il flag deve risolvere a False (default sicuro),
        quindi lo stimatore non viene interpellato per un invio normale."""
        # forza refresh cache flag
        import core.skip_predictor as sp
        sp._tr_empirico_cache["value"] = None
        with patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta") as m_emp:
            _calc_t_marcia_min(_invio(), "FAU_TEST")
        assert m_emp.call_count == 0
