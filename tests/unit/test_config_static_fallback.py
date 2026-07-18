"""
tests/unit/test_config_static_fallback.py — R-09 (revisione 07/2026)

`build_instance_cfg` deve ripiegare sullo STATIC (instances.json) quando la
chiave manca nel dynamic (es. field-wipe R-02 o reset), PRIMA della costante —
come già fa livello_trasporto (WU220). Prima del fix: dynamic mancante →
max_squadre=4 fisso / livello=globale, ignorando lo static → il master
retrocedeva a 4 squadre e i livelli 7 (imposti dall'alleanza per FAU_00/
FauMorfeus) cadevano a 6.
"""

from config.config_loader import build_instance_cfg, load_global


def _gcfg():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return load_global(str(root / "config" / "global_config.json"))


def _ist(nome, max_sq, liv):
    return {"nome": nome, "porta": 16384, "indice": 0,
            "max_squadre": max_sq, "livello": liv, "profilo": "full"}


def test_max_squadre_fallback_static_quando_dynamic_manca():
    # static=5, dynamic vuoto (wipe) → deve dare 5 (static), non 4 (vecchia costante)
    cfg = build_instance_cfg(_ist("FAU_05", 5, 6), _gcfg(), overrides={})
    assert cfg.max_squadre == 5


def test_livello_fallback_static_preserva_regola_alleanza():
    # FAU_00 static livello=7 (imposto dall'alleanza), dynamic wipato →
    # deve restare 7, NON cadere a 6 (globale). È il cuore del bug.
    cfg = build_instance_cfg(_ist("FAU_00", 5, 7), _gcfg(), overrides={})
    assert cfg.livello == 7


def test_dynamic_vince_se_presente():
    # Il fallback non deve mai scavalcare un valore dynamic presente.
    cfg = build_instance_cfg(_ist("FAU_05", 5, 6), _gcfg(),
                             overrides={"max_squadre": 3, "livello": 7})
    assert cfg.max_squadre == 3
    assert cfg.livello == 7


def test_costante_ultima_spiaggia_max_squadre_5():
    # static ANCHE mancante (istanza senza max_squadre) → costante 5 (era 4).
    cfg = build_instance_cfg({"nome": "X", "porta": 1, "indice": 0, "profilo": "full"},
                             _gcfg(), overrides={})
    assert cfg.max_squadre == 5
