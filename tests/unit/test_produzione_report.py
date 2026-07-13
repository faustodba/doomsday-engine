# ==============================================================================
#  tests/unit/test_produzione_report.py
#
#  Unit test per shared/produzione_report.py (WU204) — produzione per-istanza
#  dal Tab Report (fonte canonica, immune ad anomalie castello).
# ==============================================================================

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.produzione_report import produzione_per_istanza, PESI, RISORSE


@pytest.fixture(autouse=True)
def _isola_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    return tmp_path


def _write(tmp_path: Path, righe: list[dict]) -> None:
    p = tmp_path / "data" / "report_raccolta_dataset.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in righe:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _rep(inst, tipo, q, ts):
    return {"instance": inst, "tipo": tipo, "quantita_totale": q, "ts_raccolta": ts}


def test_rolling_finestra_pesi_e_mapping(tmp_path):
    now = datetime.now(timezone.utc)
    _write(tmp_path, [
        _rep("FAU_00", "petrolio", 264_000, (now - timedelta(hours=1)).isoformat()),
        _rep("FAU_00", "campo", 1_320_000, (now - timedelta(hours=2)).isoformat()),
        _rep("FAU_00", "petrolio", 264_000, (now - timedelta(hours=30)).isoformat()),  # fuori 24h
    ])
    d = produzione_per_istanza(window_h=24)
    assert d["modalita"] == "rolling" and d["den_h"] == 24.0
    p = d["per_istanza"]["FAU_00"]
    assert p["risorse"]["petrolio"] == 264_000       # la riga a 30h fa è esclusa
    assert p["risorse"]["pomodoro"] == 1_320_000     # campo -> pomodoro
    atteso = (1_320_000 * 1 + 264_000 * 5) / 24 / 1_000_000
    assert abs(p["pom_eq_h"] - atteso) < 1e-9
    assert abs(p["qta_h"]["petrolio"] - 264_000 / 24) < 1e-6
    assert p["n_report"] == 2


def test_modalita_giorno(tmp_path):
    _write(tmp_path, [
        _rep("FAU_00", "campo", 1_000_000, "2026-07-12T10:00:00+00:00"),
        _rep("FAU_00", "campo", 2_000_000, "2026-07-13T10:00:00+00:00"),
    ])
    d = produzione_per_istanza(giorno="2026-07-13")
    assert d["modalita"] == "giorno" and d["den_h"] == 24.0
    assert d["per_istanza"]["FAU_00"]["risorse"]["pomodoro"] == 2_000_000  # solo il 13


def test_master_incluso_nel_dict(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    _write(tmp_path, [_rep("FauMorfeus", "segheria", 500_000, now)])
    d = produzione_per_istanza(window_h=24)
    # master INCLUSO: l'esclusione dagli aggregati è del chiamante
    assert "FauMorfeus" in d["per_istanza"]
    assert d["per_istanza"]["FauMorfeus"]["risorse"]["legno"] == 500_000


def test_ts_naive_trattato_come_utc(tmp_path):
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    _write(tmp_path, [_rep("FAU_00", "petrolio", 100_000, now.replace(tzinfo=None).isoformat())])
    d = produzione_per_istanza(window_h=24)
    assert d["per_istanza"]["FAU_00"]["risorse"]["petrolio"] == 100_000


def test_file_assente_ritorna_vuoto(tmp_path):
    d = produzione_per_istanza(window_h=24)
    assert d["per_istanza"] == {}


def test_righe_malformate_o_incomplete_scartate(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    _write(tmp_path, [
        _rep("FAU_00", "petrolio", 264_000, now),
        {"instance": "FAU_00", "tipo": "petrolio", "ts_raccolta": now},  # manca quantita
        {"tipo": "petrolio", "quantita_totale": 999, "ts_raccolta": now},  # manca instance
        _rep("FAU_00", "sconosciuto", 999, now),  # tipo non mappato
    ])
    d = produzione_per_istanza(window_h=24)
    assert d["per_istanza"]["FAU_00"]["risorse"]["petrolio"] == 264_000
    assert d["per_istanza"]["FAU_00"]["n_report"] == 1


def test_pesi_e_risorse_coerenti():
    assert set(RISORSE) == {"pomodoro", "legno", "acciaio", "petrolio"}
    assert PESI == {"pomodoro": 1.0, "legno": 1.0, "acciaio": 2.0, "petrolio": 5.0}


def test_pu_da_report_conversione_struttura():
    """WU204 step 2: stats_reader._pu_da_report converte i dati report-based
    nella forma `prod_unificata` attesa dai consumer (come compute_from_storico)."""
    from dashboard.services.stats_reader import _pu_da_report
    # None -> struttura vuota (master o istanza senza dati)
    e = _pu_da_report(None)
    assert e["prod_unif_h"] == -1.0 and e["per_risorsa"] == {} and e["fonte"] == "report"
    # con dati
    p = {"risorse": {"pomodoro": 1_320_000, "legno": 0, "acciaio": 0, "petrolio": 264_000},
         "qta_h": {}, "pom_eq_h": 0.0, "n_report": 3}
    pu = _pu_da_report(p)
    assert pu["fonte"] == "report"
    assert pu["per_risorsa"]["petrolio"]["qta_tot"] == 264_000
    assert pu["per_risorsa"]["petrolio"]["pom_eq"] == 264_000 * 5
    assert "legno" not in pu["per_risorsa"]     # risorsa a 0 omessa (come castello)
    atteso = 1_320_000 * 1 + 264_000 * 5
    assert pu["pom_eq_totale"] == atteso
    assert abs(pu["prod_unif_h"] - atteso / 24 / 1_000_000) < 1e-3
