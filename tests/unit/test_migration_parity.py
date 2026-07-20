"""
tests/unit/test_migration_parity.py — WU-TaskResolution Fase 1

Garantisce che shared.task_resolution.risolvi_task_istanza() produca lo
STESSO set di task che le due logiche PRE-refactor (main.py::_thread_istanza
loop di registrazione, core/cycle_duration_predictor.py selezione
tasks_consid) producevano — congelate qui come `_old_filtro_main`/
`_old_filtro_predictor`, copie 1:1 del codice pre-refactor, NON importate
da main.py/predictor (altrimenti dopo l'integrazione delle Fasi successive
si testerebbe "nuovo contro nuovo" e il test perderebbe significato).

Verificato sulle 12 istanze REALI (config/instances.json +
config/runtime_overrides.json), sotto: comportamento nominale, whitelist
master sintetica popolata (in prod è vuota — va comunque validato quel ramo),
forza_solo_raccolta=True su ogni istanza, tipologia raccolta_fast sintetica.

Confronto per SET (non ordine): l'ordine di iterazione non è un invariante
comportamentale — main.py registra con priority esplicita
(orc.register(priority=...), indipendente dall'ordine del loop) e il
predictor somma durate per task indipendentemente dall'ordine della lista.
"""

import json
from pathlib import Path

import pytest

from shared.task_resolution import risolvi_task_istanza

_ROOT = Path(__file__).resolve().parent.parent.parent
_INSTANCES_PATH = _ROOT / "config" / "instances.json"
_OVERRIDES_PATH = _ROOT / "config" / "runtime_overrides.json"
_TASK_SETUP_PATH = _ROOT / "config" / "task_setup.json"


def _carica_istanze_reali() -> list[str]:
    data = json.loads(_INSTANCES_PATH.read_text(encoding="utf-8"))
    return [i["nome"] for i in data]


def _carica_task_setup_reale() -> list[dict]:
    return json.loads(_TASK_SETUP_PATH.read_text(encoding="utf-8"))


def _carica_overrides_istanza(nome: str) -> dict:
    data = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
    return data.get("istanze", {}).get(nome, {})


def _carica_profilo_statico(nome: str) -> str:
    data = json.loads(_INSTANCES_PATH.read_text(encoding="utf-8"))
    ist = next((i for i in data if i.get("nome") == nome), {})
    return ist.get("profilo", "full")


def _tipologia_reale(nome: str) -> str:
    ovr = _carica_overrides_istanza(nome)
    return ovr.get("tipologia") or _carica_profilo_statico(nome) or "full"


_ISTANZE_REALI = _carica_istanze_reali()
_TASK_SETUP_REALE = _carica_task_setup_reale()

# Copia congelata di main.py::_TASK_CLASS_TO_NAME al momento della Fase 1 —
# NON importare da shared.task_resolution (altrimenti "nuovo contro nuovo").
_OLD_TASK_CLASS_TO_NAME = {
    "GraficaHqTask": "grafica_hq",
    "PuliziaCacheTask": "pulizia_cache",
    "RaccoltaTask": "raccolta",
    "RaccoltaChiusuraTask": "raccolta_chiusura",
    "RaccoltaFastTask": "raccolta_fast",
    "RifornimentoTask": "rifornimento",
    "DonazioneTask": "donazione",
    "MainMissionTask": "main_mission",
    "ZainoTask": "zaino",
    "VipTask": "vip",
    "AlleanzaTask": "alleanza",
    "MessaggiTask": "messaggi",
    "ArenaTask": "arena",
    "ArenaMercatoTask": "arena_mercato",
    "DistrictShowdownTask": "district_showdown",
    "BoostTask": "boost",
    "TruppeTask": "truppe",
    "StoreTask": "store",
    "RadarTask": "radar",
    "RadarCensusTask": "radar_census",
}

