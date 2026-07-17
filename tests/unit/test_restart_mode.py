"""
tests/unit/test_restart_mode.py — WU-restart-grana-fine-scelta (17/07/2026)

Copre il `mode` del flag di restart (scelta fine-istanza vs fine-ciclo):
  - request_restart(mode=...) scrive il campo mode
  - restart_flag_mode() legge il mode (default "istanza", incl. flag legacy)
  - should_restart_now() propaga il mode nel reason
  - il check post-istanza (main.py) scatta solo per mode == "istanza"
"""

import importlib
import json

import pytest


@pytest.fixture()
def rs(tmp_path, monkeypatch):
    """restart_scheduler isolato su una root temporanea (DOOMSDAY_ROOT)."""
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    import core.restart_scheduler as _rs
    importlib.reload(_rs)
    yield _rs
    # cleanup flag
    fp = _rs._flag_path()
    if fp.exists():
        fp.unlink()


def test_request_restart_default_istanza(rs):
    assert rs.request_restart(reason="x") is True
    assert rs.restart_flag_mode() == "istanza"
    data = json.loads(rs._flag_path().read_text(encoding="utf-8"))
    assert data["mode"] == "istanza"
    assert data["reason"] == "x"


def test_request_restart_ciclo(rs):
    assert rs.request_restart(reason="y", mode="ciclo") is True
    assert rs.restart_flag_mode() == "ciclo"


def test_request_restart_mode_invalido_fallback_istanza(rs):
    rs.request_restart(reason="z", mode="pippo")
    assert rs.restart_flag_mode() == "istanza"


def test_restart_flag_mode_none_se_assente(rs):
    assert rs.restart_flag_mode() is None


def test_restart_flag_mode_legacy_senza_campo(rs):
    # Flag pre-17/07 senza `mode` → trattato come "istanza"
    rs._flag_path().write_text(json.dumps({"reason": "legacy"}), encoding="utf-8")
    assert rs.restart_flag_mode() == "istanza"


def test_should_restart_now_propaga_mode(rs):
    rs.request_restart(reason="dashboard", mode="ciclo")
    should, reason = rs.should_restart_now()
    assert should is True
    assert reason == "flag:dashboard:ciclo"


def test_should_restart_now_istanza(rs):
    rs.request_restart(reason="dashboard", mode="istanza")
    should, reason = rs.should_restart_now()
    assert should is True
    assert reason == "flag:dashboard:istanza"


def test_semantica_post_istanza(rs):
    # Il check post-istanza (main.py) scatta SOLO se mode == "istanza".
    rs.request_restart(mode="istanza")
    assert (rs.restart_flag_mode() == "istanza") is True   # scatterebbe post-istanza
    rs._flag_path().unlink()
    rs.request_restart(mode="ciclo")
    assert (rs.restart_flag_mode() == "istanza") is False   # NON scatta post-istanza
    # ma should_restart_now (fine ciclo) sì
    assert rs.should_restart_now()[0] is True
