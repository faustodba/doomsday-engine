# CLAUDE.md — Doomsday Engine V6

> File letto automaticamente da Claude Code all'avvio della sessione.
> Definisce regole operative, architetturali e di interazione vincolanti.

---

## Startup

All'inizio di ogni sessione, in questo ordine:
1. Leggere la ROADMAP locale: `C:\doomsday-engine\ROADMAP.md`
2. Leggere il file di handoff: `C:\doomsday-engine\.claude\SESSION.md`
3. Verificare la versione locale dei file coinvolti prima di operare.
4. Se la versione locale non è allineata alla ROADMAP → chiedere prima di procedere.
5. Non operare mai su versioni non allineate.
6. Riferire all'utente: obiettivo sessione, stato attuale, prossimo step.

> La ROADMAP locale è la fonte di verità del progetto.
> SESSION.md è il ponte di contesto tra sessione browser e sessione VS Code.

---

## Repo e percorsi

| Repo | Percorso locale |
|------|----------------|
| `faustodba/doomsday-engine` (V6) | `C:\doomsday-engine` |
| `faustodba/doomsday-bot-farm` (V5, produzione) | `C:\Bot-farm` |

---

## Regole di codice

- **Mai frammenti.** Rilasciare sempre file completi, coerenti, eseguibili.
- Prima di scrivere qualsiasi primitiva V6, leggere il file V5 corrispondente.
  Zone OCR, coordinate UI, template names, logica di parsing sono già calibrati in V5.
- Ogni modifica deve essere compatibile con V5 (verifica regressione).
  Se serve un componente V5 → richiederlo esplicitamente.

---