# Task master-only aggiunti DOPO la Fase 1 (WU-TaskResolution): non fanno
# parte del contratto di parità (la logica pre-Fase1 non li conosceva). Sono
# esclusi dal confronto vecchia/nuova — girano solo sul master via whitelist,
# NON in profiles["completo"]/["fast"]. Esclusi sia per class_name che per
# task_name (i filtri predictor lavorano sui nomi).
_ESCLUSI_PARITA_CLASS = {"DailyMissionAutoTask", "RadarMasterTask"}
_ESCLUSI_PARITA_NAME = {"daily_mission_auto", "radar_master"}


def _senza_esclusi_class(s: set[str]) -> set[str]:
    return {c for c in s if c not in _ESCLUSI_PARITA_CLASS}


def _senza_esclusi_name(s: set[str]) -> set[str]:
    return {n for n in s if n not in _ESCLUSI_PARITA_NAME}


def _old_filtro_main(tipologia, forza_solo_raccolta, master_whitelist) -> set[str]:
    """Copia congelata di main.py:764-780 (pre-refactor). Ritorna il SET dei
    class_name che verrebbero registrati (equivalente comportamentale — vedi
    docstring del modulo sul perché il confronto è per set)."""
    solo_raccolta = str(tipologia) == "raccolta_only" or forza_solo_raccolta
    raccolta_fast = str(tipologia) == "raccolta_fast" and not forza_solo_raccolta
    registrati = []
    for row in _TASK_SETUP_REALE:
        class_name = row["class"]
        if solo_raccolta and class_name not in ("RaccoltaTask", "RaccoltaChiusuraTask"):
            tnome = _OLD_TASK_CLASS_TO_NAME.get(class_name, "")
            if forza_solo_raccolta or tnome not in master_whitelist:
                continue
        if raccolta_fast and class_name == "RaccoltaTask":
            class_name = "RaccoltaFastTask"
        registrati.append(class_name)
    return _senza_esclusi_class(set(registrati))


def _new_filtro_main(tipologia, forza_solo_raccolta, master_whitelist) -> set[str]:
    task_overrides = {t: True for t in master_whitelist} if master_whitelist else None
    rows = risolvi_task_istanza(
        tipologia=tipologia,
        task_overrides=task_overrides,
        forza_solo_raccolta=forza_solo_raccolta,
    )
    return _senza_esclusi_class({r["class_name"] for r in rows})


def _old_filtro_predictor(tipologia, master_whitelist, task_globali) -> set[str]:
    """Copia congelata di cycle_duration_predictor.py:1018-1056 (pre-refactor)."""
    if str(tipologia) == "raccolta_only":
        tasks_consid = [t for t in ("raccolta", "raccolta_chiusura") if t in task_globali]
        for t in (master_whitelist or []):
            if t in task_globali and t not in tasks_consid:
                tasks_consid.append(t)
    elif str(tipologia) == "raccolta_fast":
        tasks_consid = []
        for t in task_globali:
            if t == "raccolta":
                tasks_consid.append("raccolta_fast")
            else:
                tasks_consid.append(t)
    else:
        tasks_consid = list(task_globali)
    return _senza_esclusi_name(set(tasks_consid))


def _new_filtro_predictor(tipologia, master_whitelist, task_globali) -> set[str]:
    task_overrides = {t: True for t in master_whitelist} if master_whitelist else None
    rows = risolvi_task_istanza(tipologia=tipologia, task_overrides=task_overrides)
    effettivi = set()
    for r in rows:
        # Kill-switch verificato sul nome NOMINALE (pre-swap) — replica
        # l'ordine dell'old_filtro_predictor: il branch raccolta_fast filtra
        # su task_globali PRIMA di applicare lo swap "raccolta"->"raccolta_fast".
        if r["task_name"] not in task_globali:
            continue
        eff_name = _OLD_TASK_CLASS_TO_NAME.get(r["class_name"], r["task_name"])
        effettivi.add(eff_name)
    return _senza_esclusi_name(effettivi)


