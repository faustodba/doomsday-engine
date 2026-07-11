# ==============================================================================
#  tests/unit/test_tempo_raccolta_estimator.py
#
#  Unit test per shared/tempo_raccolta_estimator.py (WU200).
# ==============================================================================

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.tempo_raccolta_estimator import (
    esegui_riconciliazione,
    stima_tempo_raccolta,
    pota_dataset_vecchio,
    _leggi_righe_nuove,
    _migra_pending_a_chiave_tipizzata,
    _carica_stato,
    _salva_stato,
    TTL_ORFANE_ORE,
)


def _ore_fa(n: float) -> str:
    """Timestamp ISO relativo a 'adesso' — i test usano gap relativi
    (non date fisse) per restare validi indipendentemente da quando
    vengono eseguiti rispetto al TTL_ORFANE_ORE (4h di default)."""
    return (datetime.now(timezone.utc) - timedelta(hours=n)).isoformat()


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
            _occ("FAU_00", "700_500", _ore_fa(3)),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
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
        assert abs(rec["durata_s"] - 3 * 3600) < 5  # tolleranza esecuzione test

    def test_report_senza_occupazione_e_orfana(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 0
        assert esito["report_orfane"] == 1

    def test_occupazione_senza_report_resta_pending(self, tmp_path):
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", _ore_fa(1)),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 0
        assert esito["pending_attuali"] == 1

    def test_due_occupazioni_stesso_nodo_match_su_piu_recente_precedente(self, tmp_path):
        """Scenario segnalato dall'utente: nodo rioccupato prima del match
        della prima occupazione. Il report va abbinato all'occupazione
        piu' recente TRA quelle precedenti al completamento, non alla
        prima trovata."""
        ts_occ_vecchia = _ore_fa(3)
        ts_occ_recente = _ore_fa(2)
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", ts_occ_vecchia),
            _occ("FAU_00", "700_500", ts_occ_recente),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 1
        assert esito["pending_attuali"] == 1  # la piu' vecchia resta orfana (ma non potata, <4h)

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["ts_invio"] == ts_occ_recente
        assert abs(rec["durata_s"] - 2 * 3600) < 5

    def test_respawn_tipo_diverso_non_matcha_occupazione_sbagliata(self, tmp_path):
        """WU200quinquies: segnalato dall'utente. Lo stesso nodo (stessa
        coordinata) può respawnare con tipo/livello diverso. Un'occupazione
        di tipo diverso ma temporalmente più vicina al completamento NON
        deve essere scelta al posto di quella con tipo/livello corretto,
        anche se più vecchia."""
        ts_occ_tipo_giusto = _ore_fa(3)   # petrolio Lv6 -- quella corretta
        ts_occ_tipo_sbagliato = _ore_fa(2)  # campo Lv7 -- respawn diverso, piu' recente
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", ts_occ_tipo_giusto, tipo="petrolio", livello=6),
            _occ("FAU_00", "700_500", ts_occ_tipo_sbagliato, tipo="campo", livello=7),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0), tipo="petrolio", livello=6),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 1
        assert esito["pending_attuali"] == 1  # quella di tipo sbagliato resta pending

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["ts_invio"] == ts_occ_tipo_giusto  # NON quella più recente di tipo diverso
        assert abs(rec["durata_s"] - 3 * 3600) < 5

    def test_livello_disallineato_matcha_comunque_report_fonte_di_verita(self, tmp_path):
        """WU200septies: richiesta esplicita utente. Il livello registrato
        all'invio (raccolta.py) e' solo il target di ricerca, non il
        livello reale del nodo (12-30% di mismatch misurato, vedi
        tasks/raccolta.py::_cerca_nodo). Un'occupazione con livello
        diverso dal report DEVE comunque matchare (stesso tipo) -- il
        livello persistito viene sempre dal report, mai dall'occupazione."""
        ts_occ = _ore_fa(3)
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", ts_occ, tipo="petrolio", livello=6),  # target registrato: Lv6
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0), tipo="petrolio", livello=7),  # nodo reale: Lv7
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 1
        assert esito["report_orfane"] == 0

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["livello"] == 7          # dal report -- fonte di verita'
        assert rec["livello_invio"] == 6    # target originale, conservato per confronto/debug
        assert abs(rec["durata_s"] - 3 * 3600) < 5

    def test_nessuna_occupazione_tipo_corretto_resta_orfana(self, tmp_path):
        """Se esiste un'occupazione per la stessa coordinata ma di tipo
        diverso (nessuna di tipo corretto), il report deve restare orfano
        -- non abbinato per errore alla occupazione di tipo sbagliato."""
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", _ore_fa(2), tipo="campo", livello=7),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0), tipo="petrolio", livello=6),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 0
        assert esito["report_orfane"] == 1
        assert esito["pending_attuali"] == 1  # l'occupazione di tipo campo resta li', intatta

    def test_occupazione_riusata_rimossa_dal_pool(self, tmp_path):
        """Un'occupazione consumata da un match non deve mai essere
        riusata per un secondo match (stesso giro o giro successivo)."""
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", _ore_fa(2)),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(1)),
        ])
        esegui_riconciliazione()
        # secondo report sullo stesso nodo, nessuna nuova occupazione nel frattempo
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
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
            _occ("FAU_00", "700_500", _ore_fa(3)),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
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

    def test_match_prima_di_potatura_su_batch_storico(self, tmp_path):
        """WU200quater: bug reale trovato dall'utente su FAU_02. Se
        occupazione e report arrivano ENTRAMBI nello stesso batch di lettura
        (es. primo run di recupero su storico gia' accumulato) ed entrambi
        sono piu' vecchi del TTL al momento del run, il match deve comunque
        riuscire -- non deve scattare la potatura prima che il match abbia
        la sua occasione."""
        # occupazione di 10h fa (ben oltre il TTL di 4h di default) con
        # completamento 3h dopo (quindi anche il report e' vecchio, 7h fa)
        ts_occ = _ore_fa(10)
        ts_racc = _ore_fa(7)
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_02", "690_518", ts_occ),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_02", "690_518", ts_racc),
        ])
        # primo (e unico) run: entrambi gli eventi sono letti nello stesso batch
        esito = esegui_riconciliazione()

        assert esito["match_nuovi"] == 1
        assert esito["report_orfane"] == 0
        assert esito["pending_attuali"] == 0

        out = (tmp_path / "data" / "tempo_raccolta_dataset.jsonl").read_text(encoding="utf-8")
        rec = json.loads(out.strip().splitlines()[0])
        assert rec["ts_invio"] == ts_occ
        assert abs(rec["durata_s"] - 3 * 3600) < 5

    def test_ttl_orfane_default_4_ore(self):
        """Guardrail anti-drift: richiesta esplicita utente 11/07."""
        assert TTL_ORFANE_ORE == 4.0


