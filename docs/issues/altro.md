# Issues — Altro / trasversale

> Archivio tematico voci WU/issue (estratto verbatim da `.claude/CLAUDE.md` il 07/06/2026).
> 7 voci totali · 0 aperte · 7 risolte. Legenda stato: ✅ risolta · 🟡 parziale · 🆕 aperta · 🔍 da osservare · ⏸ pausa.

## ✅ Risolti

| # | Issue | Priorità | Stato |
|---|-------|----------|-------|
| 17-bis | `InstanceState.save()` non atomica | MEDIA | ✅ RISOLTA (`a8ea422` tmp+fsync+os.replace) |
| 25 | NameError MAX_TENTATIVI_CICLO scope fix (bug introdotto+risolto 22/04) | ALTA | ✅ RISOLTA 22/04 |
| 32 | toggle_task 422 con HTMX form-encoded | MEDIA | ✅ RISOLTA 23/04 (async body parser con content-type detection) |
| 35 | storico_farm.json tracciamento giornaliero per istanza | — | ✅ IMPLEMENTATA 23/04 (data/storico_farm.json, retention 90gg) |
| 76 | Istanze disabilitate read-only nella tabella | BASSA | ✅ RISOLTA 28/04 (WU52 `72f7b0e` `disabled_attr` su input/select riga quando `abilitata=False`, evita modifiche accidentali a istanze offline) |
| 79 | Pannello produzione/ora storico 12h con sparkline | — | ✅ IMPLEMENTATA 28/04 (WU56 `39fdfcf`+`0490b18`+`a767201` layout 2-righe sparkline ASCII 14px + avg/min/max space-between, `get_produzione_storico_24h(hours=12)`, filter min>0) |
| WU165 | `tasks/messaggi.py` falliva da giorni — tab bar Alliance/System stale dopo redesign client (aggiunti REPORT/SENT/BOOK) | ALTA | ✅ RISOLTA 18/06/2026 (`e038736`) — diagnosi forense `cv2.matchTemplate` su 104 screenshot debug reali: 0/104 match con ROI/tap vecchi, 103/104 con quelli ricalibrati (`roi_alliance`, `roi_system`, `tap_tab_alliance`, `tap_tab_system`). Incluso commit del fix "PRE-OPEN DUAL-TAB" (`_rileva_tab_attivo`+`skip_tap`) già live in prod ma mai committato in dev. Scoperto e corretto anche `tests/tasks/test_messaggi.py` stale (falliva 15/27 per API single-tab obsoleta) → riscritto, ora 35/35. Nota minore non risolta: `time.sleep(3.0)` hardcoded in `_esegui_messaggi`/`_gestisci_tab` ignora `cfg.wait_open`/`cfg.wait_tab` (non bloccante, da fixare in sessione futura) |
