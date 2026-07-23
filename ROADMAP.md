# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

---

## Sessione 23/07/2026 — WU255: Mega Armament, claim challenge a catena mai gestito

Bug report utente durante il monitoraggio attivo del rollout WU254: "mega
armament non preleva tutti i claim, mancano quelli del challenge". Il
codice esistente (`_seleziona_challenge_giornaliera`) gestiva solo la
selezione once/day della challenge del giorno ("+" trovato/non trovato) —
non un terzo caso: quando lo step corrente matura la ricompensa (es.
"Resource Gathering" 1,000,000/1,000,000), nella stessa posizione appare
un CLAIM verde mai gestito. Il claim sblocca subito lo step successivo
della catena, che se già maturo richiede un altro claim.

**Delega a Gemini** (analisi zona/soglia/bozza codice), **verifica di
Claude prima di applicare**: script Python indipendente ha confermato lo
score dichiarato da Gemini (0.8209 @ 156,466) su 5 immagini reali diverse
— e scoperto in più che sul pulsante disabilitato (fine catena) lo score
crolla a 0.28, zero rischio di falso positivo. **Validazione empirica dal
vivo**: l'utente ha fermato il bot e navigato manualmente su un'istanza
(tap via ADB diretto, screenshot in tempo reale) — 3 claim consecutivi
hanno confermato la catena (1M → 3M → 5M, poi pulsante disabilitato).

Nuovo metodo `_claim_challenge_catena()` (cap 5 iterazioni), agganciato
in `run()` dopo la selezione challenge. Commit `3e9ef0f`, sync prod
verificato sul file reale, **confermato in produzione**: log reale
`[MEGA_ARMAMENT] challenge claim: 0` (riga mai esistita prima, girata
senza errori).