class TestPotaDatasetVecchio:
    """WU200bis (11/07): retention 15 giorni sul dataset di output,
    richiesta utente -- poca variabilità attesa nel tempo di raccolta."""

    def test_file_assente_nessun_errore(self, tmp_path):
        esito = pota_dataset_vecchio(giorni=15)
        assert esito == {"rimosse": 0, "rimaste": 0}

    def test_rimuove_solo_righe_piu_vecchie_del_limite(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        ora = datetime.now(timezone.utc)
        vecchia = (ora - timedelta(days=20)).isoformat()
        recente = (ora - timedelta(days=5)).isoformat()
        out = tmp_path / "data" / "tempo_raccolta_dataset.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"ts_match": vecchia, "instance": "FAU_00",
                                 "durata_s": 3600}) + "\n")
            f.write(json.dumps({"ts_match": recente, "instance": "FAU_01",
                                 "durata_s": 3600}) + "\n")

        esito = pota_dataset_vecchio(giorni=15)
        assert esito == {"rimosse": 1, "rimaste": 1}

        righe = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(righe) == 1
        assert json.loads(righe[0])["instance"] == "FAU_01"

    def test_righe_non_interpretabili_conservate(self, tmp_path):
        out = tmp_path / "data" / "tempo_raccolta_dataset.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"instance": "FAU_00"}\n', encoding="utf-8")  # manca ts_match
        esito = pota_dataset_vecchio(giorni=15)
        assert esito["rimosse"] == 0
        assert esito["rimaste"] == 1

    def test_retention_default_15_giorni(self):
        """Guardrail anti-drift: richiesta esplicita utente 11/07."""
        import shared.tempo_raccolta_estimator as mod
        assert mod.RETENTION_GIORNI == 15


