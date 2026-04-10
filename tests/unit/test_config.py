# ==============================================================================
#  tests/unit/test_config.py
#
#  Unit test per config/config.py
# ==============================================================================

import json
import tempfile
from pathlib import Path

import pytest

from config.config import (
    INTERVALLI_DEFAULT,
    RISORSE_VALIDE,
    TASK_VALIDI,
    BotConfig,
    InstanceConfig,
    load_instances,
)


# ==============================================================================
# Fixture — istanza valida minima
# ==============================================================================

def istanza_valida(**override) -> dict:
    """Dict valido per costruire InstanceConfig, con override opzionali."""
    base = {
        "name":                       "FAU_00",
        "index":                      0,
        "language":                   "it",
        "max_squadre":                5,
        "profilo":                    "standard",
        "fascia_oraria":              None,
        "risorse_abilitate":          ["pomodoro", "legno"],
        "soglie_raccolta":            {"pomodoro": 5.0, "legno": 5.0},
        "rifornimento_abilitato":     True,
        "rifornimento_risorse":       {"pomodoro": True, "legno": True},
        "rifornimento_soglie":        {"pomodoro": 5.0},
        "rifornimento_max_spedizioni": 5,
        "intervalli":                 {"store": 4.0, "messaggi": 4.0},
        "task_abilitati":             ["boost", "raccolta", "store"],
    }
    base.update(override)
    return base


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ==============================================================================
# TestBotConfig
# ==============================================================================

class TestBotConfig:

    def test_porta_formula(self):
        assert BotConfig.adb_port(0) == 16384
        assert BotConfig.adb_port(1) == 16416
        assert BotConfig.adb_port(5) == 16544
        assert BotConfig.adb_port(10) == 16704

    def test_adb_serial(self):
        assert BotConfig.adb_serial(0) == "127.0.0.1:16384"
        assert BotConfig.adb_serial(3) == "127.0.0.1:16480"

    def test_costanti_presenti(self):
        assert BotConfig.SCREEN_WIDTH == 960
        assert BotConfig.SCREEN_HEIGHT == 540
        assert BotConfig.MAX_PARALLEL >= 1


# ==============================================================================
# TestInstanceConfig — costruzione e proprietà
# ==============================================================================

