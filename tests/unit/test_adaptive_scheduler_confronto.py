# ==============================================================================
#  tests/unit/test_adaptive_scheduler_confronto.py
#
#  Unit test per il campo "confronto_tempo_raccolta" aggiunto a
#  compute_slot_liberi_atteso() (WU200ter, 11/07) — verifica che sia
#  puramente osservativo: presente/assente a seconda della disponibilità
#  dello stimatore, ma non altera MAI t_residue_min/rientro_atteso/
#  slot_liberi_atteso (nessuna regressione sul comportamento esistente).
# ==============================================================================

from datetime import datetime, timezone
from unittest.mock import patch

from core.adaptive_scheduler import compute_slot_liberi_atteso


def _record(tipo="petrolio", livello=7, load=264_000, eta_s=120, minuti_fa=10):
    ts = datetime.now(timezone.utc).isoformat()
    ts_invio = (datetime.now(timezone.utc)).isoformat()
    return {
        "ts": ts,
        "raccolta": {
            "totali": 5,
            "attive_post": 3,
            "invii": [
                {"tipo": tipo, "livello": livello, "load_squadra": load,
                 "eta_marcia_s": eta_s, "ts_invio": ts_invio, "cap_nodo": 264_000},
            ],
        },
    }


class TestConfrontoTempoRaccoltaOsservativo:

    def test_campo_presente_con_stima_disponibile(self):
        with patch("core.skip_predictor.load_metrics_history", return_value=[_record()]), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta", return_value=7200.0):
            out = compute_slot_liberi_atteso("FAU_TEST")

        assert "confronto_tempo_raccolta" in out
        assert len(out["confronto_tempo_raccolta"]) == 1
        voce = out["confronto_tempo_raccolta"][0]
        assert voce["tipo"] == "petrolio"
        assert voce["livello"] == 7
        assert voce["t_emp_min"] > 0

    def test_campo_vuoto_se_stimatore_non_ha_dati(self):
        with patch("core.skip_predictor.load_metrics_history", return_value=[_record()]), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta", return_value=None):
            out = compute_slot_liberi_atteso("FAU_TEST")

        assert out["confronto_tempo_raccolta"] == []

    def test_altri_campi_invariati_indipendentemente_dal_confronto(self):
        """Nessuna regressione: t_residue_min/rientro_atteso/slot_liberi_atteso
        devono essere identici con o senza il nuovo campo disponibile."""
        with patch("core.skip_predictor.load_metrics_history", return_value=[_record()]), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta", return_value=7200.0):
            out_con_stima = compute_slot_liberi_atteso("FAU_TEST")

        with patch("core.skip_predictor.load_metrics_history", return_value=[_record()]), \
             patch("shared.tempo_raccolta_estimator.stima_tempo_raccolta", return_value=None):
            out_senza_stima = compute_slot_liberi_atteso("FAU_TEST")

        for campo in ("t_residue_min", "rientro_atteso", "slot_liberi_atteso",
                      "score", "attive_now", "totali"):
            assert out_con_stima[campo] == out_senza_stima[campo], campo

    def test_import_fallito_non_solleva(self):
        """Se shared.tempo_raccolta_estimator non e' importabile, il resto
        della funzione deve continuare a funzionare normalmente."""
        with patch("core.skip_predictor.load_metrics_history", return_value=[_record()]), \
             patch.dict("sys.modules", {"shared.tempo_raccolta_estimator": None}):
            out = compute_slot_liberi_atteso("FAU_TEST")
        assert out["confronto_tempo_raccolta"] == []
        assert out["data_completa"] is True
