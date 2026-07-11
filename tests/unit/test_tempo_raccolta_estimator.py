# ==============================================================================
#  tests/unit/test_tempo_raccolta_estimator.py
#
#  Unit test per shared/tempo_raccolta_estimator.py (WU200).
# ==============================================================================

import json
from pathlib import Path

import pytest

from shared.tempo_raccolta_estimator import (
    esegui_riconciliazione,
    stima_tempo_raccolta,
    _leggi_righe_nuove,
)


@pytest.fixture(autouse=True)
def _isola_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    return tmp_path


def _scrivi_jsonl(path: Path, righe: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in righe:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _occ(instance, chiave, ts, tipo="petrolio", livello=7, esito="occupato"):
    return {"ts": ts, "instance": instance, "chiave": chiave, "tipo": tipo,
            "livello": livello, "esito": esito}


def _report(instance, coordinata, ts_raccolta, tipo="petrolio", livello=7):
    return {"ts_ocr": ts_raccolta, "instance": instance, "coordinata": coordinata,
            "tipo": tipo, "livello": livello, "ts_raccolta": ts_raccolta,
            "quantita_base": 264000, "quantita_bonus": 0,
            "quantita_totale": 264000, "valore_alleanza": 2640}


class TestLeggiRigheNuove:

    def test_file_assente_ritorna_vuoto(self, tmp_path):
        righe, cursor = _leggi_righe_nuove(tmp_path / "assente.jsonl", 0)
        assert righe == []
        assert cursor == 0

    def test_legge_solo_righe_nuove_dal_cursore(self, tmp_path):
        p = tmp_path / "data.jsonl"
        _scrivi_jsonl(p, [{"a": 1}, {"a": 2}])
        righe1, cursor1 = _leggi_righe_nuove(p, 0)
        assert len(righe1) == 2
        _scrivi_jsonl(p, [{"a": 3}])
        righe2, cursor2 = _leggi_righe_nuove(p, cursor1)
        assert righe2 == [{"a": 3}]
        assert cursor2 > cursor1

    def test_riga_incompleta_non_avanza_cursore(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_bytes(b'{"a": 1}\n{"a": 2}')  # ultima riga senza newline
        righe, cursor = _leggi_righe_nuove(p, 0)
        assert righe == [{"a": 1}]
        # il cursore non deve aver consumato la riga incompleta
        with p.open("rb") as f:
            f.seek(cursor)
            resto = f.read()
        assert resto == b'{"a": 2}'

    def test_riga_malformata_scartata(self, tmp_path):
        p = tmp_path / "data.jsonl"
        p.write_bytes(b'{"a": 1}\nnon e json valido\n{"a": 2}\n')
        righe, _ = _leggi_righe_nuove(p, 0)
        assert righe == [{"a": 1}, {"a": 2}]


class TestEseguiRiconciliazione:

    def test_match_semplice_1v1(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),
        ])
        esito = esegui_riconciliazione()
        assert esito["errore"] is None
        assert esito["match_nuovi"] == 1
        assert esito["report_orfane"] == 0
        assert esito["pending_attuali"] == 0

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["instance"] == "FAU_00"
        assert rec["coordinata"] == "700_500"
        assert rec["durata_s"] == 3 * 3600

    def test_report_senza_occupazione_e_orfana(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 0
        assert esito["report_orfane"] == 1

    def test_occupazione_senza_report_resta_pending(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 0
        assert esito["pending_attuali"] == 1

    def test_due_occupazioni_stesso_nodo_match_su_piu_recente_precedente(self, tmp_path):
        """Scenario segnalato dall'utente: nodo rioccupato prima del match
        della prima occupazione. Il report va abbinato all'occupazione
        piu' recente TRA quelle precedenti al completamento, non alla
        prima trovata."""
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
            _occ("FAU_00", "700_500", "2026-07-11T02:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 1
        assert esito["pending_attuali"] == 1  # la piu' vecchia (01:00) resta orfana

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["ts_invio"] == "2026-07-11T02:00:00+00:00"
        assert rec["durata_s"] == 2 * 3600

    def test_occupazione_riusata_rimossa_dal_pool(self, tmp_path):
        """Un'occupazione consumata da un match non deve mai essere
        riusata per un secondo match (stesso giro o giro successivo)."""
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),
        ])
        esegui_riconciliazione()
        # secondo report sullo stesso nodo, nessuna nuova occupazione nel frattempo
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T07:00:00+00:00"),
        ])
        esito2 = esegui_riconciliazione()
        assert esito2["match_nuovi"] == 0
        assert esito2["report_orfane"] == 1

    def test_pruning_occupazioni_orfane_scadute(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        ts_vecchia = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", ts_vecchia),
        ])
        esito = esegui_riconciliazione(ttl_ore=6.0)
        assert esito["occupazioni_potate"] == 1
        assert esito["pending_attuali"] == 0

    def test_idempotente_senza_dati_nuovi(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),
        ])
        esito1 = esegui_riconciliazione()
        esito2 = esegui_riconciliazione()
        assert esito1["match_nuovi"] == 1
        assert esito2["match_nuovi"] == 0
        assert esito2["report_orfane"] == 0

    def test_esito_non_solleva_su_file_corrotto(self, tmp_path):
        p = tmp_path / "data" / "nodi_mappa_observations.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ non e' json\n", encoding="utf-8")
        esito = esegui_riconciliazione()
        assert esito["errore"] is None  # righe malformate scartate, non un'eccezione


class TestStimaTempoRaccolta:

    def test_nessun_dato_ritorna_none(self):
        assert stima_tempo_raccolta("FAU_00", "petrolio", 7) is None

    def test_campioni_insufficienti_per_cella_fallback_globale(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", "2026-07-11T01:00:00+00:00"),
            _occ("FAU_01", "701_501", "2026-07-11T01:00:00+00:00"),
            _occ("FAU_02", "702_502", "2026-07-11T01:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", "2026-07-11T04:00:00+00:00"),   # 3h
            _report("FAU_01", "701_501", "2026-07-11T05:00:00+00:00"),   # 4h
            _report("FAU_02", "702_502", "2026-07-11T06:00:00+00:00"),   # 5h
        ])
        esegui_riconciliazione()
        # FAU_00 ha solo 1 campione (< min_campioni default 3) -> fallback
        # alla mediana globale (tipo+livello, tutte le istanze): 4h
        stima = stima_tempo_raccolta("FAU_00", "petrolio", 7, min_campioni=3)
        assert stima == 4 * 3600

    def test_campioni_sufficienti_usa_cella_specifica(self, tmp_path):
        occ = [_occ("FAU_00", f"70{i}_50{i}", f"2026-07-11T0{i}:00:00+00:00") for i in range(3)]
        rep = [_report("FAU_00", f"70{i}_50{i}", f"2026-07-11T0{i+2}:00:00+00:00") for i in range(3)]
        # durate: 2h, 2h, 2h (costante) per FAU_00
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", occ)
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", rep)
        # un'istanza diversa con durata molto piu' lunga, non deve influenzare
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_09", "999_999", "2026-07-11T01:00:00+00:00"),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_09", "999_999", "2026-07-11T10:00:00+00:00"),  # 9h
        ])
        esegui_riconciliazione()
        stima = stima_tempo_raccolta("FAU_00", "petrolio", 7, min_campioni=3)
        assert stima == 2 * 3600
