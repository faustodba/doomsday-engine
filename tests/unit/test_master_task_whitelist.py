"""
tests/unit/test_master_task_whitelist.py — WU-MasterTasks (17/07/2026)

Copre l'infrastruttura config-driven per la selezione dei task del master
(sostituisce il bundle fisso FauMorfeusSetupTask WU234):
  - config: MASTER_TASK_WHITELIST + master_task_whitelisted()
  - anti-drift della mappa _TASK_CLASS_TO_NAME vs task_setup.json
  - filtro registrazione (raccolta_only + whitelist) come nel loop main.py
  - rimozione di FauMorfeusSetupTask
  - round-trip Pydantic IstanzaOverride (no field-wipe)
"""

import json
from pathlib import Path

import pytest

from config.config_loader import build_instance_cfg, load_global

_ROOT = Path(__file__).resolve().parent.parent.parent
_TASK_SETUP = _ROOT / "config" / "task_setup.json"


def _gcfg():
    # load_global ritorna i default hardcoded se il path non esiste → robusto.
    return load_global(str(_ROOT / "config" / "global_config.json"))


# ── Config: whitelist ─────────────────────────────────────────────────────

def test_master_whitelist_caricata():
    ist = {"nome": "FauMorfeus", "porta": 16704, "indice": 10, "profilo": "raccolta_only"}
    ovr = {"tipologia": "raccolta_only",
           "master_task_whitelist": ["grafica_hq", "vip", "district_showdown"]}
    cfg = build_instance_cfg(ist, _gcfg(), overrides=ovr)
    assert cfg.MASTER_TASK_WHITELIST == ["grafica_hq", "vip", "district_showdown"]
    assert cfg.master_task_whitelisted("grafica_hq") is True
    assert cfg.master_task_whitelisted("vip") is True
    assert cfg.master_task_whitelisted("boost") is False


def test_master_whitelist_vuota_per_ordinaria():
    ist = {"nome": "FAU_01", "porta": 16416, "indice": 1, "profilo": "full"}
    cfg = build_instance_cfg(ist, _gcfg(), overrides={"tipologia": "full"})
    assert cfg.MASTER_TASK_WHITELIST == []
    assert cfg.master_task_whitelisted("grafica_hq") is False


def test_master_whitelist_none_normalizzata_a_lista():
    ist = {"nome": "FauMorfeus", "porta": 16704, "indice": 10, "profilo": "raccolta_only"}
    cfg = build_instance_cfg(ist, _gcfg(),
                             overrides={"tipologia": "raccolta_only",
                                        "master_task_whitelist": None})
    assert cfg.MASTER_TASK_WHITELIST == []


# ── Anti-drift: mappa classe→nome vs task_setup.json ──────────────────────

def test_class_to_name_copre_task_setup():
    from main import _TASK_CLASS_TO_NAME
    setup = json.loads(_TASK_SETUP.read_text(encoding="utf-8"))
    classi_setup = {row["class"] for row in setup}
    mancanti = classi_setup - set(_TASK_CLASS_TO_NAME.keys())
    assert not mancanti, f"Classi in task_setup.json non mappate: {mancanti}"


# ── Filtro registrazione (stessa logica del loop main.py) ─────────────────

def _simula_filtro(whitelist, forza_solo_raccolta=False):
    from main import _TASK_CLASS_TO_NAME, _carica_task_setup
    registrati = []
    for row in _carica_task_setup():
        class_name = row[0]
        if class_name not in ("RaccoltaTask", "RaccoltaChiusuraTask"):
            tn = _TASK_CLASS_TO_NAME.get(class_name, "")
            if forza_solo_raccolta or tn not in whitelist:
                continue
        registrati.append(class_name)
    return registrati


def test_filtro_master_registra_solo_whitelist_piu_raccolta():
    wl = ["grafica_hq", "vip", "donazione"]
    reg = _simula_filtro(wl)
    assert "RaccoltaTask" in reg           # sempre
    assert "RaccoltaChiusuraTask" in reg   # sempre
    assert "GraficaHqTask" in reg
    assert "VipTask" in reg
    assert "DonazioneTask" in reg
    assert "BoostTask" not in reg          # non in whitelist
    assert "ArenaTask" not in reg


def test_filtro_forza_solo_raccolta_ignora_whitelist():
    # Doppio giro FAU_00: forza_solo_raccolta=True → solo raccolta, whitelist ignorata
    reg = _simula_filtro(["grafica_hq", "vip"], forza_solo_raccolta=True)
    assert set(reg) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


# ── FauMorfeusSetupTask rimossa (WU234 annullato) ─────────────────────────

def test_faumorfeus_setup_rimossa():
    with pytest.raises(ImportError):
        import tasks.faumorfeus_setup  # noqa: F401


def test_faumorfeus_setup_non_in_catalogue():
    from main import _import_tasks
    tasks = _import_tasks()
    assert "FauMorfeusSetupTask" not in tasks


def test_faumorfeus_setup_non_in_task_setup():
    setup = json.loads(_TASK_SETUP.read_text(encoding="utf-8"))
    classi = {row["class"] for row in setup}
    assert "FauMorfeusSetupTask" not in classi


# ── Round-trip Pydantic (no field-wipe, bug-class WU199/WU102) ────────────

def test_pydantic_roundtrip_preserva_whitelist():
    from dashboard.models import IstanzaOverride
    raw = {"tipologia": "raccolta_only",
           "master_task_whitelist": ["grafica_hq", "vip"],
           "raccolta_reset_leggero_abilitato": True}
    d = IstanzaOverride.model_validate(raw).model_dump()
    assert d["master_task_whitelist"] == ["grafica_hq", "vip"]
    assert d["raccolta_reset_leggero_abilitato"] is True


def test_pydantic_default_whitelist_none():
    from dashboard.models import IstanzaOverride
    d = IstanzaOverride.model_validate({"tipologia": "full"}).model_dump()
    assert d["master_task_whitelist"] is None
    assert d["raccolta_reset_leggero_abilitato"] is False
