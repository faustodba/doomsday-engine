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


class TestGetProduzioneUnificataDaReport:
    """WU200 finalità 2 (13/07): produzione oraria unificata dal Tab Report
    (quantita_totale raccolte reali), immune ad anomalie castello."""

    def _rows(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        def _r(inst, tipo, q, ore_fa):
            return {"instance": inst, "tipo": tipo, "quantita_totale": q,
                    "ts_raccolta": (now - timedelta(hours=ore_fa)).isoformat()}
        return [
            _r("FAU_00", "petrolio", 264_000, 1),
            _r("FAU_00", "campo", 1_320_000, 2),
            _r("FAU_00", "petrolio", 264_000, 30),    # fuori finestra 24h -> ignorato
            _r("FauMorfeus", "campo", 1_320_000, 1),  # master -> escluso
        ]

    def _run(self, monkeypatch, rows):
        monkeypatch.setattr(rr, "_load_jsonl", lambda p: rows)
        monkeypatch.setattr("shared.instance_meta.is_master_instance",
                            lambda n: n == "FauMorfeus")
        monkeypatch.setattr("dashboard.services.config_manager.get_instances",
                            lambda: [])
        return rr.get_produzione_unificata()

    def test_master_esclusa_e_finestra_applicata(self, monkeypatch):
        d = self._run(monkeypatch, self._rows())
        nomi = [r["nome"] for r in d["per_istanza"]]
        assert "FauMorfeus" not in nomi       # master escluso dagli aggregati
        assert nomi == ["FAU_00"]

    def test_pesi_pom_eq_e_normalizzazione_oraria(self, monkeypatch):
        d = self._run(monkeypatch, self._rows())
        f0 = d["per_istanza"][0]
        # pom_eq = campo(1.32M×1) + petrolio(264K×5, solo la riga entro 24h) ;
        # la riga petrolio a 30h fa NON conta.
        atteso = (1_320_000 * 1 + 264_000 * 5) / 24 / 1_000_000
        assert abs(f0["prod_unif_h"] - atteso) < 1e-9
        # campo -> pomodoro, petrolio -> petrolio; quantità orarie
        assert abs(f0["per_risorsa"]["pomodoro"]["qta_h"] - 1_320_000 / 24) < 1e-6
        assert abs(f0["per_risorsa"]["petrolio"]["qta_h"] - 264_000 / 24) < 1e-6

    def test_nessun_dato_ritorna_struttura_vuota(self, monkeypatch):
        d = self._run(monkeypatch, [])
        assert d["per_istanza"] == []
        assert d["totale_prod_unif_h"] == 0.0