Come promemoria collaterale: `RaccoltaChiusuraTask` eredita interamente
`run()` da `RaccoltaTask` — la modalità jolly (WU254, sotto) e il suo fix
di posizionamento si applicano automaticamente anche lì, nessuna
modifica separata necessaria (verificato leggendo il codice su richiesta
esplicita dell'utente).

---

## Sessione 23/07/2026 — WU254: modalità "jolly" livello raccolta

Durante l'analisi task/priorità/schedulazione, l'utente chiede un'analisi
approfondita sulla gestione del LIVELLO in `tasks/raccolta.py` (il task
più pesante, ~54% del tempo-task totale): eliminare il controllo/
aggiustamento OCR del pannello livello ad ogni singolo CERCA.

**Prima proposta (Gemini) scartata dopo verifica**: cache stateful
in-memory che traccia i tap fatti senza mai rileggere il pannello.
Misurato sui log reali che il 28% degli aggiustamenti (+/- tap) non
viene registrato dal gioco al primo colpo (23/82 "MISMATCH level
finale") — la cache andrebbe fuori sincrono troppo spesso.

**Design finale** (idea utente, raffinata nel dialogo): "jolly" — tap
CERCA diretto senza verifica per il tentativo primario di ogni marcia
(riusa `skip_livello_check`, prima solo del fast); calibrazione
esplicita SOLO al primo ciclo dopo il reset giornaliero (00:00 UTC,
riusa il pattern `_e_dovuto_periodic_reset` già in uso da mega_armament/
radar_master) — un giro sui 4 tipi per riportare il pannello al target;
il fallback (nodo non trovato) usa sempre la verifica classica; la
lettura del popup nodo (già esistente, oggi solo diagnostica) diventa
il ground truth per telemetria quando il tentativo era in jolly.

Verificato con l'utente prima di procedere: il gioco normalizza
automaticamente al livello minimo disponibile in zona se il pannello è
troppo basso — nessun bootstrap necessario oltre alla calibrazione
giornaliera. Nuovo `core.state.RaccoltaState` + flag
`RACCOLTA_LIVELLO_JOLLY_ABILITATO` (default `False`, pattern rollout
graduale già consolidato nel progetto).

27 nuovi test. **Zero regressioni verificate con metodo rigoroso**: i
90 fail pre-esistenti in `tests/tasks/` (radar/rifornimento/store/
zaino, scollegati) confermati identici con `git stash` mirato
prima/dopo le modifiche.

Commit `d9a947d`, pushato. Sync prod byte-identico.

**Seguito stesso giorno — rollout + bug scoperto + fix**: l'utente
sceglie rollout su TUTTE le 11 istanze ordinarie insieme (FAU_00..
FAU_10, FauMorfeus escluso) invece del pattern 1-istanza-pilota usuale
del progetto — decisione esplicita, coerente con `raccolta_reset_
leggero_abilitato` (già `true` ovunque). Dopo il riavvio bot che carica
`d9a947d`, il monitoraggio attivo (log MCP) rivela un bug di
posizionamento: `_calibra_livello_giornaliero()` viene chiamata PRIMA
della prima `vai_in_mappa()` del ciclo, mentre l'istanza è ancora in
HOME — `_apri_lente_verificata()` usa coordinate fisse pensate per la
vista MAPPA, quindi il tap sulla lente fallisce sistematicamente
(osservato 6/11 istanze: FAU_02/04/05/07/08/10, log dettagliato
"[LENTE] tap NON ha aperto la lente" ×3 tentativi + BACK recovery).
Impatto pratico nullo — il resto del flusso raccolta con jolly
funziona regolarmente ereditando il pannello livello già calibrato dal
giorno prima — ma la calibrazione esplicita giornaliera falliva sempre,
su tutte le istanze.

Fix (confermato dall'utente dopo spiegazione): spostata la chiamata
dentro il ramo "primo tentativo", subito dopo la prima `vai_in_mappa()`
riuscita. `tests/tasks/test_raccolta.py` 96/96 verdi. Commit `7cebc12`,
pushato, sync prod verificato sul file reale (non solo sul log di
sync). Pending: riavvio bot (già armato dall'utente al momento del
deploy) per caricare il fix in memoria.

---

## Sessione 23/07/2026 — WU253: special_promo standard su tutte le istanze

Durante l'analisi task/priorità/schedulazione (richiesta separata),
l'utente nota nella tabella riepilogativa: "special promo vedo solo
master, invece deve essere per tutte le istanze".

Verificato prima sul codice (`tasks/special_promo.py` +
`_SpecialPromoContestBase`): nessuna assunzione hardcoded sul master,
solo il pattern generico `ctx.device`/`ctx.matcher`/`task_abilitato()`
già usato da tutti i task standard. Il docstring di
`tasks/parts_contest.py` conferma anzi che la validazione originale
(21/07) fu fatta live su FAU_00, un'istanza ordinaria — "solo master"
era una scelta di configurazione (`profiles.json`), non un vincolo
tecnico.

Fix: `special_promo` aggiunto a `profiles.json::completo`/`::fast`
(stesso pattern WU246-248). Il wiring Python esisteva già da WU250.
Aggiornati 2 file di test con esclusioni/conteggi hardcoded sul vecchio
stato master-only (`test_migration_parity.py`, `test_task_resolution.py`
— profilo completo 23→24 task). Verificato empiricamente:
`risolvi_task_istanza(tipologia='full')` risolve ora 24 task, incluso
`special_promo`.

Commit `1e11a9a`, pushato. Test: 219 verdi. Sync prod byte-identico.

---

## Sessione 23/07/2026 — WU252: predictor non conosceva 5 task recenti

L'utente chiede direttamente: "il predictor attuale sta considerando i
nuovi task?". Confronto esaustivo dei 28 task in `task_setup.json`
contro `core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME`: 3 dei
task WU246-248 già presenti (`mall_daily`, `event_center_claims`,
`titan_approaches`), ma 5 mancavano — `mega_armament` (stesso batch,
dimenticato) più i 4 master-only di WU250 (`daily_mission_auto`,
`daily_mission_claim`, `radar_master`, `special_promo`).

Meccanismo: `risolvi_task_istanza()` (mappa canonica corretta)
restituiva questi task come dovuti, ma il filtro
`if task_name not in task_globali` li scartava perché assenti dalla
mappa locale del predictor — stima di ciclo sistematicamente
sottostimata, con impatto reale dato che `adaptive_scheduler_enabled=
true` in prod (il predictor alimenta il riordino istanze). Verificato
che NON è lo stesso bug noto/intenzionale di
`GraficaHqTask`/`PuliziaCacheTask`/`ZainoTask` (escluse di design,
commento esplicito nel codice) — le 5 aggiunte qui erano dimenticanze
vere, non esclusioni volute.

Verifica empirica su dati prod reali (`predict_cycle_from_config`):
prima del fix i 5 task erano completamente assenti dal breakdown
per-istanza; dopo, tempi reali — +40.2s (`mega_armament`) su FAU_00,
+~199s totali (5 task) su FauMorfeus.

Commit `4e5cc42`, pushato. Test: 154 verdi. Sync prod byte-identico.
**Richiede riavvio BOT** (il predictor gira nel processo bot).

---

## Sessione 23/07/2026 — WU251: kill-switch raccolta non copriva raccolta_fast

Continuazione diretta di WU250: la ricognizione delegata a Gemini
("tutti i punti che leggono `globali.task.*`/`task_overrides`") ha
trovato un bug reale nello stesso audit. `tasks/raccolta_fast.py:157`
chiama `ctx.config.task_abilitato("raccolta_fast")`, ma quel nome non
era mai stato mappato in `config_loader.py::task_abilitato()` — il
fallback lo faceva risultare sempre `True`. Disabilitare `raccolta` da
dashboard non avrebbe fermato un'istanza con profilo/varianti "fast".

Verificato da Claude sui 3 livelli prima di applicare (per la regola
del workflow): codice confermato (grep vuoto su `raccolta_fast` in
`config_loader.py`/`TaskFlags`/`global_config.json`), stato reale
confermato (`runtime_overrides.json` prod: 0/12 istanze con tipologia
`raccolta_fast` oggi — impatto pratico nullo ora, gap latente per il
futuro). Fix: `"raccolta_fast"` mappato allo stesso flag di
`"raccolta"`. Test comportamentale diretto + suite (210) verdi.

Commit `e39d324`, pushato. Sync prod byte-identico.

---

## Sessione 23/07/2026 — WU250: schema statico+dinamico completo per i task master-only

**Filo dell'indagine**: l'utente nota che i nuovi task (Special Promo,
Mega Armament) non appaiono selezionati né nel pannello master né in
quello standard, nonostante girino dal vivo. Prima ipotesi ("la pagina
legge lo statico invece del merge") corretta dall'utente ("sei sicuro?
verifica meglio") — la lettura statico-only di `/ui/config/global` è
**comportamento intenzionale** (banner esplicito: baseline di reset),
uguale per TUTTI i task standard da sempre (`alleanza`/`arena`/`boost`
sono `false` nello statico pur essendo live-attivi), non un bug dei 4
task nuovi.

**Regola esplicita dell'utente** che ne è scaturita: ogni task
implementato/modificato deve avere SIA il campo statico (default
`false`, baseline neutra) SIA l'aggancio dinamico (on/off runtime),
verificato per ENTRAMBI i pannelli (standard + master), con delega a
Gemini della ricognizione più ampia su discrepanze dati e logica di
lettura live.

**Audit** `task_setup.json` vs `global_config.json`: 9 task registrati
senza schema statico. `raccolta_chiusura` esente (companion di
`raccolta`, nessuna chiamata `task_abilitato` propria). Restano 8 reali:
4 già agganciati lato Python (WU246-248: `mall_daily`, `mega_armament`,
`event_center_claims`, `titan_approaches`) ma mai arrivati nello schema
statico, e 4 senza alcun aggancio (`daily_mission_auto`,
`daily_mission_claim`, `radar_master`, `special_promo` — chiamano
`ctx.config.task_abilitato()` ma `config_loader.py` non li conosceva).

**Fix**: 8 campi in `global_config.json` (dev+prod, tutti `false`);
aggancio Python a 5 punti (`_DEFAULTS`/dataclass/`from_dict`/`to_dict`/
mappa `task_abilitato`, default `True` per i 4 master-only, a
preservare il comportamento live attuale). Verificando anche
`dashboard/models.py::TaskFlags` (come richiesto per il pannello),
trovato un **secondo gap reale**, stesso bug-pattern storico di
`raccolta` (WU102): i 4 campi master-only mancavano dal modello
Pydantic che alimenta il roundtrip Advanced/reset — un salvataggio li
avrebbe eliminati silenziosamente da `runtime_overrides.json` (extra
field ignorato, non rifiutato). Confermato con un test round-trip
diretto prima/dopo la fix.

**Delimitazione scope verificata**: `valid_tasks` dell'endpoint standard
(`api_config_overrides.py`) correttamente non include i 4 master-only —
`profiles.json` conferma che non sono mai in `completo`/`fast`, la loro
registrazione passa dal meccanismo per-istanza `task_overrides` del
pannello master (sezione③), indipendente dal kill-switch globale. Da
`shared/task_resolution.py` emerge una distinzione architetturale
intenzionale e già documentata nel modulo: REGISTRAZIONE (profilo +
task_overrides) e KILL-SWITCH GLOBALE (`task_abilitato()`) sono due
filtri ortogonali con default opposti a seconda del chiamante — non un
bug, ma la causa più profonda della "discrepanza percepita" tra
pannelli, segnalata come base per la ricognizione Gemini.

Commit `1a5915e`, pushato. 167 (`test_task_resolution`) + 43
(`test_config`+`test_config_static_fallback`) verdi. Sync prod
verificato byte-identico su `config_loader.py`+`dashboard/models.py`.
`global_config.json` non sincronizzato per design (per-ambiente).

---

## Sessione 23/07/2026 — WU249: fix vai_in_home bloccato + rivalutazione periodica catalogo

**Continua notte**: l'utente osserva dal vivo un popup di dettaglio nodo
mappa ("Lv 6 Oil Refinery") rimasto aperto per ore su FAU_10 — "non
doveva essere chiuso tranne quando era attivo il gioco district?".

**Causa radice** (log `FAU_10.jsonl`, 01:43-01:46 UTC): `vai_in_home()`
in `core/navigator.py` rilevava ripetutamente una freccia BACK non
catalogata (`_unmatched_tap_back`) via `dismiss_banners_loop`, la
trattava come "banner chiuso" e faceva sempre `continue` — scavalcando
sistematicamente il fallback (tap overlay / Android back reale) che
avrebbe potuto sbloccare davvero la UI. 8 tentativi consumati ripetendo
lo stesso tap a vuoto. Colpite anche FAU_09 (stesso pattern, log
03:24-03:30).

**Collaborazione con Gemini** (richiesta esplicita supporto nel canale):
diagnosi corretta e utile, ma verificando con lo standard a 3 livelli
solo 1 dei 3 fix dichiarati risultava realmente scritto sul disco.
Applicati da Claude: `tasks/titan_approaches.py` (controllo return di
`vai_in_home()` finale) e `core/navigator.py` (contatore
`unmatched_streak` — se dismiss_banners_loop ritorna solo tap generici
per 2+ tentativi consecutivi, forza il fallback invece di continuare).
Verificato senza regressioni via `git stash` (stessi fallimenti
pre-esistenti con e senza il fix). **Nuova regola utente**: Gemini
propone, Claude verifica sempre sul file reale e scrive lui le
modifiche (memoria `feedback_workflow_gemini_validazione.md`).

**Incidente successivo**: dopo il commit del fix, entrambi i file
(`navigator.py`, `titan_approaches.py`) sono stati sovrascritti da un
intervento esterno che ha **rimosso i fix appena verificati** e
introdotto codice malformato (return irraggiungibile dopo un altro
return, `__repr__` duplicato). Rilevato subito al successivo giro di
verifica pre-commit, ripristinato alla versione corretta via `git
checkout HEAD --`. Nessuna perdita — il commit precedente era già la
fonte di verità.

**Secondo problema, stessa sessione — rivalutazione periodica**:
l'utente nota "Login Rewards" con pallino rosso mai reclamata. Causa:
`claimable=False` deciso al primissimo incontro (22/07 12:06, subito
dopo il reset catalogo WU245) e mai più rivalutato — ma Login Rewards è
un evento CICLICO (si rinnova ogni giorno), a differenza di voci con
stato davvero fisso (Match Predictions, Titan Approaches). Niente
whitelist (richiesta esplicita utente: "non ha senso") — nuovo campo
`last_checked` (distinto da `last_seen`) + funzione `deve_rivalutare()`:
ogni voce non-claimabile viene riaperta per riverifica dopo
`RIVALUTAZIONE_GIORNI=2` dall'ultima verifica reale, indipendentemente
dal motivo per cui era stata segnata così. Forzata la rivalutazione
immediata di t001 (Login Rewards, falso negativo confermato
dall'osservazione diretta) invece di aspettare i 2 giorni pieni.

Commit `5a58ca7` (fix navigator/titan_approaches) + `5da7d07`
(rivalutazione periodica + ripristino), pushati. 167/167 test verdi,
sync prod verificato byte-identico su tutti i file coinvolti.

---

## Sessione 22/07/2026 (11) — WU248: titan_approaches standard su tutte le istanze

**Richiesta utente**: "procedi" (a "perché titan_approaches non è in
produzione?") — dopo la validazione automatica end-to-end su FAU_02
(WU247), stesso trattamento "standard" già dato a
mall_daily/mega_armament/event_center_claims in questa sessione.

**Fatto**: `config/profiles.json` — `titan_approaches` aggiunto a
`completo`/`fast` (ON default per le 10 ordinarie) + `master` (catalogo
dichiarativo, nessuna logica master-specific). Wiring dashboard
identico ai precedenti: `TaskFlags.titan_approaches`,
`GlobalConfig.task_titan_approaches`, `valid_tasks`, i 2 `ORDER` in
app.py, `_MASTER_ELIGIBLE_TASKS`, checkbox grid `config_global.html`.
**Non** aggiunto a `_MASTER_VERIFIED_TASKS` (mai eseguito sul profilo
master/FauMorfeus specificamente) — badge ⚠ prudenziale in UI, stesso
trattamento degli altri 3 task standard di oggi.

Test: rimosso da `_ESCLUSI_PARITA_*`, conteggi aggiornati (completo/fast
22→23, override 21→22, master 17→18). 167/167 verdi. Sync prod fatto
(verificato byte-identico). Commit `812d544`, pushato.

**Nota operativa**: il bot gira già in produzione (avviato dall'utente
alle 16:08, ciclo 581, zero anomalie durante tutta la sessione di test
di oggi). Questa modifica avrà effetto al **prossimo riavvio**
bot+dashboard, non sul processo corrente — coerente col comportamento
già visto per WU246.

**event_center_claims + titan_approaches ora entrambi standard su tutta
la farm** — nessun task rimasto pilot-only dall'intera esplorazione
live iniziata con mall_daily/mega_armament questa sessione.

---

## Sessione 22/07/2026 (10) — WU247: nuovo task titan_approaches

**Ultimo task della sessione**: "apri hub center di fau_00 e seleziona titan
approaches" — l'utente guida dal vivo, passo-passo, l'intero flusso
dell'evento "Titan Approaches" (3 attacchi giornalieri gratuiti contro un
boss, ricompense indipendenti dall'esito), confermando ogni pulsante e
coordinata prima di procedere. Poi: "implementa e testiamolo su fau_01".

**Design**: nuovo task dedicato (non esteso nel sistema generico di
`event_center_claims` — quello è per discovery/claim semplice, qui serve
una sequenza multi-step di combattimento, autorizzata esplicitamente
dall'utente). Riusa apertura hub + navigazione sidebar di
`shared/claim_catalog.py`, template dedicato per la riga (evento noto).

**2 situazioni distinte dopo GO** (la seconda scoperta durante il test su
FAU_01 — "ho aperto la maschera per le istanze nuove mancano gli
schieramenti"):
- Schieramento **preimpostato** (FAU_00/master, istanze con
  progressione) → Deployment Queue già 3/3 → non si tocca → CHALLENGE
  diretto.
- Schieramento **mancante** (istanze nuove) → 3 slot vuoti con "+" → tap
  propone comandante/truppe default, tap READY conferma → ripetuto fino
  a 3 volte. Rilevato automaticamente via template match (nessuna
  assunzione sull'ordine di comparsa GO/Quick Battle).

**Bug fix in corso d'opera**: il primo test su FAU_01 riportava "nessun
pallino" mentre l'utente vedeva chiaramente il badge rosso a schermo
("verifica meglio c'è il pallino rosso"). Analisi pixel HSV: il badge si
sovrappone all'angolo alto dell'icona (picco dy=-19 dal centro del match
riga, banda [-30,-9]), non è centrato sul testo come assunto — la ROI
v1 (±15 dal centro) catturava solo la coda della macchia → frazione
diluita sotto soglia (4-5% invece di 28%). Ricalibrata empiricamente su
screenshot reale, verificato 28.4% dopo il fix.

**Validato end-to-end**: prima manualmente su FAU_01 (utente guida ogni
tap, scoperta del caso "schieramento mancante"), poi in **automatico
completo** su FAU_02 dopo aver integrato la logica nel codice — 3 slot
riempiti da soli (score 0.98-1.000), 1° attacco GO+CHALLENGE+skip
(retry funzionante, skip trovato al 3° tentativo), 2° attacco
schieramento riconosciuto già pieno (non ritoccato), 3° Quick Battle
istantaneo. `go=2 quick=1 tot=3/3`, 138.6s, zero tap non sicuri.

Registrato in `task_setup.json` (priority 33, daily) + `main.py` +
`shared/task_resolution.py` + `core/cycle_duration_predictor.py` +
`run_task.py` catalogue. **Pilot-only** (escluso da
`test_migration_parity`, non in `profiles.json`) — non ancora abilitato
su nessuna istanza. 167/167 test verdi. Commit `21aab50`, pushato, sync
prod fatto (verificato byte-identico, incluso i 7 nuovi template PNG).

Sessione chiusa con "ok pronto per ripartire e testare tutto" — bot in
riavvio (a cura dell'utente).

---

## Sessione 22/07/2026 (9) — WU246: event_center_claims standard su tutte le istanze

**Richiesta utente**: "abilitiamo per tutte le istanze" — dopo la verifica live
cross-istanza (FAU_01/02/03) di WU245, stesso trattamento "standard" già
dato a `mall_daily` (WU239) e `mega_armament` (WU240).

**Fatto**: `config/profiles.json` — `event_center_claims` aggiunto a
`completo`/`fast` (ON default per le 10 ordinarie) + `master` (catalogo
dichiarativo — nessuna logica master-specific, finisce in sez.①
Standard del pannello master via `_master_exclusive_tasks()` derivato).
Wiring dashboard identico a WU239/240: `TaskFlags.event_center_claims`,
`GlobalConfig.task_event_center_claims` (+`_DEFAULTS`/`from_dict`/
`to_dict`/`task_abilitato`), `valid_tasks`, i 2 `ORDER` in app.py
(`ui_config_global` + `mobile_partial_flags`) + `_MASTER_ELIGIBLE_TASKS`,
checkbox grid `config_global.html`. **Non** aggiunto a
`_MASTER_VERIFIED_TASKS` (mai eseguito sul profilo master/FauMorfeus
specificamente, solo su ordinarie) — badge ⚠ prudenziale in UI se
selezionato lì, stesso trattamento già riservato a mega_armament/mall_daily.

Verificato che tutti gli altri punti d'aggancio (`main.py` import,
`shared/task_resolution.py::TASK_CLASS_TO_NAME`,
`core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME`,
`core/orchestrator.py`, `config_master.html` template,
`runtime_overrides.json`) erano già a posto da WU241 o non richiedevano
modifiche (pattern consolidato: task_labels/verified/runtime_overrides
non necessitano voce esplicita quando il default basta — stesso
comportamento già osservato per mall_daily/mega_armament).

**Test**: rimosso `EventCenterClaimsTask`/`event_center_claims` da
`_ESCLUSI_PARITA_*` in `test_migration_parity.py`. Conteggi aggiornati
in `test_task_resolution.py` (completo/fast 21→22, override 20→21,
master 16→17). 167/167 verdi (`test_task_resolution.py` +
`test_migration_parity.py`).

**Nota — suite pytest completa**: lanciata per scrupolo prima del
rilascio, 143 fallimenti su 1296 test totali. Verificato uno per uno
che sono debito tecnico **pre-esistente e scollegato** da questa WU:
plugin `pytest-asyncio` mancante nell'ambiente (test scritti con
`async def test_...` in `test_task.py`/`test_rifornimento_base.py`,
errore "async def functions are not natively supported" — nessuna
relazione con la regola V6 "mai async def run" nel codice applicativo,
è solo la firma del *test* stesso) + un test OCR con firma disallineata
(`test_ocr_helpers.py::test_zone_custom`, `ocr_risorse()` non accetta
più `zone_risorse`) + 2 in `test_orchestrator.py` non correlati. Nessuno
tocca i file modificati oggi. Da segnalare come issue separato se non
già noto — non indagato oltre, fuori scope di questa sessione.

Commit `a6795b5`, pushato, sync prod fatto (verificato byte-identico).
**event_center_claims ora attivo su tutta la farm** (10 ordinarie +
master), stesso stato di mall_daily/mega_armament — nessun task rimasto
pilot-only da questa esplorazione. Effetto al prossimo riavvio
bot+dashboard.

---

## Sessione 22/07/2026 (8) — WU245: event_center_claims, identità riga-sidebar (skip zero-tap)

**Continuazione della stessa esplorazione live**, questa volta su FAU_01
(seconda istanza di test, WU244 validato solo su FAU_00). Due osservazioni
dell'utente dal vivo:
1. *"hai aperto due menu contenenti pallini rossi ma che nel censimento
   precedente dovrebbero essere stati catalogati non claimabili"* +
   *"sui pallini rossi riconosciuti non claimabili non devi entrare, costo
   di tempo inutile"* — col design WU244 (identità = titolo del sottomenu),
   il riconoscimento avveniva **dopo** il tap (serviva aprire per leggere
   il titolo), quindi ogni voce nota-non-claimabile veniva comunque aperta
   ogni run solo per scoprire che non c'era nulla da fare.
2. *"mi aspetto che fai lo scanning di tutti i menù, riconosci quelli nuovi
   e/o quelli rossi, se i rossi sono claimabili entri, se non claimabili
   non entri"* — conferma esplicita del comportamento atteso.

**Fix — identità spostata da "titolo del sottomenu aperto" (post-tap) a
"riga sidebar" (icona+etichetta, pre-tap)**: il crop è preso dalla stessa
screenshot già catturata per `trova_pallini_sidebar` — zero screenshot e
zero tap aggiuntivi per il riconoscimento in sé.

`shared/claim_catalog.py`: `TITLE_CROP_ZONE`/`TITLE_MATCH_THRESHOLD` →
`ROW_CROP_X`/`ROW_CROP_HALF_H`/`ROW_MATCH_THRESHOLD`; `riconosci_titolo`/
`salva_crop_titolo`/`carica_crop_titoli` → `riconosci_riga(frame, by,
crops)`/`salva_crop_riga(id, frame, by)`/`carica_crop_righe()` +
`ritaglia_riga(frame, by)` pubblica (stessa zona usata per salvare,
riconoscere e aggiornare la cache in RAM — sempre confrontabili).

`tasks/event_center_claims.py`: loop per-pallino riordinato —
`riconosci_riga()` **prima** di qualunque tap:
- riga nota **non claimabile** → skip immediato, **zero tap** (l'intero
  punto del fix);
- riga nota **claimabile** → tap diretto, apri, claim;
- riga **mai vista** → unico caso di tap esplorativo (per imparare),
  crop salvato è quello di **prima** del tap (riga sidebar, non il
  titolo del sottomenu che si aprirà).

Vecchi crop (`data/claim_titles/t001-t008.png`, formato titolo 40×460) e
`data/claim_catalog_learned.json` **resettati** (dev+prod): incompatibili
per shape coi nuovi crop-riga (~50×220), il sistema si auto-reimpara dal
vivo per design — già la logica esistente, nessun seed manuale rifatto.

Verificato: sintassi + import runtime puliti (zero riferimenti residui ai
vecchi nomi in tutto il repo), 167/167 test verdi
(`test_task_resolution.py` + `test_migration_parity.py`). Commit
`8f07415`, pushato, sync prod fatto (codice byte-identico verificato +
`data/` ripulita a mano, stesso stato pre-reset trovato anche lì).
**Ancora non abilitato su nessuna istanza** (resta pilot, come WU244 —
nessuna richiesta esplicita di renderlo standard finora).

**Verifica dal vivo su FAU_02** (dopo chiusura FAU_01 + boot completo
FAU_02 via `core/launcher.py`, 426s, HOME OK): 2 run consecutivi con
`run_task.py --force`.
- **Run 1** (catalogo vuoto post-reset): hub-open retry scattato
  correttamente (tentativo 1 score 0.040 → tentativo 2 score 1.000,
  fix WU244 confermato ancora necessario/funzionante), scan 6
  profondità, **9 righe nuove scoperte e imparate** (t001-t009), 2
  claimabili (t002, t004) → claimati con successo (score 1.000).
  199.4s totali.
- **Run 2** (stesso catalogo, subito dopo): **t003/t005/t006/t008
  riconosciute come non-claimabili e skippate con ZERO tap**
  (score 0.865-0.983, ben sopra soglia 0.85) — la verifica diretta
  del comportamento richiesto dall'utente ("sui pallini rossi
  riconosciuti non claimabili non devi entrare"). t002/t004
  (claimati nel run 1) non ricompaiono (badge sparito). 139.5s totali
  (-30% vs run 1, coerente col minor numero di tap). Risultato
  `{}` (tot=0, nulla da reclamare) — corretto.

Catalogo appreso (9 voci reali, non più il seed vuoto) + crop riga
`t001-t009.png` sincronizzati su prod (stesso pattern manuale di WU244,
non coperto da `sync_prod.bat`).

Login Rewards non compare nello scan né su FAU_01 (sessione precedente)
né su FAU_02 — 2/2 istanze test recenti. Ipotesi più probabile: evento
a tempo non più attivo in questo momento (era stato seedato a mano
originariamente su FAU_00). Non trattato come coverage bug — il sistema
impara correttamente ciò che c'è, non deve inventare ciò che non c'è.
Da riconfermare senza urgenza se ricompare in futuro.

**Run 3 — prova CROSS-ISTANZA (FAU_03, mai toccata da questa sessione)**:
dopo chiusura FAU_02 + boot completo FAU_03 (447s, HOME OK, 1 retry
su `am start` + 1 instabilità HOME temporanea, entrambi gestiti dal
recovery esistente — nessuna anomalia). `run_task.py --force`:
**t001/t003/t005/t007 — imparate sessioni fa su FAU_02 — riconosciute
correttamente su FAU_03 e skippate a zero tap** (score 0.944-0.985).
Prova diretta che l'identità-riga è davvero indipendente dall'istanza,
non solo dal tempo/posizione (l'assunto architetturale del redesign
WU244/245). Più 2 righe nuove non-claimabili (t010,t012) e 1 nuova
claimabile scoperta e riscattata (t011, score 1.000). 165.1s (tra i
139s "tutto noto" e i 199s "tutto nuovo" — coerente con la miscela).
Hub-open retry necessario anche qui (tentativo 1 score 0.040 →
tentativo 2 score 1.000) — pattern ormai consistente su 3/3 istanze
testate. Catalogo (12 voci) + crop sync su prod.

---

## Sessione 22/07/2026 (7) — WU241→244: task `event_center_claims` + sistema di discovery, redesign dopo test live

**Continuazione della stessa esplorazione ADB su FAU_00**: dopo mall_daily,
richiesta di scansionare a fondo il menu "Event Center" (icona rotante
top-right HOME) e costruire un sistema **generalizzato** che impara da
solo quali sottomenu hanno un claim gratuito.

**WU241 — prima versione**: catalogo dichiarativo (`shared/claim_catalog.py`,
stesso pattern di `banner_catalog.py`) con 2 voci verificate a mano
(Login Rewards, Survival Preparations — claim gratuiti confermati con tap
reali) + un motore di discovery a **coordinate fisse** (profondità scroll
+ posizione Y).

**WU242**: aggiunto supporto scroll multi-profondità (`n_scroll` per voce)
dopo aver scoperto che la sidebar ha 15+ voci sotto la piega.

**WU243 — sistema di auto-apprendimento**: su richiesta esplicita
dell'utente ("la prima istanza che entra fa uno scan completo... impara
se c'è un claim... aggiorna il catalogo"), aggiunta discovery generica
via blob rossi (`trova_pallini_sidebar`, HSV filtrato per colonna+area,
scarta rumore icone). Bug trovato e corretto in validazione live:
`wait_scroll_s=0.6` catturava lo screenshot a metà animazione scroll
(inerzia MuMu) → 0 badge rilevati; alzato a 1.5s → rilevamento corretto.

**WU244 — redesign completo dopo 2 osservazioni live dell'utente**
(entrambe bug reali, non ipotetici):
1. *"gli stessi sottomenù possono trovarsi in posizioni diverse a seconda
   dell'istanza o la presenza di eventi"* → l'identità per **posizione**
   (profondità+Y) non è affidabile tra istanze/nel tempo. Fix:
   **identità = immagine del titolo del sottomenu** (crop + template
   matching, mai OCR — troppo rumoroso: "Survival Preparations" letto
   "> a Survival Preparat"; verificato score 1.0 su rivisitazioni, 0.50-0.60
   tra voci diverse). La posizione resta solo un'informazione effimera
   per il tap del giro corrente.
2. *"non sei nel menu"* / *"continui a scrollare fuori dal menu hub"* →
   (a) il tap sull'icona HOME a volte non apre l'hub (animazione in
   corso) → task scansionava alla cieca la schermata sbagliata per 105s;
   fix: verifica apertura hub (`pin_event_center_hub_open.png`, back-arrow,
   score 1.0 su 4 sottotab diversi vs ~0.53 su HOME) + retry + abort
   pulito. (b) il tap "back" dopo ogni voce chiudeva l'INTERO hub (mai
   verificato prima — la sidebar in realtà resta sempre visibile insieme
   al contenuto), causando esattamente il sintomo descritto; fix: rimosso,
   nessun tap back tra una voce e l'altra.

Rimosso anche il gate interno "una volta al giorno" (ridondante con lo
schedule `daily` già in `task_setup.json`, e comunque incompatibile con
l'identità per-titolo — ogni run deve rivedere le posizioni correnti).

**Validato live end-to-end** (`run_task.py --force` su FAU_00, aggiunto
alle 3 nuove task nel suo catalogo — mancavano, tool utile per testare un
singolo task reale senza il bot completo): scan completo 6 profondità,
titoli noti riconosciuti correttamente su rivisitazioni multiple, **2
titoli nuovi scoperti e imparati** — Season Events, Titan Approaches
(verificati visivamente dai crop salvati, entrambi correttamente non
claimabili: richiedono azioni di gioco reali). Zero tap non sicuri in
tutte le iterazioni di test.

Commit `7be4f88`→`1356f35`, pushati, sync prod fatto (codice + template +
seed `data/claim_catalog_learned.json`/`data/claim_titles/*.png`, 5 voci,
copiati a mano non essendo coperti da `sync_prod.bat`). 261/263 test
verdi. **Non ancora abilitato su nessuna istanza** (task registrato,
pilot — nessun `task_overrides`/profilo ancora impostato).

---

## Sessione 22/07/2026 (6) — WU240: mega_armament standard su tutte le istanze + UI dashboard

**Richiesta utente**: "abilita per tutte le istanze, sono fiducioso" —
dopo la verifica live WU236 (Resource Gathering per le ordinarie), stesso
trattamento standard di WU239/mall_daily anche per `mega_armament`.

**Fatto**: `config/profiles.json` — `mega_armament` aggiunto a
`completo`/`fast` (ON di default per le 10 ordinarie, ereditato dal
profilo). Era già in `master` + `task_overrides` di FauMorfeus dal
21/07, nessuna modifica lì. **Zero modifiche a `tasks/mega_armament.py`**:
il dispatcher `is_master_instance()` introdotto in WU236 seleziona già
la challenge corretta per profilo (Radar Station Events master /
Resource Gathering ordinarie), la generalizzazione era già pronta per
questo esatto momento.

Wiring dashboard identico a WU239: `TaskFlags.mega_armament`,
`GlobalConfig.task_mega_armament`, `valid_tasks`, i due `ORDER` in
app.py, `_MASTER_ELIGIBLE_TASKS` (sposta `mega_armament` dalla sezione
"③ Solo Master" del pannello master alla sezione "① Standard", dato che
`_master_exclusive_tasks()` è derivato da `master_tasks - completo_tasks`
e ora è in entrambi), checkbox grid `config_global.html`.

**Test**: rimosso `mega_armament`/`MegaArmamentTask` da
`_ESCLUSI_PARITA_*` in `test_migration_parity.py` (stesso motivo di
WU239 — non più additivo, old/new logic concordano). Conteggi
aggiornati in `test_task_resolution.py` (completo 20→21, override
19→20; il conteggio del profilo `master` resta 16, invariato —
`mega_armament` c'era già in quella lista). 261/263 verdi.

Commit `9e5e5fb`, pushato, sync prod fatto (verificato byte-per-byte).
**mega_armament ora attivo su tutta la farm** (10 ordinarie + master),
insieme a mall_daily (WU239) — nessun task rimasto in stato pilot-only
da questa sessione di esplorazione live su FAU_00. Effetto al prossimo
riavvio bot + dashboard.

---

## Sessione 22/07/2026 (5) — WU239: mall_daily standard su tutte le istanze + UI dashboard

**Richiesta utente**: `mall_daily` (WU238) non deve restare un pilot opt-in
su FAU_00 — è un task standard (nessun comportamento master-specific) e va
abilitato per tutte le istanze, visibile/gestibile sia dal pannello
master che dal pannello home standard.

**Fatto**:
- `config/profiles.json`: `mall_daily` aggiunto a `completo`/`fast` (ON di
  default per tutte le 10 istanze ordinarie, ereditato dal profilo — zero
  `task_overrides` necessari) + al catalogo dichiarativo `master`.
- `FauMorfeus` (prod `runtime_overrides.json`): `task_overrides.mall_daily
  = true` esplicito (il master non usa il profilo `completo`, serve
  l'override diretto come per gli altri task condivisi).
- **Wiring dashboard completo** (stesso trattamento di vip/arena/store,
  non solo dei task master-only):
  - `dashboard/models.py::TaskFlags.mall_daily` (kill-switch globale)
  - `config/config_loader.py::GlobalConfig.task_mall_daily` (default,
    `_DEFAULTS`, `from_dict`, `to_dict`, `task_abilitato` mappa)
  - `dashboard/routers/api_config_overrides.py::valid_tasks`
  - `dashboard/app.py`: `ORDER` in `partial_task_flags_v2` (home
    standard) + `mobile_partial_flags`, `_MASTER_ELIGIBLE_TASKS`
    (pannello master, sez. ① Standard)
  - `dashboard/templates/config_global.html`: checkbox grid Jinja +
    array `taskList` JS

**Fix test in corsa**: aggiungere `mall_daily` a `completo`/`fast` ha
cambiato i conteggi attesi in `test_task_resolution.py` (profilo
completo 19→20, profilo master 15→16 — aggiornati con commento). Rimosso
`mall_daily`/`MallDailyTask` da `_ESCLUSI_PARITA_CLASS`/`_NAME` in
`test_migration_parity.py`: non è più additivo-opt-in, quindi old/new
logic concordano di nuovo su di lui senza bisogno di esclusione. 261/263
verdi (2 fail pre-esistenti in `test_orchestrator.py`, confermati
invariati via `git stash`, non correlati).

**Gap trovato e corretto**: `config/profiles.json` non era mai stato
aggiunto alla lista di sync di `sync_prod.bat` (solo `task_setup.json`
lo era) — sync manuale fino ad ora, rischio concreto di drift dev/prod
silenzioso per qualunque modifica futura ai profili. Aggiunta riga
dedicata + commento nello script.

Commit `f58a4c3`, pushato, sync prod fatto (verificato byte-per-byte su
tutti i file toccati). Effetto al prossimo riavvio bot (task
registration) + dashboard (UI checkbox).

---

## Sessione 22/07/2026 (4) — WU238: nuovo task `mall_daily` (Daily Boost + Daily Present)

**Contesto**: continuando l'esplorazione live su FAU_00 (ADB diretto, bot
fermo) partita per WU236/237, l'utente ha chiesto di entrare nel menu
"Mall" (icona vicino a Special Promo in HOME) per vedere se c'era
qualcosa da automatizzare.

**Ricognizione live**: il Mall è prevalentemente un negozio a pagamento
(Arising Conflict, Mystery Treasure, Premium Packs, Doomsday Courier,
Privileges Subscription...) ma contiene **due claim esplicitamente
gratuiti**, entrambi verificati dal vivo con tap reali:
- **Daily Boost** → icona "Claim" (badge rosso, separata dai pacchetti a
  pagamento X1/X2/X3 sottostanti) → "You obtained Intermediate Resource
  Pack X2!".
- **Limited-Time Promo** → sotto-tab di default "Daily Present" (label
  "FREE") → pulsante verde "Free" → "You obtained 5m Construction
  Speedup X5, Battle Manual (100 EXP) X5, 1,000 Food X5, 1,000 Wood X5,
  500 Steel X5!". Dopo il claim la vista avanza automaticamente sulla
  sotto-tab successiva a pagamento (es. Monthly Special Pack) — il task
  esce subito, non la tocca.

**Implementazione**: nuovo `tasks/mall_daily.py` (`MallDailyTask`),
posizioni **fisse** (confermato dall'utente: "tutto il mapping è fisso"),
con gate via template match su "Claim"/"Free" prima di ogni tap (mai i
pacchetti a pagamento). Riusa il template del banner WU237
(`pin_privileges_subscription_title.png`) per gestire il popup
Privileges Subscription Trial se ricompare come intro Mall. Registrato
in `main.py` + `shared/task_resolution.py::TASK_CLASS_TO_NAME` +
`core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME` +
`config/task_setup.json` (priority 31, `schedule: "daily"`).

**Bug di test trovato e corretto in corsa**: la prima versione rompeva
56 test di `test_migration_parity.py` — il task, essendo in
`task_setup.json` ma non in `profiles.json["completo"/"fast"]`, veniva
incluso dalla logica "vecchia" congelata (`_old_filtro_main`, itera
tutto `task_setup.json`) ma correttamente escluso dalla nuova
(`risolvi_task_istanza`, rispetta i profili) — esattamente lo stesso
trattamento riservato ai task master-only (WU-TaskResolution). Fix:
aggiunto `MallDailyTask`/`mall_daily` a `_ESCLUSI_PARITA_CLASS`/
`_ESCLUSI_PARITA_NAME` in `test_migration_parity.py`. 167/167 verdi
dopo il fix.

**NON in `profiles.json`** (completo/fast) — additivo opt-in via
`task_overrides`, stesso pattern del rollout WU236 (mega_armament):
pilota su FAU_00 prima di un'eventuale estensione. Nessuna istanza
abilitata ancora.

Commit `d381fb2`, pushato, sync prod fatto (verificato byte-per-byte
codice+template+registrazioni). Effetto al prossimo riavvio bot
(catalogo task letto all'import).

---

## Sessione 22/07/2026 (3) — WU237: banner catalog — "Privileges Subscription Trial"

**Contesto**: durante la sessione di calibrazione live su FAU_00 (ADB
diretto, bot fermo, per il fix WU236), aperto per curiosità il menu
"Mall" vicino a Special Promo — mostra subito un popup IAP "Privileges
Subscription Trial" (30gg trial gratis). L'utente segnala: ricorrente su
**tutte le istanze ordinarie** (nessun acquisto reale fatto), va chiuso
sempre con la X, mai con "Go Claim" (trial subscription ≠ semplice claim
risorse, rischio rinnovo automatico non verificato).

**Fix**: aggiunto come 4° banner al catalogo esistente (issue #54,
`shared/banner_catalog.py`) — stesso framework già usato per
`exit_game_dialog`/`auto_collect_afk_banner`/`equipment_report`. Nuovo
template `pin_privileges_subscription_title.png` (510×60, titolo
completo, croppato dal vivo). `dismiss_action="tap_x_topright"` con
`dismiss_coords=(813,94)` (posizione X non coincide col canonico
`DEFAULT_X_TOPRIGHT`). Priority 3. Verificato: match score 1.0 sulla
sorgente, `catalog_size()` 3→4.

Commit pending (vedi sync/push sotto), sync prod fatto. Doc:
`docs/issues/ocr-vision.md` (WU237), `.claude/CLAUDE.md` riassunto issue
#54 corretto (era già stale: elencava `banner_eventi_laterale` come
attivo, in realtà disabilitato dal 26/04 — ora riflette lo stato reale:
`exit_game_dialog`+`auto_collect_afk_banner`+`equipment_report`+
`privileges_subscription_trial`). Effetto al prossimo riavvio bot.

---

## Sessione 22/07/2026 (2) — WU236: mega_armament — challenge giornaliera anche sulle ordinarie

**Segnalazione utente**: sul task `mega_armament`, per le istanze diverse dal
master serve mappare una challenge diversa da "Radar Station Events" (che
ha senso solo per il master, unico a eseguire `radar_master`).

**Ricognizione live** (FAU_00, ADB diretto): aperta la schermata "Select
today's Challenge" nel carosello Mega Armament — tra le opzioni c'è
**"Resource Gathering"** ("Gather a total of 1,000,000 resources on the
World Map"), che matura da sola tramite `raccolta` (verificato: nella
griglia missioni la voce equivalente più piccola era già 500.000/500.000
CLAIM pronta). Stesso principio del master con radar: la challenge scelta
deve corrispondere a un task che l'istanza esegue comunque.

**Fix** (`tasks/mega_armament.py`): generalizzato `_seleziona_challenge_radar`
→ `_seleziona_challenge_giornaliera` con dispatcher `_target_challenge()` su
`is_master_instance(ctx.instance_name)` (`shared/instance_meta.py`) — master
→ pin/soglia/nome radar (invariato), ordinarie → nuovo
`pin_mega_resource_icon.png` (croppato live da FAU_00, verificato
match=1.0 sulla sorgente) + "Resource Gathering". Logica di carosello/
scroll/conferma "once selected can't be changed" **identica**, solo
parametrizzata — zero rischio sul ramo master già validato. 167/167 test
(`test_task_resolution.py`+`test_migration_parity.py`) verdi, import/
dispatcher testati a mano (master→radar, FAU_00→resource, corretto).

Commit `6735b06`, pushato, sync prod fatto (verificato byte-per-byte
codice+template). **Nessuna istanza abilitata ancora** — `mega_armament`
resta opt-in per-istanza via `task_overrides`, rollout pianificato
**pilota su FAU_00 prima**, dato che la SELECT è una tantum al giorno e
irreversibile in game (stesso vincolo di sicurezza del master). Attivazione
FAU_00 in sospeso, richiede conferma esplicita utente prima del primo run
reale.

---

## Sessione 22/07/2026 — WU235: radar_master schedule `periodic`→`periodic_reset`

**Segnalazione utente**: `radar_master` deve girare al primo avvio
dell'istanza master dopo il reset 00:00 UTC (quando il gioco rigenera
ricompense/missioni radar), poi ogni 12h — non solo "12h dall'ultimo run"
puro. Osservato in produzione 21-22/07: `radar_master` (priorità 24,
`interval_hours=12.0`, `schedule: "periodic"`) ultimo run 21/07 17:07 UTC →
rimasto "non dovuto" per tutti i tick del master del 22/07 fino alle 05:07
UTC, indipendentemente dal reset giornaliero.

**Causa**: `schedule_type: "periodic"` (`core/orchestrator.py::_e_dovuto_periodic`)
è puro rolling-interval dall'ultimo run, mai ancorato al reset. Esiste già
in codice il meccanismo corretto, `"periodic_reset"`
(`_e_dovuto_periodic_reset`, vero al primo tick dopo il reset 00:00 UTC
OPPURE se trascorse `interval_hours`) — usato da `MegaArmamentTask` dal
21/07, il cui docstring dichiara esplicitamente l'intento originale: mega
deve girare per primo dopo il reset "prima che radar_master accumuli
eventi" — intento mai applicato a `radar_master` stesso.

**Fix**: una riga in `config/task_setup.json`, `RadarMasterTask.schedule`
da `"periodic"` a `"periodic_reset"`. Nessuna modifica a
`tasks/radar_master.py` (schedule_type/interval_hours iniettati da
`main.py::_TaskWrapper` leggendo `task_setup.json`, non hardcoded nella
classe). **Ordine già corretto senza altre modifiche**: priorità
`mega_armament=21 < radar_master=24` garantisce che al primo tick
post-reset la challenge del giorno sia selezionata da mega_armament PRIMA
che radar_master raccolga gli eventi.

Doc: `docs/OVERVIEW.md` §5.6-ter, `docs/issues/radar.md` (WU235).
**Richiede riavvio bot** (`task_setup.json` letto solo all'import del
modulo). Non ancora validato live post-fix (in attesa di riavvio).

---

## Sessione 21/07/2026 (continuazione) — Pannello master + fix radar_master + fix report_raccolta

**Pannello master riorganizzato** (`dashboard/templates/config_master.html`,
richiede riavvio dashboard): arena/arena_mercato/store spostati da ①Standard a
②**"Task con variante master"** (hanno comportamento personalizzato sul
master — variante task_varianti o codice dedicato — non sono identici alle
ordinarie). Rimossi i parametri raccolta (livello nodo/trasporto) da ②, non
utili qui (si editano nella vista istanze). Nuovo toggle **⚔️ Modalità WAR**:
disabilita raccolta (e raccolta_chiusura in automatico via companion
`_TASK_COMPANION["raccolta"]=("raccolta_chiusura",)` in
`shared/task_resolution.py`). Commit `f2c3c34` (WAR mode) + `6fb20f0`/`5ef0ea3`
(riorganizzazione pannello). 167/167 test.

**Fix `radar_master`** (`tasks/radar_master.py`, commit `4cb6f8e`): bug utente
osservato nel tick reale del master — dopo il tap Complete All il codice
aspettava un tempo FISSO poi un SOLO screenshot; su batch grandi l'animazione
della maschera ricompensa dura di più → screenshot a metà animazione → nessuno
stato riconosciuto → falso "stato inatteso" → abort prematuro (radar_master
era l'unico task fallito nel tick di validazione). Fix: **poll** post-tap
(screenshot+check ogni 1.5s, max 12s) finché lo stato si stabilizza. 14/14 test.

**Fix `report_raccolta`** (`shared/report_raccolta.py`, commit `a555d65`,
calibrato live sul master via ADB): con altri eventi nel report (il master ha
centinaia di Battle Report) l'assunzione WU199sexies "Gathering Report è
l'unico elemento della lista flat" era falsa → il bot scrollava 15 pagine
leggendo la lista sbagliata, 0 righe raccolta. Fix a 2 fasi: FASE1 fast-path
(Sort Mail OFF, ricerca diretta, economico per istanze pulite); FASE2
fallback SOLO se Fase1 fallisce (Sort Mail ON, vista a categorie, Gathering
Report sempre sotto "Other", navigazione via template match+scroll, mai
posizione fissa). Selezione ora richiesta esplicitamente prima di
leggere/cancellare (anche in solo_reset=True) — mai azione distruttiva su
selezione non confermata. 4 template nuovi (`pin_report_other`,
`pin_chevron_up`, `pin_gathering_header`, + `pin_gathering_report` già in
repo). 30/30 test. **Non ancora validato live post-fix** (bot spento durante
l'implementazione) — da verificare al prossimo riavvio.

**Validazione end-to-end contest in produzione** (tick reale del master,
prima del fix radar_master): mega_armament OK (guard once/day, grid claim 2,
collect 1), special_promo OK (Parts Contest claim 1+collect 1, altri 3 skip
corretto), radar_master FALLITO (causa del fix sopra). Diagnosi fatta
incrociando `bot.log` (locale, solo eventi MAIN/orchestrator) con la JSONL
per-istanza (dettaglio task, `data/logs/<istanza>.jsonl`) e lo state
`schedule.<task>.last_run` (UTC) — nota: bot.log e state sono in fusi orari
diversi, va sempre convertito prima di confrontare timestamp.

**Bot SPENTO a fine sessione** (utente l'ha fermato per lavoro live sul
master) — **richiede riavvio** per caricare tutto il codice sopra. Pending:
challenge Mega per-istanza (avviato, non completato — FAU_09/10 non
raggiungibili), fix daily_mission da validare, follow-up store/arena/raccolta.

---

## Sessione 21/07/2026 — Task master `parts_contest` (Special Promo)

Nuovo task custom master `parts_contest`: ritira le ricompense **GRATIS**
dell'evento Special Promo → Parts Contest, tappando **solo pulsanti verdi**
("Claim" nei sotto-tab Daily Missions/Challenges) + "COLLECT ALL" sulla
traccia. **Mai** pulsanti a pagamento ("Keep Claiming"/euro).

**Discriminanti** (validati live su FAU_00, 960×540):
- Sotto-tab: scan **colore** bande verdi (verde=gratis; ambra "Keep Claiming"/
  "Go"=skip). Un tap incassa tutte le missioni complete.
- Traccia: **match TESTO** `pin_collect_all` — "COLLECT ALL" è **ambra** come
  "Keep Claiming" (il colore NON li distingue, match 1.000 vs 0.371) → tap
  posizione fissa (575,503) solo se il testo matcha.
- Navigazione a posizioni variabili via template: `pin_special_promo` (barra
  eventi HOME, tap sull'**icona** `cy-15` non la label) + `pin_parts_contest`
  (sidebar + scroll). Struttura interna a **coordinate fisse**.

**Validato end-to-end**: claim verdi → Lv.1→Lv.3 → COLLECT ALL → box ritirati,
badge Parts Contest azzerato, nessun pagamento. Skip path OK (FAU_01 senza
evento). Commit `feat`+`chore`, 167/167 test, sync prod OK. Config master
`task_overrides.parts_contest=true` (runtime_overrides dev+prod, non committato)
→ **richiede riavvio bot**. Solo master per ora. Priority 26/12h/periodic.

**Refactor + 2° contest `customization_contest`** (stessa sessione): estratta
base condivisa `tasks/special_promo.py::_SpecialPromoContestBase`; parts_contest
sottoclasse (has_subtabs=True), customization sottoclasse (has_subtabs=False —
solo traccia + COLLECT ALL, niente sotto-tab). Aggiunti alla base: **apertura
Special Promo verificata con retry** (tap singolo talvolta non apre),
**selezione voce sidebar verificata con retry** (tap singolo talvolta non
commuta), **gate pallino rosso** sulla voce sidebar (badge → processa; no badge
→ skip). Validato live FAU_00: customization badge→COLLECT ALL, no-badge→skip,
regressione parts OK. Priority 27/12h. **Vehicle Redesign** (3° contest, priority 28, has_subtabs=False, validato live sul master) rilasciato nella stessa sessione. Rilasciato anche **Mega Armament** (4° contest, il più complesso: scelta challenge giornaliera radar once/day + grid claim + collect all, priority 21 prima di radar_master). Rilasciato anche **Chip Challenge** (5° e ultimo, priority 29). Serie contest Special Promo COMPLETA (mega 21, parts 26, custom 27, vehicle 28, chip 29)
sono sottoclassi banali della base.

---

## Sessione 20/07/2026 (9) — WU-TaskResolution Fase 1: `risolvi_task_istanza()`

Ripresa dello sviluppo dei task extra/custom per Master e istanze ordinarie
(`docs/issues/master-tasks-refactor-design.md`, convergenza Claude⇄Gemini
17/07, mai implementata). Fase 1: sostituire le 3 logiche divergenti che
decidono "quali task esegue l'istanza X" (main.py loop registrazione,
predictor, dashboard hardcoded) con un'unica funzione, **zero cambio
funzionale**, garantito da un test di parità automatico.

**Implementato**: `shared/task_resolution.py::risolvi_task_istanza()` (nuovo)
+ `config/profiles.json` (nuovo, 4 profili: `completo`/`solo_raccolta`/
`fast`/`master`). Sostituisce il filtro manuale in `main.py::_thread_istanza`
(righe 739-780) e la selezione `tasks_consid` in
`core/cycle_duration_predictor.py` (righe ~1018-1056). `main.py::_TASK_CLASS_TO_NAME`
diventa alias della mappa canonica (era una copia manuale da tenere in sync).

**Due scoperte durante l'implementazione** (verificate sul codice, correggono
la proposta originale — dettagli in `docs/issues/master-tasks-refactor-design.md`):
1. Il kill-switch `globali.task.*` NON è nella catena di precedenza della
   funzione unica — resta un livello ortogonale gestito da ciascun chiamante
   (main.py: dentro `should_run()`, default `True`; predictor: a monte,
   default `False` — due filtri distinti preesistenti, non unificati).
2. Bug preesistente in `core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME`
   (manca 3 classi) — il predictor esclude sempre `grafica_hq`/
   `pulizia_cache`/`zaino` dalla stima indipendentemente dai flag dashboard.
   Lasciato intatto deliberatamente (fuori scope, cambierebbe la stima).

**Test**: 176 nuovi/riscritti, tutti verdi — `test_task_resolution.py` (15,
algoritmo puro), `test_migration_parity.py` (145, vecchia logica congelata
vs nuova su tutte le 12 istanze reali + scenari sintetici), riscritto
`test_master_task_whitelist.py` (12, ora chiama la funzione vera invece di
reimplementarla — era la quarta copia divergente). Durante la scrittura
della parità trovato e corretto un bug reale nella bozza iniziale (kill-switch
verificato su nome post-swap invece che pre-swap) — la parità ha fatto
esattamente il suo lavoro. Suite completa: 178 falliti/1020 passati,
verificato che ogni fallimento rientra nel debito pre-esistente noto
(orchestrator/zaino/navigator/alleanza/main/radar/rifornimento/task-async/
ocr_helpers/store/arena) — zero nuove regressioni.

**Non ancora fatto**: Fase 2 (`task_overrides`/UI dedicata, sostituisce
`master_task_whitelist`), Fase 3 (varianti — pilota `arena`, **decisione A1
ancora aperta**: quali altri task differenziare oltre ad arena, rimandata
esplicitamente dall'utente), Fase 4 (cleanup `tipologia` deprecata).

**Richiede riavvio BOT** per essere attiva (main.py + predictor toccati) —
non ancora riavviato, da pianificare (mai mid-tick). Commit + push +
sync prod da completare in questa sessione.

---

## Sessione 19/07/2026 (8) — Fix bug monitor (day-over-day) + pannello dedicato `/ui/config/master`

Continuazione della sessione (7): mentre si attende il rientro di Gemini
(token saturi), due attività separate:

**1. Bug nel sistema di monitoraggio stesso** — vedi dettagli in sessione (7)
aggiornata / `docs/revisione_bot_2026-07.md` §2-bis. Fix `--dod` day-over-day
in `tools/verifica_fix_revisione.py`, commit `97be59e`.

**2. Pannello dedicato `/ui/config/master`** (richiesta utente, non un fix):
nuova pagina separata da `/ui/config/global`, 3 sezioni classificate sui dati
reali del codice (nessuna congettura):
- **① Task Standard**: grafica_hq/pulizia_cache/boost/rifornimento/truppe/
  donazione/main_mission/zaino/vip/alleanza/messaggi/arena/arena_mercato/
  district_showdown/store/radar — stesso codice di un'istanza ordinaria
  (verificato zero branching su raccolta_only/master), **selezione
  interattiva** (whitelist) di quali far girare sul master, badge ⚠ sui
  non ancora validati.
- **② Task Personalizzati**: raccolta/raccolta_chiusura (sempre attivi) —
  livello nodo + livello trasporto, con valore "standard" calcolato dal
  valore più diffuso tra le istanze ordinarie (non hardcoded); verificato
  7 vs 6, 25 vs 20 per il master attuale.
- **③ Task Solo Master**: task esclusivi del master (classe dedicata, non
  un toggle su un task condiviso) — **onestamente vuota**, nessuno esiste
  oggi nel catalogo (`FauMorfeusSetupTask` rimosso con WU-MasterTasks).

**Correzione post-feedback utente (stesso giorno)**: la prima
implementazione mostrava in ③ la whitelist di task CONDIVISI con le
istanze ordinarie ("sono per tutte le istanze", feedback diretto) —
spostata in ① dove appartiene concettualmente; ③ resa onestamente vuota
con nota + rimando a `docs/issues/master-tasks-refactor-design.md`
(variante `arena`, decisione A1) per il futuro.

Nome generico "master" (non "FauMorfeus", su richiesta utente esplicita):
risolve il/i nome/i master via `shared.instance_meta.get_master_instances()`,
nessun nome hardcoded — resta valido se cambia quale istanza è il master.
**Zero nuove API**: riusa `PATCH /api/config/overrides/istanze/{nome}` già
esistente. Solo `GET /ui/config/master` + `config_master.html` + link nav.

Validato: render con dati prod reali (whitelist 8/8 corretti in ①), edge
case nessun master, home non impattata. Suite dashboard 20/20 verdi. Sync
prod, commit `d681251` + `c17ab7d` (fix). **Richiede riavvio DASHBOARD** (non bot).

Dettagli completi: `docs/issues/dashboard-config.md`.

**3. Aggiornamento batch `livello_trasporto` (config live, in-game, 19-20/07)**
— l'utente alza manualmente il livello "stazione di scambio" di alcune
istanze e lo comunica una per volta; `runtime_overrides.json` aggiornato
dynamic dev+prod ad ogni richiesta (merge-preserving, hot-reload, no restart).
**Stato**: FAU_01/02/03/04/05 → 21 (era 20), FAU_00=24 (pre-esistente),
**FAU_06-10 ancora a 20** — probabile continuazione in sessione successiva,
chiedere prima di assumere completato. Con 5/10 ordinarie a 21 si è creato un
pareggio nella "moda" usata dal pannello master per il valore "standard" —
segnalato a Gemini (non ancora rientrato), non ancora deciso se aggiustare il
criterio. Non committato in git (stato live, stesso trattamento di
`state/*.json`). Dettagli in `.claude/SESSION.md`.

---

## Sessione 17-18/07/2026 (7) — Revisione tecnica bot+dashboard R-01..R-10 + throttle DS

Revisione autonoma Claude/Gemini (4 assi: correttezza, architettura, performance,
dashboard+affidabilità/test) su `docs/revisione_bot_2026-07.md`. Dopo la Fase B
(10 findings qualificati con Gemini), Gemini è andato offline (token saturi);
implementazione/validazione proseguita da Claude con spiegazione dettagliata +
conferma utente per ciascun fix.

**Risolti (7)**:
- **R-10**: `pytest.ini` (testpaths=tests, --import-mode=importlib, ignore
  test_device.py obsoleto) → collection sbloccata (crash→1009 test raccolti).
- **R-09**: fallback static `max_squadre`/`livello` (`_ovr(k, ist.get(k,cost))`,
  pattern WU220) + allineato `instances.json` driftato (FAU_01-10 4→5).
- **R-02**: field-wipe Pydantic → `extra='allow'` su Istanza/Globali/RuntimeOverride
  (validato su config prod reale, 0 campi persi). **Richiede riavvio DASHBOARD**.
- **R-03**: raccolta — screenshot post-marcia mancante → esito prudente FALLITO
  (no falso OK). Commit `e698eb8`.
- **R-04**: rifornimento — invio confermato solo se pannello VAI chiuso (no
  doppio invio). Commit `bf744db`.
- **R-05**: alleanza — gate HOME `skip()`→`fail()`, uniformato a messaggi/boost
  (skip rinviava 4h, rischio perdita claim). Commit `8df5a48`.
- **R-07**: store — `STORE_NON_TROVATO` `fail()`→`skip()` (no rescan griglia
  ogni ciclo). Commit `f0e4e0d`.
- **R-06**: finestra evento DistrictShowdown duplicata (task↔predictor,
  drift latente su `ds_end_hour`) → unificata in
  `shared/task_scheduling.py::is_in_ds_event_window`. Commit `407f60c`.

**Chiuso non riprodotto (1)**:
- **R-08**: proposta "persistenza dadi esauriti" **scartata** — telemetria
  live (FAU_00/FAU_01, 6-7 run/giorno con roll reale 160-270s ciascuna) +
  conferma utente (20 dadi iniziali ven + 1/30min fino a fine evento + reward)
  smentiscono un pool unico esauribile. Implementarlo avrebbe causato perdita
  di dadi (regressione), non un'ottimizzazione. Nessuna modifica al codice.

**Sistema di monitoraggio anti-regressione** — `tools/verifica_fix_revisione.py`
(baseline/check, KPI fail_rate+throughput/run+ERROR/h+eccezioni da telemetry
events + log per-istanza) + Monitor live poll 10min (solo transizioni
azionabili). Baseline pre-restart catturata in prod.

**Ottimizzazione post-revisione — throttle DS ven/sab** (richiesta utente,
fuori scope R-01..R-10): nuovo `DistrictShowdownState` (`core/state.py`,
pattern BoostState) — venerdì/sabato skip se gap < 300min (~10 dadi) dall'ultimo
`dadi_esauriti` confermato; domenica nessun gate (a ridosso chiusura evento,
ogni dado va raccolto subito). Timer riparte SOLO su conferma positiva, mai su
esiti ambigui (vincolo esplicito utente). Retrocompatibile con state file prod
esistenti. Commit `319ac06`.

**Test**: +12 (`test_state.py` DS throttle), +8 (`test_ds_event_window_r06`),
+5 (`test_field_wipe_r02`), +4 (`test_config_static_fallback`). Suite completa
860 pass/177 fail (baseline sessione 829/180) — zero fail nuovi, i 177 sono
debito pre-esistente noto (orchestrator/zaino/navigator/alleanza/main/radar/
rifornimento/task-async/ocr_helpers/store-residual/arena).

**19 commit pushati su origin/main** (`f50be08..319ac06`).
**Richiede riavvio BOT** (R-03/04/05/06/07/09 + throttle DS) **+ DASHBOARD** (R-02).
Doc completo: `docs/revisione_bot_2026-07.md`.

---

## Sessione 17/07/2026 (6) — WU-MasterTasks: selezione task master config-driven (ANNULLA WU234)

Richiesta utente: per necessità di tempo, delegare al master (FauMorfeus)
una serie di task che normalmente esegue a mano, **selezionabili** e con la
**stessa schedulazione** delle istanze ordinarie — annullando il bundle
giornaliero fisso WU234.

**Progettato + implementato** un'infrastruttura generica config-driven che
sostituisce il task-bundle WU234:
- Nuovo campo per-istanza `master_task_whitelist` (lista nomi task) in
  `runtime_overrides.json` (dynamic). Il master (`tipologia=raccolta_only`)
  registra sempre RaccoltaTask/RaccoltaChiusuraTask + i task selezionati,
  ciascuno con la sua schedulazione normale da `task_setup.json`.
- `main.py`: filtro `_solo_raccolta` ora consulta la whitelist (mappa
  `_TASK_CLASS_TO_NAME` classe→nome, anti-drift vs task_setup.json).
  `forza_solo_raccolta` (doppio giro FAU_00) → whitelist ignorata.
- `config/config_loader.py`: `MASTER_TASK_WHITELIST` + `master_task_whitelisted()`.
- `tasks/grafica_hq.py` + `tasks/pulizia_cache.py`: lo skip interno
  `raccolta_only` è ora **whitelist-aware** (saltano solo se il master non
  li ha selezionati; prima erano sempre saltati per il master).
- **UI**: nuova sezione "task del master" in `/ui/config/global` con checkbox
  per task, salva via `PATCH /api/config/overrides/istanze/{nome}`.
- **Pydantic** `IstanzaOverride`: aggiunti `master_task_whitelist` **e**
  `raccolta_reset_leggero_abilitato` (quest'ultimo mancava — bug-class
  field-wipe WU199/WU102: un save dashboard avrebbe revertito il rollout
  WU232 di stamattina; ora blindato).
- **Rimosso** `FauMorfeusSetupTask` (WU234): `tasks/faumorfeus_setup.py`,
  test, riga catalogo `main.py`, riga `task_setup.json`, eccezione filtro.

**Whitelist FauMorfeus impostata (prod)**: grafica_hq, pulizia_cache, vip,
alleanza, messaggi, donazione, district_showdown (7 — "monopoli" dell'utente
= district_showdown). Nota: boost, che era nel bundle WU234, NON è più
eseguito dal master (non selezionato).

**Test**: `tests/unit/test_master_task_whitelist.py` 11/11 (whitelist config,
anti-drift mappa, filtro registrazione, rimozione WU234, round-trip Pydantic).
`test_config.py` verde. Sync dev→prod byte-identico (9 file + rimozione task).
**Richiede riavvio BOT** (codice) + **riavvio DASHBOARD** (UI/modello/endpoint).

---

## Sessione 17/07/2026 (5) — WU234: FauMorfeusSetupTask (bundle giornaliero master) [ANNULLATA da (6)]

Richiesta utente: FauMorfeus (master, `tipologia=raccolta_only`) non riceve
MAI grafica_hq/pulizia_cache/boost/vip — `main.py::_thread_istanza` filtra
la registrazione al solo `RaccoltaTask`/`RaccoltaChiusuraTask` per quel
profilo. Utente vuole questi 4 task, "proprio uguali" alle istanze
ordinarie, lanciati una sola volta dopo il reset giornaliero.

**Implementato**: `tasks/faumorfeus_setup.py::FauMorfeusSetupTask`, nuovo
task che riusa la logica esistente (non riscritta):
`esegui_grafica_hq()`/`esegui_pulizia_cache()` chiamate direttamente
(bypassando lo skip `raccolta_only` nei wrapper `GraficaHqTask.run()`/
`PuliziaCacheTask.run()`), `BoostTask`/`VipTask` riusati via
`should_run()+run()` diretto (nessuno skip di tipologia nei due, quindi
nessun bypass necessario). Best-effort: un fallimento non blocca gli altri
3. `ctx.navigator.vai_in_home()` chiamato a mano fra uno step e il
successivo (l'orchestrator lo farebbe automaticamente per task singoli, ma
qui sono 4 step dentro un unico `run()`).

`should_run()` → `is_master_instance(ctx.instance_name)`. Registrato in
`config/task_setup.json` con `"schedule": "daily"` (riusa lo scheduling
giornaliero già esistente di VipTask/ZainoTask — risolve esattamente "al
primo avvio dopo il reset giornaliero"). Una riga toccata in `main.py`
(filtro `_solo_raccolta` esteso con l'eccezione `FauMorfeusSetupTask` —
sicuro sulle istanze ordinarie perché la sua stessa `should_run()` le
esclude comunque).

Test: 8/8 nuovi (`tests/tasks/test_faumorfeus_setup.py`) + suite
`test_vip.py`/`test_boost.py`/`test_config.py`/`test_scheduler.py`
invariata (150/150). Documentato in `docs/OVERVIEW.md` §5.20. Richiede
**riavvio BOT** (nuova classe task, non solo config).

---

## Sessione 17/07/2026 (4) — WU231/232/233: blacklist atomica, canary reset leggero, fail-fast launcher

**WU231 — `BlacklistFuori` scrittura non atomica + azzeramento silenzioso su JSON
corrotto (`a8230ca`).** Trovato durante analisi di robustezza raccolta: `_carica()`
tornava `{}` su qualunque eccezione di parsing (JSON troncato da crash a metà
scrittura → blacklist persa senza log), `_salva()` scriveva diretto sul file finale
(crash a metà write → stesso esito). Fix: scrittura atomica tmp+`os.replace`,
`_corrotto` flag + log ERROR invece di azzeramento silenzioso. Test +8.

**WU232 — canary strumentato reset leggero raccolta (`4b7b94d`).** Un thread con
Gemini proponeva di sostituire il reset pesante (HOME→MAPPA) dopo un fallimento
`_verifica_tipo` con un singolo `BACK`. Verifica storica ha trovato che il commit
`7c5e789` (18/04) documenta un fallimento SISTEMATICO già osservato con esattamente
quel pattern (BACK singolo + cambio livello). Rischio riclassificato da basso ad
alto → invece del fix diretto, canary opt-in per istanza
(`raccolta_reset_leggero_abilitato`, dynamic) con strumentazione dedicata
(log `[CANARY-RESET-LEGGERO]`). Attivato su FAU_02, poi esteso a FAU_07+FAU_10 su
richiesta utente. **13/13 eventi confermati OK, zero soft-fail, zero hard-fail**
(verificato indipendentemente anche da Gemini, riconciliato un disaccordo di
conteggio 15 vs 13 dovuto a doppio conteggio con sfasamento di 2h). Monitoraggio
in corso, nessuna decisione di rollout ancora presa. Test +14 (81/81 totali in
`test_raccolta.py`).

**WU233 — Launcher: fail-fast su `MuMuManager launch` returncode ignorato.**
Da un secondo thread Gemini (`boot_stability_analysis.md`, 4 proposte su
`core/launcher.py`). Verificate tutte prima di applicare: **3/4 respinte o
ridimensionate** (il kill-server ADB incondizionato è il fix storico `#F1b`,
commit `1d1b4eb`, per un incidente reale — 5/11 istanze fallite in un ciclo; il
crash-recovery in `attendi_home` è già coperto da meccanismi esistenti; il socket
check preventivo ha valore marginale). **1/4 confermata**: `avvia_istanza()`
ignorava il `returncode` di `MuMuManager launch` — un errore bloccante faceva
comunque attendere l'intero timeout di polling (~200s) prima di fallire. Fix
isolato, nessun impatto su `istanza_metrics.py`. Sync prod immediato. Dettagli
completi dello scambio in `docs/issues/infra-startup.md` (WU233) e
`shared_ai_exchange/claude_to_gemini.md` (seq 46).

---

## Sessione 15-16/07/2026 (3) — WU227/228/229: log rotation, doppio giro nel piano, potatura orfani

**WU227 — rotazione log `.jsonl` fallita in silenzio (fix, `689c5c6`).** Scoperto
dall'utente sul doppio giro FAU_00: i due passaggi finivano mescolati nello stesso
file. Causa (tutte le istanze, da sempre): `main.py` ruotava con `os.replace` in un
`except: pass`, ma `get_logger` tiene il file **aperto** e su Windows il rename di
un file aperto fallisce → la rotazione riusciva solo alla 1ª run dopo un riavvio.
Fix: `StructuredLogger.rotate()`/`rotate_logger()` (chiude, rinomina, riapre); WARN
invece del silenzio. Test 19→27 (+2 pre-esistenti sanati). Riavvio BOT.

**WU228/228b — doppio giro visibile nella pianificazione (`24a3420`+`447b68c`).**
Utente: "la pianificazione dice FauMorfeus, invece è partito FAU_00". Il 2° giro è
inserito al volo dal gate del master, fuori dall'ordine persistito.
`ordina_istanze_adaptive(includi_doppio_giro=True)` opt-in aggiunge una voce
virtuale `FAU_00 ↻²` prima del master. La lista è ESECUTIVA → main.py filtra
`is_doppio_giro` (lista byte-identica al default), e `get_remaining_from_resume` lo
esclude (senza, un resume rieseguirebbe FAU_00 come tick completo). **228b**: la
voce non si disegna se aritmeticamente impossibile — se FAU_00 è in coda la finestra
`t_master − t_avvio` < 120min. Verificato sul ciclo reale (finestra 38m → niente
voce). **Nota**: la posizione "prima del master" è progettuale, non calcolata — il
greedy avanza il tempo ma non lo stato simulato, quindi non può valutare un'istanza
già pianificata; miglioria futura identificata (stato simulato → 2° giro candidato
ordinario). Riavvio BOT + DASHBOARD.

**WU229 — potatura anticipata orfani (`eeaff2f`).** Utente: "record vecchi di 800
min, perché non eliminati?". Erano orfani tenuti fino al TTL 12h. La classificazione
orfano (WU226) viveva solo nel pannello, non nel pruning. `esegui_riconciliazione`
ora pota prima del TTL se raccolta finita + istanza ripassata a leggere ≥2 volte
senza report. Soglia 2 (conservativa: ~7h oltre la fine, oltre il max reale 5.1h).
Sul pool reale: 65→59 pending, massimo da 730min a 361min. Test 33→39. Riavvio
DASHBOARD.

**WU230 — sonda measure-before-cut OCR ramo skip (`4d48e6b`).** Da uno scambio con
una seconda AI (Gemini, `shared_ai_exchange/`) che proponeva di rimuovere la verifica
finale del livello nel ramo skip. Nel ramo skip le due letture sono dello stesso
pannello statico → la 2ª coglie solo glitch transitori, ma il tasso di disaccordo non
è misurato. Prima di tagliare, sonda OSSERVATIVA (zero cambio comportamento): log
`[MONITOR-OCR-SKIP]` sulle anomalie (disaccordo + 2ª lettura `-1`). Denominatore =
righe `"skip reset"`. Richiede **riavvio BOT**; poi analisi dopo N cicli e decisione
sul taglio. Test 64/64. Dettagli in `docs/issues/raccolta.md`.

---

## Sessione 15/07/2026 (2) — WU224/225/226: TTL orfane, ricostruzione storico, riclassificazione pannello

**WU226 — il "ritardo" non esiste (fix finale del pannello).** Segnalazione
utente: *"questi dati così sono senza logica, il ritardo è dovuto alla lettura
causa blocco del bot"*, con righe tipo "in ritardo di 518min" in cima. Aveva
ragione, ed era un **effetto combinato di WU224+WU225**: il TTL a 12h tiene le
occupazioni nel pool 3× più a lungo e l'ordinamento per ritardo le portava in
testa, seppellendo l'unica informazione vera. Il "ritardo" non è un concetto
valido: la stima è una mediana (metà delle raccolte la sfora per definizione) e
il completamento si vede solo quando l'istanza ripassa a leggere il tab.

`get_occupati_in_volo` ora **classifica** — discriminante *"l'istanza ha riletto
il tab DOPO la fine prevista?"* (nuovo `_letture_report_per_istanza()`, cluster
`ts_ocr` per gap >60min): `orfana` (ha riletto, report assente → non arriverà:
marcia fallita o riga persa — **unico stato azionabile**), `in_volo`,
`attesa_lettura` (neutro), `senza_stima`. Prod: 66 pending = **10 orfane / 42 in
volo / 14 attesa lettura**; le 5 righe FAU_03 a 8.5h erano esattamente il caso
dell'utente (restart 13:36 → rimessa in coda).

**Esclusione master** (richiesta utente: *"FauMorfeus è un dato completamente
inattendibile, raccoglitori inviati manualmente, o gioco disabilitato per
eventi"*): verificato che il master **non entrava già** in stime/pool/pending/
match — `nodi_mappa.py:108` gli blocca le occupazioni a monte, e senza invio non
c'è match (0 su tutti e tre). **Ma i suoi report sì**: 42 righe. Corretto: il
riepilogo confrontava occupazioni senza master (1419) con report con master
(1280) → ora 1238 vs match 1208 = **30 orfani reali**. E **i "72 orfani
irrecuperabili" di WU225 erano 42 FauMorfeus by design + 30 genuini** → tasso
reale 2.4%, non 5.7%. Test 9→19, baseline invariata (51 fail / 444 pass).

---

## Sessione 15/07/2026 (2a) — WU224 ordinamento in-volo + WU225 diagnosi TTL orfane

**WU224 — ordinamento pannello (commit di questa sessione).** Richiesta utente:
"ordina la lista in base al tempo più lungo del ritardo".
`dashboard/services/report_raccolta_reader.py::get_occupati_in_volo` ordinava per
`(instance, ts_invio)` → ora per `residuo_min` crescente (più in ritardo in testa,
`n/d` in fondo). Verificato sui dati prod. **Richiede riavvio DASHBOARD**, non il bot.

**WU225 — diagnosi (APERTA, nessun fix applicato).** La domanda dell'utente
("FAU_02 avviata ora non compare, e perché non FAU_05 che è fortemente in
ritardo?") ha fatto emergere due artefatti dello stesso meccanismo:

- **Scheduling: nessun errore.** L'ordine deciso alle 15:08 era
  `FAU_00 → FAU_02 → FAU_05 → ...` — FAU_05 era *già* la prossima. Al passo 2
  FAU_02 `sla=5/5, anz=234m` ha battuto FAU_05 `sla=4/5, anz=220m` (gli slot
  precedono l'anzianità); al passo 3 FAU_05 arriva a `sla=5/5` ed è scelta.
- **Il "ritardo" del pannello non è un ritardo di gioco**: il completamento
  esiste solo quando l'istanza riparte e legge il tab Report → latenza
  invio→report ≈ un periodo di ciclo. `TTL_ORFANE_ORE=4.0` pota prima. Le 4
  righe FAU_05 sono state potate alle 15:32:35 *durante* l'analisi; le 5 di
  FAU_02 alle 15:17, ~10min prima che ripartisse.
- **Impatto misurato**: 1269 report → 491 matchati, **706 orfani ma abbinabili**
  (660 con durata <4h). Cattura 41% dei campioni. Perdita **selettiva sui
  lenti**: persi p50 3.00h/p90 3.89h vs matchati p50 2.82h/p90 3.19h. Periodo
  di ciclo p50 3.46h, 29% ≥4h. Critico perché WU223 Fase C ha eliminato lo
  statico → questo dataset è l'unica fonte del predictor.
- Il fermo bot del giorno (aggiornamento) ha allungato il ciclo ma **non è la
  causa**: 52-69% di orfani anche nei giorni senza fermo.

**WU225 — fix applicato**: `TTL_ORFANE_ORE` **4.0 → 12.0**, nient'altro (test
guardrail aggiornato, suite 33/33). Effetto dal **riavvio dashboard**. Due
proposte intermedie scartate su challenge dell'utente, entrambe smentite dalla
simulazione fedele del matcher sullo storico:

- *guard sulla durata plausibile* → rifiuta **zero**; a qualunque TTL fino a 48h
  le durate restano ≤5.10h, zero implausibili. Le chiavi riusate (unica
  popolazione dove la collisione è possibile) hanno durate **più strette** delle
  chiavi usate una volta sola. La chiave + "più recente precedente a
  `ts_raccolta`" bastano da sole; il TTL è igiene del pool, non una difesa.
- *riconciliazione live dopo la lettura del tab* → 497 match vs 506 (TTL 4h),
  1190 vs 1189 (TTL 10h): rumore. Non si legge più in fretta un report non
  ancora nato. Costerebbe una race cross-processo su
  `tempo_raccolta_match_state.json` (`_lock` è per-processo) → la scelta
  architetturale del 10/07 (match nel loop, non nel task) resta giusta.

Curva TTL (match/orfani): 4h 506/768 · 8h 1146/128 · **12h 1201/73** · 16-48h
1202/72 (satura).

**WU225b — ricostruzione storico (fatta, in prod 16:16).** Nuovo
`tools/rebuild_tempo_raccolta_dataset.py`: dry-run default in sandbox,
`--apply` con backup in `data/archive/`, guard anti-race sul loop dashboard
(`_lock` è per-processo). **Non reimplementa il matcher** — azzera lo stato e
richiama `esegui_riconciliazione()` su tutto lo storico in un batch (scenario
già previsto da WU200quater: match precede potatura → zero divergenza dal
comportamento live). Risultato: **491 → 1208 match (+717)**, celle ≥3 campioni
**35 → 49**/57, p90 3.19→3.74h, max 4.02→5.10h (il 4.02 era la firma della
censura). Integrità: cursori a EOF, 0 duplicati, 0 occupazioni riusate, 0
durate ≤0. Nessun riavvio necessario.

**Effetto sul predictor**: 8/20 celle campione cambiate di ≥5min, delta medio
+5.2min. `campo`/L7 (una delle 6 celle tappate dal pool WU223) rivela uno
spread reale di **95min** che il pool appiattiva: FAU_00 171→**126min**,
FAU_07 170→**221min**, FAU_05 171→208, FAU_02 164→179.

Dettagli in `docs/issues/telemetria-predictor.md` (WU224/WU225).

---

## Sessione 15/07/2026 — WU223: fallback cross-istanza + Fase C (statico eliminato)

**Contesto** (richiesta utente: "per ovviare al problema del 12% effettua una
media di quella tipologia dalle altre istanze simili FAU_01…FAU_10, con un
censimento dei buchi" → "fallback cross-istanza senza FAU_00, poi elimina la
parte statica"): il predictor T_marcia empirico (WU202 Fase B) copriva l'88%
delle celle; il restante 12% cadeva sulla stima statica (6 celle a bassa
allocazione: FAU_00/05/03/09 campo·L7, FAU_08/07 acciaio·L6).

**Step 1 — fallback cross-istanza (commit `7834aeb`).** Nuovo tier in
`stima_tempo_raccolta`: se una cella `(istanza,tipo,livello)` non ha ≥3 campioni
diretti né proporzione per-istanza, usa la **mediana del pool `(tipo,livello)`
dalle ordinarie** (tutte tranne FAU_00, più veloce ~2h09m → esclusa per non
abbassare la mediana altrui). Censimento: campo/L7 pool=29 (2h51m), acciaio/L6
pool=6 (2h44m) → **tutti i 6 buchi coperti empiricamente**. Copertura 88%→~100%.

**Step 2 — Fase C, statico ELIMINATO (commit `f3ce078`).** Con copertura ~100%
lo statico è peso morto. Rimossi: `_calc_t_marcia_static`, tabella
`predictor_t_l_max` (`_load_t_l_max_config`/`_get_t_l_max_min`), flag
`tempo_raccolta_empirico_enabled` (cache + config + PATCH + toggle),
`core/t_marcia_calibration.py`, campo osservativo `confronto_tempo_raccolta`,
tool `predictor_backtest_empirico.py`. `_calc_t_marcia_min` ora: empirico →
(fallback) costante farm `_FALLBACK_RACCOLTA_MIN=168min` → None solo per invio
degenere. Toggle dashboard → badge "permanente". Test `test_calc_t_marcia_tiered`
riscritto (6/6 pass), `test_adaptive_scheduler_confronto` rimosso.

**Stato**: ✅ **LIVE dal 15/07 13:36** — il riavvio bot per l'aggiornamento MuMu
ha attivato il batch (WU214/217/218/221/219/220 + WU223). Verificato: prod non
contiene più `_calc_t_marcia_static` (Fase C), i file erano sincronizzati alle
11:52 e il processo è partito alle 13:36; nessun file runtime del bot risulta
più recente dell'avvio. Conferma a runtime: gli `[ADAPT-TRACE]` del ciclo 15:08
riportano il campo `emp=N/nMαX` → `_calc_t_marcia_min` sta usando la stima
empirica. Dettagli in `docs/issues/predictor-cutover-plan.md` §5.3.2.

---

## Sessione 12/07/2026 — WU202: cutover predictor Fase B (T_marcia empirico, flag-gated)

**Contesto** (richiesta utente: "estrai, verifica e progetta" → "procedi con la
fase B completa, poi allinea la documentazione"): il sistema
report_raccolta + tempo_raccolta_estimator (WU199/WU200) misura il tempo di
raccolta reale per (istanza,tipo,livello). Obiettivo: inserirlo come parametro
del predictor T_marcia, sostituendo il modello statico dove ci sono dati.

**Estrazione + analisi** — nuovo documento `docs/issues/predictor-cutover-plan.md`:
mappa dei 3 consumer di `_calc_t_marcia_min`, snapshot dati prod (155 match,
24/40 celle ≥3 campioni, calibrazione closed-loop quasi inerte 5/21 coef attivi,
eta mediano 59s), e **revisione sui dati** dell'elenco eliminazioni della
memoria WU200ter: confermato eliminare `core/t_marcia_calibration.py`, ma
`config/predictor_t_l_max.json` va **declassato a fallback** (non eliminato —
acciaio/campo-L6 scarni), swap **tiered** non secco, `empirical_slot_predictor`
rimandato.

**Fase B implementata** (flag OFF, zero regressione):
- `core/skip_predictor.py::_calc_t_marcia_min` TIERED — stima empirica primaria
  (`stima_tempo_raccolta`, `durata_s + eta`) se cella ≥3 campioni, altrimenti
  fallback statico invariato. Gate `tempo_raccolta_empirico_enabled` (default
  OFF, DYNAMIC>STATIC, cache 15s). Firma invariata → 3 consumer coperti.
- Fix confronto WU200ter `2×eta → eta` (un eta di troppo, ~1min).
- Cache mtime sul dataset (`shared/tempo_raccolta_estimator._carica_dataset_output`,
  pattern WU197) — il confronto già oggi rileggeva l'intero file per-invio.
- Flag in `config/config_loader.py` + `global_config.json`; toggle UI nella
  card adaptive scheduler (`/api/adaptive-scheduler` PATCH dual-write).
- Test `tests/unit/test_calc_t_marcia_tiered.py` (6). Suite correlata 42/42.
  Verifica end-to-end su dati prod: FAU_00 +3.2%, FAU_02 (lento) **+15.6%**,
  acciaio L6 (cella scarna) fallback identico. Baseline pytest invariata
  (51 failure pre-esistenti, async/deps/fixture stale).

**Pending utente**: attivare shadow → LIVE pilota → estendere. Fase C (rimozione
`t_marcia_calibration`) non iniziata.

---

## Sessione 11-12/07/2026 — WU200: tempo_raccolta_estimator + pannello dashboard + verifica live cicli notturni

**WU200 — stimatore empirico tempo di raccolta** (11/07, dettagli completi in
`docs/issues/telemetria-predictor.md`): costruito su richiesta utente
("possiamo già implementare il sistema, abbiamo tutti gli elementi") il
job di riconciliazione fra evento invio (`nodi_mappa_observations.jsonl`,
esito `occupato`) e completamento (`report_raccolta_dataset.jsonl`, vedi
WU199 in `docs/issues/raccolta.md`) — nuovo modulo
`shared/tempo_raccolta_estimator.py`, loop periodico in
`dashboard/app.py::_tempo_raccolta_loop()` (15 min, mai nel task raccolta).
4 bug trovati e corretti durante lo sviluppo, tutti scoperti da richieste
di verifica dati live dell'utente (WU200quater ordine match/potatura,
WU200quinquies filtro tipo/livello, WU200sexies chiave esplicita a 4
componenti, WU200septies — decisione finale: il Tab Report è fonte di
verità sul livello, non l'occupazione all'invio, che registra solo il
target di ricerca). WU200ter collega il risultato all'adaptive scheduler
in sola osservazione (`confronto_tempo_raccolta`, zero regressione
verificata via test dedicato).

**Pannello dashboard `/ui/report-raccolta`** (11-12/07, richiesta utente
"puoi costruire una pannello di appoggio per visualizzare in questa
fase?"): nuovo `dashboard/services/report_raccolta_reader.py` + 6
partial HTMX + template dedicato. 6 sezioni: riepilogo dataset,
raccoglitori in volo con stima arrivo, timeline eventi, tempo di
raccolta aggregato per (istanza,tipo,livello) — **sostituita su feedback
utente** rispetto alla prima versione (lista raw per-match, giudicata
poco utile) — e produzione oraria unificata per istanza/totale farm
(riusa `shared/prod_unificata.py`, nessun nuovo calcolo). Nota di
processo: 2 commit sono stati etichettati `WU200bis`/`WU200quater`
riusando per errore numerazione già impiegata l'11/07 per il fix
TTL/retention e per il fix ordine match/potatura — disambiguato nei
`docs/issues/` per hash commit, nessun impatto sul codice.

**Analisi cicli notturni** (12/07, richiesta utente): cicli 490-492
(sera→notte→primo mattino) tutti completati, **zero fail rate** in
telemetria (230 eventi, 0 `success=False`, 0 anomalie). Ciclo 491 (283min
vs 203/177min degli altri due) non è un'istanza rotta ma **clustering di
task periodici** (rifornimento/store/vip/donazione/alleanza/messaggi/
arena_mercato/boost tutti scaduti insieme su più istanze) — lavoro reale
in più, non retry. Il cycle duration predictor sottostima pesantemente
proprio in presenza di clustering (37-50% di errore sul ciclo 491, vs
0.4-5% sul ciclo 492 "pulito") — non approfondito oltre, area di
miglioramento futura per `core/cycle_duration_predictor.py` se si vorrà
riprendere. 47 report riconciliati overnight, durata reale media 2.68h,
FAU_00 in testa (10 completamenti).

**WU201 — cluster boot-timeout mattutino** (12/07, dettagli in
`docs/issues/infra-startup.md`): utente ha segnalato istanze non
avviate — prima verifica su log JSONL/telemetria ha dato falso negativo
(evento invisibile lì), trovato poi in `bot.log`: 8/11 istanze hanno
colpito il timeout 300s "schermata ancora UNKNOWN" fra le 06:56 e le
09:00 locali, ciascuna chiusa e rimandata al ciclo successivo senza
retry immediato. Causa sistemica non diagnosticata (sospetto
rallentamento host). Mitigazione: `timeout_carica_s` 300→400s in
`runtime_overrides.json` (dynamic). **Scoperta collaterale**: un boot
fallito non viene marcato come tale in `data/telemetry/cicli.json` (resta
`esito: "ok"`) — bug di tracciamento noto, non corretto in questa
sessione.

**Task zaino riattivato in modalità `svuota`** (12/07): dopo 25 giorni
di gap (task disabilitato dal 17/06), riattivato su tutte le 11 istanze
ordinarie — 100% successo, zero anomalie, ~2.6 miliardi di unità totali
scaricate (accumulo storico). Confermato con l'utente: questo tipo di
evento (dump one-time nel castello) è uno dei motivi per cui è in corso
la seconda finalità di WU200 — un futuro calcolo produzione basato su
`report_raccolta` (resa per nodo raccolto), svincolato dalle variazioni
di deposito castello non correlate a produzione reale (zaino, rifornimento
ricevuto). Nessun codice scritto per questa seconda finalità in questa
sessione — solo la direzione confermata (memoria
`project_tempo_raccolta_estimator.md`).

**Chiarito** (non un bug): la dashboard mostra `risorse_iniziali`, uno
snapshot fatto all'apertura sessione/tick — non si aggiorna finché la
sessione non si chiude (`risorse_finali`, al tick successivo della stessa
istanza). Un evento che modifica il deposito a metà tick (es. zaino
svuota, se gira dopo rifornimento nell'ordine task) resta invisibile in
quel campo fino al giro successivo. Nessun fix applicato, solo spiegato.

---

## Sessione 10-11/07/2026 — WU199: report_raccolta fase 2 live + fix ordine rollout + sanity check OCR

**Notte 10→11/07 — WU199decies/undecies + validazione completa + flip a fase 2**:
dopo WU199nonies (bug critico tab, sotto), altri 2 fix minori: WU199decies
(log esplicito per check Sort Mail anche quando già OFF — utente ha
notato che il check era silenzioso nel caso normale) e WU199undecies
(`WAIT_OPEN`/`WAIT_TAB` allineati a `MessaggiConfig` — 2.0s→3.0s, FAU_03 e
FAU_08 avevano mostrato "tab non confermato" al primo tentativo con
2.0s). Utente è andato a dormire chiedendo di attivare la fase 2 "a fine
di questo ciclo" — gestito in autonomia: atteso il completamento del
ciclo (verificato via marker `MAIN CICLO N` successivo), **12/12 istanze
con `delete_ok: True`, zero warning, zero anomalie** (incluso FAU_08, che
in precedenza aveva fallito il tap tab — riuscito al primo colpo coi
nuovi delay). Flip `report_raccolta_solo_reset=False` su tutte le 12
eseguito subito dopo la conferma, allineato all'inizio del ciclo
successivo (nessun rischio di flip a metà ciclo). Prima lettura vera in
corso, verifica in monitoraggio.

**WU199nonies (commit `f6040d9`) — BUG CRITICO risolto**: l'utente ha
verificato live che FAU_03 aveva cancellato i messaggi **Alliance** invece
del report raccolta. Causa: `esegui_report_raccolta()` tappava
`TAP_TAB_REPORT` senza mai verificare che il tab fosse davvero cambiato —
se il tab restava su Alliance (stato in cui il flusso lo lascia
deliberatamente a fine di ogni run precedente, WU199bis), l'azione
"Read and claim all" + "Delete read" (WU199sexies) colpiva Alliance.
Fix: verifica OCR positiva ("Sort Mail", presente solo sul tab Report)
prima di qualunque azione, retry singolo + abort completo in sicurezza se
non confermato (nessuna lettura, nessun Delete). **Mitigazione immediata**:
`report_raccolta_abilitato=False` su tutte le 12 istanze finché il fix non
è sincronizzato e riavviato — nessuna nuova esecuzione possibile nel
frattempo. 4 nuovi test (2 end-to-end che validano l'assenza di tap
distruttivi), 21/21 verdi. **Riavvio + riattivazione da fare
esplicitamente dopo conferma utente.**

Continuazione diretta della sessione 09/07 (2). Fase 1 (reset) completata su
tutte le 12 istanze durante la notte, poi attivata la fase 2
(`solo_reset=False`, lettura vera con dedup + Delete a fine lista).

**Bug di processo scoperto in live (non un bug di codice)**: l'utente ha
chiesto di attivare la fase 2 "al volo" mentre il ciclo di reset era ancora
in corso. Le istanze non ancora raggiunte da `_leggi_risorse()` in quel
ciclo (FAU_07/06/03/02...) hanno trovato il flag già `False` al loro turno
— partite dritte in lettura completa senza mai passare dal reset. Per
istanze con backlog storico mai svuotato (FAU_02: 48 righe/15 pagine, cap
`MAX_PAGINE` raggiunto senza mai trovare `fine_lista_raggiunta` → nessun
Delete) ha riprodotto esattamente il problema che la fase 1 doveva evitare.
Diagnosticato da osservazione diretta utente ("FAU_02 non ha eliminato
tutti i nodi"). **Lezione generale salvata in memoria**
(`feedback_rollout_sequenziale_flag`): su un'architettura sequenziale
(un'istanza alla volta), un flag con semantica ordine-dipendente non va mai
flippato a metà ciclo — verificare via log che TUTTE le istanze abbiano
completato il passaggio precedente prima di procedere allo step successivo.
Fix applicato: `solo_reset=True` su tutte e 12, verificato via `bot.log`
che tutte avessero `delete_ok: True`, solo dopo flip a `solo_reset=False`
su tutte e 12.

**WU199quinquies — sanity check capacità nominale** (commit `cedbcdf`):
ispezionando i primi dati reali del dataset (232 righe/11 istanze) emerso
un pattern di corruzione OCR deterministico: bleed dell'icona risorsa nel
crop del valore, letto come cifra spuria prependuta al numero corretto —
sempre "5" per campo (es. `51,320,000` invece di `1,320,000`), sempre "2"
per segheria (es. `21,200,000` invece di `1,200,000`). Fix in
`shared/report_raccolta.py::_estrai_riga()`: tabella `_CAPACITA_MAX`
(valori nominali noti, memoria `reference_capacita_nodi`) usata come
sanity check — `quantita_base` oltre il nominale per (tipo, livello), o
`tipo` non riconosciuto, forzano `quantita_base=-1`, che instrada la riga
nello stesso path di scarto-e-ritenta già usato per OCR fallita (non
persistita, non marcata vista, riletta al giro successivo a un offset di
scroll diverso). 6 nuovi test in `tests/unit/test_report_raccolta.py`,
nessuna regressione sulla suite `raccolta`. Sync dev→prod + commit+push +
riavvio prod fatti (flag `restart_requested` consumato, fix attivo).

**Reset completo richiesto di nuovo** — utente ha notato ordine righe
sospetto su FAU_09 (riga fuori sequenza nel dataset) e ha chiesto
investigazione live. Scoperto un toggle "Sort Mail" mai considerato prima
(in alto a sinistra nel tab Report). Test live su FAU_08/FAU_10 (screenshot
+ tap via `AdbDevice` diretto, bot in pausa manuale sull'istanza):
- **Sort Mail NON riordina le righe** (ipotesi iniziale errata) — passa a
  una vista a categorie (Battle/Group Battles/Jungle Crisis/Zombie/Scout/
  Other), col Gathering Report annidato sotto "Other". Nessun impatto
  sull'ordine interno delle righe, che resta sempre più-vecchio-in-alto
  (bersaglio mobile, non fissabile via toggle).
- **"Delete read"** testato con conferma reale ("You're about to delete
  all read mails in the current tab") → produce lo stesso risultato di
  "Delete" diretto (report azzerato a "No mail received"). Per il nostro
  caso (un solo elemento mail che accumula tutte le righe) i due pulsanti
  sono equivalenti — nessuna cancellazione incrementale/parziale
  disponibile via UI.

**WU199sexies** (commit `14d6404`): su richiesta utente, il flusso ora
forza sempre il toggle OFF (rilevamento via differenza di luminosità tra
le due metà del cursore — tap SOLO se rilevato ON, mai alla cieca) e
sostituisce il tap diretto "Delete" con "Read and claim all" + "Delete
read" (2 tap, stesso risultato finale, ma garantisce il claim di eventuali
reward prima della cancellazione). 7 nuovi test, 77/77 verdi. Sync dev→prod
fatto, commit+push fatto. **Riavvio prod da programmare.**

Nel frattempo: `report_raccolta_solo_reset=True` riarmato su tutte le 12
istanze per un nuovo ciclo di reset completo (dataset ridotto a poche righe
per istanza, più facile da validare). Verificato che il cambio flag non è
retroattivo sulle istanze già passate nel ciclo corrente (config letta a
inizio `_leggi_risorse`, non ri-letta a metà) — serve un ciclo intero dal
momento del cambio per coprire tutte e 12.

**WU199septies — riattivato hook "occupato"** (commit `2e87f3c`): nuovo
filone di sviluppo discusso con l'utente, parallelo al calcolo produzione
oraria. Idea: incrociare l'evento "occupato" (invio, `ts`) — riattivato in
`tasks/raccolta.py` dopo essere spento da WU184 30/06, riusa lo schema
esistente `shared/nodi_mappa.py` → `data/nodi_mappa_observations.jsonl` —
con l'evento di completamento in `report_raccolta_dataset.jsonl`
(`ts_raccolta`) per ottenere `durata_reale_s` per `(tipo, livello)`, al
posto della stima statica attuale ("~2h per L7", `reference_capacita_nodi`
in memoria). Il concetto era già anticipato (mai implementato) nel
docstring di `core/istanza_metrics.py::aggiungi_invio_raccolta`
("tempo_raccolta_empirico"). **Verifica fattibilità match 1vs1** (10/07,
su 282 righe report_raccolta pre-reset): 271/282 coppie
`(instance, coordinata)` uniche, solo 10 con >1 osservazione (max 3) —
match affidabile con logica "occupazione più recente non ancora usata".
Nota: `raccolta_fast` non produce mai l'evento "occupato" (coordinate non
lette, rimosse in WU198) — resta fuori dallo stimatore, gap trascurabile
oggi (solo FAU_08). FauMorfeus esclusa alla fonte (lettura coordinate
inaffidabile, `ISTANZE_ESCLUSE`). **Piano**: far accumulare dati in
parallelo su entrambi i dataset per ~1 settimana (target ~17/07) prima di
costruire il job di match (periodico, fuori dal task — pattern
`_nodi_mappa_rebuild_loop`). Dettagli in memoria
`project_tempo_raccolta_estimator`.

### Prossimo step
- Riavviare prod per attivare WU199sexies (toggle OFF + Read-claim+Delete-read)
  + WU199septies (hook occupazione) insieme.
- Lasciar completare il ciclo di reset su tutte le 12 istanze.
- Continuare a monitorare il dataset (`data/report_raccolta_dataset.jsonl`)
  su più cicli per confermare che gli outlier smettano di comparire.
- FauMorfeus non ha ancora prodotto righe nel dataset — verificare al
  prossimo ciclo.
- Fase 3 (sostituzione algoritmo produzione) resta non iniziata.
- **~17/07**: rivedere `nodi_mappa_observations.jsonl` +
  `report_raccolta_dataset.jsonl` accumulati, poi costruire il job di
  match/join per lo stimatore tempo di raccolta (WU199septies).

---

## Sessione 09/07/2026 (2) — WU199: report_raccolta — lettura Gathering Report, fase 1 (reset)

Richiesta utente: calcolare la produzione oraria precisa per istanza. Scoperta
chiave: il tab **Report** della schermata Messaggi (mai usato dal bot prima —
noto solo dal commento WU su REPORT/SENT/BOOK aggiunti il 18/06) contiene un
log "Gathering Report" con ogni marcia di raccolta completata: coordinata
nodo, tipo+livello, timestamp esatto, quantità raccolta (base + eventuale
bonus), valore donato all'alleanza — dati molto più precisi dell'attuale
OCR deposito differenziale (`main.py::_leggi_risorse`).

**Piano in 3 fasi concordato con l'utente**:
1. Pulizia report su tutte le istanze (nessuna lettura, solo reset baseline)
2. Lettura dati + storage + gestione scroll (già implementata, da validare live)
3. Sostituzione dell'algoritmo produzione attuale col nuovo (futura, affiancamento prima del cutover)

**Fase 1 — implementata e attivata in prod stanotte**. Calibrazione OCR fatta
live su FAU_05 (screenshot reali, bot fermo, nessuna collisione ADB) e
validata anche su FAU_00 (istanza più avanzata — menu Report con albero
categorie Battle/Group Battles/Jungle Crisis/Zombie/Scout/Other, ma pannello
dati e bottone "Delete" identici). Scoperto: il tab Report è un LOG puro
(risorse già depositate al rientro squadra), non una coda reward — "Read and
claim all"/"Delete read" non hanno effetto, solo "Delete" (contestuale)
svuota tutto in un tap, nessuna conferma.

**Decisione architetturale importante** (corretta in corsa su richiesta
utente): NON un Task schedulato nell'orchestrator — `esegui_report_raccolta()`
è chiamata diretta da `main.py::_leggi_risorse()` (closure `on_home_ready` di
`attendi_home()`), stesso punto del boot in cui si aggiorna
`produzione_corrente`. Due flag per-istanza via `_ovr()` in
`config_loader.py` (pattern identico a `RACCOLTA_FUORI_TERRITORIO_ABILITATA`,
controllabili da `runtime_overrides.json::istanze.<nome>`, mai da
`instances.json` statico): `REPORT_RACCOLTA_ABILITATO` (default False) e
`REPORT_RACCOLTA_SOLO_RESET` (default True — fase 1 attuale, solo Delete,
nessuna lettura OCR).

**Bug trovati e corretti durante l'implementazione della fase 2** (pronta ma
non ancora attiva, `solo_reset=False`):
- Griglia fissa dei 79.5px di stride non reggeva lo scroll libero (non
  "snap to row" del gioco) → `_trova_anchor_riga()` rileva dinamicamente la
  posizione via profilo di luminosità ad ogni pagina.
- Quantità raccolta leggeva il bonus invece della base quando presente
  (`numeri[-1]` invece di `numeri[0]`).
- Cifre singole confuse dall'OCR (7→2, 6→0) per crop senza upscale — aggiunto
  upscale 3x (pattern standard del codebase, es. `_ocr_coord_box`).
- **Rischio perdita dati** identificato e corretto: il Delete scattava anche
  su stop anticipato ambiguo (0 righe = ancora non rilevata, non
  necessariamente fine lista — verificato empiricamente che pagine successive
  trovano comunque altre righe). Fix: Delete solo se `fine_lista_raggiunta`
  è confermata da una pagina parziale con **almeno 1** riga valida.

Validato: simulazione end-to-end su 13 screenshot reali in sequenza (stato
dedup condiviso) → 37 righe nuove persistite, secondo giro identico → 0
nuove (idempotenza confermata). Test `config_loader` 39/39 verdi.

Sync dev→prod fatto e verificato byte-identico (`main.py`,
`config/config_loader.py`, `shared/report_raccolta.py`). Flag
`report_raccolta_abilitato: true` impostato su tutte le 12 istanze in
`runtime_overrides.json` prod (solo questa chiave aggiunta, resto del file
verificato intatto). **Bot riavviato dall'utente** con la fase 1 attiva.

### Prossimo step
- Osservare i log `[REPORT-RACCOLTA]` sulle prime istanze del nuovo ciclo per
  confermare che il reset avvenga senza anomalie su tutte e 12.
- Dopo un ciclo di reset pulito su tutte le istanze: passare a fase 2
  (`report_raccolta_solo_reset=False`), prima su una singola istanza
  canarino, per validare lo scroll dal vivo (mai testato in produzione, solo
  su screenshot statici).
- Fase 3 (sostituzione algoritmo produzione) resta non iniziata — richiede
  affiancamento e confronto con l'algoritmo attuale prima di qualunque
  cutover.

---

## Sessione 09/07/2026 — WU198: raccolta_fast, snellimento verifiche + rimozione blacklist

Richiesta utente: velocizzare ulteriormente `RaccoltaFastTask` saltando passaggi
di verifica ridondanti.

**Fase 1 — skip verifica tipo + delay fast finalmente agganciati.** Verificato
sui log storici prod (1033 CERCA, `.jsonl`+`.jsonl.bak`) che la verifica visiva
del tipo selezionato (`_verifica_tipo`) intercetta un problema reale solo 1
volta su 1033 (score minimo osservato 0.980 su soglia 0.85 — margine ampio,
coordinate `TAP_ICONA_TIPO` tarate benissimo). Aggiunti a `_cerca_nodo()`
(condivisa con lo standard) 3 parametri opt-in con default che preservano il
comportamento esistente: `skip_verifica_tipo`, `delay_tap_icona`,
`delay_cerca`. `RaccoltaFastTask` ora li usa; scoperto che
`FAST_DELAY_TAP_ICONA`/`FAST_DELAY_CERCA` erano definiti in `_DEFAULTS_FAST`
ma mai letti da nessuna parte (config morta dal WU57 originale) — ora
finalmente agganciati.

**Fase 2/3 — rimozione blacklist RAM e fuori-territorio, rotazione tipo
forzata.** Analisi del check territorio (`_nodo_in_territorio`): non è un
rischio per le truppe, verifica solo un buff di resa (+30%) — misurato 25.9%
di hit rate su blacklist_fuori nello standard oggi (270/1041 CERCA, 45 nodi in
`blacklist_fuori_globale.json`). Prima iterazione: rimosso il check
interamente. Utente ha poi richiesto anche la rimozione della blacklist RAM
(reserve/commit del nodo) — chiarito che protegge da un fallimento reale: se
una seconda squadra viene mandata su un nodo appena riservato ma non ancora
"occupato" (squadra ancora in viaggio), quella seconda squadra marcia e torna
indietro senza raccogliere (può capitare anche fra istanze diverse — per
questo esiste `RaccoltaChiusuraTask` a fine tick). Design finale concordato:
blacklist RAM e fuori-territorio **rimosse entrambe** (rischio residuo
accettato esplicitamente), ma il check territorio **reintrodotto** in forma
solo visiva (senza database, né lookup né aggiornamento). Mitigazione al
rischio blacklist: rotazione tipo **incondizionata** in `run()` — `idx_tipo`
avanza ad ogni marcia del batch indipendentemente dall'esito (prima avanzava
solo su successo confermato, quindi in caso di fallimento ripeteva lo stesso
tipo). Bonus: rimossa anche `_leggi_coord_nodo()` (apriva un popup UI separato
— tap lente coordinate + OCR X/Y — usato solo per generare la chiave
blacklist, ora superfluo).

Test: `test_raccolta.py` 62/62 verdi (58 preesistenti + 4 nuovi su
`_cerca_nodo` skip_verifica_tipo/delay override). Suite estesa `tests/tasks/`
286/378 verdi, invariata rispetto al baseline (92 fail preesistenti scollegati:
orchestrator/radar/rifornimento/store). Nessun test dedicato per
`raccolta_fast.py` (gap preesistente, non colmato in questa sessione).

**Nota stato**: nessuna istanza usa oggi `tipologia=raccolta_fast` (tutte
`full`/`raccolta_only` — l'ultimo utilizzo reale risale al 06/06/2026,
FAU_00). L'utente attiverà manualmente la tipologia fast su una singola
istanza "canarino" dopo il riavvio del bot.

### Prossimo step
- Dopo il riavvio: l'utente sceglie manualmente su quale istanza attivare
  `tipologia=raccolta_fast`.
- Osservare `marce_fallite`/`recovery_count` in telemetria sull'istanza
  canarino per confermare che la rotazione forzata mitighi a sufficienza
  l'assenza di blacklist RAM (nessun dato storico disponibile per questo
  design specifico).

---

## Sessione 07/07/2026 — WU197: dashboard, "simulazione ordine adattivo" 45s → 1.2s

Richiesta utente: "simulazione ordine adattivo compare con molta
lentezza, verifica la lentezza della dashboard".

**Misurato** `preview_adaptive_scheduler()` (il pannello che il poll HTMX
di `predictor_istanze.html` richiama ogni 30s) su dati reali prod:
**45.3 secondi** per una singola risposta.

**Root cause**: `core/adaptive_scheduler.py::ordina_istanze_adaptive` è un
greedy O(n²) (~66-78 chiamate per 11-12 istanze) e ad ogni chiamata
`core/skip_predictor.py::load_metrics_history()` rileggeva l'INTERO file
`data/istanza_metrics.jsonl` (6903 righe, 5.8MB) da zero, senza alcuna
cache (428ms/call misurati → 28.2s per 66 chiamate). Scavando oltre,
trovati altri **2 scanner indipendenti** con lo stesso bug (nessuna
cache): `_l2_collect_samples` e `_read_units_history`, entrambi raggiunti
da `predict_cycle_from_config()` — che da solo misurava 11.6-13.1s per
chiamata, sempre cold.

**Fix**: nuovo indice cached `{istanza: [record,...]}` in
`core/skip_predictor.py::_load_metrics_index()`, invalidato su cambio
`mtime` del file (zero staleness percepibile — il file cresce di poche
righe per tick, molto più lentamente del poll dashboard). Le 3 funzioni
duplicate ora attingono da questo indice condiviso invece di rileggere
il file ciascuna per conto proprio.

**Risultato misurato**: `preview_adaptive_scheduler()` end-to-end
45.3s → 1.2s a processo freddo, ~0.1-0.2s a cache calda (36-450×).
Validato bit-a-bit vecchio vs nuovo output su tutte le 12 istanze/3 task
reali — zero mismatch. Suite pytest 573/140/4err invariata. Sync dev+prod
verificato byte-identico. Dettagli `docs/issues/telemetria-predictor.md`
(WU197).

### Prossimo step
- Riavviare il processo DASHBOARD (`run_dashboard_prod.bat`) per attivare
  il fix — servizio separato dal bot, nessun riavvio bot necessario per
  questo specifico fix (il bot beneficerà comunque al restart già
  pianificato per WU195/196 nella stessa sessione, dato che
  `core/skip_predictor.py` è condiviso anche da `tasks/raccolta.py`/
  `raccolta_fast.py`).
- Da chiedere esplicitamente all'utente prima di riavviare, come da
  policy (mai riavviare processi senza conferma).

---

## Sessione 07/07/2026 — WU196: daily report, nuova sezione 12 "Deposito attuale"

Richiesta utente: verificare se il daily report mostrasse, per ogni
istanza, le risorse presenti nel deposito.

**Verificato**: nessuna delle 11 sezioni esistenti lo faceva. Sez. 2
(Produzione interna rifugio) mostra il *delta* di produzione, sez. 3 il
netto spedito al master, sez. 5 (Rifornimento) ha una colonna "residuo"
che è la quota giornaliera di invio rimanente (`provviste_residue`), non
lo stock in magazzino.

**Trovato**: il dato esiste già, raccolto ma non esposto. `tasks/zaino.py
::_ocr_deposito()` legge la barra risorse HOME ma solo per calcolare
quanto scaricare dallo zaino (transiente, non persistito). Fonte migliore
individuata in `main.py::_leggi_risorse()` — hook `on_home_ready` di
`attendi_home()`, gira ad ogni avvio istanza indipendentemente da
ZainoTask, fa OCR robusto a consenso 3-su-5 della barra risorse e lo
passa a `ctx.state.apri_sessione(risorse_now, ...)`, persistito come
`state/<ist>.json::produzione_corrente.risorse_iniziali` — la sessione
ancora aperta rappresenta quindi l'ultima lettura nota del deposito,
aggiornata ogni ciclo per ogni istanza.

**Implementato**: nuova `_section_deposito_attuale()` in
`core/daily_report.py`, stesso pattern di lettura file-per-istanza di
`_section_produzione_rifugio` (master FauMorfeus separato), esposta come
**sezione 12** in testo e HTML — tabella istanza × 4 risorse + timestamp
ultima lettura. A differenza delle altre 11 sezioni (filtrate per
`date`=ieri UTC) è un valore **live**, non storico — documentato
esplicitamente nel testo del report e in `docs/OVERVIEW.md` §4.17.
Nessuna nuova lettura OCR introdotta: solo esposizione di un dato già
raccolto.

Validato con dati reali prod (12 istanze, valori e timestamp plausibili
in entrambi i render). Suite pytest 573 passed / 140 failed / 4 errors —
invariata. Sync dev+prod verificato byte-identico. Dettagli
`docs/issues/notifiche-alert.md` (WU196).

### Prossimo step
- Effetto al prossimo restart bot (già armato per WU195 nella stessa
  sessione — nessun restart aggiuntivo necessario).
- Osservare il prossimo daily report reale per confermare che la
  sezione 12 compaia correttamente con dati freschi per tutte le istanze.

---

## Sessione 07/07/2026 — WU195: grafica HQ + pulizia cache come task indipendenti

Richiesta utente: rendere abilitabili/disabilitabili separatamente da
dashboard le due fasi che oggi girano incondizionatamente ad ogni avvio
istanza — impostazione Graphics Quality HIGH (WU78-rev) e pulizia cache
giornaliera — finora accoppiate in un'unica chiamata
`imposta_settings_lightweight()` da `core/launcher.py`, senza toggle.

**Implementato**: split in due task orchestrator indipendenti, seguendo il
pattern esistente (`tasks/donazione.py`):
- `tasks/grafica_hq.py::GraficaHqTask` (priority 1) — Graphics/Frame/
  Optimize HIGH, autosufficiente (propria navigazione HOME→Avatar→
  Settings→System Settings→BACK×3→HOME).
- `tasks/pulizia_cache.py::PuliziaCacheTask` (priority 2) — pulizia cache
  (invariata: `_pulisci_cache`/gate giornaliero `data/cache_state.json`),
  autosufficiente (HOME→Avatar→Settings→BACK×2→HOME).

`core/settings_helper.py::imposta_settings_lightweight()` rimossa,
sostituita da `esegui_grafica_hq()` + `esegui_pulizia_cache()`. Rimosso il
blocco in `core/launcher.py` che le chiamava incondizionatamente (con lo
skip `raccolta_only` ora spostato dentro i due task). Wiring completo:
`main.py` (catalogo task), `config/task_setup.json` (2 righe `always`),
`config/config_loader.py` (5 punti: `_DEFAULTS`, dataclass, `_from_raw`,
`to_dict`, `task_abilitato`), `dashboard/models.py::TaskFlags`,
`dashboard/routers/api_config_overrides.py` (`valid_tasks`),
`dashboard/app.py::partial_task_flags_v2` (`ORDER`),
`dashboard/templates/config_global.html` (checkbox grid + `taskList` JS,
tenuti sincronizzati).

**Verificato**: test funzionale isolato (sandbox `DOOMSDAY_ROOT`, 6
scenari: `should_run` gating, esecuzione `run()` happy-path device fake,
skip cache-già-pulita-oggi, skip `raccolta_only`, wiring
`config_loader.py` end-to-end, catalogazione `main.py`) — 6/6 PASS. Render
Jinja2 standalone di `config_global.html` con mock context — checkbox
`grafica_hq`/`pulizia_cache` presenti, nessun errore di sintassi. Suite
pytest completa: 573 passed / 140 failed / 4 errors — invariata rispetto
al baseline noto (nessuna regressione, nessun failure nuovo riconducibile
ai file toccati).

Nota: la tabella `_TASK_SETUP` che `.claude/CLAUDE.md` richiede in questo
file non è più presente qui — la documentazione task-per-task vive in
`docs/OVERVIEW.md` §5 (ora estesa a 5.18/5.19 per i due nuovi task).
Segnalato, non forzata una tabella inesistente.

### Prossimo step
- Sync dev→prod, commit+push.
- Chiedere conferma esplicita all'utente prima di riavviare il bot prod
  (necessario: la modifica tocca `main.py`/`core/launcher.py` e aggiunge
  2 nuove classi task, effettive solo dopo restart).
- Dopo il primo ciclo prod con i nuovi task attivi: verificare via MCP
  monitor (`log_tail`/`istanza_launcher`) che `grafica_hq`/`pulizia_cache`
  girino correttamente in sequenza a inizio ciclo per ogni istanza.

---

## Sessione 06/07/2026 — WU192 ricalibrata + WU192-bis conflitto login altro dispositivo

Richiesta utente: verificare se FauMorfeus (e le altre istanze) fossero
ancora colpite dal timeout boot dopo il fix WU192 di ieri (soglia
`is_loading_splash` 0.75→0.55).

**Trovato**: il fix di ieri, calibrato su un solo screenshot reale (score
0.599), non bastava — 5 nuovi timeout oggi su FAU_06/07(×3)/10. Misurato
lo score dello stesso splash su 8 screenshot reali (percentuali 4%-23%):
range 0.277-0.629, molto più ampio del previsto (la barra di progresso
dell'evento bleeda diversamente nella ROI a seconda di quanto è piena).
Soglia ricalibrata 0.55→0.20, validata stavolta su **13 campioni reali**
(8 positivi a percentuali diverse + 5 negativi da schermate MAP genuine):
13/13 corretti, margine 3× sopra il rumore di fondo. Sync dev+prod, commit
`3dc3932`.

**WU192-bis — scoperta collaterale**: cercando sistematicamente falsi
positivi della soglia abbassata (girata la funzione reale su tutti i 632
screenshot storici in `debug_task/`), trovato uno screenshot borderline
(score 0.251) che non è affatto uno splash: dialog **"Login failed:
session expired!"** con bottone OK, seguito da schermata "IGG Account /
Last login". Utente ha confermato: il gioco permette un solo dispositivo
alla volta — aprire l'account da un altro dispositivo mentre il bot lo usa
invalida la sessione lato server, e il bot non può auto-risolvere (serve
re-inserire credenziali).

Utente ha chiesto di gestire la situazione con un **alert email**.
Implementato: nuovo `shared/ui_helpers.py::is_login_conflict()` (template
`pin_login_conflict.png`, soglia 0.55 su 3 positivi confermati vs cluster
negativo ≤0.455), hook in `core/launcher.py::attendi_home()` con priorità
sopra il check splash (che altrimenti intercetta la stessa schermata per
primo, essendo l'icona Live Chat ancora visibile nell'angolo) — se
rilevato, invia alert email (`core/alerts.py`, nuovo `event_type
"login_conflict"`, cooldown 30min) e abortisce subito il boot invece di
aspettare i 300s. Scoperto e corretto anche un problema collaterale: il
master toggle `alerts_enabled` per gli alert real-time risultava assente
in prod — l'intero sistema (non solo questo nuovo alert) era di fatto
inerte dall'implementazione originale (WU137 fase 2). Attivato su
`runtime_overrides.json` prod.

Verificato end-to-end in sandbox: l'alert genera correttamente una mail in
coda verso il destinatario configurato. Test 7/7 su screenshot reali,
suite pytest 573/713 invariata. Sync dev+prod, commit `ae26f6d`. Dettagli
`docs/issues/ocr-vision.md` (WU192) e `docs/issues/notifiche-alert.md`
(WU192-bis).

Nota: durante la sessione l'utente ha fermato manualmente il bot prod per
caricare FauMorfeus a mano e osservare dal vivo la schermata di blocco.

### Prossimo step
- Riavviare il bot prod quando l'utente ha finito la verifica manuale, per
  attivare la soglia ricalibrata (0.20) + il nuovo alert login-conflict.
- Osservare la prossima occorrenza reale di conflitto login per confermare
  che l'alert email arrivi davvero (finora validato solo in sandbox/dry-run).

---

## Sessione 05/07/2026 — WU191: adaptive scheduler 3 fix predizione + WU192 FauMorfeus boot

Richiesta utente: verifica funzionalità adaptive scheduler su tutti i cicli
LIVE disponibili (retention log: solo `bot.log`+`.bak`, 03/07 16:09 → 04/07
20:46), confrontando per ogni ciclo/istanza lo `slot_liberi_atteso` predetto
al momento della decisione con lo stato reale degli slot (`attive_pre` OCR
HOME) all'avvio del tick. Risultato: **28% match esatto** su 104 confronti
validi (40% sottostima, 32% sovrastima, delta medio -0.09) — utente ha
richiesto di individuare i punti critici del processo predittivo e
proporre fix.

**3 cause individuate e corrette (WU191)**, dettagli completi in
`docs/issues/telemetria-predictor.md`:
1. `core/empirical_slot_predictor.py` — il lookup empirico (70% del blend
   appena `n_samples≥30`, soglia raggiunta da settimane) non aveva mai un
   limite temporale: scansionava tutti i 59 giorni di storico, mescolando
   il regime pre/post switch `raccolta_fast→full` (WU143 09/05). Aggiunta
   finestra `WINDOW_DAYS=14` + soglia minima `MIN_SAMPLES=5`.
2. Stesso file — bucket gap troppo grossolani (`>120min` sconfinato,
   assorbiva la maggioranza dei cicli reali da 150-220min). Ora 7 fasce
   fino a 240min + nuove funzioni pubbliche `get_full_lookup()`/
   `bucket_labels()`: eliminata la copia duplicata e disallineata da mesi
   nel pannello dashboard `/ui/partial/predictor-slot-distribuzione`
   (bonus: risolto anche il path prod hardcoded, ora rispetta
   `DOOMSDAY_ROOT`).
3. `core/adaptive_scheduler.py::compute_slot_liberi_atteso` — il residuo
   T_marcia era ancorato al `ts` di fine-tick invece che al `ts_invio`
   reale di ciascuna marcia (dato già presente, mai usato) — sottostimava
   l'elapsed per marce partite a inizio tick lungo. Confermato che
   `ts_invio` è già catturato post-conferma reale della marcia
   (`tasks/raccolta.py::_esegui_marcia`), non serviva altro fix lì.

Smoke test isolato (sandbox `DOOMSDAY_ROOT` dedicato) 3/3 verdi, suite
pytest 573/713 invariata. Sync dev+prod fatto, commit `6889a88` pushato.
Effetto al prossimo restart bot (nessun restart armato — in attesa di
conferma utente).

**WU192 — scoperta durante la verifica, poi risolta** (richiesta utente
parallela: "verifica la raccolta relativa FauMorfeus, sembra che il bot non
stia mandando raccoglitori"): confermato — **non un bug del
predictor/raccolta**, l'istanza non arriva mai a HOME. Rilevati 5 episodi
in 24h per FauMorfeus (17:51, 20:40, 23:28, 01:56, 05:14 — quasi ogni suo
turno) con `TIMEOUT: schermata ancora UNKNOWN dopo 300s` → istanza chiusa
senza raccolta. Screenshot `debug_task/boot_unknown/*_streak5_*.png`
confermano lo stesso schermo anche su **FAU_01/FAU_06/FAU_07** (1 episodio
ciascuna nelle stesse 24h) — non isolato a FauMorfeus come sembrava
all'inizio, solo molto più frequente lì: splash crossover "DOOMSDAY x FAIRY
TAIL" (client v1.58.0), barra caricamento ferma 6-23%.

Utente ha chiesto conferma: il banner-learner (WU190, appena riattivato)
non doveva servire proprio a questo? Verificato di no — il learner impara
popup con una X da chiudere, uno splash di caricamento non ne ha nessuna
(`[LEARNER] detect_x_candidates: 0 candidate` è corretto, non un bug).
La funzione giusta è `shared/ui_helpers.py::is_loading_splash()`, già
esistente e pensata apposta per questo (2 anchor invarianti al reskin
evento) — ma su QUESTO splash la barra di progresso dell'evento si
sovrappone al bordo della ROI "Live Chat", degradando il match: misurato
score reale 0.599 contro soglia 0.75. Fix: soglia abbassata a 0.55,
validata su screenshot reali (splash rilevato correttamente, 3 schermate
MAP genuine restano a score -0.06/0.06/0.0 — nessun rischio falsi
positivi). Suite pytest 572/713 invariata. Sync dev+prod, commit `0939d58`.

### Prossimo step
- Decidere quando riavviare il bot prod per attivare **entrambi** i fix
  (WU191 adaptive scheduler + WU192 splash loading) — un solo restart le
  copre entrambe essendo sequenziali nella stessa sessione.
- Dopo il riavvio: osservare se gli episodi `TIMEOUT: schermata ancora
  UNKNOWN` su splash crossover scompaiono (specialmente su FauMorfeus) e se
  il match rate predetto/reale dell'adaptive scheduler migliora sui
  prossimi cicli LIVE.

---

## Sessione 03/07/2026 (2) — WU188: arena, video-intro non riconosceva la lista già raggiunta

Richiesta utente: nel task arena, dopo l'introduzione del riconoscimento
skip/open (WU185), la logica verifica solo la presenza di questi due
oggetti ma non controlla se la maschera interna arena (`lista`) è già
presente — cosa che dovrebbe fermare subito il loop di ricerca.

**Diagnosi confermata sui log prod** (`.jsonl`+`.jsonl.bak`, tutte le 12
istanze): **FAU_00, FAU_03, FAU_06, FAU_07, FAU_09** (e FAU_10 in
precedenza) mostrano, **ogni giorno**, sempre lo stesso pattern — tutti i 5
tentativi di cattura Skip falliscono (nessun video reale in corso, solo
lag di rendering al check iniziale), poi il fallback passivo trova `lista`
raggiungibile **1 secondo dopo** l'ultimo tentativo fallito. Costo
stimato ~200s (3,3 min) sprecati per istanza per esecuzione, con 5
uscite/rientri Arena inutili — su ~11-12 istanze con arena giornaliera,
~35-40 min/giorno sprecati sulla farm.

**Causa**: il check no-op in testa a `_gestisci_video_intro()`
([tasks/arena.py:488-492](tasks/arena.py#L488-L492)) fa un singolo
screenshot senza retry — se la lista non ha ancora finito di renderizzarsi
nell'istante del tap "Arena of Doom" (lag di caricamento, non video
reale), il codice imbocca l'intero percorso "gestione video intro" pur non
essendoci alcun video. Il loop di poll interno (righe 496-515) controllava
poi solo `skip_intro`/`open_intro`, mai `lista` — quindi non poteva
autocorreggersi finché non esauriva tutti i 5 tentativi.

**Fix**: aggiunto check `lista` come prima verifica di ogni iterazione del
poll interno — se rilevata, ritorna immediatamente (video già concluso,
nessun tap necessario). Risolve elegantemente anche il caso limite del
check iniziale troppo rapido: la lista viene comunque intercettata al
1°/2° poll (~1-2s) invece che dopo l'intero loop di 5 tentativi.

Nuovo test di regressione `test_lista_rilevata_durante_poll_ferma_ricerca`
in `tests/tasks/test_arena.py`, verificato che fallisce senza il fix (4
retry ingresso inutili invece di 0). Aggiornato anche
`test_skip_mai_catturato_fallback_lista` (pre-esistente) per riflettere il
nuovo conteggio chiamate a `lista` — comportamento atteso invariato (5
tentativi esauriti + fallback quando la lista non è davvero raggiungibile
prima). Suite arena 18/19 verdi (1 fail pre-esistente scollegato,
documentato in WU185: `result.data["errore"]=""` invece di `None`). Suite
completa 573/713 verdi, nessuna nuova regressione.

Sync dev+prod fatto, commit+push.

---

## Sessione 03/07/2026 — WU187: fix break streak maschera non propagava al while esterno

Richiesta utente: verifica anomalia FAU_00 raccolta — slot pieni ma il bot
continuava a tentare invii. Diagnosi log FAU_00 (`03:48-03:52 UTC`): OCR
iniziale legge `attive=3/5` (2 slot liberi) ma il gioco ha in realtà già
5/5 slot occupati — stesso bug noto "3 letto invece di 5" mai risolto del
tutto (commento pre-esistente in `ocr_helpers.py`, fix 15/04/2026). La rete
di sicurezza WU69 (29/04) — 2 fallimenti "maschera non aperta" consecutivi
su tipi diversi → slot pieni dedotti indipendentemente dall'OCR — riconosce
correttamente la situazione e logga "uscita immediata", ma il bot tenta
comunque un ulteriore invio a vuoto prima di fermarsi davvero.

**Root cause** ([tasks/raccolta.py:2180-2187](tasks/raccolta.py#L2180-L2187)):
il `break` al raggiungimento di `SOGLIA_MASK_STREAK` esce solo dal `for tipo
in sequenza` interno, non dal `while` esterno di `_loop_invio_marce` che lo
contiene — a differenza del pattern gemello "No Squads" (righe 2198-2199),
che dopo il for ricontrolla il flag e fa break anche dal while. Confermato
non essere un caso isolato: scan dei log JSONL prod (`.jsonl`+`.jsonl.bak`,
finestra ~30/06-03/07) ha trovato **8 episodi su 6 istanze diverse**
(FAU_00×2, FAU_02, FAU_05, FAU_06, FAU_07, FauMorfeus×2), **100% di
riproduzione** (8/8 seguiti dal tentativo extra). Costo ~60-90s sprecati
per episodio (confermato 77s nel caso FAU_00 03/07) — nei casi osservati
limitato a un solo tentativo extra solo per coincidenza (`fallimenti_cons`
che raggiunge `max_fallimenti` nello stesso momento); con `max_fallimenti`
più alto il danno sarebbe maggiore (verificato in test: senza fix la
chiamata a `_invia_squadra` continua fino a 10 volte con
`RACCOLTA_MAX_FALLIMENTI=10`, invece di fermarsi a 2).

**Fix**: aggiunto check `if getattr(ctx, "_raccolta_slot_pieni", False): break`
dopo il for, simmetrico al check esistente per `_raccolta_no_squads`. Nuovo
test di regressione `TestLoopInvioMarceSlotPieniStreak` in
`tests/tasks/test_raccolta.py` (mock `_invia_squadra` con streak forzato,
`RACCOLTA_MAX_FALLIMENTI` alto per isolare il bug dalla coincidenza) —
verificato che fallisce senza il fix (`call_count == 10` invece di `2`) e
passa con il fix. Suite raccolta 58/58 verdi, suite completa 571/712 verdi
(141 fail pre-esistenti invariati, nessuno relativo a raccolta).

Sync dev+prod fatto, commit+push, restart one-shot armato su richiesta
esplicita dell'utente ("se non impatta sulla stabilità procederei con il
fix ed il riarmo automatico").

---

## Sessione 02/07/2026 — WU186: retention automatica file JSONL predittivo (60gg)

Richiesta utente durante verifica del sistema predictor ("esiste un sistema di
retention dei dati?"): `tools/rotate_predictor_logs.py` (WU168, 19/06) esisteva
già ma era **solo manuale** — mai eseguito in prod. Verificato: `istanza_
metrics.jsonl` 5.4MB/6.619 righe, `cycle_snapshots.jsonl` 8.0MB, nessuna
cartella `data/archive/`. Utente conferma: 60 giorni di retention vanno bene.

**Fix**: estratta `run_retention(root, days, apply)` riutilizzabile dal tool
esistente (CLI invariata + nuovo uso programmatico). Aggiunto `data/
predictions/scheduler_ab.jsonl` ai target (stesso problema, mai coperto
nemmeno dal tool manuale). Nuovo background task `dashboard/app.py::
_predictor_retention_loop` — stesso pattern già in uso per
`_predictor_recorder_loop`/`_nodi_mappa_rebuild_loop`: poll ogni 30min,
esegue la rotazione 1×/die (persistenza `data/predictor_retention_state.json`
per sopravvivere ai restart dashboard), cutoff `PREDICTOR_RETENTION_DAYS=60`
(costante in `dashboard/app.py`).

Smoke test su sandbox isolata (righe sintetiche a 90/59/10 giorni): righe
>60gg correttamente archiviate in `data/archive/<file>_<YYYY-MM>.jsonl`,
righe recenti mantenute nel file live, nessuna perdita dati. `py_compile` OK.
Nessun test pytest dedicato (repo non testa unitariamente `dashboard/app.py`
né `tools/*.py`, coerente con WU168).

**Effetto**: richiede riavvio della dashboard prod per attivare il loop
(nessun riavvio bot necessario — la rotazione tocca solo file che il bot
scrive in append, mai in lettura esclusiva; scrittura atomica tmp+replace
già presente nel tool, sicura anche a bot live).

---

## Sessione 01/07/2026 — WU185: Arena — video introduttivo post-aggiornamento client

Dopo la reinstallazione di tutte le istanze MuMu (aggiornamento software client
richiesto dall'utente), il task `arena` falliva sistematicamente (3/3 tentativi)
su più istanze (FAU_01, FAU_02, FAU_05, FAU_06, FAU_08 osservati live). Diagnosi
log: dopo il tap "Arena of Doom" il pin `lista` non veniva mai trovato (score
0.0-0.22 costante) — segno di una schermata diversa persistente.

**Osservazione live** (monitor MCP `anomalie_live`/`log_tail` + watcher ADB
read-only dedicato, catturati screenshot reali su FAU_08/FAU_10): il client
mostra un **video introduttivo** al primo ingresso in Arena of Doom dopo
l'aggiornamento, con pulsante **"Skip"** in alto a destra visibile per diversi
secondi. Indicazione utente: se la finestra Skip viene persa, il video
prosegue forzatamente su una schermata con pulsante **"Open"** (busta) — da lì
NON è più possibile saltare. Verificato anche che in V5 (`C:\Bot-farm`) non
esiste alcuna gestione pregressa per questo — comportamento nuovo introdotto
dall'aggiornamento client.

**Fix** (`tasks/arena.py`): nuovo metodo `_gestisci_video_intro()` chiamato
subito dopo il tap "Arena of Doom" (prima dei check esistenti glory/lista).
Poll regolare cercando il pin `skip_intro` → tap dinamico appena trovato. Se
compare `open_intro` prima (finestra persa), esce e rientra in Arena of Doom
da capo, fino a **5 tentativi dedicati**. Dopo 5 tentativi falliti: fallback
passivo `_attendi_fine_video_intro()` — gestisce "Open" quando richiesto e
attende il ritorno naturale alla lista sfide (il loop esterno dei 3 tentativi
di `ArenaTask` resta comunque il fallback finale). Nuovi template calibrati su
screenshot reali: `pin_arena_08_skip_intro.png` (ROI 870,0,960,55) e
`pin_arena_09_open_intro.png` (ROI 400,240,565,320).

**Bonus fix incidentale**: stub `FakeNavigator` in `tests/tasks/test_arena.py`
mancava `vai_in_home()` (necessario per il retry del nuovo codice) — la sua
assenza faceva fallire 9 test pre-esistenti con `AttributeError`, mascherati
fino ad ora. Aggiunto, 9 test tornano verdi.

Test: 4 nuovi scenari dedicati (no-op se video già superato, skip catturato
al 1° tentativo, skip perso poi catturato al retry, 5 tentativi falliti →
fallback) tutti verdi. Suite arena 17/18 verde (1 fail pre-esistente e
scollegato: `result.data["errore"]` è `""` invece di `None` in `run()`, non
toccato da questo WU). Suite completa progetto: 0 fail riconducibili ad arena.

**🔍 DA OSSERVARE**: il path di fallback (5 tentativi Skip falliti → lascia
scorrere il video) non è mai stato osservato in produzione — comportamento
del client oltre la schermata "Open" sconosciuto. Monitorare i prossimi cicli
per log `[ARENA] [INTRO] Skip non catturato dopo 5 tentativi` ed eventuale
`fallback passivo esaurito` (nessuna lista raggiunta entro 30s extra).

Sync dev+prod fatto, restart one-shot armato. Commit `24897dc` su `main`.

### Aggiornamento 01-02/07/2026 — validazione live post-restart

Monitoraggio esplicito richiesto dall'utente sul ciclo 402 (primo post-fix).
**Skip catturato 8/8 (100%)** su tutte le istanze osservate (FAU_01/02/05/06/
08/09/10 + FAU_04) — il fix cattura sempre correttamente il pulsante Skip.

Su 3/8 istanze (FAU_02/06/09) l'arena è comunque fallita **dopo** lo Skip:
schermo mai riconosciuto (home/map score bassi), popup "Glory Silver" letto
come assente (score 0.08-0.11) nonostante fosse realmente presente, e
`exit_game_dialog` ricorrente durante i tentativi di recovery.

**Causa reale (non un difetto del fix)**: per diagnosticare dal vivo è stato
usato un watcher esterno (script standalone, fuori dal processo bot) che
catturava screenshot via `adb exec-out screencap` in parallelo alle stesse
istanze. Verifica diretta su FAU_09: ri-applicando lo stesso template
`pin_arena_07_glory.png` su uno screenshot catturato dal watcher nello stesso
istante del check ufficiale del bot → score **0.999** (popup realmente
presente e leggibile), contro lo **0.110** letto dal bot in produzione nello
stesso momento. Il lock anti-concorrenza `_screencap_global_lock` in
`core/device.py` protegge solo chiamate interne allo stesso processo bot, non
un processo esterno — collisione ADB sulla stessa porta ha probabilmente
corrotto lo screenshot del bot proprio nel momento critico del check Glory.

**Conferma pulita**: interrotto ogni polling ADB esterno. Nel ciclo 403
(senza interferenza), FAU_02 ha ritentato arena e completato **senza alcun
video** (lista trovata immediatamente, score 0.993) — conferma che (a) il
video è realmente un evento one-time per istanza, consumato correttamente al
primo skip anche quando il tentativo era poi fallito per il bug di
osservazione, e (b) il fix WU185 funziona correttamente end-to-end quando non
disturbato. FAU_06/09 non hanno fatto in tempo a ritentare prima che scattasse
il gate orario UTC<10 di fine giornata (nuovo giorno UTC 02/07) — ritenteranno
automaticamente dopo le 10:00 UTC, nessuna azione richiesta.

**Lezione operativa**: non usare mai script di screenshot ADB esterni al
processo bot su istanze live in produzione — il lock di concorrenza non
copre processi esterni. Per diagnosi live, preferire l'osservazione via log
(`mcp__doomsday-monitor__log_tail`/`anomalie_live`, sola lettura su file)
oppure il `DebugBuffer` interno del task (screenshot presi dal bot stesso,
nessuna doppia richiesta ADB).

---

## Sessione 30/06/2026 — WU184: disabilitazione anagrafe nodi (mappatura)

Analisi correlazione feature-catalogo ↔ esiti raccolta (per istanza):
contesa↔sec/marcia +0.40, ma **strutturale non temporale** (variazione oraria
piatta ~92-100s), **fill slot 100%** (nessuno spreco da recuperare) e ciclo
sequenziale (tempo totale invariante all'ordine). Conclusione: l'anagrafe nodi
**non è sfruttabile** né per instradare i raccoglitori (non si sa a priori se un
nodo esiste ed è libero — contesa con giocatori esterni), né per ordinare le
istanze (differenze legate a *dove* stanno i rifugi, non a *quando* si eseguono;
e i rifugi sono tutti concentrati → relazione geografica non utile).

**Decisione utente**: disabilitare l'anagrafe nodi + pannello dashboard +
schedulazione, alleggerendo il sistema. **Commentato (non cancellato)** per
reversibilità:
- `tasks/raccolta.py`: 4 hook `registra_osservazione` (trovato/occupato/fuori)
  commentati.
- `dashboard/app.py`: **schedulazione** `_nodi_mappa_rebuild_loop` (create_task +
  shutdown) rimossa → niente più rebuild ogni 20 min; route `/ui/nodi-mappa` e
  `/api/nodi-mappa/rebuild` disabilitate (decorator commentato, funzioni orfane).
- `base.html`: link nav "nodi mappa" commentato.
- Moduli `shared/nodi_mappa.py` e `tools/costruisci_catalogo_nodi.py` lasciati in
  repo (non più invocati). Dati `nodi_mappa_*` non più aggiornati.

**MANTENUTO** (sistema diverso, dipendenza viva): `cap_nodi_dataset` +
`registra_cap_sample` → alimenta daily report sez.8 "Copertura Squadre"
([daily_report.py:716](core/daily_report.py#L716)) + pagina `/ui/raccolta`.

**Verifica robustezza**: `py_compile` OK, **57/57 test raccolta verdi**,
dashboard importa OK (route nodi-mappa assenti, `/ui/raccolta` presente).

**Prossimo step**: nessuno. Sistema alleggerito. I file dati `nodi_mappa_*`
possono essere cancellati manualmente (gitignored) se si vuole liberare spazio.

---

## Sessione 28/06/2026 — WU183 (cont.): dismiss banner in-loop (caso FAU_02)

La statistica WU183 ha subito catturato il caso che l'utente sospettava: FAU_02
alle 04:12 ha registrato **`tutte_ko=True`** (tutte e 4 le risorse −1). Analisi
log: dopo ~8 conferme HOME stabile (home=0.988), un **banner ha coperto la
top-bar durante la lettura** → tutte le risorse −1 → fallback ai valori
precedenti. Il template HOME (`pin_region`) resta 0.988 anche con la barra
risorse coperta → la stabilizzazione conferma HOME ma **non** la barra in alto.
FAU_02 mostra `exit_game_dialog` ricorrente (9× in ~14h + 1 `vai_in_home
FALLITO`): instabilità a livello istanza.

**Fix (punto b, era rimandato)**: dismiss del banner **dentro** il loop di
consenso. In `ocr_risorse_robust` nuovo param `on_banner` + budget
`max_dismiss=2`: se una lettura torna con tutte le 4 risorse −1 (banner),
chiama `on_banner()` (= `dismiss_banners_loop`) e ritenta **senza consumare** un
tentativo di consenso (guard `hard_cap` anti-loop). `main.py` passa
`on_banner=_dismiss_banner` a entrambe le letture. Smoke test esteso (scenari E
recupero post-dismiss, F budget rispettato senza loop) + A/B/C invariati, tutti
verdi. `py_compile` OK.

**Limite**: recupera i banner **transienti**; se `exit_game_dialog` ri-compare
in continuo (instabilità MuMu FAU_02) il dismiss mitiga ma non cura — resta da
valutare la **salute istanza FAU_02** separatamente (riavvio/reinstall MuMu).

**Prossimo step**: dopo il riavvio, verificare nei log `[OCR-CONS] ... dismiss
N/2` su FAU_02 e che i `tutte_ko` in `ocr_read_stats.jsonl` calino.

---

## Sessione 27/06/2026 (2) — WU183 lettura risorse: ordine boot + stabilità HOME + statistica

Continuazione WU182. L'utente ha individuato un problema di **sequenza di
avvio**: la lettura risorse girava DOPO i settings a click cieco (Graphics
HIGH), quindi su sistema lento poteva trovare lo schermo sporco (banner /
schermata sbagliata da tap ciechi su HOME non davvero stabile) → OCR fallita.

**Ordine reale individuato**: `attendi_home` → stabilizzazione (5 poll) →
vai_in_home → **settings (click ciechi)** → troops → (main) comprimi_banner →
**lettura risorse**. Cioè il read avveniva a valle di ~22s di navigazione
cieca, senza ri-verifica HOME.

**Modifiche (WU183)**:
1. **Read PRIMA dei settings**: la lettura risorse è ora iniettata in
   `attendi_home` come callback `on_home_ready`, eseguita subito dopo il
   `vai_in_home()` finale e **prima** dei settings. Gira sulla HOME più pulita
   possibile. Resta una closure in `main.py` (usa `ctx.state`). File:
   `core/launcher.py` (param `on_home_ready` + chiamata), `main.py` (closure).
2. **Stabilizzazione HOME 5→7 poll** ([launcher.py](core/launcher.py)): +~2.5s
   per istanza nel caso positivo (trascurabile), HOME più solida prima dei
   click ciechi.
3. **Statistica fallimenti lettura**: ogni lettura appende un record a
   `data/ocr_read_stats.jsonl` (append-only, sopravvive alla rotazione log):
   `{ts, instance, fallback:[risorse], tutte_ko, diamanti_ok}`. Nuovo tool
   `tools/ocr_stats.py` per la sintesi (usato da Monitor). Serve a quantificare
   quanto spesso l'OCR fallisce → decisioni future.

`py_compile` OK su main/launcher/ocr_helpers. Monitor attivo fino al 28/06
mezzanotte sui fallimenti lettura. Restart bot armato (riarmato per includere
WU183).

**Prossimo step**: domani valutare `data/ocr_read_stats.jsonl` — se i
fallimenti residui sono concentrati su poche istanze/risorse, decidere se
servono (a) mediana mobile inter-tick o (c) filtro per-salto, o se basta così.

---

## Sessione 27/06/2026 — WU182 produzione risorse: lettura OCR a consenso

Analisi produzione risorse su richiesta utente → valori anomali su alcune
istanze (FAU_05 acciaio 30.3M, FAU_02 legno −0.5M).

**Diagnosi** (lettura completa della catena OCR→sessione→report):
- La produzione è un **delta telescopico**: somma giornaliera per risorsa ≈
  (ultima lettura del giorno − prima lettura). Le oscillazioni intermedie si
  annullano, **gli estremi no** → un singolo misread OCR su prima/ultima
  lettura inquina l'intero totale della risorsa.
- FAU_05 acciaio: valore vero **~74.10M stabile** (letto identico 5 volte),
  ma misread come 11.x/41.3 agli estremi → fantasma `41.30 − 11.00 = 30.30M`.
  FAU_02 legno: jitter ±0.2M su ~35M piatto → telescopa a −0.5M.
- Causa nel codice: [`ocr_risorse_robust`](shared/ocr_helpers.py) usava
  "prima lettura ≠ −1 vince" → non filtrava i **misread plausibili** (11.10M
  e 74.10M sono entrambi validi). Il filtro outlier del report (>30M/h) è
  per-ora e asimmetrico, non neutralizza gli estremi telescopici.

**Fix (punto b)**: lettura a **consenso 3-su-5** in `ocr_risorse_robust`. Per
ogni risorsa si raccolgono letture da screenshot FRESCHI e ravvicinati
(~0.8s, dove la produzione reale ≪ granularità 0.1M, quindi ogni divergenza è
errore OCR); si accetta il valore solo quando compare 3 volte (moda), il
misread di minoranza è scartato; senza consenso → −1 → fallback al valore
precedente (conservativo: meglio "0 prodotto" che uno spike). Early-exit a 3
letture se stabili. Diamanti inclusi. Chiamanti `main.py` aggiornati (5 tent).
Smoke test 4 scenari OK (oscillazione FAU_05 → 74.10M; no-consenso → −1;
stabile → early-exit; banner → tutti −1). `py_compile` OK.

**Limite noto**: il consenso intercetta i misread **frame-dipendenti** (caso
FAU_05, dove il valore giusto è maggioranza). Punti (a) mediana mobile
inter-tick e (c) filtro per-salto restano da discutere/valutare dopo
osservazione runtime.

**Prossimo step**: monitorare i log `[OCR-CONS]` e i totali produzione dopo
il riavvio; verificare scomparsa dei fantasmi (FAU_05 acciaio, FAU_02 legno).

---

## Sessione 26/06/2026 — WU181 store: re-center deterministico sul rifugio

Verifica funzionamento task `store` su richiesta utente. Telemetria 26/06
(28 run): 14 ok (202 oggetti, 14 free refresh), 5 skip (merchant non
disponibile, legittimi), **9 fail "Store non trovato" (32%)**.

**Diagnosi** (smontate 2 ipotesi sbagliate):
- *Non* è l'edificio che scompare (è sempre presente) né il revert della
  modalità grafica HIGH (la UI HOME rende a `0.988` identica in fail e ok).
- È l'**origine dello scan non ancorata**: l'offset memorizzato
  (`store_position`, WU172) e la griglia ±600px sono relativi al pan di camera
  EREDITATO dal task precedente. `vai_in_home()` ri-centra sul rifugio solo se
  trova lo schermo in MAP (toggle MAP→HOME); entrando da HOME già attiva è un
  no-op → pan ereditato.

**Correlazione predecessore→esito** (decisiva): tutti i 9 fail preceduti da
`messaggi` (7) o `arena_mercato` (2) — lasciano un pan non centrato; **0 fail
su 15 run** dopo `raccolta`/`donazione` — pan centrato. Score: verify pos.memo
0.33-0.36 + grid_max 0.40-0.43 (rumore) nei fail vs 0.66-0.74 negli ok.

**Fix** (`tasks/store.py::run`, step 0): forzato il giro
`vai_in_mappa()` + `vai_in_home()` prima dello scan → la camera si aggancia al
rifugio in modo deterministico, l'offset memorizzato torna valido a
prescindere dal task precedente. Il banner eventi ri-aperto dal giro viene
richiuso dal `_comprimi_banner` successivo (regola: default chiuso, apertura
solo per district_showdown). Best-effort: se il giro non riesce, procede con
l'origine corrente. Chiude anche l'ipotesi storica "Store edificio da
spostare" (non era la posizione dell'edificio).

Test `tests/tasks/test_store.py`: 34/39 (5 fail pre-esistenti invariati,
verificato via `git stash`), nessuna regressione. Sync dev+prod. Restart bot
eseguito dall'utente da `start.bat` (26/06 19:26 UTC) — il flag graceful è
stato rimosso perché i `.bat` erano LF-rotti (vedi nota infra sotto).

**Validato sul campo 27/06** (log `Re-center rifugio via MAP→HOME ✓` attivo su
FAU_07/08/09/10): **11 run, 0 fail (0%)** contro 9/28 (32%) pre-fix. I
predecessori che causavano TUTTI i fail ora ne causano zero: `arena_mercato`
7 run (6 ok, 1 skip), `messaggi` 1 run (ok). I 4 skip residui sono `Merchant
non confermato`/`Carrello non trovato` legittimi (store trovato e aperto,
mercante non offerente per rotazione VIP), non più "Store non trovato".
Diagnosi e fix confermati.

**Nota infra (stessa sessione)**: i `.bat` (`sync_prod.bat`, `start.bat`,
`run_dashboard_prod.bat`, …) erano finiti in LF dopo il rename dei launcher
(`run_prod.bat`+`riavvia_bot.bat` → `start.bat`) → `cmd.exe` non li parsava
(eseguiva frammenti di metà riga). Convertiti a CRLF + aggiunto
`.gitattributes` (`*.bat eol=crlf`) per evitare il regresso. Contenuto
launcher dev↔prod verificato identico (solo EOL); `run.bat` resta
env-specific e non sincronizzato.

**Prossimo step**: monitoraggio continuo store nelle prossime ore (campione
27/06 ancora piccolo, 11 run); chiusura definitiva issue se il trend 0%
"Store non trovato" si conferma su più cicli.

---

## Sessione 25/06/2026 (7) — WU178 catalogo nodi: rigenerazione automatica periodica

Dopo aver verificato che l'hook "occupato" scriveva correttamente (6-7
osservazioni reali da FAU_01/FAU_07), l'utente ha notato che la dashboard
non mostrava ancora nulla — causa: il catalogo è un artefatto statico, non
si auto-aggiornava (richiedeva rilancio manuale del tool CLI). Richiesta:
rigenerazione automatica periodica, con indicazione del prossimo
aggiornamento in UI.

**Implementazione**:
- `tools/costruisci_catalogo_nodi.py` refactored — logica estratta in
  `build_catalogo(root, days, write, verbose)`, riutilizzabile sia da CLI
  sia da un chiamante Python diretto (`main()` ora thin wrapper).
- Nuovo background task `dashboard/app.py::_nodi_mappa_rebuild_loop()`
  (stesso pattern del `_predictor_recorder_loop` già esistente nel
  lifespan): rigenera il catalogo ogni 20 min
  (`NODI_MAPPA_REBUILD_INTERVAL_MIN`), aggiorna uno stato in-process
  condiviso col route (`_nodi_mappa_rebuild_state`) con timestamp
  ultimo/prossimo.
- Pagina `/ui/nodi-mappa`: nuova riga "🔄 catalogo rigenerato
  automaticamente ogni 20 min · ultimo: GG/MM HH:MM · prossimo: GG/MM
  HH:MM" (ora locale).

Validato end-to-end: dashboard riavviata, log confermano avvio loop +
rigenerazione immediata al boot (242 coordinate, 215 senza occupante),
pagina mostra "ultimo: 25/06 17:32 · prossimo: 25/06 17:52" (+20min
esatti). Test 57/57 verdi. Sync dev+prod.

**Prossimo step**: nessuna azione richiesta — il catalogo ora si mantiene
fresco da solo. Il numero di nodi "senza occupante" scenderà
progressivamente nelle prossime ore/giorni man mano che le 11 istanze
completano marce sui rispettivi nodi.

---

## Sessione 25/06/2026 (6) — WU177 catalogo nodi: osservazione vs occupazione, eventi distinti

L'utente ha corretto il mio approccio WU176 (cutoff temporale arbitrario):
"la data ultima osservazione nasce dal cerca e dalla lettura del nodo,
mentre l'ultima istanza occupante invece nasce quando è confermato l'invio
del raccoglitore" — sono due eventi REALMENTE distinti nel flusso
`tasks/raccolta.py`, non lo stesso evento con un filtro temporale.

**Fix architetturale corretto**:
- Nuovo esito `"occupato"` in `shared/nodi_mappa.py` (terzo valore oltre
  `trovato`/`fuori_territorio`).
- Nuovo hook in `tasks/raccolta.py` al **Step 7 (COMMIT)** — dopo
  `blacklist.commit(chiave, eta_s)`, quando `_esegui_marcia` ha già avuto
  successo. Distinto dall'hook esistente a "nodo trovato — procedo" (CERCA
  + lettura, Step 1-2, ben prima del tentativo di marcia).
- `tools/costruisci_catalogo_nodi.py` riscritto: `prima/ultima_osservazione`
  + tipo/livello continuano a derivare da `trovato` (invariato);
  `ultima_istanza`/`ultima_occupazione_ts` derivano ESCLUSIVAMENTE da
  `occupato`. Nessun cutoff arbitrario necessario — "occupato" non esiste
  nel seed storico (il mining dei log originale catturava solo
  "trovato"/"RESERVED", mai "COMMITTED"), quindi è per costruzione sempre
  dato genuinamente live.

Test: 57/57 verdi. Catalogo rigenerato: 218 coordinate, 0 con occupazione
confermata al momento (atteso — il bot deve ancora ricaricare il nuovo
hook). Verificato che la dashboard riflette il dato senza riavvio proprio
(legge il catalogo da disco ad ogni richiesta, nessuna cache).

**Restart bot armato** (`claude_nodi_occupazione_confermata_WU177`) — a
fine ciclo corrente caricherà il nuovo hook. Da quel momento, ogni marcia
completata con successo popolerà `ultima_istanza` per quella coordinata.

Sync dev+prod, commit+push.

**Prossimo step**: dopo il restart, osservare che le prime marce
completate popolino `ultima_istanza` (rieseguire `tools/
costruisci_catalogo_nodi.py --prod --write` periodicamente per
rigenerare il catalogo con i nuovi dati "occupato").

---

## Sessione 25/06/2026 (5) — WU176 catalogo nodi: ultima istanza solo se live

Dopo aver chiarito il formato date (sessione precedente), l'utente ha
notato un'altra incongruenza: ogni nodo nel catalogo mostrava un'istanza
occupante anche se il sistema live era partito da meno di un'ora —
sospetto fondato, verificato sui dati: **202/214 nodi (94%)** avevano
`ultima_istanza` risalente al seed storico (mining log una tantum di
WU173, prima dell'attivazione dell'hook), non un'occupazione reale
recente. Solo 12 nodi riflettevano una genuina osservazione live.

**Fix**: nuova costante `SEED_CUTOFF_TS` (timestamp fisso del boot che ha
attivato l'hook) in `tools/costruisci_catalogo_nodi.py` — `ultima_istanza`
/`ultima_occupazione_ts` popolati SOLO da osservazioni con `ts >= cutoff`;
altrimenti `None` (`—` in dashboard). Tipo/livello/confidenza continuano a
usare tutto lo storico (seed incluso resta prova valida di identità del
nodo, non di occupazione attuale). Nuovo contatore `n_senza_occupante_live`
in dashboard.

Catalogo rigenerato: 216 coordinate, 16 con occupante live, 200 in attesa
di rivisitazione. Sync dev+prod, dashboard riavviata e verificata
end-to-end (curl su produzione: 16 istanze popolate, 200 "—").

**Prossimo step**: il numero di nodi "senza occupante live" scenderà
naturalmente nel tempo man mano che il bot rivisita le coordinate —
nessuna azione richiesta, solo attesa + rebuild periodico del catalogo.

---

## Sessione 25/06/2026 (4) — WU175 catalogo nodi: separazione territorio + ultima istanza

L'utente ha chiesto la colonna "ultima istanza occupante" e, analizzando il
dato, ha notato un'incongruenza: la coordinata 696_532 con 48-49 osservazioni
è impossibile se si parla di "nodo occupato" (un'occupazione reale è limitata
da disponibilità squadre/tempi di marcia, non può ripetersi 48 volte in 2
giorni). Verifica sui dati grezzi: confermato, **100% di quelle osservazioni
erano `esito=fuori_territorio`**, zero `trovato` — il nodo non è mai stato
occupato, solo scoperto e scartato ripetutamente durante la ricerca.

Root cause: il catalogo WU173 mischiava due popolazioni semanticamente
diverse — `trovato` (squadra realmente inviata: 212 coordinate distinte,
max 4 osservazioni/coordinata su 2gg, comportamento coerente con vera
occupazione) vs `fuori_territorio` (solo scoperta/scarto, nessun limite di
ripetizione: concentrato su SOLO 3 coordinate con conteggi abnormi 49/32/16).
Le due popolazioni non si sovrappongono mai (0 coordinate in comune) — una
volta blacklistato un nodo non viene mai più "trovato".

**Fix** (richiesta esplicita utente: "i nodi fuori territorio devono essere
conteggiati a parte, non hanno nessuna utilità, la mappatura è utile [solo
per] i nodi in territorio, il nodo occupato è effettivamente l'ultima
istanza che ha occupato il nodo"):
- `tools/costruisci_catalogo_nodi.py` riscritto — il catalogo principale
  contiene SOLO coordinate con ≥1 osservazione `trovato`; le coordinate
  solo-fuori-territorio sono escluse e contate a parte in un nuovo file
  `data/nodi_mappa_catalogo_meta.json`.
- Ogni entry del catalogo ha 2 nuovi campi: `ultima_istanza` +
  `ultima_occupazione_ts`, derivati dall'osservazione `trovato` più recente
  (mai dalle `fuori_territorio`, che non rappresentano occupazione).
- Dashboard: nuova colonna "ultima istanza occupante" + contatore "N fuori
  territorio (escluse)" nel sommario.
- Bonus fix scoperto in corso d'opera: `n_cross_istanza` della dashboard
  contava erroneamente anche le coordinate ambigue nelle "confermate
  cross-istanza" (24 vs 20 del tool CLI) — corretto escludendo `ambiguo`.

Catalogo rigenerato: 214 coordinate in territorio (50 ricorrenti, 92%
concordanti), 3 coordinate fuori territorio escluse. Validato end-to-end
con dashboard locale (porta temporanea 8799). Test: 559 pass / 148 fail
(pre-esistenti, nessuna regressione). Sync dev+prod, commit+push.

**Prossimo step**: continuare ad accumulare osservazioni (passivo). Da
rivalutare periodicamente con `tools/costruisci_catalogo_nodi.py --prod
--write` se procedere alla fase 2 (uso attivo del catalogo).

---

## Sessione 25/06/2026 (3) — WU174 dashboard: pagina /ui/nodi-mappa

L'utente ha chiesto: (1) confermare che il dataset WU173 è persistente
locale e non derivato dai log delle istanze (confermato — `tools/
costruisci_catalogo_nodi.py` legge solo `data/nodi_mappa_observations.jsonl`,
il mining dai log è stato usato SOLO per il seed iniziale una tantum); (2)
se è possibile un sistema di visualizzazione su dashboard.

Proposta (confermata dall'utente via scelta multipla): scatter SVG +
tabella, stesso pattern già usato in `/ui/ab-test`.

**Implementazione**:
- `dashboard/services/stats_reader.py::get_nodi_mappa_catalogo()` — legge
  `data/nodi_mappa_catalogo.json`, filtra per tipo/min_osservazioni, calcola
  `ambiguo` a runtime (`n_concordanti < n_osservazioni` — non persistito nel
  catalogo, vedi discussione sulla scelta arbitraria in caso di parità 1-vs-1).
- `dashboard/app.py` — route `/ui/nodi-mappa` + `_build_nodi_mappa_svg()`
  (scatter inline, stesso pattern del trend SVG di `/ui/ab-test`): posizione
  = cx/cy reali, colore = tipo (rosso/marrone/grigio/viola), raggio =
  confidenza (n_osservazioni, cap 15), anello rosso tratteggiato = ambiguo.
- `dashboard/templates/nodi_mappa.html` (NEW) — sezione scatter + sezione
  tabella filtrabile (tipo, soglia min osservazioni), badge ⚠ sulle righe
  ambigue. Link nav in `base.html`.

**Validazione end-to-end** (dashboard locale, porta temporanea 8799): 210
coordinate → 214 cerchi SVG (210 nodi + 4 anelli ambigui, combaciante con
l'analisi precedente), filtri verificati (`tipo=petrolio&min_oss=2` → 11
coordinate, `min_oss=10` → 3 coordinate, entrambi coerenti con la
distribuzione reale). SVG validato come XML ben formato.

Test: 148 fail / 559 pass su tutta la repo (pre-esistenti, nessuna nuova
regressione — variazione di 1 rispetto alla sessione precedente, probabile
test non deterministico estraneo a questa modifica). Sync dev+prod.

**Prossimo step**: riavviare la dashboard (uvicorn non ha `--reload` in
prod) per attivare la nuova pagina. Da rieseguire `tools/
costruisci_catalogo_nodi.py --prod --write` periodicamente per aggiornare
il catalogo via via che il dataset accumula osservazioni — la pagina
dashboard legge sempre l'ultimo catalogo scritto su disco.

---

## Sessione 25/06/2026 (2) — WU173 raccolta: dataset mappatura nodi (fase 1)

L'utente ha chiesto un'analisi più approfondita: è possibile mappare tutti i
nodi della mappa? Le coordinate sono ricorrenti? A parità di coordinata il
nodo è sempre lo stesso tipo/livello? Obiettivo finale (dichiarato
esplicitamente, fase 2 futura): una volta che il dataset è ritenuto
completo/attendibile, usarlo per velocizzare l'invio raccoglitori saltando
la scansione CERCA.

**Analisi preliminare** (mining log esistenti, ~46h di storico — vedi nota
sotto su profondità): 357 osservazioni, 214 coordinate distinte. 88% delle
coordinate ricorrenti (43/49) coerenti tipo+livello; 25/49 confermate
cross-istanza (prova diretta della mappa condivisa). Un caso (696_532)
mostra cambio tipo a un mese di distanza — coerente con l'ipotesi
dell'utente sul respawn dei nodi terminati. Bug scoperto: la lettura
coordinate di FauMorfeus è inattendibile (legge ripetutamente la coordinata
del proprio rifugio invece del nodo).

**Implementazione fase 1** (raccolta dati, nessun cambio di comportamento):
- Nuovo modulo `shared/nodi_mappa.py` — `registra_osservazione()` append-only
  su `data/nodi_mappa_observations.jsonl`, esclude FauMorfeus alla fonte.
- 3 hook in `tasks/raccolta.py::_tenta_marcia` (nodo trovato/RESERVED, nodo
  fuori-territorio skip ×2 varianti) — ogni CERCA che legge chiave+tipo+
  livello alimenta il dataset, indipendentemente dall'esito.
- Nuovo tool `tools/costruisci_catalogo_nodi.py [--prod] [--days N]
  [--write]`: majority-vote per coordinata, report instabilità + conferme
  cross-istanza + verdetto di maturità.
- Seed iniziale: 357 osservazioni minate dai log correnti (dev+prod) +
  primo catalogo `data/nodi_mappa_catalogo.json` (210 coordinate).
- Bug collaterale corretto: fixture autouse `DOOMSDAY_ROOT` aggiunta a
  `test_raccolta.py` (isola anche la pollution pre-esistente di
  `cap_nodi_dataset.jsonl` durante i test).

Test: 57/57 verdi `test_raccolta.py`, nessuna regressione sul resto della
repo (149 fail pre-esistenti invariate). Sync dev+prod, commit+push.

**Nota onestà sui dati**: la profondità storica reale dei log è ~46h (log
corrente + un solo `.bak`, ruotano giornalmente) — 161/210 coordinate (77%)
viste 1 sola volta, zero conferma indipendente. Il verdetto "maturo" del
tool guarda solo le coordinate ricorrenti (91.8% concordi), non la copertura
totale — il dataset deve continuare ad accumulare cicli prima di essere
considerato pronto per la fase 2.

**Fase 2 (NON implementata, gating esplicito dell'utente)**: uso attivo del
catalogo in `tasks/raccolta.py` per saltare la scansione CERCA e navigare
direttamente alla coordinata nota, quando il dataset sarà ritenuto maturo.

**Prossimo step**: lasciare accumulare osservazioni per più giorni/settimane
(il dataset si alimenta passivamente ad ogni ciclo di tutte le istanze),
poi rieseguire `tools/costruisci_catalogo_nodi.py --prod` periodicamente per
valutare la copertura totale (non solo le ricorrenti) prima di decidere se
procedere alla fase 2.

---

## Sessione 25/06/2026 — WU172 store: memorizzazione posizione edificio per istanza

L'utente ha chiesto una nuova regola per il task `store`: il posizionamento
dell'edificio è fisso in ogni istanza (non cambia mai), quindi prova prima
con una posizione memorizzata e solo se fallisce fai lo scan completo a
griglia (25 passi) per ritrovarlo — aggiornando la memoria se la posizione
è cambiata.

**Mining storico** richiesto esplicitamente dall'utente: analizzati i log
`[STORE] passo N → score=... *** match ***` di tutte le istanze (correnti +
`.jsonl.bak` del giorno prima). Risultato netto: **passo 7 vincente per
10/11 istanze** (FAU_07 passo 8) — segnale fortissimo, non casuale. Passo 7
corrisponde a un offset di swipe `(0,+300)` dalla vista di partenza (dalla
griglia a spirale `cfg.griglia`); passo 8 → `(+300,+300)`.

**Implementazione**:
- Nuovo modulo `shared/store_position.py` — `load()`/`save()` per istanza,
  storage `data/store_position.json`, atomic write (pattern identico a
  `morfeus_state.py`).
- `tasks/store.py::_esegui_store`: prima dello scan, se esiste una posizione
  memorizzata → un singolo swipe diretto (`_applica_delta_swipe`, helper
  estratto e riusato anche dalla cascata di recovery multi-candidato
  preesistente) + 1 verifica. Confermata → store gestito direttamente, scan
  saltato (~20-40s risparmiati nel caso comune). Non confermata → torna allo
  start (swipe inverso) e fa lo scan classico invariato, che a fine ricerca
  aggiorna la memoria **solo se la posizione è nuova o diversa**.
- Seed iniziale `data/store_position.json` popolato con i dati minati
  (dev+prod, 11 istanze).

**Bug collaterale trovato e corretto durante l'implementazione**: il nuovo
codice chiamava sempre `store_position.load/save`, scrivendo nella vera
cartella `data/` del repo dev durante l'esecuzione dei test (nessun
isolamento `DOOMSDAY_ROOT`) — aggiunta fixture `autouse` in
`tests/tasks/test_store.py` (pattern già usato in `test_telemetry_rollup.py`).

Test: 34/39 verdi in `test_store.py` (5 fail pre-esistenti invariate,
verificato identico set pre/post-fix via `git stash`), nessuna regressione
sul resto della repo (149 fail pre-esistenti totali su tutta la suite, tutte
unrelated). Sync dev+prod, commit+push.

**Prossimo step**: osservare i prossimi cicli — confermare nei log che
`Posizione memorizzata: ... *** confermata ***` scatti per la maggioranza
delle istanze (skip scan) e che l'eventuale aggiornamento di posizione
(`Posizione store aggiornata in memoria`) avvenga solo quando l'edificio
risulta davvero altrove.

---

## Sessione 23/06/2026 (2) — WU171 messaggi: tab attivo sbagliato, alliance mai raccolto

L'utente ha segnalato che il task `messaggi` "continua a non funzionare bene":
il controllo dice di trovarsi su Alliance ma in realtà è su System, quindi
tappa di nuovo System (già lì) e non recupera mai le ricompense Alliance.

Diagnosi log+screenshot FAU_10 (11:28 UTC, `data/messaggi_debug/`):
`[PRE-OPEN] alliance=0.928 system=1.000` → il bot rileva `tab attivo: alliance`,
ma lo screenshot `01_post_open` mostra **System** realmente attivo (oro, badge
12) e Alliance inattivo (badge 4). Conseguenza: `[ALLIANCE] già attivo dal
PRE-OPEN — tap skippato` (mai tappato Alliance), claim "Read and claim all"
eseguito sul contenuto di System spacciandolo per Alliance, poi il passo
System tappa di nuovo lo stesso tab (già lì) e claima **due volte lo stesso
contenuto**. Alliance non viene mai visitata.

**Root cause** (`tasks/messaggi.py::_rileva_tab_attivo`): la logica era
`if score_a >= soglia: return "alliance"` valutato PRIMA del check su system
— quando ENTRAMBI superano `soglia_open=0.80` simultaneamente, alliance vince
sempre, indipendentemente da quale punteggio sia più alto o quale tab sia
realmente attivo. Verificato che questo overlap di punteggi è **sistematico**,
non occasionale: stessi identici valori (alliance=0.928, system=1.000)
confermati su 5/5 istanze controllate (FAU_02/03/04/09/10) — il template
`pin_msg_02_alliance.png` non discrimina a sufficienza fra stato attivo e
inattivo del tab.

**Fix**: nuovo helper `_tab_piu_probabile(score_a, score_s, soglia)` — ritorna
il tab col punteggio PIÙ ALTO fra quelli sopra soglia, non il primo che la
supera. Usato sia nel check iniziale che nel retry. Nessuna modifica a
template/soglie. Test: 42/42 verdi. Sync dev+prod, restart armato.

**Prossimo step**: dopo il restart, verificare che le prossime esecuzioni di
`messaggi` su istanze che si aprono con System come tab di default mostrino
`tab attivo: system` nel log (non più sempre `alliance`), e che `output`
riporti `alliance=true` genuino (non un claim duplicato su System).

---

## Sessione 23/06/2026 — WU163 rifornimento: debug match pin rifugio falso positivo

L'utente ha segnalato (con problemi di connettività in corso) che FAU_10 non
aveva inviato rifornimento perché non riusciva a tappare sul rifugio. Verifica
log (`logs/FAU_10.jsonl` 07:02 UTC, `logs/FAU_05.jsonl` 05:53 UTC stesso giorno):
ROI primaria del match pin rifugio fallisce (score 0.406-0.543 < soglia 0.70),
ROI retry "trova" con score borderline 0.59-0.60 (soglia permissiva 0.55) — ma
è un **falso positivo**: il tap risultante su (435,174) — identico su entrambe
le istanze, sospetto elemento fisso — non apre RESOURCE SUPPLY (score
0.397-0.406 vs soglia 0.75) → 0 spedizioni. Le altre 6/9 istanze attive quel
giorno hanno avuto match diretto forte (score 0.886) e 5/5 spedizioni — non è
un problema generale, è il caso limite già previsto nel commento WU161
(`tasks/rifornimento.py:407-410`).

**Ipotesi utente da verificare**: icone evento sulla mappa che coprono/
confondono il pin del rifugio nella ROI di ricerca (coerente con precedente
WU162, che aveva già introdotto il collasso del banner eventi laterale per lo
stesso motivo — ma quel collasso gestisce solo quel banner specifico).

**Azioni**:
1. Attivato `globali.debug_tasks.rifornimento=true` in `runtime_overrides.json`
   prod (dynamic, hot-reload, nessun riavvio necessario per questo flag).
2. Refactor del dump screenshot esistente in `tasks/rifornimento.py::_centra_mappa`
   in helper dedicato `_dump_debug_screenshot(ctx, screen, tag, score)`, con due
   tag distinti: `fail` (match fallito su entrambe le ROI, comportamento
   preesistente) e **`suspect`** (NUOVO — match confermato SOLO dalla soglia
   permissiva di retry, score < 0.70 — il caso a rischio falso positivo).
   Nessun cambio di comportamento/logica di tap, solo osservabilità aggiuntiva
   in `data/rifornimento_debug/`.
3. Test: 43/43 verdi (le 9 failure pre-esistenti in `test_rifornimento.py` sono
   debito tecnico invariato, confermato identico anche su `git stash`).
4. Sync dev→prod, commit+push, restart one-shot armato a fine ciclo corrente.

**Prossimo step**: alla prossima occorrenza del bug (qualsiasi istanza),
analizzare lo screenshot `*_suspect_score*.png` in `data/rifornimento_debug/`
per confermare/escludere l'ipotesi icone evento. Se confermata, valutare fix
(es. estendere `dismiss_banners_loop`/`comprimi_banner_home` prima della
ricerca pin, oppure escludere la zona delle icone dalla ROI di matching).

---

## Sessione 22/06/2026 — WU170 messaggi: popup reward intercetta tap cambio tab

L'utente ha segnalato (2ª volta, dopo verifica visiva diretta su FAU_08) che
il bot raccoglieva solo su una tab senza spostarsi sull'altra, pur con i log
che mostravano `alliance_ok=system_ok=True`. Diagnosticato forzando la
cattura debug screenshot su OGNI esecuzione (`force=True` temporaneo +
riavvio), poi confrontando i 4 campioni raccolti:

- FAU_00, FAU_10, FAU_04 → corretti (tab cambia, contenuto visivamente diverso)
- **FAU_03 (23:53:21 UTC) → bug confermato in diretta**

Confronto pixel-preciso della tab bar (crop ROI esatte usate dal codice)
sullo screenshot `03_post_system` ha mostrato il tab **"ALLIANCE" ancora
attivo** (dorato) nonostante il log dicesse `[PRE-SYSTEM] score=0.919 → OK`.

**Root cause**: il claim "Read and claim all" su Alliance genera un popup
reward ("Congratulations! You got") che resta aperto sopra la schermata. Il
tap successivo per passare a System (328,34) cade su un'area "tap empty
space to close" del popup, **chiudendolo senza mai raggiungere il tab bar**
— il bot resta su Alliance ma il check System produce un **falso positivo**
del template matching (score 0.919, sopra soglia 0.80). I messaggi System
non vengono mai raccolti, claim parziale completamente invisibile — stesso
pattern di mascheramento di WU165/167, ma più subdolo (qui il punteggio
template è genuinamente alto, non un retry insufficiente).

**Fix**: nuovo `_dismiss_popup_reward()` chiamato dopo ogni claim, chiude
esplicitamente il popup (se presente) prima di procedere al tab successivo.
Nuovo template `pin_msg_05_congrats.png` estratto da screenshot reale,
verificato empiricamente con `TemplateMatcher` reale (score=1.000 su popup
vs -0.029/0.097 su schermate normali). Test 42/42 verdi (5 nuovi). Debug
flush temporaneo rimosso post-fix. Sync dev+prod, restart armato.

**Restart confermato**: ciclo 271 avviato 2026-06-22 04:29 UTC, `boot_ts`
coincide, flag consumato. Fix attivo in produzione.

---

## Sessione 20/06/2026 — WU169 DistrictShowdown "icona evento non trovata" intermittente

L'utente ha chiesto di verificare se i fallimenti "icona evento non trovata"
coincidessero con il banner eventi chiuso (l'icona DS è visibile solo a
pannello aperto). Confermato con i dati: 24 fallimenti su 10gg, due pattern
distinti.
- **08/05**: 8 fallimenti consecutivi su tutte le istanze, zero successi
  quel giorno → evento mensile non attivo, legittimo.
- **19-20/06**: 16 fallimenti **intervallati con successi sulla stessa
  istanza** a poche ore di distanza (es. FAU_00 fail 19:52 → ok 22:45) →
  bug transiente, non "evento spento".

Causa, 2 varianti osservate sulla stessa FAU_03 (`tasks/district_showdown.py`):
- **(A)** banner rilevato chiuso correttamente ma `time.sleep(1.0)` dopo il
  tap di apertura — sotto il minimo 2.0s della REGOLA DELAY UI — icona
  cercata su schermata non ancora renderizzata.
- **(B)** nessun log "banner chiuso": il check originale agiva solo se
  `score_chiuso >= 0.85`; sotto soglia (banner in transizione) il tap di
  apertura veniva saltato silenziosamente, icona rimasta nascosta.

Fix: nuovo `_assicura_banner_aperto()` — loga sempre entrambi i punteggi,
tappa apri a meno che "aperto" non sia confermato (evita di richiudere un
banner già aperto). `run()` ora fa un retry completo (check banner +
ricerca icona) se il primo tentativo fallisce. Verificato con fake
device/matcher i 3 casi (chiuso→tap, ambiguo→tap, aperto→no-op). Sync
dev+prod.

---

## Sessione 19/06/2026 (sera) — WU168 adaptive scheduler: 3 fix dataset/calibrazione

Partito da una richiesta di recap+analisi del sistema predittivo ("qual è il
dataset?" → proposta migliorativa → "implementa tutti i punti"). Durante
l'implementazione del fix proposto (auto-calibrazione T_L_max) è emerso un bug
molto più fondamentale di quanto previsto.

**Bug critico scoperto**: la calibrazione closed-loop T_marcia
(`core/t_marcia_calibration.py`, proposta B 08/05) non ha **mai funzionato**
da quando è stata introdotta — sempre 0 campioni, `coef` sempre 1.0. Causa,
3 bug cumulativi in `core/istanza_metrics.py`:
1. `imposta_adaptive_scheduler_meta` scriveva la chiave `"adaptive_scheduler"`
   nel buffer, ma il reader si aspettava `"adaptive_scheduler_meta"` (mismatch).
2. La chiave non era nella whitelist di `chiudi_tick()` → mai scritta su disco
   anche a mismatch risolto.
3. L'hook è chiamato dal main loop PRIMA che `inizia_tick()` crei il buffer per
   quell'istanza (lo scheduler ordina tutte le istanze prima di avviare i
   thread) → `buf=None` sempre, scartato silenziosamente.

Fix: chiave corretta + whitelist aggiornata + staging
`_PENDING_SCHEDULER_META` consumato da `inizia_tick()` indipendentemente
dall'ordine di chiamata. Verificato end-to-end su sandbox isolata con la
sequenza reale (meta → inizia_tick → chiudi_tick).

**Fix #2 — scoping calibrazione** (`core/skip_predictor.py::_calc_t_marcia_min`):
`coef` moltiplicava l'intera `T_marcia = 2×eta + sat×T_L_max`, correggendo
anche `eta_marcia` (misura OCR diretta, non una stima — non andrebbe
corretta da un coefficiente aggregato). Ora `coef` moltiplica solo il termine
`sat×T_L_max`. Aggiunto campo informativo `effective_t_l_max` (base×coef) in
`compute_calibration()` per audit drift del baseline manuale
`config/predictor_t_l_max.json` — non sovrascritto automaticamente.

**Fix #3 — smoothing cliff** (`core/adaptive_scheduler.py::_blend_alpha`): da
gradini netti (salto di 0.3 per un solo campione extra a n=5) a interpolazione
lineare continua, stessi estremi (α=1.0 a n=0, α=0.3 a n≥30).

**Fix #4 — igiene storage**: `cycle_snapshots.jsonl` (6.3MB/3.649 righe,
più pesante di `istanza_metrics.jsonl` con meno della metà delle righe) per
duplicazione di `input_context` quasi-statico ogni 15min. Dedup write-side +
resolver read-side trasparente (zero modifiche ai consumer dashboard). Più
`tools/rotate_predictor_logs.py` (CLI manuale, dry-run default, archiviazione
mensile) — testato su sandbox, ricostruzione bit-a-bit identica all'originale.

Nessun test dedicato (convenzione repo: solo `tasks/*.py` ha test unitari).
Validazione via sandbox isolate + dry-run. Sync dev+prod.

---

## Sessione 19/06/2026 — WU167 claim parziale messaggi → fail

**WU167 — `messaggi` riportava successo pieno anche con claim parziale.** L'utente
ha chiesto di monitorare la prossima esecuzione di `messaggi` per verificare che
alliance e system venissero davvero raccolti entrambi ("non so cosa perché non
ho visto l'operazione completa"). Verifica live: l'esecuzione più recente (FAU_04,
13:45 UTC) ha confermato entrambe le tab raccolte correttamente (`[PRE-OPEN]
alliance=0.928 system=1.000`, due tap "Read and claim all", `output={"alliance":
true,"system":true}`).

Durante la verifica, analisi dello storico telemetrico (`data/telemetry/events/`)
ha però scoperto un bug reale, stesso pattern di mascheramento di WU165:
`tasks/messaggi.py::_mappa_esito()` ritornava `TaskResult.ok()` anche quando
**una sola** delle due tab veniva raccolta (`alliance_ok or system_ok`, non
`and`) — il fallimento parziale restava visibile solo nel campo `output` interno,
invisibile a telemetria/dashboard aggregate. Caso reale: FAU_04 18/06 22:29 UTC,
`[PRE-SYSTEM] score=0.528 → NO` (3 tentativi, lag UI cambio tab) →
`output={"alliance":true,"system":false}` ma `outcome="ok"`. Frequenza storica:
19/1480 esecuzioni "ok" (1.3%), sempre `system=False`, mai il contrario.

Fix (`tasks/messaggi.py::_mappa_esito`): ok solo se **entrambe** le tab riuscite,
altrimenti `TaskResult.fail("Claim parziale: alliance=... system=...")`. Bonus
WU79: retry al ciclo successivo invece di aspettare 4h. `debug.flush()` ora forza
il salvataggio screenshot anche su claim parziale (non solo doppio fallimento) per
diagnosi futura. Test aggiornati (2 nuovi unitari su `_mappa_esito`, 1 nuovo
integration su `run()`, 1 esistente corretto per la nuova semantica) — 37/37 verdi.
Sync dev+prod.

---

## Sessione 18/06/2026 — Fix MessaggiTask (tab bar stale + dual-tab uncommitted)

**WU165 — `tasks/messaggi.py` falliva da giorni** ("schermata non aperta" sistematico).
Diagnosi forense con `cv2.matchTemplate` pixel-precisa su 104 screenshot debug reali
(`data/messaggi_debug/`): il client gioco ha aggiunto i tab REPORT/SENT/BOOK alla
schermata Messaggi (prima solo Alliance+System), spostando a sinistra le posizioni
di Alliance e System. Le ROI/tap configurate erano stale: **0/104** screenshot
superavano la soglia con le vecchie coordinate, **103/104** con quelle ricalibrate.

Fix applicato (dev+prod):
- `roi_alliance`: `(283,23,367,47)` → `(145,15,250,50)`
- `roi_system`: `(417,23,490,50)` → `(280,15,377,50)`
- `tap_tab_alliance`: `(325,35)` → `(198,34)`
- `tap_tab_system`: `(453,36)` → `(328,34)`

Incluso nello stesso commit anche il fix "PRE-OPEN DUAL-TAB" (`_rileva_tab_attivo` +
`skip_tap`), che era già live in prod (copiato a mano) ma mai committato in dev —
gap di processo rispetto al protocollo Rilasci.

**Test suite stale scoperta e corretta**: `tests/tasks/test_messaggi.py` era ancora
scritto per la vecchia API single-tab (`MessaggiConfig(wait_back=...)`, `cfg.n_back_close`
— campi non più esistenti) e falliva 15/27, nonostante la ROADMAP dichiarasse 27/27.
Riscritto con copertura per `_rileva_tab_attivo()` e `skip_tap` in `_gestisci_tab()`.
Ora 35/35 verdi. Commit `e038736`, pushato su `main`.

**Nota dead-config risolta nello stesso giorno** (commit `54ab117`): `time.sleep(3.0)`
hardcoded in `_esegui_messaggi`/`_gestisci_tab` ignorava `cfg.wait_open`/`cfg.wait_tab`,
rendendo inefficace il tuning manuale fatto dall'utente in precedenza (tentativo di
fix prima di scoprire la causa reale). Wired ai campi cfg; `wait_tab` default
2.0→3.0 per preservare il timing reale già in esecuzione (nessun cambio comportamento
a runtime). Bonus: i test ora azzerano davvero i sleep (`_cfg_zero()`), suite passata
da 60s a 0.14s.

**Bug telemetria scoperto e risolto** (commit `6e1c5ce`): l'utente ha notato che la
dashboard/MCP `performance_task` mostrava messaggi al "100% eseguiti" nonostante il
fallimento multi-giorno. Causa: `_mappa_esito()` mappava `SCHERMATA_NON_APERTA` su
`TaskResult.skip()` (success=True) — `main.py:915` (`esito = "ok" if lr.success else
"err"`) non distingue skip da vero completamento, quindi lo storico/dashboard
mostrava "ok" per ogni fallimento. La telemetria granulare (`data/telemetry/events`,
campo `outcome`) registrava invece correttamente 441 skip vs 9 ok da inizio giugno —
discrepanza tra le due viste confermata da verifica diretta. Fix: "schermata non
aperta" non è un no-op legittimo ma un'incapacità di eseguire il task → ora
`TaskResult.fail()`. Effetto collaterale positivo: per WU79 `last_run` non avanza su
fail, quindi un blocco analogo futuro viene ritentato al ciclo successivo invece di
aspettare le 4h piene in silenzio. Test aggiornati, 35/35 verdi.

**WU166 — Pulizia cache: storico persistente + alert proattivo.** Scoperto durante
l'indagine WU165 (l'utente ha chiesto verifica esplicita "funziona la clear cache
mattutina?"): la pulizia FUNZIONAVA correttamente per tutte le 11 istanze del 18/06
(confermato via `cache_state.json` + `data/cache_debug/`), ma senza nessuna traccia
persistente — bypassa Task/telemetria e le righe `[CACHE]` nei log istanza si perdono
alla rotazione (solo l'ultimo tick resta in `logs/<NOME>.jsonl`). Un fallimento notturno
sarebbe stato invisibile.

Fix in 2 parti (dev+prod):
- `core/settings_helper.py::_log_cache_history()` — append-only `data/cache_history.jsonl`,
  un record per ogni tentativo (ok/fail/durata/msg).
- `core/alerts.py::check_cache_pulizia_giornaliera(cutoff_hour_utc=12)` — alert se manca
  la marca giornaliera dopo mezzogiorno UTC. Esclude istanze `tipologia=="raccolta_only"`
  (FauMorfeus/master, replica esatta esclusione `core/launcher.py:1064`) per evitare falsi
  positivi. Wired in `main.py` accanto a `check_master_saturo`/`check_heartbeat_cicli`/
  `check_maintenance_long`. Cooldown 4h.

Nessun test dedicato (repo non testa unitariamente `core/` helper, solo `tasks/*.py`).
Effetto al prossimo restart bot (flag one-shot già armato per WU165).

---

## Sessione 07/06/2026 — Analisi multi-agente + Fase 0 + notifiche A+B

**Analisi approfondita read-only** (44 agenti, 16 subsystem) → `docs/analisi_2026-06-07.md`.
27 findings critical/high verificati su codice (0 falsi positivi). 5 temi ricorrenti:
(1) monitoring cieco, (2) default silenzioso da config, (3) success spurio su screenshot
None, (4) fragilità OCR/ROI, (5) igiene repo. Piano in 5 fasi (0=osservabilità → 4=igiene).

**Fix max_squadre** (WU-MaxSquadre, bug-class C6) — FAU_00/FauMorfeus usavano 4 slot invece
di 5: `_ovr("max_squadre", 4)` legge solo dynamic, il campo mancava in `runtime_overrides`
→ fallback hardcoded. Fix dynamic `max_squadre: 5`. Validato: FAU_00 `inviate=5`.

**Fase 0 — osservabilità** (WU163, commit `5090ef5`):
- C1/O1 `check_heartbeat_cicli`: leggeva `cicli.json` (dict) come lista + chiave `ts_end`
  errata → l'unico alert *critical* "bot morto" non scattava MAI. Fix: `load_cicli()` + `end_ts`.
- C3/O4 `record_istanza_tick_end`: hardcoded `esito="ok"` anche su cascade → sezioni
  cascade/abort/fail del daily report codice morto. Fix: thread propaga esito reale via
  `_ultimo_esito_tick` letto dopo `t.join()`.

**Notifiche A+B** (WU164, commit `0e9e04b` + config dynamic):
- Errore salvataggio dashboard "from_addr non valido" = mittente vuoto (validazione endpoint).
- A: `enabled/alerts_enabled=true` + `from_addr=bot.dooms.report@gmail.com` +
  `recipients=[fausto.pace@gmail.com]` (hot-reload).
- B: `notify_alert` generico + routing heartbeat/maintenance/restart su Telegram (prima solo
  cascade/DRL). Coupling: `trigger_alert` richiede ≥1 destinatario email anche per Telegram.

**Restart**: armato (flag manuale one-shot), scatta a fine ciclo 426 per attivare B.

> **Issues aperti dall'analisi** (in `docs/analisi_2026-06-07.md`): Fase 1 (success spuri
> marcia/spedizione su screenshot None C4/C9, atomic blacklist C7, store skip C8, OCR 999M C10);
> Fase 2 (merge `_save_ov` C5, fallback `_ovr` static C6, auth dashboard C2); Fasi 3-4 perf+igiene.

---

## Stato step pytest

| Step | File principali | Test | Note |
|------|----------------|------|------|
| 1-10 | `core/`, `shared/`, `config/` | ✅ | Infrastruttura base |
| 11 | `tasks/boost.py` | ✅ 35/35 | |
| 12 | `tasks/store.py` | ✅ 39/39 | VIP Store + mercante diretto |
| 13 | `tasks/messaggi.py` | ✅ 37/37 | WU165 18/06: ricalibrazione tab bar + commit fix dual-tab. WU167 19/06: claim parziale → fail |
| 14 | `tasks/alleanza.py` | ✅ 24/24 | |
| 15 | `tasks/vip.py` | ✅ 30/30 | |
| 16 | `tasks/arena.py` | ✅ 10/10 | tap_barra("campaign") |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | struttura V5+V6, tap_barra |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 57/57 | territorio + allocation gap V5 |
| 22 | `core/orchestrator.py` | ✅ 49/49 | |
| 23 | `dashboard/` | ✅ 30/30 | |
| 24-25 | Fix + refactoring | ✅ | |
| 26 | `dashboard/` V6 rewrite | ✅ | FastAPI+HTMX, 6 test client, commit `9773de3` |
| **nav** | `core/navigator.py` | ✅ 20/20 | tap_barra() TM barra inferiore |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Piano test runtime — Stato al 21/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01..05 | Infrastruttura, navigator, OCR, slot | ✅ | |
| RT-06 | VIP claim | ✅ | |
| RT-07 | Boost | ✅ | BoostState scheduling 16/04/2026. RIAPERTO 19/04 (tap non responsivo) → RISOLTO 19/04 (tap `speed_cx/speed_cy`, cy<400 responsivo, polling `pin_speed_use` 4s). Verificato FAU_00 test isolato ore 18:12 + FAU_01 ciclo completo da freddo: boost 8h attivato entrambi. |
| RT-08 | Messaggi + Alleanza | ✅ | |
| RT-09 | Store | ✅ | 18 acquistati + Free Refresh |
| RT-10 | Arena | ✅ | 5 sfide + skip checkbox |
| RT-11 | Raccolta V6 upgrade | ✅ | OCR coord X_Y, ETA, interleaving, psm=6 fix 3/5→5/5. Test 2/5→3 marce + 5/5→skip. 15/04/2026 |
| RT-12 | Tick completo FAU_01 | ✅ | Tick completo funzionante |
| RT-tap | tap_barra barra inferiore | ✅ | score=1.000 tutti 5 bottoni su FAU_01 |
| RT-15 | Arena + ArenaMercato | ✅ | Arena: 5/5 sfide 8.4s/sfida; ArenaMercato: pack360=5; fix BACK×2 |
| RT-16 | Rifornimento via mappa | ✅ | 5/5 spedizioni, qta reale 4M, provviste tracciate, soglia/abilitazione OK |
| RT-17 | Rifornimento via membri | ✅ | 1/1 spedizione, navigazione lista alleanza, avatar trovato, btn risorse 0.986 |
| RT-18 | Scheduling restart-safe | ⏳ | VIP daily OK (skip <24h, ISO string). Da testare: (1) periodic skip <interval; (2) --force daily; (3) restore_to_orchestrator al riavvio main.py |
| RT-19 | Radar + RadarCensus | ✅ | badge OK (78,315), pallini 2/2, census 10 icone, map_annotated OK. Fix pendente: falso positivo "Complete All" zona basso-sx |
| RT-20 | Zaino BAG + SVUOTA | ✅ | bag: TM-based scan+greedy+esecuzione, caution popup, fix campo qty. svuota: sidebar+USE MAX validata. Entrambe le modalità chiuse |
| RT-21 | Pytest aggiornato 258/258 | ✅ | BoostState/VipState/ArenaState/RifornimentoState + gate should_run() orchestrator. 16/04/2026 |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dopo RT-18 + RT-22..24 |
| RT-14 | Full farm 12 istanze | ⏳ | |
| RT-22 | Ciclo notte prod 20→21/04 | 🟡 | 25 cicli 22:30→05:51, raccolta 24OK/6ERR. Rifornimento validato 11/11 istanze → **68 spedizioni, ~140.7M risorse** a FauMorfeus (legno 91.8M, petrolio 31.8M, pomodoro 17.1M). **Aperti:** arena 5 istanze KO (Issue #14), engine_status stale (#15), OCR legno anomalo FAU_10 (#16). |

---

## Indice documentazione

La cronologia dettagliata e lo storico issue sono stati riorganizzati (07/06/2026).
Questo file resta la vista **corrente + strutturale**; il resto è linkato qui.

### Issue & changelog
| Cosa | Dove |
|------|------|
| Stato issue **per tematica** (storico WU completo) | [`docs/issues/`](docs/issues/README.md) |
| Issue **aperti** (riassunto) | [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Issues — stato sintetico" |
| Storico cronologico ROADMAP (sessioni, "Fix applicati") | [`docs/changelog/ROADMAP-storico.md`](docs/changelog/ROADMAP-storico.md) |
| Analisi architetturale 07/06 (punti critici, piano 5 fasi) | [`docs/analisi_2026-06-07.md`](docs/analisi_2026-06-07.md) |

### Architettura & riferimento
| Cosa | Dove |
|------|------|
| Overview architettura sistema | [`docs/OVERVIEW.md`](docs/OVERVIEW.md) |
| Architettura bot Telegram | [`docs/TELEGRAM_BOT_ARCHITECTURE.md`](docs/TELEGRAM_BOT_ARCHITECTURE.md) |
| Reference API moduli | [`docs/reference.html`](docs/reference.html) |
| Regole operative & standard V6 | [`.claude/CLAUDE.md`](.claude/CLAUDE.md) |

### Tematiche issue
- [Raccolta](docs/issues/raccolta.md) · [Rifornimento & Zaino](docs/issues/rifornimento-zaino.md) · [Arena/Combat](docs/issues/arena-combat.md) · [Truppe](docs/issues/truppe.md)
- [Radar](docs/issues/radar.md) · [Dashboard & Config](docs/issues/dashboard-config.md) · [Telemetria/Predictor](docs/issues/telemetria-predictor.md)
- [Notifiche & Alert](docs/issues/notifiche-alert.md) · [OCR/Vision](docs/issues/ocr-vision.md) · [Infra/Startup](docs/issues/infra-startup.md) · [Telegram](docs/issues/telegram.md)
