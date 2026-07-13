# ==============================================================================
#  tests/unit/test_allocazione_per_istanza.py
#
#  Unit test per l'allocazione raccolta PER-ISTANZA (WU205 step 1) —
#  config_loader._InstanceCfg risolve ALLOCAZIONE_* da override runtime con
#  fallback al globale, normalizzando a frazioni somma=1.
# ==============================================================================

from config.config_loader import GlobalConfig, build_instance_cfg


def _gcfg():
    # GlobalConfig di default (_from_raw({}) → allocazione 0.4/0.3/0.2/0.1)
    return GlobalConfig._from_raw({})


def _alloc(c):
    return (round(c.ALLOCAZIONE_POMODORO, 4), round(c.ALLOCAZIONE_LEGNO, 4),
            round(c.ALLOCAZIONE_PETROLIO, 4), round(c.ALLOCAZIONE_ACCIAIO, 4))


def _globale(g):
    return (round(g.allocazione_pomodoro, 4), round(g.allocazione_legno, 4),
            round(g.allocazione_petrolio, 4), round(g.allocazione_acciaio, 4))


def test_no_override_usa_globale():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g, {})
    assert _alloc(c) == _globale(g)          # (0.4, 0.3, 0.2, 0.1)


def test_override_percentuali_normalizzate_a_frazioni():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g,
                           {"allocazione": {"pomodoro": 10, "legno": 10,
                                            "petrolio": 70, "acciaio": 10}})
    assert _alloc(c) == (0.1, 0.1, 0.7, 0.1)


def test_override_gia_frazioni_rinormalizzate():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g,
                           {"allocazione": {"pomodoro": 1, "legno": 1,
                                            "petrolio": 7, "acciaio": 1}})
    assert _alloc(c) == (0.1, 0.1, 0.7, 0.1)


def test_override_parziale_una_risorsa():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g,
                           {"allocazione": {"petrolio": 100}})
    assert _alloc(c) == (0.0, 0.0, 1.0, 0.0)


def test_somma_zero_fallback_globale():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g,
                           {"allocazione": {"pomodoro": 0, "legno": 0,
                                            "petrolio": 0, "acciaio": 0}})
    assert _alloc(c) == _globale(g)


def test_override_non_dict_ignorato():
    g = _gcfg()
    c = build_instance_cfg({"nome": "FAU_X"}, g, {"allocazione": "boh"})
    assert _alloc(c) == _globale(g)


def test_istanze_diverse_target_diversi():
    """Due istanze con override diversi → target diversi (il cuore della feature)."""
    g = _gcfg()
    c_petr = build_instance_cfg({"nome": "FAU_00"}, g,
                                {"allocazione": {"pomodoro": 10, "legno": 10,
                                                 "petrolio": 70, "acciaio": 10}})
    c_bulk = build_instance_cfg({"nome": "FAU_05"}, g,
                                {"allocazione": {"pomodoro": 40, "legno": 40,
                                                 "petrolio": 10, "acciaio": 10}})
    assert _alloc(c_petr) == (0.1, 0.1, 0.7, 0.1)
    assert _alloc(c_bulk) == (0.4, 0.4, 0.1, 0.1)


# ── Step 2: schema IstanzaOverride + persistenza runtime_overrides ────────────

def test_round_trip_runtime_overrides(tmp_path):
    """Save→load di runtime_overrides con allocazione per-istanza + risoluzione
    config_loader dal dict serializzato (end-to-end schema → bot)."""
    from dashboard.models import RuntimeOverrides, IstanzaOverride, AllocazioneOverride
    ov = RuntimeOverrides()
    ov.istanze["FAU_00"] = IstanzaOverride(
        allocazione=AllocazioneOverride(pomodoro=10, legno=10, petrolio=70, acciaio=10))
    p = tmp_path / "runtime_overrides.json"
    ov.save(p)

    ov2 = RuntimeOverrides.load(p)
    a = ov2.istanze["FAU_00"].allocazione
    assert a is not None and a.petrolio == 70

    ovr_dict = ov2.istanze["FAU_00"].model_dump(exclude_none=True)
    c = build_instance_cfg({"nome": "FAU_00"}, _gcfg(), ovr_dict)
    assert _alloc(c) == (0.1, 0.1, 0.7, 0.1)


def test_istanza_senza_allocazione_omessa_dal_json(tmp_path):
    """allocazione None → esclusa dal JSON (exclude_none) → fallback globale."""
    import json
    from dashboard.models import RuntimeOverrides, IstanzaOverride
    ov = RuntimeOverrides()
    ov.istanze["FAU_00"] = IstanzaOverride(abilitata=True)
    p = tmp_path / "runtime_overrides.json"
    ov.save(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "allocazione" not in d["istanze"]["FAU_00"]


def test_merge_patch_preserva_allocazione():
    """Bug-class WU199: patchare un ALTRO campo (via il merge di patch_istanza)
    NON deve perdere l'allocazione esistente."""
    from dashboard.models import IstanzaOverride, AllocazioneOverride
    current = IstanzaOverride(
        allocazione=AllocazioneOverride(pomodoro=10, legno=10, petrolio=70, acciaio=10))
    current_dict = current.model_dump()     # include allocazione
    current_dict["abilitata"] = False       # patch di un altro campo (whitelist)
    new = IstanzaOverride.model_validate(current_dict)
    assert new.allocazione is not None and new.allocazione.petrolio == 70
