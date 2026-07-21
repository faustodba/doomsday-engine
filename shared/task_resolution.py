"""
shared/task_resolution.py — fonte unica per "quali task registra l'istanza X".

WU-TaskResolution Fase 1 (docs/issues/master-tasks-refactor-design.md):
sostituisce 3 logiche divergenti (main.py::_thread_istanza,
core/cycle_duration_predictor.py, dashboard) con un'unica funzione
`risolvi_task_istanza()`. Fase 1 è puramente di UNIFICAZIONE — zero cambio
funzionale, garantito da tests/unit/test_migration_parity.py.

NON applica il kill-switch `globali.task.*` (verificato: main.py non lo
applica nel loop di registrazione, resta dentro should_run() di ogni task
con default True; il predictor lo applica a monte con default False — due
filtri distinti con default opposti, applicati da chiamanti diversi). Resta
un livello ortogonale gestito da ciascun chiamante, esattamente come oggi.

`task_name` nel risultato resta NOMINALE (pre-swap, es. sempre "raccolta"
anche quando class_name è RaccoltaFastTask) perché serve in due vocabolari
diversi: appartenenza a profilo/whitelist (nominale) e lookup statistiche
durata nel predictor (che usa "raccolta_fast" come chiave separata). Il
chiamante che serve il nome "effettivo" post-swap lo deriva da
TASK_CLASS_TO_NAME[class_name].
"""
from __future__ import annotations

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROFILES_PATH_DEFAULT = os.path.join(_ROOT, "config", "profiles.json")
_TASK_SETUP_PATH_DEFAULT = os.path.join(_ROOT, "config", "task_setup.json")


# Mappa canonica classe→nome task (snake_case). Copia di main.py::_TASK_CLASS_TO_NAME
# (che diventa alias di questa). NON è la stessa mappa di
# core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME — quella ha un bug
# preesistente (manca GraficaHqTask/PuliziaCacheTask/ZainoTask) usato SOLO per
# task_setup_by_name/strict-schedule nel predictor, fuori scope Fase 1.
TASK_CLASS_TO_NAME = {
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
    "DailyMissionAutoTask": "daily_mission_auto",   # 20/07 task custom master
    "DailyMissionClaimTask": "daily_mission_claim",  # 21/07 claim a fine ciclo
    "RadarMasterTask": "radar_master",              # 20/07 task custom master
    "PartsContestTask": "parts_contest",            # 21/07 task custom master (Special Promo)
    "CustomizationContestTask": "customization_contest",  # 21/07 task custom master (Special Promo)
    "VehicleRedesignTask": "vehicle_redesign",            # 21/07 task custom master (Special Promo)
    "MegaArmamentTask": "mega_armament",                  # 21/07 task custom master (Special Promo)
    "ChipChallengeTask": "chip_challenge",                # 21/07 task custom master (Special Promo)
    "SpecialPromoTask": "special_promo",                  # 21/07 task GLOBALE master (processa i 4 contest COLLECT-ALL)
}

# Mapping legacy tipologia(dynamic)/profilo(static) -> profilo nuovo
# (config/profiles.json). Stesso vocabolario legacy oggi usato da
# config_loader.py:1205 (_tipologia = ovr.get("tipologia") or ist.get("profilo", "full")).
_LEGACY_TIPOLOGIA_TO_PROFILO = {
    "full": "completo",
    "raccolta_only": "solo_raccolta",
    "raccolta_fast": "fast",
}

_DEFAULT_PROFILO = "completo"

# WU (21/07) — COMPANION TASK: un task "principale" trascina il suo companion,
# che NON è selezionabile da solo (non sta in alcun profilo, non è un toggle in
# dashboard). Serve per task accoppiati come daily_mission_auto (trigger, pri
# 23) -> daily_mission_claim (claim, pri 199): la dashboard mostra on/off solo
# il primo, il secondo si accende/spegne con lui. Dipendenza one-directional
# (il principale attiva il companion, mai il contrario). Applicato DOPO gli
# override: rimuovere il principale rimuove anche il companion.
_TASK_COMPANION: dict[str, tuple[str, ...]] = {
    "daily_mission_auto": ("daily_mission_claim",),
}


