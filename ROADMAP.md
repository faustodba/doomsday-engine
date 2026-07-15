# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

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
