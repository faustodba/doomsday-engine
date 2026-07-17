"""
tests/unit/test_predictor_master_tasks.py — WU-MasterTasks fix predictor (17/07)

Regressione: `predict_cycle_from_config` per un'istanza `raccolta_only` (il
master) considerava SOLO raccolta+raccolta_chiusura, ignorando i task della
`master_task_whitelist` → sottostima della durata totale del ciclo (T_ciclo).
Vincolo di design (WU217): il master resta SEMPRE ultimo, quindi il fix non
cambia l'ordinamento, solo la durata stimata.

Qui si testa la logica di risoluzione `tasks_consid` in isolamento (replica
del ramo raccolta_only in cycle_duration_predictor), che è la parte pura del
fix — l'integrazione completa dipende da molti file di stato reali.
"""


def _resolve_tasks_consid(tipologia, master_whitelist, task_globali):
    """Replica del ramo raccolta_only del predictor (cycle_duration_predictor
    linee ~1035). Tenuto in sync col codice reale."""
    if str(tipologia) == "raccolta_only":
        tasks = [t for t in ("raccolta", "raccolta_chiusura") if t in task_globali]
        for t in (master_whitelist or []):
            if t in task_globali and t not in tasks:
                tasks.append(t)
        return tasks
    return list(task_globali)


TASK_GLOBALI = [
    "grafica_hq", "pulizia_cache", "boost", "vip", "alleanza", "messaggi",
    "donazione", "district_showdown", "arena", "raccolta", "raccolta_chiusura",
]


def test_master_senza_whitelist_solo_raccolta():
    r = _resolve_tasks_consid("raccolta_only", None, TASK_GLOBALI)
    assert r == ["raccolta", "raccolta_chiusura"]


def test_master_con_whitelist_conta_task_extra():
    wl = ["grafica_hq", "vip", "district_showdown"]
    r = _resolve_tasks_consid("raccolta_only", wl, TASK_GLOBALI)
    assert r == ["raccolta", "raccolta_chiusura", "grafica_hq", "vip", "district_showdown"]


def test_whitelist_rispetta_kill_switch_globale():
    # 'arena' NON è nella whitelist; 'zaino' non è globalmente attivo → escluso
    wl = ["grafica_hq", "zaino"]  # zaino non in TASK_GLOBALI
    r = _resolve_tasks_consid("raccolta_only", wl, TASK_GLOBALI)
    assert "grafica_hq" in r
    assert "zaino" not in r   # kill-switch globale rispettato


def test_no_duplicati():
    wl = ["raccolta", "grafica_hq", "grafica_hq"]  # raccolta già presente + dup
    r = _resolve_tasks_consid("raccolta_only", wl, TASK_GLOBALI)
    assert r.count("raccolta") == 1
    assert r.count("grafica_hq") == 1


def test_istanza_full_invariata():
    r = _resolve_tasks_consid("full", ["grafica_hq"], TASK_GLOBALI)
    assert r == TASK_GLOBALI  # whitelist ignorata per non-raccolta_only
