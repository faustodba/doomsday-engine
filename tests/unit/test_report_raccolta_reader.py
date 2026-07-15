# ==============================================================================
#  tests/unit/test_report_raccolta_reader.py
#
#  Unit test per dashboard/services/report_raccolta_reader.py:
#    - get_stima_matrice()      (WU202d)
#    - get_produzione_unificata (WU204, shaping)
#    - get_occupati_in_volo()   (WU226, classificazione stati + master escluso)
# ==============================================================================

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from dashboard.services import report_raccolta_reader as rr


class TestGetOccupatiInVoloStati:
    """WU226 (15/07) — il pannello marcava ogni residuo negativo come "in
    ritardo di N min" e ordinava per quel numero, mettendo in testa proprio le
    voci prive di significato (segnalato dall'utente). Un residuo negativo di
    solito misura solo che l'istanza non è ancora ripassata a leggere il tab
    Report: il completamento non esiste finché non lo si legge (WU225). La
    discriminante vera è "l'istanza ha riletto DOPO la fine prevista?"."""

    ORA = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def _run(self, monkeypatch, invii, letture, stima_s=3 * 3600):
        """invii: [(istanza, coord, tipo, livello, ore_fa)]
           letture: {istanza: [ore_fa, ...]} — quando ha letto il tab Report"""
        pending = {}
        for inst, coord, tipo, lv, ore_fa in invii:
            ts = (self.ORA - timedelta(hours=ore_fa)).isoformat()
            pending.setdefault(f"{inst}|{coord}|{tipo}", []).append({"ts": ts, "livello": lv})
        monkeypatch.setattr(rr, "_load_state", lambda: {"pending": pending})
        monkeypatch.setattr(rr, "_letture_report_per_istanza",
                            lambda: {i: [self.ORA - timedelta(hours=h) for h in sorted(hs, reverse=True)]
                                     for i, hs in letture.items()})
        monkeypatch.setattr("shared.tempo_raccolta_estimator.stima_tempo_raccolta",
                            lambda i, t, l: stima_s)

        class _Ora(datetime):
            @classmethod
            def now(cls, tz=None):
                return TestGetOccupatiInVoloStati.ORA
        monkeypatch.setattr(rr, "datetime", _Ora)
        return rr.get_occupati_in_volo()

    def test_in_volo_se_stima_non_ancora_scaduta(self, monkeypatch):
        r = self._run(monkeypatch, [("FAU_01", "700_500", "segheria", 7, 1.0)], {})
        assert [x["stato"] for x in r] == ["in_volo"]
        assert r[0]["residuo_min"] > 0

    def test_attesa_lettura_se_scaduta_ma_istanza_non_ripassata(self, monkeypatch):
        # invio 8h fa, stima 3h -> finita 5h fa. Nessuna lettura DOPO la fine.
        r = self._run(monkeypatch, [("FAU_01", "700_500", "segheria", 7, 8.0)],
                      {"FAU_01": [7.0]})   # lettura 7h fa = PRIMA della fine (5h fa)
        assert [x["stato"] for x in r] == ["attesa_lettura"]
        assert r[0]["letture_dopo"] == 0

    def test_orfana_se_istanza_ha_riletto_dopo_la_fine_senza_report(self, monkeypatch):
        # invio 8h fa, stima 3h -> finita 5h fa. Due letture dopo: report mai arrivato.
        r = self._run(monkeypatch, [("FAU_01", "700_500", "segheria", 7, 8.0)],
                      {"FAU_01": [4.0, 1.0]})
        assert [x["stato"] for x in r] == ["orfana"]
        assert r[0]["letture_dopo"] == 2

    def test_confine_lettura_esattamente_alla_fine_non_conta(self, monkeypatch):
        # lettura ESATTAMENTE all'istante di fine: il report non puo' esserci
        # ancora -> non e' orfana (serve `>`, non `>=`).
        r = self._run(monkeypatch, [("FAU_01", "700_500", "segheria", 7, 8.0)],
                      {"FAU_01": [5.0]})
        assert [x["stato"] for x in r] == ["attesa_lettura"]

    def test_senza_stima_se_cella_povera(self, monkeypatch):
        r = self._run(monkeypatch, [("FAU_01", "700_500", "acciaio", 6, 9.0)], {},
                      stima_s=None)
        assert [x["stato"] for x in r] == ["senza_stima"]
        assert r[0]["residuo_min"] is None

    def test_ordine_orfane_poi_in_volo_poi_attesa(self, monkeypatch):
        r = self._run(monkeypatch, [
            ("FAU_01", "700_500", "segheria", 7, 1.0),   # in volo (residuo +120)
            ("FAU_02", "701_500", "segheria", 7, 2.5),   # in volo (residuo +30) -> arriva prima
            ("FAU_03", "702_500", "segheria", 7, 8.0),   # attesa lettura
            ("FAU_04", "703_500", "segheria", 7, 9.0),   # orfana
        ], {"FAU_04": [1.0]})
        assert [x["stato"] for x in r] == ["orfana", "in_volo", "in_volo", "attesa_lettura"]
        # fra gli in volo: prima chi arriva prima
        volo = [x for x in r if x["stato"] == "in_volo"]
        assert volo[0]["instance"] == "FAU_02"

    def test_orfane_ordinate_dalla_piu_vecchia(self, monkeypatch):
        r = self._run(monkeypatch, [
            ("FAU_01", "700_500", "segheria", 7, 8.0),
            ("FAU_02", "701_500", "segheria", 7, 11.0),
        ], {"FAU_01": [1.0], "FAU_02": [1.0]})
        assert [x["instance"] for x in r] == ["FAU_02", "FAU_01"]


