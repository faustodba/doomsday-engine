"""
tests/unit/test_task_resolution.py — WU-TaskResolution Fase 1

Copre l'algoritmo puro di shared.task_resolution.risolvi_task_istanza():
mapping legacy tipologia->profilo, task_overrides add/remove, swap fast,
forza_solo_raccolta, precedenza profilo esplicito vs tipologia. Nessun
consumer (main.py/predictor) toccato — vedi tests/unit/test_migration_parity.py
per la garanzia di byte-identità coi consumer reali.
"""

from shared.task_resolution import TASK_CLASS_TO_NAME, risolvi_task_istanza


def _class_names(risultato):
    return [r["class_name"] for r in risultato]


def _task_names(risultato):
    return [r["task_name"] for r in risultato]


# ── Mapping legacy tipologia -> profilo ────────────────────────────────────

def test_tipologia_full_risolve_profilo_completo():
    reg = risolvi_task_istanza(tipologia="full")
    assert "RaccoltaTask" in _class_names(reg)
    assert "ArenaTask" in _class_names(reg)
    assert "GraficaHqTask" in _class_names(reg)
    # tutte le 19 classi di task_setup.json presenti
    assert len(reg) == 19


def test_tipologia_raccolta_only_risolve_solo_raccolta():
    reg = risolvi_task_istanza(tipologia="raccolta_only")
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


def test_tipologia_raccolta_fast_applica_swap():
    reg = risolvi_task_istanza(tipologia="raccolta_fast")
    assert "RaccoltaFastTask" in _class_names(reg)
    assert "RaccoltaTask" not in _class_names(reg)
    # raccolta_chiusura NON è toccata dallo swap (solo RaccoltaTask lo è)
    assert "RaccoltaChiusuraTask" in _class_names(reg)
    # task_name resta nominale "raccolta" anche se class_name è swappata
    riga_raccolta = next(r for r in reg if r["class_name"] == "RaccoltaFastTask")
    assert riga_raccolta["task_name"] == "raccolta"
    assert riga_raccolta["variante"] == "fast"


def test_tipologia_sconosciuta_o_assente_fallback_completo():
    reg_assente = risolvi_task_istanza(tipologia=None)
    reg_ignota = risolvi_task_istanza(tipologia="qualcosa_di_strano")
    assert len(reg_assente) == 19
    assert len(reg_ignota) == 19


# ── task_overrides (add/remove) ────────────────────────────────────────────

def test_override_rimuove_task_da_profilo_completo():
    reg = risolvi_task_istanza(tipologia="full", task_overrides={"boost": False})
    assert "BoostTask" not in _class_names(reg)
    assert len(reg) == 18


def test_override_aggiunge_task_a_solo_raccolta():
    reg = risolvi_task_istanza(
        tipologia="raccolta_only",
        task_overrides={"grafica_hq": True, "vip": True, "donazione": True},
    )
    nomi = _class_names(reg)
    assert "RaccoltaTask" in nomi
    assert "RaccoltaChiusuraTask" in nomi
    assert "GraficaHqTask" in nomi
    assert "VipTask" in nomi
    assert "DonazioneTask" in nomi
    assert "BoostTask" not in nomi
    assert "ArenaTask" not in nomi


def test_override_vuoto_o_none_non_cambia_nulla():
    base = risolvi_task_istanza(tipologia="raccolta_only")
    reg_none = risolvi_task_istanza(tipologia="raccolta_only", task_overrides=None)
    reg_vuoto = risolvi_task_istanza(tipologia="raccolta_only", task_overrides={})
    assert _class_names(base) == _class_names(reg_none) == _class_names(reg_vuoto)


# ── forza_solo_raccolta (doppio giro FAU_00) — precedenza assoluta ────────

def test_forza_solo_raccolta_ignora_profilo_completo():
    reg = risolvi_task_istanza(tipologia="full", forza_solo_raccolta=True)
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


def test_forza_solo_raccolta_ignora_whitelist_master():
    # Invariante critico main.py:746/761/767 — anche con whitelist popolata,
    # forza_solo_raccolta vince e non registra nessun task extra.
    reg = risolvi_task_istanza(
        tipologia="raccolta_only",
        task_overrides={"grafica_hq": True, "vip": True},
        forza_solo_raccolta=True,
    )
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


def test_forza_solo_raccolta_non_applica_mai_lo_swap_fast():
    # Mai variante fast in doppio giro, anche se la tipologia sarebbe fast.
    reg = risolvi_task_istanza(tipologia="raccolta_fast", forza_solo_raccolta=True)
    assert "RaccoltaFastTask" not in _class_names(reg)
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


# ── profilo esplicito (Fase 2+, hook inerte ma testato) ────────────────────

def test_profilo_esplicito_precede_tipologia():
    reg = risolvi_task_istanza(tipologia="full", profilo="solo_raccolta")
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


def test_profilo_sconosciuto_fallback_a_tipologia():
    reg = risolvi_task_istanza(tipologia="raccolta_only", profilo="non_esiste")
    assert set(_class_names(reg)) == {"RaccoltaTask", "RaccoltaChiusuraTask"}


def test_profilo_master_catalogo_dichiarativo_non_wired():
    # Il profilo "master" esiste in profiles.json ma non è mai selezionato
    # automaticamente da nessuna tipologia legacy in Fase 1 — solo via
    # profilo esplicito (introspezione/UI futura, Fase 2).
    reg = risolvi_task_istanza(profilo="master")
    nomi = _class_names(reg)
    assert "TruppeTask" not in nomi  # esclusa per byte-identità con la whitelist attuale
    assert "GraficaHqTask" in nomi
    assert "DistrictShowdownTask" in nomi
    # 20/07: +daily_mission_auto +radar_master (task esclusivi master) → 12 (era 10)
    assert "DailyMissionAutoTask" in nomi
    assert "RadarMasterTask" in nomi
    assert len(reg) == 12


# ── Ordine risultato (per priority, come task_setup.json) ─────────────────

def test_risultato_ordinato_per_priority():
    reg = risolvi_task_istanza(tipologia="full")
    priorities = [r["priority"] for r in reg]
    assert priorities == sorted(priorities)


# ── Mappa canonica ───────────────────────────────────────────────────────

def test_task_class_to_name_copre_tutte_le_classi_task_setup():
    import json
    from pathlib import Path

    setup_path = Path(__file__).resolve().parent.parent.parent / "config" / "task_setup.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    classi = {row["class"] for row in setup}
    mancanti = classi - set(TASK_CLASS_TO_NAME.keys())
    assert not mancanti, f"Classi in task_setup.json non mappate: {mancanti}"
