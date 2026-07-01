# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

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

Sync dev+prod fatto, restart one-shot armato. Nessun commit ancora quando
questa sezione è stata scritta — vedi commit successivo per hash.

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