class TestSenzaMaster:
    """WU226 — il master (FauMorfeus) è giocato a mano: raccoglitori inviati
    manualmente, gioco chiuso durante gli eventi. `nodi_mappa.ISTANZE_ESCLUSE`
    gli blocca già le OCCUPAZIONI (quindi non entra in match/pending/stime), ma
    i suoi REPORT venivano scritti e finivano in riepilogo e timeline."""

    def test_filtra_solo_il_master(self, monkeypatch):
        monkeypatch.setattr("shared.instance_meta.is_master_instance",
                            lambda n: n == "FauMorfeus")
        righe = [{"instance": "FAU_00"}, {"instance": "FauMorfeus"}, {"instance": "FAU_05"}]
        assert [r["instance"] for r in rr._senza_master(righe)] == ["FAU_00", "FAU_05"]

    def test_instance_mancante_non_esplode(self, monkeypatch):
        monkeypatch.setattr("shared.instance_meta.is_master_instance",
                            lambda n: n == "FauMorfeus")
        assert rr._senza_master([{"instance": None}, {}]) == [{"instance": None}, {}]


class TestLettureReportPerIstanza:
    """WU226 — le righe lette nella stessa passata condividono il boot: si
    raggruppano per gap > 60 min."""

    def test_raggruppa_per_passata_e_separa_i_boot(self, monkeypatch):
        base = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
        rep = [
            {"instance": "FAU_00", "ts_ocr": base.isoformat()},
            {"instance": "FAU_00", "ts_ocr": (base + timedelta(minutes=2)).isoformat()},
            {"instance": "FAU_00", "ts_ocr": (base + timedelta(hours=4)).isoformat()},
            {"instance": "FAU_05", "ts_ocr": (base + timedelta(minutes=30)).isoformat()},
        ]
        monkeypatch.setattr(rr, "_load_jsonl", lambda p: rep)
        out = rr._letture_report_per_istanza()
        assert len(out["FAU_00"]) == 2      # 2 passate, non 3 righe
        assert len(out["FAU_05"]) == 1


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
