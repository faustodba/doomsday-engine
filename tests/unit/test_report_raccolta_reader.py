# ==============================================================================
#  tests/unit/test_report_raccolta_reader.py
#
#  Unit test per il pivot get_stima_matrice() (WU202d) —
#  dashboard/services/report_raccolta_reader.py.
# ==============================================================================

from unittest.mock import patch

from dashboard.services import report_raccolta_reader as rr


def _cella(inst, tipo, liv, med_h, n):
    return {"instance": inst, "tipo": tipo, "livello": liv, "n": n,
            "mediana_h": med_h, "media_h": med_h, "min_h": med_h, "max_h": med_h,
            "affidabile": n >= 3}


class TestGetStimaMatrice:

    def _matrice(self, flat):
        with patch.object(rr, "get_stima_per_cella", return_value=flat):
            return rr.get_stima_matrice()

    def test_righe_ordine_fisso_8_con_label(self):
        m = self._matrice([_cella("FAU_00", "campo", 7, 2.0, 5)])
        ordine = [(r["tipo"], r["livello"]) for r in m["righe"]]
        assert ordine == [("campo", 6), ("campo", 7), ("segheria", 6), ("segheria", 7),
                          ("acciaio", 6), ("acciaio", 7), ("petrolio", 6), ("petrolio", 7)]
        lab = {r["tipo"]: r["label"] for r in m["righe"]}
        assert lab["campo"] == "pomodoro"
        assert lab["segheria"] == "legno"
        assert lab["petrolio"] == "petrolio"

    def test_colonne_istanze_ordinate_e_deduplicate(self):
        m = self._matrice([
            _cella("FAU_02", "petrolio", 7, 3.0, 4),
            _cella("FAU_00", "petrolio", 7, 2.5, 4),
            _cella("FAU_00", "campo", 6, 2.4, 3),
        ])
        assert m["istanze"] == ["FAU_00", "FAU_02"]

    def test_scala_solo_su_celle_affidabili(self):
        m = self._matrice([
            _cella("FAU_00", "campo", 7, 2.0, 5),      # affidabile
            _cella("FAU_00", "petrolio", 7, 3.0, 5),   # affidabile
            _cella("FAU_00", "acciaio", 6, 9.0, 1),    # n<3: NON entra nella scala
        ])
        assert abs(m["min_h"] - 2.0) < 1e-9
        assert abs(m["max_h"] - 3.0) < 1e-9

    def test_bucket_estremi_e_none_se_non_affidabile(self):
        m = self._matrice([
            _cella("FAU_00", "campo", 7, 2.0, 5),      # min -> bucket 0
            _cella("FAU_00", "petrolio", 7, 3.0, 5),   # max -> bucket 4
            _cella("FAU_00", "petrolio", 6, 2.5, 5),   # medio -> bucket 2
            _cella("FAU_00", "acciaio", 6, 2.6, 1),    # n<3 -> bucket None
        ])
        def cella(tipo, liv):
            r = next(r for r in m["righe"] if (r["tipo"], r["livello"]) == (tipo, liv))
            return r["celle"]["FAU_00"]
        assert cella("campo", 7)["bucket"] == 0
        assert cella("petrolio", 7)["bucket"] == 4
        assert cella("petrolio", 6)["bucket"] == 2
        assert cella("acciaio", 6)["bucket"] is None   # poco affidabile: niente heat

    def test_cella_assente_non_presente_nel_dict(self):
        m = self._matrice([_cella("FAU_00", "campo", 7, 2.0, 5)])
        riga = next(r for r in m["righe"] if (r["tipo"], r["livello"]) == ("campo", 7))
        assert "FAU_00" in riga["celle"]
        # livello/tipo senza dati: nessuna cella
        riga_vuota = next(r for r in m["righe"] if (r["tipo"], r["livello"]) == ("legno", 6) or (r["tipo"], r["livello"]) == ("segheria", 6))
        assert riga_vuota["celle"] == {}

    def test_dataset_vuoto_matrice_valida(self):
        m = self._matrice([])
        assert m["istanze"] == []
        assert len(m["righe"]) == 8
        assert all(r["celle"] == {} for r in m["righe"])