# Whitelist sintetiche da esercitare (prod ha whitelist vuota — il ramo va
# comunque validato). Usiamo nomi di task realmente esistenti.
_WHITELIST_SINTETICHE = [
    [],
    ["grafica_hq", "vip", "donazione"],
    ["boost", "alleanza", "messaggi", "district_showdown"],
]

# task_globali sintetico per il ramo predictor (kill-switch a monte, fuori
# scope Fase 1 — qui simuliamo "tutti abilitati" e un caso parziale).
_TASK_GLOBALI_TUTTI = list({
    _OLD_TASK_CLASS_TO_NAME[row["class"]] for row in _TASK_SETUP_REALE
    if row["class"] in _OLD_TASK_CLASS_TO_NAME
})
_TASK_GLOBALI_SINTETICI = [
    _TASK_GLOBALI_TUTTI,
    ["raccolta", "raccolta_chiusura", "grafica_hq", "vip"],
]


@pytest.mark.parametrize("nome_istanza", _ISTANZE_REALI)
class TestParitaMain:
    def test_nominale(self, nome_istanza):
        tipologia = _tipologia_reale(nome_istanza)
        wl = _carica_overrides_istanza(nome_istanza).get("master_task_whitelist") or []
        assert _old_filtro_main(tipologia, False, wl) == _new_filtro_main(tipologia, False, wl)

    @pytest.mark.parametrize("whitelist", _WHITELIST_SINTETICHE)
    def test_whitelist_sintetica(self, nome_istanza, whitelist):
        tipologia = _tipologia_reale(nome_istanza)
        assert _old_filtro_main(tipologia, False, whitelist) == _new_filtro_main(tipologia, False, whitelist)

    def test_forza_solo_raccolta(self, nome_istanza):
        tipologia = _tipologia_reale(nome_istanza)
        wl = ["grafica_hq", "vip", "donazione"]
        assert _old_filtro_main(tipologia, True, wl) == _new_filtro_main(tipologia, True, wl)

    def test_raccolta_fast_sintetica(self, nome_istanza):
        # Nessuna istanza prod usa oggi raccolta_fast — validiamo comunque il ramo.
        assert _old_filtro_main("raccolta_fast", False, []) == _new_filtro_main("raccolta_fast", False, [])


@pytest.mark.parametrize("nome_istanza", _ISTANZE_REALI)
class TestParitaPredictor:
    @pytest.mark.parametrize("task_globali", _TASK_GLOBALI_SINTETICI)
    def test_nominale(self, nome_istanza, task_globali):
        tipologia = _tipologia_reale(nome_istanza)
        wl = _carica_overrides_istanza(nome_istanza).get("master_task_whitelist") or []
        assert (_old_filtro_predictor(tipologia, wl, task_globali)
                == _new_filtro_predictor(tipologia, wl, task_globali))

    @pytest.mark.parametrize("whitelist", _WHITELIST_SINTETICHE)
    def test_whitelist_sintetica(self, nome_istanza, whitelist):
        tipologia = _tipologia_reale(nome_istanza)
        task_globali = _TASK_GLOBALI_SINTETICI[0]
        assert (_old_filtro_predictor(tipologia, whitelist, task_globali)
                == _new_filtro_predictor(tipologia, whitelist, task_globali))

    def test_raccolta_fast_sintetica(self, nome_istanza):
        task_globali = _TASK_GLOBALI_SINTETICI[0]
        assert (_old_filtro_predictor("raccolta_fast", [], task_globali)
                == _new_filtro_predictor("raccolta_fast", [], task_globali))


def test_invariante_forza_solo_raccolta_ignora_whitelist_su_tutte_le_istanze():
    for nome in _ISTANZE_REALI:
        tipologia = _tipologia_reale(nome)
        reg = _new_filtro_main(tipologia, True, ["grafica_hq", "vip", "donazione", "boost"])
        assert reg == {"RaccoltaTask", "RaccoltaChiusuraTask"}, (
            f"{nome}: forza_solo_raccolta deve ignorare la whitelist, trovato {reg}"
        )