class TestInstanceConfigBase:

    def test_costruzione_valida(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        assert cfg.name == "FAU_00"
        assert cfg.index == 0
        assert cfg.language == "it"

    def test_port_derivata(self):
        cfg = InstanceConfig.from_dict(istanza_valida(index=3))
        assert cfg.port == 16384 + 3 * 32

    def test_adb_serial_derivata(self):
        cfg = InstanceConfig.from_dict(istanza_valida(index=2))
        assert cfg.adb_serial == "127.0.0.1:16448"

    def test_task_set(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        assert "boost" in cfg.task_set
        assert isinstance(cfg.task_set, frozenset)

    def test_risorse_set(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        assert "pomodoro" in cfg.risorse_set

    def test_task_abilitato(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        assert cfg.task_abilitato("boost") is True
        assert cfg.task_abilitato("arena") is False

    def test_intervallo_ore_presente(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        assert cfg.intervallo_ore("store") == 4.0

    def test_intervallo_ore_default(self):
        # Task non presente negli intervalli → usa INTERVALLI_DEFAULT
        cfg = InstanceConfig.from_dict(istanza_valida())
        val = cfg.intervallo_ore("radar")
        assert val == INTERVALLI_DEFAULT.get("radar", 4.0)

    def test_fascia_oraria_none(self):
        cfg = InstanceConfig.from_dict(istanza_valida(fascia_oraria=None))
        assert cfg.fascia_oraria is None

    def test_fascia_oraria_tuple(self):
        cfg = InstanceConfig.from_dict(istanza_valida(fascia_oraria=[8, 22]))
        assert cfg.fascia_oraria == (8, 22)

    def test_repr(self):
        cfg = InstanceConfig.from_dict(istanza_valida())
        r = repr(cfg)
        assert "FAU_00" in r
        assert "port=" in r

    def test_serializzazione_roundtrip(self):
        d = istanza_valida()
        cfg = InstanceConfig.from_dict(d)
        d2 = cfg.to_dict()
        cfg2 = InstanceConfig.from_dict(d2)
        assert cfg2.name == cfg.name
        assert cfg2.port == cfg.port
        assert cfg2.task_abilitati == cfg.task_abilitati

    def test_port_non_nel_json(self):
        """to_dict() non deve contenere port o adb_serial."""
        cfg = InstanceConfig.from_dict(istanza_valida())
        d = cfg.to_dict()
        assert "port" not in d
        assert "adb_serial" not in d


# ==============================================================================
# TestInstanceConfig — validazione
# ==============================================================================

class TestInstanceConfigValidation:

    def test_name_vuoto_solleva(self):
        with pytest.raises(ValueError, match="name"):
            InstanceConfig.from_dict(istanza_valida(name=""))

    def test_index_negativo_solleva(self):
        with pytest.raises(ValueError, match="index"):
            InstanceConfig.from_dict(istanza_valida(index=-1))

    def test_index_troppo_grande_solleva(self):
        with pytest.raises(ValueError, match="index"):
            InstanceConfig.from_dict(istanza_valida(index=16))

    def test_language_non_valida_solleva(self):
        with pytest.raises(ValueError, match="language"):
            InstanceConfig.from_dict(istanza_valida(language="fr"))

    def test_max_squadre_non_valido_solleva(self):
        with pytest.raises(ValueError, match="max_squadre"):
            InstanceConfig.from_dict(istanza_valida(max_squadre=3))

    def test_profilo_non_valido_solleva(self):
        with pytest.raises(ValueError, match="profilo"):
            InstanceConfig.from_dict(istanza_valida(profilo="elite"))

    def test_risorsa_non_valida_solleva(self):
        with pytest.raises(ValueError, match="risorsa"):
            InstanceConfig.from_dict(
                istanza_valida(risorse_abilitate=["pomodoro", "oro"])
            )

    def test_task_non_valido_solleva(self):
        with pytest.raises(ValueError, match="task"):
            InstanceConfig.from_dict(
                istanza_valida(task_abilitati=["boost", "volare"])
            )

    def test_fascia_oraria_fuori_range_solleva(self):
        with pytest.raises(ValueError, match="fascia_oraria"):
            InstanceConfig.from_dict(istanza_valida(fascia_oraria=[8, 25]))

    def test_spedizioni_negative_solleva(self):
        with pytest.raises(ValueError, match="spedizioni"):
            InstanceConfig.from_dict(
                istanza_valida(rifornimento_max_spedizioni=-1)
            )

    def test_campo_mancante_solleva_key_error(self):
        d = istanza_valida()
        del d["name"]
        with pytest.raises(KeyError):
            InstanceConfig.from_dict(d)

    def test_raccolta_only_valido(self):
        cfg = InstanceConfig.from_dict(istanza_valida(profilo="raccolta_only"))
        assert cfg.profilo == "raccolta_only"

    def test_lingua_en_valida(self):
        cfg = InstanceConfig.from_dict(istanza_valida(language="en"))
        assert cfg.language == "en"

    def test_max_squadre_4_valido(self):
        cfg = InstanceConfig.from_dict(istanza_valida(max_squadre=4))
        assert cfg.max_squadre == 4


# ==============================================================================
# TestLoadInstances
# ==============================================================================

class TestLoadInstances:

    def test_carica_istanze_valide(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            write_json(path, [istanza_valida(), istanza_valida(name="FAU_01", index=1)])
            configs = load_instances(path)
            assert len(configs) == 2
            assert configs[0].name == "FAU_00"
            assert configs[1].name == "FAU_01"

    def test_file_non_trovato_solleva(self):
        with pytest.raises(FileNotFoundError):
            load_instances("/percorso/inesistente/instances.json")

    def test_json_malformato_solleva(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            path.write_text("{ INVALID }", encoding="utf-8")
            with pytest.raises(Exception):  # JSONDecodeError
                load_instances(path)

    def test_lista_vuota_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            write_json(path, [])
            configs = load_instances(path)
            assert configs == []

    def test_non_lista_solleva(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            write_json(path, {"name": "FAU_00"})  # dict, non lista
            with pytest.raises(ValueError, match="lista"):
                load_instances(path)

    def test_istanza_invalida_solleva(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            bad = istanza_valida(language="xyz")
            write_json(path, [bad])
            with pytest.raises(ValueError):
                load_instances(path)

    def test_indici_duplicati_sollevano(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            # Due istanze con stesso index=0
            write_json(path, [
                istanza_valida(name="FAU_A", index=0),
                istanza_valida(name="FAU_B", index=0),
            ])
            with pytest.raises(ValueError, match="duplicati"):
                load_instances(path)

    def test_carica_example_json(self):
        """Verifica che instances.example.json sia valido."""
        example_path = Path("config/instances.example.json")
        if example_path.exists():
            configs = load_instances(example_path)
            assert len(configs) >= 1
            for cfg in configs:
                assert cfg.port > 0

    def test_errori_multipli_riportati(self):
        """Se più istanze sono invalide, tutti gli errori sono nel messaggio."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instances.json"
            write_json(path, [
                istanza_valida(name="FAU_A", index=0, language="xx"),
                istanza_valida(name="FAU_B", index=1, language="yy"),
            ])
            with pytest.raises(ValueError) as exc_info:
                load_instances(path)
            msg = str(exc_info.value)
            assert "FAU_A" in msg
            assert "FAU_B" in msg
