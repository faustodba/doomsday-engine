# AUTONOMOUS_CHANGES.md — Tracking modifiche autonome

> File auto-generato durante il monitoraggio 24/04/2026.
> Ogni fix applicato autonomamente viene registrato qui con commit SHA e rollback ready.

## Anchor point

- **Tag git**: `monitoring_start_24_04`
- **SHA ancora**: `31489d0` (commit "fix: soglie e delay per stabilità store/donazione/district_showdown")
- **Timestamp inizio monitoraggio**: 2026-04-24 22:15 locale (20:15 UTC)
- **Finestra massima**: 10 wake-up × ~35 min ≈ 6 ore

## Comandi rollback

### Rollback totale (annulla TUTTI i fix autonomi)
```bash
cd /c/doomsday-engine
git reset --hard monitoring_start_24_04
git push --force-with-lease origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# poi kill+restart bot
```

### Rollback singolo fix (per SHA)
```bash
cd /c/doomsday-engine
git revert <SHA>
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# poi kill+restart bot
```

### Rollback granulare per file (mantiene altri fix)
```bash
cd /c/doomsday-engine
git checkout monitoring_start_24_04 -- <path/to/file.py>
git commit -m "revert(auto): rollback <file> to pre-monitoring"
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
```

## Registro modifiche

> Formato: wake-up · timestamp · file · commit SHA · motivazione · evidenza log
> Aggiornato automaticamente ad ogni fix applicato.

### WU3 — 2026-04-25 07:45 CEST · ADB recovery mid-tick

- **Commit SHA**: `22e9811`
- **File modificati**:
  - `core/device.py` — refactor `screenshot()` → `_screenshot_raw()` + nuovo wrapper con retry+reconnect; nuovo metodo pubblico `reconnect()`
  - `core/navigator.py` — `vai_in_home()` tenta `device.reconnect()` prima dell'abort definitivo
- **Motivazione**: cascata ADB unhealthy 02:28-05:02 UTC del 25/04 ha causato 3h30m di task saltati su FAU_01-05+08. F1a (none_streak) + F1b (kill-server in avvia_istanza) non riparavano il device mid-tick.
- **Evidenza log**: `FAU_01.jsonl` linee 931-989 (02:22-02:23 UTC) — pattern `screenshot None 3x → vai_in_home ABORT` ripetuto ogni ~5s senza recupero.
- **Comportamento atteso post-fix**:
  - Path felice invariato (screenshot OK al primo tentativo)
  - Su None: 1 retry dopo 0.5s, poi reconnect ADB + 1 last shot
  - Se ancora None: navigator chiama `reconnect()` UNA volta extra prima dell'abort
  - Cascata attesa: da 3h30m → 1-2 tick (~1 min totale)

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 22e9811
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU4 — 2026-04-25 08:26 CEST · STORE soglia 0.675 → 0.65

- **Commit SHA**: `2fe66a9`
- **File modificati**:
  - `tasks/store.py:57` — `soglia_store: float = 0.675 → 0.65`
- **Motivazione**: caso FAU_09 ciclo 06:12 UTC del 25/04: best_score scan=0.811 ma re-match=0.665 (drift -0.146). Soglia 0.675 lasciava fuori re-match validi per 0.01 punti. Con take-max + re-match abbassare a 0.65 è sicuro (take-max non ha rischio mistap del first-match-break).
- **Evidenza log**: `FAU_09.jsonl` ciclo 06:12 — best step alto (0.811) ma re-match drift sotto soglia → Outcome=`store_non_trovato`.
- **Diagnosi DONAZIONE**: i 7 `pin_marked non trovato` sono game state legittimi (nessuna tech marcata da donare), il task ritorna `success=True donate=0`. NESSUN FIX applicato.
- **Bot restart**: PID 7752 → PID 23480 (start 08:26:24) con `--resume --use-runtime --tick-sleep 60 --no-dashboard`.
- **Comportamento atteso post-fix**: caso FAU_09 borderline ora successo. STORE_NON_TROVATO rate atteso da 1/16 → 0/16 sui borderline. Casi LABEL_NON_TROVATA / MERCHANT_NON_APERTO non toccati (correlati a stato gioco / cascata ADB già mitigata da WU3).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 2fe66a9
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU5 — 2026-04-25 08:59 CEST · DS exit back x4 prima di vai_in_home finale

