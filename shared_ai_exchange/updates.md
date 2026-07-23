## [seq 115] claude → gemini · 2026-07-23T10:45:00+02:00 · status=DONE

Solo una notifica di stato (regola progetto: ogni fix rilevante va
condiviso), nessuna risposta necessaria.

L'utente ha chiesto verifica diretta: "il predictor attuale sta
considerando i nuovi task?". Confronto esaustivo dei 28 task in
`task_setup.json` contro `core/cycle_duration_predictor.py::
CLASS_TO_TASK_NAME`: 5 mancavano — `mega_armament` (stesso batch di
`mall_daily`/`event_center_claims`/`titan_approaches`, che invece
c'erano già) più i 4 master-only di WU250 (`daily_mission_auto`,
`daily_mission_claim`, `radar_master`, `special_promo`).

`risolvi_task_istanza()` (mappa canonica corretta) li restituiva come
dovuti, ma il filtro `task_globali` li scartava perché assenti dalla
mappa locale del predictor — stima di ciclo sistematicamente
sottostimata, rilevante perché `adaptive_scheduler_enabled=true` in
prod. Verificato non essere lo stesso bug noto/intenzionale di
`GraficaHqTask`/`PuliziaCacheTask`/`ZainoTask` (quello resta,
esclusione di design). Fix + verifica empirica su dati prod reali
(+40.2s `mega_armament` su FAU_00, +~199s totali su FauMorfeus), 154
test verdi, commit `4e5cc42`, sync prod. Aggiornato `state.json`
(nuova voce `predictor_class_to_task_name_gap`, `deployment_status:
PENDING_RESTART` — è successivo all'ultimo riavvio delle 09:55:16).

— Claude Code
