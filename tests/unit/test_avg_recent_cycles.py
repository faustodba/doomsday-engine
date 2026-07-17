"""
tests/unit/test_avg_recent_cycles.py — WU-cicli-fantasma (17/07/2026)

`_avg_recent_cycles_min` deve escludere dalla media:
  - il ciclo corrente (ultimo, in corso)
  - i cicli `aborted` (interrotti mid-ciclo da restart)
  - i cicli-fantasma < _MIN_CICLO_REALE_S (artefatto restart+resume, es. 2s)

Regressione del bug reale osservato 17/07: dopo restart fine-istanza, la
finestra "ultimi 5" conteneva solo cicli-fantasma da 2s → media 0.0 → il
caller cadeva sul fallback hardcoded 80min invece del reale ~200min.
"""

import importlib
import json

import pytest


@pytest.fixture()
def cdp(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    (tmp_path / "data" / "telemetry").mkdir(parents=True)
    import core.cycle_duration_predictor as _m
    importlib.reload(_m)
    return _m, tmp_path


def _scrivi_cicli(root, cicli):
    p = root / "data" / "telemetry" / "cicli.json"
    p.write_text(json.dumps({"cicli": cicli}), encoding="utf-8")


def test_esclude_cicli_fantasma_e_aborted(cdp):
    m, root = cdp
    cicli = [
        {"numero": 531, "completato": True, "durata_s": 7416},   # 123.6 min
        {"numero": 532, "completato": True, "durata_s": 8502},   # 141.7 min
        {"numero": 536, "completato": True, "aborted": True, "durata_s": 0},  # interrotto
        {"numero": 538, "completato": True, "durata_s": 2},       # fantasma resume
        {"numero": 540, "completato": True, "durata_s": 2},       # fantasma resume
        {"numero": 541, "completato": False, "durata_s": 0},      # corrente in corso
    ]
    _scrivi_cicli(root, cicli)
    avg = m._avg_recent_cycles_min(n=5)
    # solo 531 e 532 sono reali → media (123.6 + 141.7)/2 ≈ 132.65
    assert avg is not None
    assert abs(avg - ((7416 + 8502) / 2) / 60) < 0.01


def test_solo_fantasma_ritorna_none_non_zero(cdp):
    # Il bug reale: finestra con soli cicli-fantasma. Deve dare None (→ il
    # caller usa il fallback), NON 0.0 (che è comunque falsy ma semanticamente
    # sbagliato e fragile).
    m, root = cdp
    cicli = [
        {"numero": 538, "completato": True, "durata_s": 2},
        {"numero": 540, "completato": True, "durata_s": 2},
        {"numero": 541, "completato": False, "durata_s": 0},
    ]
    _scrivi_cicli(root, cicli)
    assert m._avg_recent_cycles_min(n=5) is None


def test_soglia_60s(cdp):
    m, root = cdp
    assert m._MIN_CICLO_REALE_S == 60
    cicli = [
        {"numero": 1, "completato": True, "durata_s": 59},   # sotto soglia → escluso
        {"numero": 2, "completato": True, "durata_s": 60},   # esattamente soglia → incluso
        {"numero": 3, "completato": False, "durata_s": 0},
    ]
    _scrivi_cicli(root, cicli)
    avg = m._avg_recent_cycles_min(n=5)
    assert avg == 1.0   # solo il ciclo da 60s = 1.0 min


def test_prende_ultimi_n_reali(cdp):
    m, root = cdp
    cicli = [{"numero": i, "completato": True, "durata_s": i * 600} for i in range(1, 11)]
    cicli.append({"numero": 11, "completato": False, "durata_s": 0})  # corrente
    _scrivi_cicli(root, cicli)
    avg = m._avg_recent_cycles_min(n=3)
    # ultimi 3 reali = numeri 8,9,10 → durate 4800,5400,6000 s
    assert abs(avg - ((4800 + 5400 + 6000) / 3) / 60) < 0.01
