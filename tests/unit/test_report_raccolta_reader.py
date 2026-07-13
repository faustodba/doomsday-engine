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


class TestGetProduzioneUnificataShaping:
    """WU204: get_produzione_unificata è ora solo lo SHAPING sopra
    shared.produzione_report.produzione_per_istanza (esclusione master,
    completamento colonne config a zero, totali). La lettura report è testata
    in test_produzione_report.py."""

    def _p(self, **risorse):
        r = {"pomodoro": 0.0, "legno": 0.0, "acciaio": 0.0, "petrolio": 0.0}
        r.update(risorse)
        pom_eq = r["pomodoro"] * 1 + r["legno"] * 1 + r["acciaio"] * 2 + r["petrolio"] * 5
        return {"risorse": r, "qta_h": {k: v / 24.0 for k, v in r.items()},
                "pom_eq_h": pom_eq / 24.0 / 1_000_000, "n_report": 1}

    def _run(self, monkeypatch, per_istanza, cfg_nomi=None):
        monkeypatch.setattr(
            "shared.produzione_report.produzione_per_istanza",
            lambda **kw: {"per_istanza": per_istanza, "den_h": 24.0, "modalita": "rolling"})
        monkeypatch.setattr("shared.instance_meta.is_master_instance",
                            lambda n: n == "FauMorfeus")
        monkeypatch.setattr("dashboard.services.config_manager.get_instances",
                            lambda: [{"nome": n} for n in (cfg_nomi or [])])
        return rr.get_produzione_unificata()

    def test_master_escluso_e_totale_solo_ordinarie(self, monkeypatch):
        per = {"FAU_00": self._p(petrolio=264_000, pomodoro=1_320_000),
               "FauMorfeus": self._p(legno=1_320_000)}
        d = self._run(monkeypatch, per)
        nomi = [x["nome"] for x in d["per_istanza"]]
        assert "FauMorfeus" not in nomi
        assert nomi == ["FAU_00"]
        atteso = (1_320_000 * 1 + 264_000 * 5) / 24 / 1_000_000
        assert abs(d["per_istanza"][0]["prod_unif_h"] - atteso) < 1e-9
        assert abs(d["totale_prod_unif_h"] - atteso) < 1e-9   # master NON nel totale

    def test_completamento_colonne_config_a_zero(self, monkeypatch):
        per = {"FAU_00": self._p(petrolio=264_000)}
        d = self._run(monkeypatch, per, cfg_nomi=["FAU_00", "FAU_05"])
        nomi = [x["nome"] for x in d["per_istanza"]]
        assert nomi == ["FAU_00", "FAU_05"]        # FAU_05 presente anche senza report
        f5 = next(x for x in d["per_istanza"] if x["nome"] == "FAU_05")
        assert f5["prod_unif_h"] == 0.0
        assert all(f5["per_risorsa"][r]["qta_h"] == 0.0
                   for r in ("pomodoro", "legno", "acciaio", "petrolio"))

    def test_nessun_dato_ritorna_struttura_vuota(self, monkeypatch):
        d = self._run(monkeypatch, {})
        assert d["per_istanza"] == []
        assert d["totale_prod_unif_h"] == 0.0
