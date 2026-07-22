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
    # tutte le 22 classi del profilo completo presenti (19 + mall_daily WU238
    # + mega_armament WU240 + event_center_claims WU246)
    assert len(reg) == 22


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
    assert len(reg_assente) == 22
    assert len(reg_ignota) == 22


# ── task_overrides (add/remove) ────────────────────────────────────────────

def test_override_rimuove_task_da_profilo_completo():
    reg = risolvi_task_istanza(tipologia="full", task_overrides={"boost": False})
    assert "BoostTask" not in _class_names(reg)
    assert len(reg) == 21


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


# ── Merge whitelist(legacy) + task_overrides(esplicito) — Fase 2 ───────────
# La logica di merge vive nei chiamanti (main.py/predictor): costruiscono
# {**{t: True for t in master_task_whitelist}, **task_overrides}. Qui
# replichiamo quel dict e verifichiamo il contratto "esplicito vince".

def _merge_caller(master_whitelist, task_overrides):
    """Replica esatta del merge in main.py:743-746 / predictor:1049-1052."""
    wl = {t: True for t in (master_whitelist or [])}
    expl = task_overrides or {}
    return {**wl, **expl} or None


def test_merge_esplicito_rimuove_task_aggiunto_da_whitelist():
    # whitelist aggiunge boost; l'esplicito lo rimuove → esplicito vince.
    merged = _merge_caller(["boost", "vip"], {"boost": False})
    reg = risolvi_task_istanza(tipologia="raccolta_only", task_overrides=merged)
    nomi = _class_names(reg)
    assert "VipTask" in nomi          # dalla whitelist, non contraddetto
    assert "BoostTask" not in nomi    # rimosso dall'esplicito
    assert "RaccoltaTask" in nomi and "RaccoltaChiusuraTask" in nomi


def test_merge_unione_whitelist_ed_esplicito():
    merged = _merge_caller(["boost"], {"vip": True})
    reg = risolvi_task_istanza(tipologia="raccolta_only", task_overrides=merged)
    nomi = _class_names(reg)
    assert "BoostTask" in nomi and "VipTask" in nomi


def test_merge_solo_esplicito_su_profilo_completo():
    # nessuna whitelist (istanza ordinaria): l'esplicito rimuove da completo.
    merged = _merge_caller([], {"arena": False, "store": False})
    reg = risolvi_task_istanza(tipologia="full", task_overrides=merged)
    nomi = _class_names(reg)
    assert "ArenaTask" not in nomi and "StoreTask" not in nomi
    assert "BoostTask" in nomi   # non toccato


def test_merge_entrambi_vuoti_equivale_a_none():
    assert _merge_caller([], {}) is None
    assert _merge_caller(None, None) is None


# ── Companion task (daily_mission_auto → daily_mission_claim) ───────────────

def test_companion_principale_trascina_companion():
    # abilitare il principale aggiunge il companion (non è nel profilo)
    reg = risolvi_task_istanza(tipologia="raccolta_only",
                               task_overrides={"daily_mission_auto": True})
    nomi = _class_names(reg)
    assert "DailyMissionAutoTask" in nomi
    assert "DailyMissionClaimTask" in nomi   # companion agganciato


def test_companion_senza_principale_rimosso():
    # il companion NON è attivabile da solo: senza il principale viene rimosso
    reg = risolvi_task_istanza(tipologia="raccolta_only",
                               task_overrides={"daily_mission_claim": True})
    assert "DailyMissionClaimTask" not in _class_names(reg)


def test_companion_rimuovere_principale_rimuove_companion():
    # partendo dal profilo completo (che non ha daily_mission_*), niente companion
    reg = risolvi_task_istanza(tipologia="full")
    assert "DailyMissionClaimTask" not in _class_names(reg)
    assert "DailyMissionAutoTask" not in _class_names(reg)


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
    # 21/07: daily_mission_claim NON è nel profilo (è companion di
    # daily_mission_auto) ma viene aggiunto in risoluzione → 13 totali.
    # 21/07: i 4 contest COLLECT-ALL (parts/custom/vehicle/chip) sono ora
    # mappati nel task GLOBALE `special_promo` (1 solo task che li processa in
    # sequenza); mega_armament resta separato (prima di radar). → 15.
    # 22/07: +mall_daily (task standard, non esclusivo, ma ora presente anche
    # nel catalogo dichiarativo master) → 16.
    # 22/07 (WU246): +event_center_claims (stesso trattamento, verifica live
    # cross-istanza FAU_01/02/03 completata) → 17.
    assert "DailyMissionAutoTask" in nomi
    assert "DailyMissionClaimTask" in nomi   # aggiunto come companion
    assert "RadarMasterTask" in nomi
    assert "MegaArmamentTask" in nomi
    assert "SpecialPromoTask" in nomi
    assert "MallDailyTask" in nomi
    assert "EventCenterClaimsTask" in nomi
    # i task individuali NON sono più registrati (mappati in special_promo)
    assert "PartsContestTask" not in nomi
    assert "ChipChallengeTask" not in nomi
    assert len(reg) == 17


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