class TestStimaTempoRaccolta:

    def test_nessun_dato_ritorna_none(self):
        assert stima_tempo_raccolta("FAU_00", "petrolio", 7) is None

    def test_campioni_insufficienti_per_cella_fallback_globale(self, tmp_path):
        # occ tutte recenti (sopravvivono al TTL 4h); il gap verso il
        # completamento (che puo' cadere "nel futuro" rispetto a adesso)
        # e' pura logica di confronto tra timestamp, non legato all'orologio.
        occ_ts = _ore_fa(0.5)
        occ_dt = datetime.now(timezone.utc) - timedelta(hours=0.5)
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_00", "700_500", occ_ts),
            _occ("FAU_01", "701_501", occ_ts),
            _occ("FAU_02", "702_502", occ_ts),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", (occ_dt + timedelta(hours=3)).isoformat()),
            _report("FAU_01", "701_501", (occ_dt + timedelta(hours=4)).isoformat()),
            _report("FAU_02", "702_502", (occ_dt + timedelta(hours=5)).isoformat()),
        ])
        esegui_riconciliazione()
        # FAU_00 ha solo 1 campione (< min_campioni default 3) -> fallback
        # alla mediana globale (tipo+livello, tutte le istanze): 4h
        stima = stima_tempo_raccolta("FAU_00", "petrolio", 7, min_campioni=3)
        assert abs(stima - 4 * 3600) < 1

    def test_campioni_sufficienti_usa_cella_specifica(self, tmp_path):
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        occ = [_occ("FAU_00", f"70{i}_50{i}", (base + timedelta(minutes=i)).isoformat())
               for i in range(3)]
        rep = [_report("FAU_00", f"70{i}_50{i}", (base + timedelta(minutes=i, hours=2)).isoformat())
               for i in range(3)]
        # durate: 2h, 2h, 2h (costante) per FAU_00
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", occ)
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", rep)
        # un'istanza diversa con durata molto piu' lunga, non deve influenzare
        _scrivi_jsonl(tmp_path / "data" / "nodi_mappa_observations.jsonl", [
            _occ("FAU_09", "999_999", _ore_fa(0.5)),
        ])
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_09", "999_999",
                     (datetime.now(timezone.utc) - timedelta(hours=0.5) + timedelta(hours=9)).isoformat()),
        ])
        esegui_riconciliazione()
        stima = stima_tempo_raccolta("FAU_00", "petrolio", 7, min_campioni=3)
        assert stima == 2 * 3600


