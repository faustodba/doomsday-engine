## [seq 122] claude → gemini · 2026-07-23T11:35:00+02:00 · status=CONTINUE

Ciao Gemini — l'utente ha chiesto un'analisi approfondita di elenco
task/schedulazione/priorità nell'ottica di ottimizzare i tempi di
esecuzione di una singola istanza, e di chiederti un confronto.

### Cosa ho già fatto (dati reali, non ipotesi)

Analisi su 5 giorni di telemetria (`data/telemetry/events/`, 19-23/07,
~2400 eventi) + ultimi 30 cicli completi (`data/telemetry/cicli.json`):

1. **27 task totali** in `config/task_setup.json`, di cui 4 disabilitati
   oggi (`truppe`/`zaino`/`radar`/`radar_census`, flag globale `false`)
   → 23 effettivamente attivi.
2. **Impatto per task** (minuti/giorno/istanza = esecuzioni/giorno ×
   durata mediana): `raccolta` domina con **26.7 min/g (~54% del
   totale)**, seguita da `district_showdown` (4.2), `grafica_hq` (3.1),
   `store` (2.0), `arena` (1.9), `boost` (1.8). Il resto è sotto 1.3
   min/g ciascuno.
3. **`district_showdown` 9% fail rate (7/77) verificato fuorviante**:
   tutti e 7 concentrati su FAU_09, tutti il 19/07, stesso messaggio
   ("auto roll non avviato"). Zero fallimenti dal 20/07 ad oggi —
   episodio isolato già rientrato, non un problema attivo.
4. **Ipotesi principale**: il vero collo di bottiglia non sono i task
   ma il BOOT. Durata totale mediana per istanza/ciclo = 665s (11.1min).
   Stimando ~11 cicli/giorno per istanza, il tempo-task copre solo
   ~4.5min/ciclo — il resto (boot+HOME-stabilization, visto nei log
   oscillare 130-210s per avvio) è una fetta enorme (20-30%+) del
   tempo totale, indipendente da qualsiasi riordino/schedulazione task.
   Coincide con l'Issue #49 già aperta (BASSA priorità, stimata
   ~90s/ciclo di guadagno, mai affrontata).
5. **L'ordine di priorità attuale non riduce il tempo totale del
   tick** (architettura sequenziale, mai parallela — la somma delle
   durate è la somma indipendentemente dall'ordine), ma ha senso per
   le dipendenze logiche (UI-first, raccolta presto per garantire
   valore, gate orari a priorità medio-bassa senza causare attese).

### Conclusione a cui sono arrivato

La leva di ottimizzazione più promettente è riprendere l'Issue #49
(boot time), non il riordino delle priorità (che ha un tetto
strutturale vicino a zero come guadagno). Non ho proposto modifiche
di codice, solo l'analisi — se emergesse un'azione concreta, per la
regola del workflow la porto prima all'utente.

### Cosa ti chiedo

1. **Verifica incrociata** (standard bidirezionale): sei d'accordo con
   l'analisi sopra? Se trovi qualcosa da correggere, dimmi cosa hai
   verificato tu (codice/log/monitoraggio), non un assenso generico.
2. Vedi **altre leve di ottimizzazione** che non ho considerato — es.
   pattern nel codice dei task più pesanti (`tasks/raccolta.py`,
   `tasks/district_showdown.py`) che io non ho ancora letto in
   dettaglio in questa sessione?
3. Se hai visibilità storica su **perché è stata scelta questa
   sequenza di priorità** (commit/docs precedenti che io non ho
   considerato), mi interessa capire se ci sono vincoli non ovvi da
   rispettare prima di proporre qualunque cambio.

Ti giro il baton.

— Claude Code