## Standard architetturale V6 (vincolante)

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` |
| Navigator | `ctx.navigator.vai_in_home()` | `await ctx.navigator...` |
| Barra inferiore | `ctx.navigator.tap_barra(ctx, "voce")` | coordinate fisse Campaign/Alliance/etc. |
| Template matching | `matcher.find_one()`, `matcher.score()` | `matcher.match()`, `matcher.find()` |
| Screenshot frame | `screen.frame` | `device.last_frame` |
| Device costruttore | `AdbDevice(host=H, port=P, name=N)` | `AdbDevice(porta_int)` |

---

## Regole speciali per task

- **RaccoltaTask** non ha schedulazione: deve essere eseguito per ogni istanza
  a patto che ci siano slot liberi. Non aggiungere mai `interval` o `schedule`.
- Il contatore slot squadre X/Y è leggibile via OCR sia da HOME che da MAPPA.
  Non assumere mai che si legga solo in mappa.
- **Lettura iniziale slot OCR** deve essere fatta in HOME (più stabile di MAPPA
  dove banner/animazioni causano falsi positivi).
- **Sanity check OCR slot**: se `attive > totale_noto` → OCR sicuramente sbagliato
  (es. "5" letto come "7"). Fallback conservativo: assumere slot pieni, skip.
- **BlacklistFuori territorio** è GLOBALE (file `data/blacklist_fuori_globale.json`
  condiviso tra tutte le istanze — stessa mappa di gioco). Non reintrodurre mai
  file per istanza come `blacklist_fuori_FAU_XX.json`.
- **Logica raccolta — gestione fallimenti**:
  - CERCA fallita (tipo NON selezionato) = `tipo_bloccato=True` → blocca tipo, NON incrementa fallimenti_cons
  - Skip neutro (nodo in blacklist) = dopo 2 skip neutri consecutivi sullo stesso tipo → blocca tipo
  - Fallimento puro (marcia fallita) = incrementa fallimenti_cons, torna HOME, rilegge slot
  - Se slot pieni in qualsiasi momento → uscita immediata dal loop
  - Loop esterno: max 3 tentativi ciclo raccolta; rilettura slot tra tentativi
- **reset_istanza()**: chiamare sempre all'inizio di ogni ciclo prima di `avvia_istanza()`.
  Garantisce stato pulito indipendentemente da crash/interruzioni precedenti.
- **Stabilizzazione HOME**: dopo `attendi_home()`, la HOME deve essere stabile per
  3 poll consecutivi da 5s (15s di stabilità) prima di avviare il tick.
  Timeout 30s: se non converge, procede comunque con `vai_in_home()` finale.
- **REGOLA DELAY UI (vincolante)**: dopo ogni `ctx.device.tap()` che apre un
  popup, overlay o pannello, usare `time.sleep(2.0)` minimo prima di
  `ctx.device.screenshot()` o `matcher.find_one()`. Delay insufficiente causa
  score template matching basso o OCR su schermata non ancora renderizzata.
  Derivato da bug rifornimento: `sleep(0.3)` → score `0.387`, `sleep(2.0)` →
  score `0.934`.

---

## Regole bat di rilascio

- Usare **path assoluti espliciti** per i file sorgente nei `.bat`.
- Vietato: `%~dp0`, `%USERNAME%\Downloads` o path relativi.
- Il bat deve dichiarare una variabile `FILE_DIR` configurabile in cima al file,
  con istruzione chiara per l'utente, oppure copiare i file direttamente
  in `C:\doomsday-engine` prima dell'esecuzione.

---

## Issues — stato sintetico

> Lo **storico completo** delle voci WU/issue (222 voci) è stato spostato in
> [`docs/issues/`](../docs/issues/README.md), **diviso per tematica** (riorg 07/06/2026).
> Qui restano solo gli **issue aperti/parziali**. Per i dettagli di una voce risolta,
> cercare l'ID (es. `WU143`) nel file tematico corrispondente.

### 🔓 Aperti / parziali

| Tema | # | Issue | Priorità | Stato |
|------|---|-------|----------|-------|
| infra-startup | 12 | Stabilizzazione HOME FAU_01/FAU_02 non converge | MEDIA | 🟡 mitigato (window 30→60s commit `9c1dfb4`) |
| infra-startup | 49 | Ottimizzazioni startup istanza (DELAY_POLL, stable_polls, delay_carica) | BASSA | 🆕 APERTA 24/04 — guadagno stimato ~90s/ciclo, rimandata post-stabilizzazione DS |
| arena-combat | 51 | DistrictShowdown — gate readiness popup fase 3/4/5 (tap a vuoto su MuMu lento → blocco WARFARE) | BASSA | 🆕 APERTA 24/04 (downgrade ALTA→BASSA 04/05) — proposta: `_wait_template_ready` analogo a pin_dado su sentinel di ogni popup (pin_alliance_influence / pin_achievement_rewards / pin_alliance_list / pin_vs_fund_raid). Non bloccante: DS è disabilitato dal flag dashboard (WU108) finché evento non utile o stabilizzazione MuMu |
| arena-combat | 52 | Notte 26/04 — produzione_corrente null + stab HOME 88% timeout + ARENA→ADB cascade + FAU_07 deficit | MIX | 🟡 parziale — 52c risolto da #56 WU24; 52a/b/d aperti |
| telemetria-predictor | 53 | Telemetria task & dashboard analytics — events JSONL + rollup + KPI | — | 🆕 APERTA 26/04 — MVP ~12h (memoria `project_telemetria_arch.md`) |
| ocr-vision | 54 | Banner catalog & dismissal pipeline boot stabilization — 573 UNKNOWN polls | — | 🟡 parziale — framework + 3 banner attivi (exit_game_dialog, auto_collect_afk_banner, banner_eventi_laterale) |
| rifornimento-zaino | 65 | Wait > 60s rifornimento → anticipare task post-raccolta nel tempo morto | BASSA | 🆕 APERTA 26/04 step 2 — quando wait>60s, eseguire prima i task post-raccolta poi tornare a raccolta dopo verifica tempo trascorso |
| rifornimento-zaino | WU163 | Rifornimento — match pin rifugio falso positivo via soglia retry permissiva | MEDIA | 🔍 23/06 IN OSSERVAZIONE — FAU_10/FAU_05 0 spedizioni per tap su elemento sbagliato (435,174), score retry borderline 0.59-0.60. Debug attivato + dump mirato `suspect`/`fail` in `data/rifornimento_debug/`. Ipotesi utente: icone evento sulla mappa. Dettagli in `docs/issues/rifornimento-zaino.md` |
| infra-startup | 72 | Fase 4 #69 false negative su gioco in background — exit early ma 47s polling sterile | DA OSSERVARE | 🔍 26/04 osservato 1 volta su FAU_10 (19:36:39 "no Live Chat" exit ma gioco in background → 47s polling fino a monkey recovery 19:37:27 + Live Chat rilevato 19:37:31). HOME raggiunto 157s vs 110s atteso. Da monitorare se ricorre, eventuale fix con `_gioco_in_foreground` check pre-splash |
| ocr-vision | 54 | Banner catalog & dismissal pipeline boot stabilization | — | 🟡 parziale (estesa con `pin_btn_x_close` + `pin_btn_back_arrow` in WU26/66) |
| notifiche-alert | 81 | Update Version popup gioco — detect + gestione | BASSA | 🆕 APERTA 28/04 (downgrade ALTA→BASSA 04/05) — pulsante "Update Version" + icona triangolo arancione "Up" appare in HOME riga eventi superiore quando client gioco ha nuova versione. Zona ~520-590, 40-95. Proposta: template `pin_update_version.png` + hook `attendi_home`, decisione skip istanza/alert dashboard/auto-pause se >=80% istanze. Pattern affine a #77 MAINTENANCE ma livello client. APK update richiede interazione utente (sideload/store) — bot non può autonomamente. Non bloccante finché non ricorre |
| radar | — | Bot in modalità raccolta-only (28/04 19:45) | — | ⏸️ Tutti i task disabilitati da dashboard tranne `raccolta` (always) + `radar_census`. Modalità sicura mentre si indaga issue arena #83/#84. Ri-abilitare task uno alla volta dopo fix |
| rifornimento-zaino | — | Notte 28→29/04 maintenance mode 6h49m (motivo "aggiornamento") | — | ⚠️ Utente attiva manualmente maintenance da dashboard alle 22:56 28/04 (per aggiornare software MuMu) e dimentica di disattivarla. Bot in pausa fino kill+restart 05:46 29/04. 0 spedizioni rifornimento notturne |
| arena-combat | — | Pulizia + reinstallazione istanze MuMu (29/04 pomeriggio) | — | 🛠️ IN CORSO 29/04 — utente sta reinstallando le istanze MuMu (cascata ADB persistente FAU_02/03/04 durante test arena, FAU_00 stabile). Bot in pausa. Post-pulizia: validare ADB stabile + test settings lightweight + integrazione launcher + ri-test arena |
| arena-combat | 89 | Template arena Failure/Continue/Victory stale — UI client ridisegnata | ALTA | 🟡 PARZIALE 30/04 10:10 (WU77) — con cascade ADB risolto da Issue #88, finalmente possibile vedere il post-battle: client gioco ha ridisegnato UI. **Failure**: era "Failure" arancione/viola in (414,94,544,146); ora "Failure" bianco grande su sfondo magenta in (380,42,535,88). **Continue**: era "Tap to Continue" pulsante in (410,443,547,487); ora testo corsivo in (380,503,535,530). **Victory**: ancora da catturare. WU77 sostituiti template + ROI per Failure (155×46 score 0.998) e Continue (155×27 score 0.996), validato runtime su 3 sfide FAU_10. Tap coord _TAP_CONTINUE_VICTORY/FAILURE entrambi (457,515) per nuovo design unificato. Victory rimane vecchio template per ora — sarà aggiornato quando capita Victory naturale |
| raccolta | — | Modalità raccolta_fast estesa a tutte le istanze (06/05 pomeriggio) | — | 🟡 In corso 06/05 — utente attiva `tipologia=raccolta_fast` su tutte le istanze ordinarie + monitor attivo + debug screenshot toggle ON (`globali.debug_tasks.raccolta_fast=True`). Analisi costi/benefici dopo 1-2 cicli completi: confronto `sec_per_marcia` fast vs standard, ratio successo, `marce_fallite`, `recovery_count`. Telemetria `task=raccolta_fast` distinta da `raccolta` standard, `output.fast=True` campo dedicato. |
| raccolta | WU199 | report_raccolta — lettura Gathering Report per produzione/ora precisa | MEDIA | 🟡 FASE 2 STABILE IN PROD dall'11/07/2026 (validata 12/12 istanze `delete_ok: True`, zero anomalie). Piano 3 fasi: (1) reset ✅, (2) lettura+storage+scroll ✅ — include fix critico WU199nonies (tab sbagliato, mai più senza verifica OCR positiva pre-azione distruttiva) e redesign fine-lista WU199duodecies (fermo scroll same-run invece di dedup storico globale), (3) sostituzione algoritmo produzione — non iniziata, ma il dataset è già in uso da WU200 (stimatore tempo raccolta, `docs/issues/telemetria-predictor.md`) e ne è la base per il futuro ricalcolo produzione. Dettagli completi in `docs/issues/raccolta.md` |
| telemetria-predictor | WU200 | Stimatore tempo raccolta empirico + pannello dashboard `/ui/report-raccolta` | MEDIA | ✅ IN PROD dall'11-12/07/2026. `shared/tempo_raccolta_estimator.py` riconcilia invio↔completamento per (istanza,tipo,livello), loop dashboard 15min. Collegato in sola osservazione all'adaptive scheduler (WU200ter, zero regressione). Pannello di validazione `/ui/report-raccolta` con 6 sezioni incluse produzione unificata per istanza/farm. Seconda finalità confermata 12/07: base per futuro calcolo produzione svincolato da anomalie castello (zaino svuota, rifornimento). Dettagli in `docs/issues/telemetria-predictor.md` + memoria `project_tempo_raccolta_estimator.md` |
| telemetria-predictor | WU202/WU223 | Cutover predictor — T_marcia da misura empirica (Fase B→C completata) | MEDIA | ✅ CHIUSA 15/07. Fase B (12/07): `_calc_t_marcia_min` tiered flag-gated. **WU223 (15/07)**: fallback cross-istanza in `stima_tempo_raccolta` (pool `(tipo,livello)` dalle ordinarie escl. FAU_00) → copertura empirica 88%→~100%, chiusi i 6 buchi statici (campo/L7, acciaio/L6). **Fase C (15/07)**: statico ELIMINATO — rimossi `_calc_t_marcia_static`, tabella `predictor_t_l_max`, flag `tempo_raccolta_empirico_enabled`, `core/t_marcia_calibration.py`, campo osservativo `confronto_tempo_raccolta`, tool backtest empirico. Empirico ora permanente; ultima spiaggia = costante farm `_FALLBACK_RACCOLTA_MIN=168min`. Toggle dashboard → badge "permanente". Test riscritti (6/6). Commit `7834aeb`+`f3ce078`. Piano in `docs/issues/predictor-cutover-plan.md` |
| infra-startup | WU201 | Cluster boot-timeout 300s — 8/11 istanze in ~2h la mattina 12/07 | MEDIA | 🟡 MITIGATO 12/07/2026 — `timeout_carica_s` 300→400s (dynamic). Causa sistemica non diagnosticata (sospetto rallentamento host, nessuna telemetria host-level). Evento visibile SOLO in `bot.log`, invisibile a log JSONL per-istanza/telemetria eventi/`cicli.json` (che marca il boot fallito come `esito: "ok"` — bug di tracciamento noto, non corretto). Dettagli in `docs/issues/infra-startup.md` |
| radar | WU158 | Anagrafe avatar membri alleanza — POC validato 99% accuracy | — | 🟡 POC IMPLEMENTATO 12/05 (script standalone `c:/tmp/test_anagrafe_*.py`), **integrazione bot pending**. **Obiettivo**: banca dati visiva di tutti gli avatar (~103 per HE-DAWN) navigando Alliance→Members→R4/R3/R2/R1 con scroll incrementale + dedup pHash. Usabile dal task radar per match avatar sulla mappa (identificare membri propria alleanza vs esterni). **Calibrazione per sezione (960×540)**: R4 (3 col box60 stride77 1frame), R3 (2 col box60 stride68 scroll 204px = 3 stride), R2/R1 (2 col box52 stride65 scroll 130px = 2 stride). Y_TL anchored al badge della sezione corrente + offset calibrato (R4+38, R3+32, R2+37, R1+37). **Slow_drag** duration 1500 ms = scroll lineare 1:1 (no momentum). **OCR contatori** (ROI x=780-860 escluso icona people, Otsu PSM7) → atteso pre-scansione (R4=8/8, R3=17, R2=30, R1=48). **Stop dinamico**: detect badge sezione successiva (sc≥0.85) → leggi TUTTE righe valide entro screen + STOP (no filtro margine, il pHash dedup gestisce overlap). R1 (ultima): backup `no_new ≥ 3`. **Filtro avatar**: edge density Canny > 0.08 AND grayscale std > 25 (discrimina avatar da testo/bg vuoto). **Dedup**: pHash 64-bit DCT-based + Hamming distance ≤ 6 (avatar default visivamente identici uniti in 1 entry). **Validazione**: FAU_05 = 104/103 (99% — 1 falso positivo R2), FAU_04 = 102/103 (con drift). **Trigger design**: flag `globali.radar_anagrafe_pending` autocancellante (pattern come "riavvia bot ciclo"), bottone UI manuale. Prima istanza ordinaria che vede flag ON lo esegue (FauMorfeus master escluso). **Memoria dettagliata**: `project_anagrafe_membri.md`. **Pending**: integrazione `shared/avatar_registry.py` + `tasks/radar_anagrafe.py` + endpoint + UI + match runtime in `radar_actions.py`. |

> Aggiornare `docs/issues/` + questo riassunto ad ogni sessione (vedi sezione Rilasci).

---

## Protocollo SESSION.md

SESSION.md è il file di handoff tra sessione browser (claude.ai) e sessione
VS Code (Claude Code). Va aggiornato ad ogni passaggio di contesto.

### Regole
- Leggere sempre SESSION.md all'avvio prima di qualsiasi operazione.
- Dopo ogni step completato: aggiornare "Risultato ultima operazione" e "Prossimo step".
- Dopo ogni sessione VS Code: aggiornare "Stato attuale" con un riassunto.
- SESSION.md NON va in git (è in .gitignore).

### Passaggio browser → VS Code
L'utente dirà: `"Leggi SESSION.md e dimmi dove eravamo rimasti."`
Rispondere con: obiettivo, stato attuale, prossimo step — senza chiedere altro.

### Passaggio VS Code → browser
L'utente incollerà il risultato della sessione VS Code nel browser.
Aggiornare SESSION.md con il nuovo stato prima di procedere.

---

## Esecuzione

- Scomporre ogni processo in step semplici.
- Procedere step-by-step: un passo alla volta, non anticipare.
- Nessuna modifica complessa senza validazione intermedia.

---

## Interazione

- Chiedere feedback a ogni fase rilevante.
- Attendere conferma prima di ogni step critico.
- Non procedere in autonomia su operazioni distruttive o ambigue.

---

## Rilasci (batch)

Ogni rilascio segue questa sequenza:
1. Copia del file in `C:\doomsday-engine\<path>\`
2. Commit + push su `faustodba/doomsday-engine`
3. Aggiornare `ROADMAP.md` (sezione sessione corrente in testa) + `docs/changelog/ROADMAP-storico.md`
   se serve trasferire dettaglio cronologico
4. Aggiungere la voce WU nel file tematico `docs/issues/<tema>.md` (Risolti) e, se è un issue
   nuovo/aperto, aggiornare il riassunto "Issues — stato sintetico" in questo CLAUDE.md
5. Aggiornamento SESSION.md con stato post-rilascio

---

## Struttura documentazione (riorg 07/06/2026)

| File | Ruolo |
|------|-------|
| `.claude/CLAUDE.md` | Regole operative + standard V6 + riassunto **issue aperti** (questo file) |
| `ROADMAP.md` | Vista **corrente + strutturale** (sessione in corso, stato pytest/RT, indice) |
| `docs/issues/<tema>.md` | Storico WU/issue **per tematica** (verbatim) — fonte di verità issue |
| `docs/changelog/ROADMAP-storico.md` | Storico cronologico ROADMAP (sessioni, "Fix applicati") |
| `.claude/SESSION.md` | Handoff: ultime 3 sessioni (resto in `SESSION-storico.md`, locale) |
| `docs/OVERVIEW.md`, `docs/reference.html`, `docs/TELEGRAM_BOT_ARCHITECTURE.md` | Architettura & reference |

- Aggiornare `ROADMAP.md` (testa) + `docs/issues/` ad ogni sessione.
- Lo **stato issue per tematica** in `docs/issues/` è la fonte di verità; CLAUDE.md ne tiene
  solo il sottoinsieme aperto.

---

## Miglioramenti

- Proporre ottimizzazioni tecniche/architetturali a fine sessione o quando rilevate.
- Le proposte non bloccano il lavoro corrente — vanno documentate come issue o note.

---

## Coerenza

- Garantire coerenza semantica, architetturale e di stile tra tutti i moduli.
- Seguire pattern e convenzioni esistenti (nomi, firme, struttura classi).
- Evitare l'introduzione di nuovi pattern senza esplicita approvazione.

---

## Regole anti-disallineamento (vincolanti)

- `_TASK_SETUP` in `main.py` è la fonte di verità per priorità e scheduling
- La tabella "_TASK_SETUP" in `ROADMAP.md` deve essere identica a `main.py`
- Ogni modifica a `_TASK_SETUP` deve aggiornare `ROADMAP.md` nella stessa sessione
- Prima di ogni sessione: verificare allineamento `_TASK_SETUP` ↔ `ROADMAP.md`
- `schedule_type "always"` → `interval=0.0`. Task always: `RifornimentoTask`, `RaccoltaTask` (il guard `should_run()` interno decide se eseguire in base a pre-condizioni)
- Priorità: numero più basso = eseguito prima nel tick

---

## Modalità esecuzione

- Architettura: SEQUENZIALE — una istanza alla volta, mai parallele
- Ciclo: FAU_00 → FAU_01 → FAU_02 → sleep 30min → ripeti
- `_thread_istanza` esegue UN SOLO tick per chiamata (no while loop interno)
- Parallelismo multi-istanza rimandato a quando implementato max_parallel
- Interferenze ADB/MuMu in parallelo documentate in Issue #9 e #10

---

## Note ambiente

### MuMu Player — avvio automatico
- Windows 10: MuMuManager può avviare istanze senza che MuMuPlayer sia aperto
- Windows 11: MuMuPlayer deve essere già avviato prima di chiamare avvia_istanza()
- In produzione (Windows 11): aggiungere avvio automatico MuMuPlayer.exe
  prima del loop istanze in main.py, oppure richiedere avvio manuale preliminare
- TODO: verificare se MuMuManager espone un comando per avviare il player stesso

---

## MCP Monitor

Il progetto include un MCP server locale per analisi log in tempo reale.

### Configurazione
- Server: `C:\doomsday-engine\monitor\mcp_server.py`
- Config: `C:\doomsday-engine\.mcp.json` (formato corretto Claude Code)
- Trasporto: stdio
- Python: `py -3.14` (Python Launcher Windows, risolve a Python 3.14.x)
- DOOMSDAY_ROOT puntato a prod: `C:\doomsday-engine-prod`

### Avvio
Il server si avvia automaticamente quando Claude Code carica il progetto
(richiede riavvio di Claude Code dopo la creazione di `.mcp.json`).
Il file `.claude\mcp_servers.json` era nel formato sbagliato ed è ignorato.

### Strumenti disponibili
| Tool | Parametri | Descrizione |
|------|-----------|-------------|
| `ciclo_stato` | — | Summary completo ultimo ciclo tutte le istanze |
| `anomalie_live` | — | Anomalie ultimi 10 minuti tutte le istanze |
| `istanza_anomalie` | nome, n_righe=200 | Anomalie ultime N righe istanza |
| `istanza_raccolta` | nome | Statistiche raccolta ultimo tick |
| `istanza_launcher` | nome | Stato launcher ultimo avvio |
| `log_tail` | nome, n=50 | Ultime N righe log istanza |

### Pattern anomalie rilevati
- ERROR: FALLITO, vai_in_mappa fallito, avvia_istanza() fallito,
  impossibile andare in mappa, abort sequenza livelli, screenshot None
- WARN: NON selezionato, stabilizzazione timeout, HOME instabile,
  troppi fallimenti, timeout battaglia

### Regola operativa
Durante ogni sessione di test attivo, interrogare `anomalie_live`
ogni 5 minuti per rilevare problemi in tempo reale senza
attendere la fine del ciclo.

---

## Regola generale

> Approccio strutturato, verificabile, tracciabile.
> Ogni scelta deve essere giustificabile e reversibile.