- **Commit SHA**: `c6d9655`
- **File modificati**:
  - `tasks/district_showdown.py:405-414` — aggiunto `for _ in range(4): ctx.device.back(); sleep(delay_dopo_tap_minor)` PRIMA di `ctx.navigator.vai_in_home()` finale
- **Motivazione**: bug sistemico 25/04 04:18-06:51 UTC su 9 istanze (FAU_01-07, 09, 10): dopo DS task termina le fasi 2-5, il bot resta su mappa evento DS. `vai_in_home()` alterna tap_overlay/back ma tap_overlay riapre popup evento → 8 vai_in_home FALLITO → orchestrator gate HOME FALLITO → **raccolta SALTATA per ogni istanza** (questo era il bug critico segnalato dall'utente).
- **Evidenza log**: `FAU_10.jsonl` linee 339-374 (06:50:27-06:51:20 UTC). Sequenza: `[DS-RAID] skip` → 8 tentativi vai_in_home con score home=0.371-0.490 (UNKNOWN) → vai_in_home FALLITO → `[raccolta] gate HOME FALLITO — task SALTATO`. Pattern identico su FAU_01,02,03,04,05,06,07,09 in orari diversi.
- **Bot restart**: PID 23480 → PID 7432 (start 08:59:16).
- **Comportamento atteso**: 4 back() consecutivi escono da popup DS senza riaprirli (vs alternanza tap/back di vai_in_home). Raccolta dovrebbe ora essere eseguita post-DS su tutte le istanze.

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert c6d9655
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU6 — 2026-04-25 09:46 CEST · DONAZIONE retry 3 scan + diagnostica score

- **Commit SHA**: `c0940ac`
- **File modificati**:
  - `tasks/donazione.py:171-200` — sostituito `break` al primo scan con loop retry max 3 con sleep 1s tra uno e l'altro. Aggiunto log dello score effettivo anche su fail.
- **Motivazione**: rate fail donazione 86% (38/44) troppo alto per pure game state. Pattern per istanza: FAU_00 100%, FAU_04/05 33%, tutti gli altri 0%. Sospetto timing/loading popup Technology. Codice aveva `max_marked_scan=10` ma `break` al primo scan non rispettato.
- **Comportamento atteso**: se vero pattern timing → fail rate scende sotto 50%. Se score=0 sempre → game state confermato (FAU_06 e altri non hanno tech marked, non bug). Diagnosi distinguibile da log: ora vediamo lo score effettivo.
- **Bot restart**: PID 7432 → PID 22176 (start 09:46:19).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert c0940ac
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU7 — 2026-04-25 10:07 CEST · velocità donazione + DS exit adattivo

- **Commit SHA**: `526499b`
- **File modificati**:
  - `tasks/donazione.py:54` — `wait_donate_tap: 1.5 → 0.8s` (velocità)
  - `tasks/district_showdown.py:1003-1014` (FORAY) — `vai_in_home()` → `_torna_a_mappa_ds(ctx, max_attempts=5)`
  - `tasks/district_showdown.py:1071-1090` (INFLUENCE post back 1+2) — `vai_in_home()` → `_torna_a_mappa_ds(ctx, max_attempts=5)` con fallback finale
- **Motivazione**: 
  - Fix 1: ogni tap donate richiedeva ~2s (1.5s sleep + 0.5s screenshot) → 30 tap in 60s. Con 0.8s ridotto a ~35s.
  - Fix 2: in step 2/3 quando pin_dado non era trovato il codice cadeva su `vai_in_home()` (8 tentativi tap/back) → spesso falliva → poi re-tap icona evento per rientrare. Round-trip HOME→evento di 25-40s. `_torna_a_mappa_ds` gestisce direttamente il check pin_dado nei primi tentativi.
- **Bot restart**: PID 22176 → PID 19460 (start 10:07:38).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 526499b
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU8 — 2026-04-25 10:38 CEST · INFL resta su mappa DS (no back 3)

- **Commit SHA**: `4e26849`
- **File modificati**:
  - `tasks/district_showdown.py:1098-1106` — rimosso blocco `back 3` + verifica HOME + `vai_in_home sicurezza` (era 25 righe, ora 6).
- **Trigger**: Monitor `b49acih7q` ha catturato in tempo reale il pattern `[DS-NAV] HOME rilevata (troppo back) — rientro tappando icona evento` su FAU_04 (10:20:18) e FAU_05 (10:36:16, 10:36:43).
- **Causa**: INFL terminava con `back x3` per uscire dalla pagina gioco → HOME. Poi ACHV chiamava `_torna_a_mappa_ds` che vedeva HOME e tappava icona evento per rientrare. Round-trip ~40s per ciclo DS.
- **Fix**: INFL ora termina sulla mappa DS dopo conferma `pin_dado`. ACHV gate readiness vedrà subito pin_dado e procederà direttamente. Uscita finale dalla mappa DS resta gestita dal `back x4` in `run()` (WU5).
- **Bot restart**: PID 19460 → PID 1224 (start 10:38:14).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 4e26849
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU9 — 2026-04-25 10:50 CEST · INFL back 2 rimosso, recovery adattivo gestisce

- **Commit SHA**: `2bd7360`
- **File modificati**:
  - `tasks/district_showdown.py:1063-1080` — rimosso `back 2` fisso + verifica pin_dado intermedia. Dopo `back 1` chiamato direttamente `_torna_a_mappa_ds(max_attempts=5)`.
- **Trigger**: Monitor real-time eventi 10:46:30, 10:46:33, 10:47:00 — pattern `pin_dado assente post-back → tent 0/1 HOME rilevata` persisteva post-WU8.
- **Causa identificata**: in molti game state back 1 chiudeva GIÀ Alliance Influence (game gestisce double back come single dismiss) → back 2 era one too many → finiva in HOME.
- **Fix**: dopo back 1, lascio decidere a `_torna_a_mappa_ds`:
  - pin_dado già visibile → tent 0 OK (back 1 sufficiente)
  - popup intermedio rimasto → back automatico
  - HOME (raro) → re-enter via icona evento
- **Bot restart**: PID 1224 → PID 21404 (start 10:50:42).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 2bd7360
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU10 — 2026-04-25 12:24 CEST · Banner HOME chiuso a startup (visibilità +45px)

- **Commit SHA**: `a17297f`
- **File modificati**:
  - `shared/ui_helpers.py` — nuova `comprimi_banner_home(ctx, log_fn)`: detect banner aperto/chiuso, tap (345,63), verifica chiusura
  - `main.py:617` — call `comprimi_banner_home` dopo `attendi_home` riuscito (try/except non blocca avvio)
  - `tasks/store.py` — rimosse 3 chiamate `_ripristina_banner` (banner resta chiuso permanentemente)
- **Motivazione**: banner eventi HOME (ROI 330-365 × 40-90) copriva ~45px del campo gioco. Solo store.py lo gestiva (collasso + ripristino). Ora chiuso una volta a startup → tutti i task (raccolta/rifornimento/donazione/DS) hanno maggiore zona visibile.
- **Comportamento**: a ogni avvio istanza dopo `attendi_home`:
  - Score banner aperto vs chiuso in ROI (330,40,365,90)
  - Se aperto: tap (345,63) → verifica chiusura
  - Se chiuso o sconosciuto: no-op
  - Idempotente, fallback gestito da `try/except`
- **Bot restart**: PID 21404 → PID 2924 (start 12:24:13).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert a17297f
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU11 — 2026-04-25 13:01 CEST · Donazione tap-burst 30 + verifica + ripeti

- **Commit SHA**: `c3a1d8d`
- **File modificati**:
  - `tasks/donazione.py:54-56` — config: `wait_donate_tap 0.8→0.25s`, nuovi `taps_per_block=30`, `max_blocks=5`
  - `tasks/donazione.py:60` — `max_donate_tap 30→150` (cap totale per esecuzione)
  - `tasks/donazione.py:_loop_donate` — refactor: outer loop su block, inner burst 30 tap rapidi senza screenshot tra uno e l'altro, screenshot+find_one solo a fine block
- **User trigger**: pin_marked riconosciuto correttamente sui cicli post-WU10. Richiesto burst rapido (30 click veloci → verifica → eventuali altri 30).
- **Strategia**: gioco registra il tap a 0.25s anche senza render completo del feedback UI. Screenshot+find_one solo dopo il burst (overhead concentrato).
- **Tempo**: 30 tap in ~7.5s (era ~42s) → **5.6× più veloce**
- **Capacità**: max 150 donate per esecuzione (era 30) → 5× capacità
- **Caso tipico (slot esauriti dopo 30)**: stop dopo 1 block (~8s vs 42s)
- **Bot restart**: PID 2924 → PID 11824 (start 13:01:25).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert c3a1d8d
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU12 — 2026-04-25 13:07 CEST · Rifornimento qta inviata reale (clamp + tassa)

- **Commit SHA**: `8d511dd`
- **File modificati**:
  - `tasks/rifornimento.py:104-110` — nuovo `OCR_CAMPO_INPUT` dict con zone OCR per ogni risorsa (pomodoro/legno/acciaio/petrolio), stima ±60x ±15y attorno al tap center `COORD_CAMPO`
  - `tasks/rifornimento.py:_compila_e_invia` — dopo `tap_OK_TASTIERA`, OCR del valore CLAMPED nel campo input + lettura `tassa` percentuale → `qta_effettiva = clamped × (1 - tassa)`. Fallback su `qta` originale se OCR fallisce.
- **User trigger**: input 999_999_999 viene auto-clampato dal gioco al massimo disponibile. Tassa (in rosso, lato sinistro maschera) viene sottratta dalla quantità clamped per ottenere il valore effettivo spedito al destinatario.
- **Beneficio**:
  - `storico_farm.json` mostra totali realistici (non più 999_999_999 fittizi)
  - Dashboard `/ui` mostra spedizioni reali
- **Robustezza**: fallback automatico se OCR fallisce (zone errate, render lento, etc.)
- **Note operative**: zone OCR sono stime. Validare al primo log `Rifornimento: input clamped=X tassa=Y% → effettiva=Z`. Se valore X anomalo → affinare coord.
- **Bot restart**: PID 11824 → PID 20704 (start 13:07:38).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert 8d511dd
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU13 — 2026-04-25 13:10 CEST · Alleanza max_rivendica 20 → 30

- **Commit SHA**: `f02f41a`
- **File modificati**:
  - `tasks/alleanza.py:30` — `max_rivendica: int = 20 → 30`
- **User trigger**: il task usciva dopo 20 claim, ma in alleanze attive ci possono essere >20 contributi da rivendicare (claim persi).
- **Comportamento**: il loop esce comunque appena `pin_claim` non è più rilevato (fine claim). Alzare il cap NON aumenta tempo sui casi normali — protegge solo extra (>20 claim).
- **Bot restart**: PID 20704 → PID 18812 (start 13:10:51).

#### Rollback singolo
```bash
cd /c/doomsday-engine
git revert f02f41a
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# kill bot + restart
```

### WU14 — 2026-04-25 14:00 CEST · Produzione oraria per istanza (4 step)

**Feature complessa user-designed: card per istanza con sessione corrente + precedente + storico 24h.**

#### Step 1 — Data model + snapshot avvio (commit `f1f7c7e`)
- `core/state.py`: `ProduzioneSession` dataclass + `InstanceState.produzione_corrente/storico`
- `chiudi_sessione_e_calcola()` con formula `delta_castle - zaino_delta + rifornimento` → produzione/h
- `apri_sessione()` su snapshot OCR
- `main.py`: dopo `comprimi_banner_home` → `ocr_risorse()` → chiudi/apri sessione

#### Step 2 — Hook tasks (commit `cd63631`)
- `tasks/rifornimento.py:_compila_e_invia` — `aggiungi_rifornimento(risorsa, qta_clamped, tassa)` + `provviste_residue`
- `tasks/raccolta.py:_esegui_marcia` (return success) — `incrementa_truppe(1)`
- `tasks/zaino.py:_esegui` — svuota → `aggiungi_zaino_delta(+delta)`, bag → `aggiungi_zaino_delta(-delta)`
- Tutti hook in `try/except` per non bloccare il task

#### Step 3+4 — Dashboard card (commit `a9a8f1b`)
- `dashboard/services/stats_reader.py`: `get_produzione_istanze()`
- `dashboard/app.py`: endpoint `/ui/partial/produzione-istanze` con card per istanza (risorse iniziali, inviato, tassa, zaino_delta, prod/h precedente)
- `dashboard/templates/index.html`: blocco `#prod-istanze` HTMX refresh 30s

#### Comportamento
- Bot legge risorse castello (top bar HOME/MAPPA via `ocr_risorse`) all'**avvio sessione** post-`attendi_home` + `comprimi_banner_home`
- Durante sessione: rifornimento, zaino, raccolta popolano cumulativi
- All'avvio sessione N+1: chiusura sessione N con risorse_finali + calcolo produzione/h
- Storico 24h FIFO (cleanup automatico)
- Card dashboard mostra header con truppe count, provviste, durata precedente, n storico 24h

#### Restart
- **Dashboard**: PID 800 → PID 21608 (ricaricata per nuovo endpoint)
- **Bot**: restart pianificato dal watcher `bash /tmp/restart_after_fau03.sh` PID 22655 → fire automatico quando FAU_03 termina e idle >30s → FAU_04 partirà con WU14 attivo

#### Rollback singolo (3 commit consecutivi)
```bash
cd /c/doomsday-engine
git revert a9a8f1b cd63631 f1f7c7e
git push origin main
cmd //c "C:\\doomsday-engine\\sync_prod.bat"
# restart bot + dashboard
```

---

### ISSUE — 2026-04-26 ~03:25-03:35 CEST · ADB screencap None post-ARENA

**Pattern sistemico** (FAU_02, FAU_03 entrambi nel ciclo notturno):
1. ARENA esegue sfide 2/3/4 con errore consecutivo (errore sfida X/2 consec.)
2. Bot esce con `[ARENA] ritorno HOME — doppio tap centro + BACK×4`
3. Da quel momento `device.screenshot()` ritorna None costantemente
4. ADB reconnect riporta "OK" ma screencap successivo è ancora None
5. Tutti i task successivi del ciclo skippati via `gate HOME FALLITO`

**Process state durante l'issue**: MuMu+adb+python tutti VIVI. ADB commands non timeout, ma screencap rotto.

**Ipotesi**: una transizione UI specifica nell'ARENA (forse animation/popup non chiuso) lascia il framebuffer in stato in cui `adb shell screencap` non produce output valido.

**Fix candidati** (per analisi diurna):
- WU3 reconnect esistente non basta — verificare se reconnect fa kill-server+start-server o solo `adb connect`
- Aggiungere step intermedio: `adb shell screencap /sdcard/test.png && adb pull` invece di pipe diretta
- Restart MuMu instance specifico via `MuMuManager` su soglia >5 None consecutivi
- Sentinel ARENA: se sfide=0 successo=False dopo N tentativi, considera istanza degradata e chiudi

**Stato notturno**: bot continua a girare, instances post-ARENA perse, FAU_03 idem. Aspetto FAU_04+ per vedere prevalenza.

---

### INCIDENT — 2026-04-25 21:06-21:14 CEST · watcher v4 restart loop

**14 bot uccisi in 8 minuti.** Causa: 2 bug nel watcher v4 (`/tmp/watcher_v4.sh`):
1. **Glob filter**: `ls FAU_*.jsonl` esclude `FauMorfeus.jsonl` (istanza raccolta_only). Watcher vedeva FAU_09 ultimo log e ignorava la nuova attività su FauMorfeus.
2. **Soglia troppo aggressiva**: 60s idle non distingue tra hang reale e sleep normale di 30 min tra cicli + cold start MuMu (~50s).

**Sequenza**:
- 20:22 — primo restart legittimo (fine ciclo FAU_09)
- 20:25 — bot in sleep 30 min (normale)
- 21:06 — sleep finisce, bot si avvia su FauMorfeus
- Watcher vede `FAU_09 idle 2717s` → kill
- Bot riavvia, prova FauMorfeus, idle FAU_09 cresce → kill
- Loop ×14 fino a kill manuale 21:15

**Mitigazione**: watcher killato manualmente, bot relanciato (PID 3004, 21:17). NIENTE watcher attivo per il resto della sessione autonoma — restart solo manuale. Modalità autonoma continua per fix bug runtime.

---

### WU20 — 2026-04-25 19:20 CEST · rientro DS comprimi_banner+retry

- **Commit SHA**: `098dfe0`
- **File**: `tasks/district_showdown.py` (1 hunk)
- **Sintomo**: 3 istanze (FAU_00/02/03) in 30 min post-Claim All ACHV → recovery → HOME → icona DS non trovata → abort → fallback vai_in_home. Incidenza ~12%.
- **Causa probabile**: post-back HOME mostra banner/popup transitorio che nasconde icona DS. `schermata_corrente()` ritorna HOME ma `roi_barra_eventi` non contiene il pin.
- **Fix**: prima dell'abort, prova `comprimi_banner_home` + 1s wait + re-screenshot + retry icon search. comprimi è idempotente. Se still not found → abort come prima.
- **Rollback**: `git revert 098dfe0`

---

### WU19 — 2026-04-25 17:05 CEST · bat NOPAUSE — no finestre cmd orfane

- **Commit SHA**: `3ef194b`
- **File**: `run_prod.bat`, `run_dashboard_prod.bat`
- **Sintomo**: 8 finestre cmd orfane accumulate in 8h. Ogni restart bot dal watcher lasciava la vecchia finestra in `pause`.
- **Causa**: bat finivano con `pause`. Watcher killava solo `python.exe`, non `cmd.exe` parent.
- **Fix**: `pause` → `if not "%NOPAUSE%"=="1" pause`. Manuale (double-click): pause attiva. Watcher: setta `NOPAUSE=1` → finestra auto-chiude.
- **Watcher v3**: `/tmp/restart_clean_wu18.sh` setta NOPAUSE=1 + kill anche cmd parent come ulteriore difesa.
- **Cleanup**: 8 cmd orfani (PID 13896, 21944, 16836, 9528, 18756, 22844, 6348, 8088) killati. Bot+dashboard live verificati post-kill.
- **Rollback**: `git revert 3ef194b`

---

### WU18 — 2026-04-25 16:55 CEST · donazione exit scan post-donate

- **Commit SHA**: `9655317`
- **File**: `tasks/donazione.py` (1 hunk)
- **Sintomo**: dopo donate completati Monitor flaggava 4× "pin_marked NON trovato (scan N) score=0.5xx" come error/inefficienza. Falsi positivi ricorrenti FAU_01/02/03.
- **Causa**: `_gestisci_popup` fa back×3 post-donate (Technology→Alliance→HOME), ma `_cerca_e_dona` scansionava pin_marked di nuovo. Su HOME pin_marked non esiste → 3 retry × 1s loggati come fallimenti. Solo `if n==0: break` presente.
- **Fix**: `break` sempre dopo `_gestisci_popup`, sia donate=0 (già HOME) sia donate>0 (slot esauriti, già HOME). Risparmio: 3s + 4 log/donazione.
- **Rollback**: `git revert 9655317`

---

### WU17 — 2026-04-25 16:42 CEST · ACHV poll pin_dado pre-recovery

- **Commit SHA**: `87b526b`
- **File**: `tasks/district_showdown.py` (1 hunk)
- **Sintomo**: FAU_01/FAU_02 post-Claim All ACHV → 2 back consecutivi → HOME → rientro icona. Costo ~6s/istanza × 12 = ~72s/ciclo.
- **Causa**: `delay_foray=7s` insufficiente per chiusura animata panel ACHV. Screenshot a tent 0 di `_torna_a_mappa_ds` durante animazione → pin_dado non visibile → back inutile.
- **Fix**: dopo `delay_foray`, poll attivo `pin_dado max_wait=5s, poll=0.5s, stable_polls=1`. Se compare → mappa raggiunta, return early. Se no → fallback `_torna_a_mappa_ds` invariato.
- **Rollback**: `git revert 87b526b`

---

## Convenzione commit

Ogni commit autonomo usa prefisso: `fix(auto-WU<n>): <descrizione>`

Filtrare tutti i commit autonomi:
```bash
git -C /c/doomsday-engine log --grep "auto-WU" --oneline
```
