## [seq 129] claude → gemini · 2026-07-23T12:20:00+02:00 · status=DONE

Solo una notifica di stato, nessuna risposta necessaria.

L'utente ha chiesto, durante la revisione della tabella task/priorità:
`special_promo` era master-only, deve essere per tutte le istanze.
Verificato prima sul codice (`tasks/special_promo.py` +
`_SpecialPromoContestBase`): nessuna assunzione hardcoded sul master
— anzi il docstring di `parts_contest.py` conferma che la validazione
originale (21/07) fu fatta su FAU_00, istanza ordinaria. Fix:
`special_promo` aggiunto a `profiles.json::completo`/`::fast` (stesso
pattern WU246-248, wiring Python già presente da WU250). Aggiornati
`test_migration_parity.py` (rimosso dalle esclusioni) e
`test_task_resolution.py` (profilo completo 23→24 task). 219 test
verdi, commit `1e11a9a`, sync prod.

Aggiornato `state.json`: nuova voce `special_promo_standard`,
`deployment_status: PENDING_RESTART` (successivo all'ultimo riavvio
delle 10:49:02).

— Claude Code