def _load_profiles(path: str | None = None) -> dict:
    p = path or _PROFILES_PATH_DEFAULT
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_task_setup(path: str | None = None) -> list[dict]:
    p = path or _TASK_SETUP_PATH_DEFAULT
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def risolvi_task_istanza(
    *,
    tipologia: str | None = None,
    profilo: str | None = None,
    task_overrides: dict[str, bool] | None = None,
    task_varianti: dict[str, str] | None = None,
    forza_solo_raccolta: bool = False,
    profiles_path: str | None = None,
    task_setup_path: str | None = None,
) -> list[dict]:
    """Risolve la lista di task che un'istanza registra, in ordine di priority.

    Precedenza:
      1. forza_solo_raccolta=True (doppio giro FAU_00) -> SOLO
         {raccolta, raccolta_chiusura}, classi STANDARD (mai variante fast),
         ignora profilo/task_overrides/task_varianti — invariante verificato
         su main.py:746,761,767.
      2. profilo esplicito (se presente in profiles.json), altrimenti mapping
         legacy da `tipologia` (full->completo, raccolta_only->solo_raccolta,
         raccolta_fast->fast; valore sconosciuto/assente -> completo, replica
         l'`or "full"` di main.py/config_loader).
      3. task_overrides: add(True)/remove(False) di un task_name rispetto al
         set del profilo (vocabolario NOMINALE, es. "raccolta", mai
         "raccolta_fast").
      4. task_varianti: variante esplicita per task_name, precede le
         `varianti` statiche del profilo (Fase 3 — inerte se non passato,
         salvo le varianti già dichiarate nel profilo stesso, es.
         fast.varianti.raccolta="fast").

    NON applica il kill-switch globale `globali.task.*` — resta a carico del
    chiamante (main.py: dentro should_run() di ogni task; predictor: filtro
    a monte su task_globali), esattamente come oggi.

    Ritorna list[dict] ordinata per priority, ciascuno con:
      class_name      : classe finale (con swap fast già applicato)
      task_name        : nome NOMINALE (pre-swap)
      priority          : da task_setup.json
      interval_hours    : da task_setup.json
      schedule          : da task_setup.json
      variante          : None | "fast" (altre in Fase 3)
    """
    profili = _load_profiles(profiles_path)
    setup = _load_task_setup(task_setup_path)

    if forza_solo_raccolta:
        tasks_nominali = {"raccolta", "raccolta_chiusura"}
        varianti: dict[str, str] = {}
    else:
        if profilo and profilo in profili:
            profilo_key = profilo
        else:
            profilo_key = _LEGACY_TIPOLOGIA_TO_PROFILO.get(str(tipologia), _DEFAULT_PROFILO)
        pdef = profili.get(profilo_key) or profili.get(_DEFAULT_PROFILO, {})
        tasks_nominali = set(pdef.get("tasks", []))
        varianti = dict(pdef.get("varianti", {}))

        for tname, on in (task_overrides or {}).items():
            if on:
                tasks_nominali.add(tname)
            else:
                tasks_nominali.discard(tname)

        # Companion: il principale trascina il companion; assente il principale,
        # il companion è rimosso (accoppiamento one-directional, dashboard mostra
        # solo il principale). Vedi _TASK_COMPANION.
        for base, companions in _TASK_COMPANION.items():
            if base in tasks_nominali:
                tasks_nominali.update(companions)
            else:
                for c in companions:
                    tasks_nominali.discard(c)

        if task_varianti:
            varianti = {**varianti, **task_varianti}

    risultato = []
    for row in setup:
        class_name = row.get("class", "")
        task_name = TASK_CLASS_TO_NAME.get(class_name)
        if task_name is None or task_name not in tasks_nominali:
            continue
        variante = varianti.get(task_name)
        final_class = class_name
        if variante == "fast" and class_name == "RaccoltaTask":
            final_class = "RaccoltaFastTask"
        risultato.append({
            "class_name": final_class,
            "task_name": task_name,
            "priority": row.get("priority"),
            "interval_hours": row.get("interval_hours"),
            "schedule": row.get("schedule"),
            "variante": variante,
        })

    risultato.sort(key=lambda r: r["priority"])
    return risultato
