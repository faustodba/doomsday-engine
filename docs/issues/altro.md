# Issues — Altro / trasversale

> Archivio tematico voci WU/issue (estratto verbatim da `.claude/CLAUDE.md` il 07/06/2026).
> 6 voci totali · 0 aperte · 6 risolte. Legenda stato: ✅ risolta · 🟡 parziale · 🆕 aperta · 🔍 da osservare · ⏸ pausa.

## ✅ Risolti

| # | Issue | Priorità | Stato |
|---|-------|----------|-------|
| 17-bis | `InstanceState.save()` non atomica | MEDIA | ✅ RISOLTA (`a8ea422` tmp+fsync+os.replace) |
| 25 | NameError MAX_TENTATIVI_CICLO scope fix (bug introdotto+risolto 22/04) | ALTA | ✅ RISOLTA 22/04 |
| 32 | toggle_task 422 con HTMX form-encoded | MEDIA | ✅ RISOLTA 23/04 (async body parser con content-type detection) |
| 35 | storico_farm.json tracciamento giornaliero per istanza | — | ✅ IMPLEMENTATA 23/04 (data/storico_farm.json, retention 90gg) |
| 76 | Istanze disabilitate read-only nella tabella | BASSA | ✅ RISOLTA 28/04 (WU52 `72f7b0e` `disabled_attr` su input/select riga quando `abilitata=False`, evita modifiche accidentali a istanze offline) |
| 79 | Pannello produzione/ora storico 12h con sparkline | — | ✅ IMPLEMENTATA 28/04 (WU56 `39fdfcf`+`0490b18`+`a767201` layout 2-righe sparkline ASCII 14px + avg/min/max space-between, `get_produzione_storico_24h(hours=12)`, filter min>0) |