class TestMigrazionePendingChiaveTipizzata:
    """WU200septies (11/07): migrazione al formato chiave corrente
    'istanza|coordinata|tipo' (SENZA livello — il Tab Report è la fonte
    di verità sul livello, non l'occupazione, vedi nota in testa al
    modulo). Gestisce sia il vecchissimo formato 2 parti sia
    l'intermedio WU200sexies a 4 parti."""

    def test_migra_voce_vecchissimo_formato_2_parti(self):
        vecchio = {
            "FAU_00|700_500": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(vecchio)
        assert nuovo == {
            "FAU_00|700_500|petrolio": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }

    def test_migra_voce_formato_intermedio_4_parti_wu200sexies(self):
        intermedio = {
            "FAU_00|700_500|petrolio|7": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(intermedio)
        assert nuovo == {
            "FAU_00|700_500|petrolio": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }

    def test_chiave_gia_formato_corrente_passa_invariata(self):
        gia_corrente = {
            "FAU_00|700_500|petrolio": [{"ts": "2026-07-11T01:00:00+00:00"}],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(gia_corrente)
        assert nuovo == gia_corrente

    def test_due_voci_stesso_nodo_livelli_diversi_migrano_alla_stessa_chiave(self):
        """A differenza di WU200sexies, due occupazioni con stesso tipo ma
        livello diverso (target di ricerca diverso) finiscono ORA nella
        stessa chiave -- il livello non distingue più i bucket."""
        formato_intermedio = {
            "FAU_00|700_500|petrolio|6": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 6},
            ],
            "FAU_00|700_500|petrolio|7": [
                {"ts": "2026-07-11T02:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(formato_intermedio)
        assert set(nuovo.keys()) == {"FAU_00|700_500|petrolio"}
        assert len(nuovo["FAU_00|700_500|petrolio"]) == 2

    def test_due_voci_stessa_coordinata_tipi_diversi_migrano_a_chiavi_separate(self):
        vecchio = {
            "FAU_00|700_500": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 6},
                {"ts": "2026-07-11T02:00:00+00:00", "tipo": "campo", "livello": 7},
            ],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(vecchio)
        assert set(nuovo.keys()) == {"FAU_00|700_500|petrolio", "FAU_00|700_500|campo"}
        assert len(nuovo["FAU_00|700_500|petrolio"]) == 1
        assert len(nuovo["FAU_00|700_500|campo"]) == 1

    def test_voce_senza_tipo_scartata_difensivamente(self):
        vecchio = {
            "FAU_00|700_500": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": None, "livello": None},
            ],
        }
        nuovo = _migra_pending_a_chiave_tipizzata(vecchio)
        assert nuovo == {}

    def test_migrazione_automatica_al_caricamento_stato(self, tmp_path):
        """Uno stato salvato nel vecchio formato viene migrato in modo
        trasparente al primo _carica_stato() -- nessun'azione manuale
        richiesta, nessuna occupazione persa."""
        stato_vecchio = {
            "cursor_occupazioni": 100,
            "cursor_report": 50,
            "pending": {
                "FAU_00|700_500": [
                    {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
                ],
            },
        }
        _salva_stato(stato_vecchio)
        stato_migrato = _carica_stato()
        assert stato_migrato["pending"] == {
            "FAU_00|700_500|petrolio": [
                {"ts": "2026-07-11T01:00:00+00:00", "tipo": "petrolio", "livello": 7},
            ],
        }
        # i cursori restano intatti, solo il pending viene ristrutturato
        assert stato_migrato["cursor_occupazioni"] == 100
        assert stato_migrato["cursor_report"] == 50

    def test_occupazione_pending_vecchio_formato_matcha_dopo_migrazione(self, tmp_path):
        """End-to-end: un'occupazione salvata nel pending col vecchio
        formato deve continuare a trovare il suo match dopo la migrazione
        automatica -- nessuna occupazione in volo va persa dal refactor."""
        ts_occ = _ore_fa(2)
        stato_vecchio = {
            "cursor_occupazioni": 999999,  # gia' letta, non ri-leggere da capo
            "cursor_report": 0,
            "pending": {
                "FAU_00|700_500": [
                    {"ts": ts_occ, "tipo": "petrolio", "livello": 7},
                ],
            },
        }
        _salva_stato(stato_vecchio)
        _scrivi_jsonl(tmp_path / "data" / "report_raccolta_dataset.jsonl", [
            _report("FAU_00", "700_500", _ore_fa(0)),
        ])
        esito = esegui_riconciliazione()
        assert esito["match_nuovi"] == 1
        assert esito["report_orfane"] == 0
