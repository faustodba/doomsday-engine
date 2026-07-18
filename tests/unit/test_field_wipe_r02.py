"""
tests/unit/test_field_wipe_r02.py — R-02 (revisione 07/2026)

Bug-class "field-wipe": i modelli Pydantic degli override (default extra='ignore')
scartavano ogni campo di runtime_overrides.json non dichiarato → al round-trip
load→save della dashboard il campo spariva dal file. Fix: extra='allow' su
IstanzaOverride / GlobaliOverride / RuntimeOverrides → i campi ignoti sopravvivono.
Colpito 2 volte in prod (raccolta_reset_leggero_abilitato, master_task_whitelist).
"""

from dashboard.models import IstanzaOverride, GlobaliOverride, RuntimeOverrides


def test_istanza_preserva_campo_ignoto():
    raw = {"tipologia": "full", "campo_futuro": 42, "lista_domani": [1, 2]}
    d = IstanzaOverride.model_validate(raw).model_dump()
    assert d["campo_futuro"] == 42
    assert d["lista_domani"] == [1, 2]


def test_globali_preserva_campo_ignoto():
    raw = {"nuovo_flag_globale": True}
    d = GlobaliOverride.model_validate(raw).model_dump()
    assert d.get("nuovo_flag_globale") is True


def test_runtime_annidato_preserva_campo_istanza_ignoto():
    raw = {"istanze": {"FAU_X": {"tipologia": "full", "X_futuro": "vivo"}}}
    d = RuntimeOverrides.model_validate(raw).model_dump()
    assert d["istanze"]["FAU_X"]["X_futuro"] == "vivo"


def test_campi_espliciti_restano_validati():
    # extra='allow' non deve disattivare la validazione dei campi dichiarati.
    d = IstanzaOverride.model_validate(
        {"tipologia": "full", "master_task_whitelist": ["grafica_hq"]}
    ).model_dump()
    assert d["master_task_whitelist"] == ["grafica_hq"]
    assert d["raccolta_reset_leggero_abilitato"] is False  # default esplicito


def test_roundtrip_completo_non_perde_nulla():
    # Simula _load_ov -> _save_ov su un blocco con mix noto+ignoto.
    raw = {
        "globali": {"g_noto_ignoto": 1},
        "istanze": {
            "FAU_00": {
                "tipologia": "full",
                "master_task_whitelist": ["vip"],
                "raccolta_reset_leggero_abilitato": True,
                "campo_mai_visto": "resta",
            }
        },
    }
    d = RuntimeOverrides.model_validate(raw).model_dump()
    fm = d["istanze"]["FAU_00"]
    assert fm["campo_mai_visto"] == "resta"
    assert fm["master_task_whitelist"] == ["vip"]
    assert fm["raccolta_reset_leggero_abilitato"] is True
    assert d["globali"]["g_noto_ignoto"] == 1
