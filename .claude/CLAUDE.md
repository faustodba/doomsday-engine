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

## Issues aperti (stato al 27/04/2026)

> **Nota**: la numerazione seguente è una tabella di tracking interno di CLAUDE.md
> e NON è perfettamente allineata alla numerazione della sezione "Issues aperti" di ROADMAP.md.
> Per issue dettagliate consultare sempre `ROADMAP.md` → "Issues aperti (priorità)".

| # | Issue | Priorità | Stato |
|---|-------|----------|-------|
| 1 | Rifornimento — da abilitare e testare | ALTA | ✅ RISOLTA 20/04 (DELAY UI + retry OCR), validata prod 11/11 istanze ciclo 20→21 |
| 3 | Zaino — deposito OCR | MEDIA | ⏳ in attesa |
| 5 | Alleanza — COORD hardcoded | BASSA | ⏳ in attesa |
| 9 | Raccolta — tipo NON selezionato FAU_01/FAU_02 | MEDIA | ✅ RISOLTA (fix flush frame cached + attendi_template) |
| 11 | Raccolta — Issue tipo NON selezionato FAU_01/FAU_02 | MEDIA | ⏳ parziale |
| 12 | Stabilizzazione HOME FAU_01/FAU_02 non converge | MEDIA | 🟡 mitigato (window 30→60s commit `9c1dfb4`) |
| 13 | Boost `gathered` non riconosciuto | MEDIA | ✅ RISOLTA 20/04 (`wait_after_tap_speed: 2.0s`) |
| 13-bis | ADB screenshot None cascata (FAU_03/04/06/07 ciclo 19/04) | ALTA | ✅ RISOLTA (F1a `624ba7a` + F1b `1d1b4eb`) |
| 14 | Arena START CHALLENGE non visibile (FAU_02/03/04/07/08 ciclo 20→21) | ALTA | 🆕 NUOVA 21/04 |
| 14-bis | Arena hang indefinito (FAU_10 ciclo 19/04 — kill manuale) | ALTA | ✅ RISOLTA (F2 timeout 300s `3c959cf`) |
| 15 | `engine_status.json` stale writer (fermo 03:51, log prosegue fino 05:51) | ALTA | 🆕 NUOVA 21/04 |
| 15-bis | Raccolta "No Squads" non rilevato (FAU_08) | MEDIA | ✅ RISOLTA (F3 `pin_no_squads` + uscita loop `701f7bd`) |
| 16 | OCR FAU_10 — valore "compila" scambiato per "reali" (legno=999M singola occorrenza) | MEDIA | 🆕 NUOVA 21/04 |
| 16-bis | `RACCOLTA_TRUPPE` non letto (FAU_09) | MEDIA | ✅ RISOLTA (`9ba08a0`) |
| 17 | Storico `engine_status.storico` filtrato — solo `raccolta`+`arena` | MEDIA | 🆕 NUOVA 21/04 |
| 17-bis | `InstanceState.save()` non atomica | MEDIA | ✅ RISOLTA (`a8ea422` tmp+fsync+os.replace) |
| 18 | Dashboard `/ui` mostra raw `global_config`, bot usa merged con overrides | MEDIA | ✅ RISOLTA 22/04 (get_merged_config — dashboard ora mostra valori reali bot) |
| 18-bis | `radar_tool/templates/` mancante (dev+prod) | BASSA | ⏳ workaround: radar_census saltato |
| 19 | Race buffer stdout ultima istanza a fine ciclo (cosmetico) | BASSA | ⏳ usare `python -u` o `sys.stdout.flush()` |
| 20 | Dashboard V6 rewrite (FastAPI+Jinja2+HTMX) | — | ✅ CHIUSA 20/04 — commit `9773de3` + `runtime.json` orfano eliminato |
| 21 | `gitignore` duplicato errato e `rifornimento_mappa.py` V5 legacy — da valutare eliminazione | BASSA | ⏳ prossima sessione |
| 22 | Dashboard `layout` istanze deprecato — rimosso dalla UI (bot usa TM) | BASSA | ✅ RISOLTA 22/04 |
| 23 | smoke_test GlobalConfig dict vs dataclass (pre-esistente) | BASSA | ⏳ prossima sessione |
| 24 | Raccolta No Squads — loop esterno + while interno + check universale (3-level break) | ALTA | ✅ RISOLTA 22/04 (FAU_09/10 da ~40 detection/tick a 1) |
| 25 | NameError MAX_TENTATIVI_CICLO scope fix (bug introdotto+risolto 22/04) | ALTA | ✅ RISOLTA 22/04 |
| 26 | Rifornimento distribuzione sbilanciata — soglia_campo_m 50→5 | MEDIA | ✅ RISOLTA 22/04 (pomodoro era sempre sotto soglia 50M) |
| 27 | Dashboard stats OCR anomali gonfiano totali (legno 1.1B vs 117M reali) | MEDIA | ✅ RISOLTA 22/04 (_MAX_QTA_SPEDIZIONE=100M filtro) |
| 28 | Emulator orfani dopo kill unclean del bot (MuMuPlayer resta aperto) | ALTA | ✅ RISOLTA 23/04 (_cleanup_tutti_emulator a startup + pre-ciclo) |
| 29 | Rifornimento ts_invio sottostimava ETA di ~20s | MEDIA | ✅ RISOLTA 23/04 (ts_invio DOPO _compila_e_invia) |
| 30 | raccolta_only non filtrava task: FauMorfeus tentava boost/vip/arena/... | ALTA | ✅ RISOLTA 23/04 (_thread_istanza filtra su tipologia) |
| 31 | TipologiaIstanza pydantic rifiutava raccolta_only → 500 su tutti i PATCH | ALTA | ✅ RISOLTA 23/04 (enum esteso raccolta_only) |
| 32 | toggle_task 422 con HTMX form-encoded | MEDIA | ✅ RISOLTA 23/04 (async body parser con content-type detection) |
| 33 | Allocazione dashboard in percentuali vs frazioni (UI mostrava 4000%) | MEDIA | ✅ RISOLTA 23/04 (get_merged_config normalizza) |
| 26 | Allocazione raccolta non collegata al bot (_RATIO_TARGET_DEFAULT hardcoded) | MEDIA | ✅ RISOLTA 23/04 (commit `424b440` — _from_raw normalize + ratio_cfg end-to-end) |
| 36 | Override null (livello/max_squadre/layout) causava int(None) TypeError | ALTA | ✅ RISOLTA 23/04 (commit `4afb14e` — _ovr None-safe + exclude_none save) |
| 37 | setModeRemote JS non definita (pill compound task-flags-v2 silent error) | MEDIA | ✅ RISOLTA 23/04 (commit `c9ced2a` — JS + 2 endpoint PATCH rifornimento-mode/zaino-mode) |
| 25 | Tracciamento diamanti nello state (OCR già letto ma non persistito) | BASSA | 🆕 NUOVA 23/04 |
| 34 | engine_status.json WinError 5 (collision os.replace con dashboard reader) | BASSA | ✅ RISOLTA 23/04 (retry backoff 0.1-0.5s × 5) |
| 35 | storico_farm.json tracciamento giornaliero per istanza | — | ✅ IMPLEMENTATA 23/04 (data/storico_farm.json, retention 90gg) |
| 38 | Dashboard leggeva config/state da dev invece di prod (config_manager non onorava DOOMSDAY_ROOT) | MEDIA | ✅ RISOLTA 23/04 (_PROD_ROOT in config_manager coerente con stats_reader) |
| 39 | Flag abilitata istanza applicato solo a fine ciclo (fino ~2h ritardo mid-cycle) | MEDIA | ✅ RISOLTA 23/04 (hot-check runtime_overrides prima di reset_istanza in main loop) |
| 40 | Flag rifornimento_mappa duplicato — sub-mode incoerente tra dashboard e bot | MEDIA | ✅ RISOLTA 23/04 (unica fonte rifornimento.mappa_abilitata; eliminato task.rifornimento_mappa) |
| 41 | Integrazione DonazioneTask nella dashboard (pill + toggle) | — | ✅ IMPLEMENTATA 23/04 (TaskFlags + valid_tasks + ORDER) |
| 42 | Donazione — ramo "pin_marked non trovato" non chiude Technology → raccolta salta | ALTA | ✅ RISOLTA 23/04 (back x3 nel branch pin_marked assente) |
| 43 | Integrazione DistrictShowdownTask nella dashboard + pipeline | — | ✅ IMPLEMENTATA 24/04 (TaskFlags + valid_tasks + ORDER + template + sync_prod) |
| 44 | DistrictShowdownTask — conformità V6 API (6 bug bloccanti) | ALTA | ✅ RISOLTA 24/04 (name metodo, task_abilitato, TaskResult.message, screen no .frame, zone, e_dovuto(ctx)) |
| 45 | DistrictShowdown — MatchResult sempre truthy, uso `.found` consistente | ALTA | ✅ RISOLTA 24/04 (10 check convertiti al pattern `.found`) |
| 46 | Launcher — am start OK ma gioco in background + polling troppo rapido | ALTA | ✅ RISOLTA 24/04 (monkey sempre + foreground check + monkey recovery + poll 7s) |
| 47 | DistrictShowdown — tap hardcoded su Start falliva quando popup shift | ALTA | ✅ RISOLTA 24/04 (tap dinamico su coord match + wait_template_ready adattivo) |
| 48 | DistrictShowdown — loop infinito quando gioco esce + skip animation | ALTA | ✅ RISOLTA 24/04 (early-exit 3 cicli streak + check skip 840,371) |
| 49 | Ottimizzazioni startup istanza (DELAY_POLL, stable_polls, delay_carica) | BASSA | 🆕 APERTA 24/04 — guadagno stimato ~90s/ciclo, rimandata post-stabilizzazione DS |
| 50 | DistrictShowdown — finestre temporali evento (Ven 00:00 → Lun 00:00 UTC, Fund Raid Dom 20:00 → Lun 00:00) | — | ✅ IMPLEMENTATA 24/04 (`_is_in_event_window` + `_is_in_fund_raid_window` in DistrictShowdownTask) |
| 51 | DistrictShowdown — gate readiness popup fase 3/4/5 (tap a vuoto su MuMu lento → blocco WARFARE) | ALTA | 🆕 APERTA 24/04 — proposta: `_wait_template_ready` analogo a pin_dado su sentinel di ogni popup (pin_alliance_influence / pin_achievement_rewards / pin_alliance_list / pin_vs_fund_raid) |
| 52 | Notte 26/04 — produzione_corrente null + stab HOME 88% timeout + ARENA→ADB cascade + FAU_07 deficit | MIX | 🟡 parziale — 52c risolto da #56 WU24; 52a/b/d aperti |
| 53 | Telemetria task & dashboard analytics — events JSONL + rollup + KPI | — | 🆕 APERTA 26/04 — MVP ~12h (memoria `project_telemetria_arch.md`) |
| 54 | Banner catalog & dismissal pipeline boot stabilization — 573 UNKNOWN polls | — | 🟡 parziale — framework + 3 banner attivi (exit_game_dialog, auto_collect_afk_banner, banner_eventi_laterale) |
| 55 | Store re-match fallback multi-candidate — swipe non-idempotente bordi mappa | ALTA | ✅ RISOLTA 26/04 (WU23 — multi-candidate sorted desc, cascade retry) |
| 56 | Cascata ADB persistente FAU_04 12 min sterile — reconnect cosmetico | ALTA | ✅ RISOLTA 26/04 (WU24 — `ADBUnhealthyError` + abort tick + chiudi istanza) |
| 57 | State save per task — fine-grained persistence (BoostState scadenza persa post-cascata FAU_04) | ALTA | ✅ RISOLTA 26/04 (WU25 — `orc.tick()` save dopo ogni task, `_state_dir()` env-based) |
| 58 | Rifornimento log netto/lordo/tassa — `inviato_oggi` lordo invece di netto | MEDIA | ✅ RISOLTA 26/04 (qta_clamped_real ritornato da `_compila_e_invia`, `registra_spedizione(qta_inviata=qta_effettiva)` netto) |
| 59 | Boost debug `_salva_debug_shot` 6 giorni attivo, 105MB accumulati | BASSA | ✅ RISOLTA 26/04 (chiamate commentate, screenshot eliminati prod+dev) |
| 60 | Foreground check falso positivo post-restart — penalità 43s/istanza × 12 (~9min/restart) | ALTA | ✅ RISOLTA 26/04 (`_gioco_in_foreground` usa `mCurrentFocus` invece di `pkg in dumpsys activity top`) |
| 61 | Discovery snapshot mancante post-dismiss banner / mid-tick UNKNOWN | MEDIA | ✅ RISOLTA 26/04 → SUPERSEDED da #63 (snapshot rimossi, sostituiti da tap X auto in memoria) |
| 62 | Riordino priorità task + chiusura raccolta (boost→riforn→raccolta→...→raccolta_chiusura) | MEDIA | ✅ RISOLTA 26/04 (RaccoltaChiusuraTask sottoclasse, priority 200; task_setup.json riordinato; filtro raccolta_only esteso) |
| 63 | Tap X auto-fallback per banner unmatched + no più screenshot su disco | MEDIA | ✅ RISOLTA 26/04 (`dismiss_banners_loop` tap (910,80) post-HOME-check; counter `_unmatched_tap_x` in dict ritorno; cartelle banner_unmatched/+vai_in_home_unknown/ rimosse) |
| 64 | Raccolta legge slot mentre rifornimento ancora in volo → slot OCR ridotti | MEDIA | ✅ RISOLTA 26/04 step 1 (`RifornimentoState.eta_rientro_ultima` ISO; raccolta wait sempre fino a rientro, cap safety 600s) |
| 65 | Wait > 60s rifornimento → anticipare task post-raccolta nel tempo morto | BASSA | 🆕 APERTA 26/04 step 2 — quando wait>60s, eseguire prima i task post-raccolta poi tornare a raccolta dopo verifica tempo trascorso |
| 66 | Banner unmatched: X cerchio dorato + freccia BACK ↩ via match dinamico (2 template) | MEDIA | ✅ RISOLTA 26/04 (`pin_btn_x_close.png` 45×50 cerchio dorato per popup eventi; `pin_btn_back_arrow.png` 45×55 freccia BACK per schermate nidificate Alliance/Hero/Bag; flow A1 X→A2 BACK→B HOME/MAP→C BREAK). Test: Pompeii X=1.000, Alliance BACK=1.000 |
| 68 | Stabilizzazione HOME: dismiss banners loop NON chiamato attivamente (149s avvio FAU_05 invece di ~30s) | ALTA | ✅ RISOLTA 26/04 (launcher.attendi_home invoca `_try_dismiss()` pre-stab + on-instability + pre-vai_in_home_finale; rimosso `_snap_post_home` write su disco) |
| 69 | Fase 4 attesa caricamento: polling HOME/MAP ogni 2s troppo aggressivo + classify instabile durante load | MEDIA | ✅ RISOLTA 26/04 (nuovo flow: post sleep 10s, check `is_loading_splash` → se attivo aggancio fino a scomparsa Live Chat ogni 3s, se assente exit subito; Live Chat invariante più affidabile di classify HOME/MAP fluttuante) |
| 71 | Store scan grid: continua tutti i 25 step anche con match >= 0.80 (~30-40s sprecati) | MEDIA | ✅ RISOLTA 26/04 (`soglia_store_early_exit=0.80`: scan interrotto al primo match alto, procede diretto al tap; multi-candidate fallback preservato per casi sotto early_exit) |
| 72 | Fase 4 #69 false negative su gioco in background — exit early ma 47s polling sterile | DA OSSERVARE | 🔍 26/04 osservato 1 volta su FAU_10 (19:36:39 "no Live Chat" exit ma gioco in background → 47s polling fino a monkey recovery 19:37:27 + Live Chat rilevato 19:37:31). HOME raggiunto 157s vs 110s atteso. Da monitorare se ricorre, eventuale fix con `_gioco_in_foreground` check pre-splash |
| 34 | Risorse netto/lordo/tassa schema (state + dashboard) | MEDIA | ✅ RISOLTA 27/04 (WU34 `RifornimentoState.inviato_lordo_oggi/tassa_oggi/tassa_pct_avg` + dashboard 6 row card + WU35 RISORSE FARM panel cleanup NETTO + WU36 CSS spacing) |
| 39 | OCR "Daily Receiving Limit" FauMorfeus + dashboard | MEDIA | ✅ RISOLTA 27/04 (WU39 commit `ef81639` — `OCR_DAILY_RECV_LIMIT` 547,146,666,173 + `shared/morfeus_state.py` storage globale + dashboard riga capienza con color coding) |
| 53 | Telemetria task & dashboard analytics — events JSONL + rollup + KPI | — | ✅ CHIUSA 27/04 (WU38-44 — pipeline 8/8 step, 9 commit `5153733`→`399eba0`, 19/19 test verdi). Vedi sezione "Sessione 27/04/2026" in ROADMAP.md |
| 54 | Banner catalog & dismissal pipeline boot stabilization | — | 🟡 parziale (estesa con `pin_btn_x_close` + `pin_btn_back_arrow` in WU26/66) |
| 46 | state.rifornimento azzerato post-restart bot — race con `_controlla_reset` | ALTA | ✅ MITIGATO 27/04 (WU45 commit `8b0091f` — dashboard fallback su `data/storico_farm.json` quando state vuoto). Issue root da indagare separatamente |
| 47 | Pannello dashboard 'produzione/ora' sempre vuoto — `metrics.*_per_ora` mai popolati | MEDIA | ✅ RISOLTA 27/04 (WU47 commit `aeaa6fb` — `chiudi_sessione_e_calcola()` propaga `prod_ora` a `metrics.aggiorna_risorse()` se durata≥300s) |
| 49 | Cicli persistenti su file dedicato + numerazione globale crescente | MEDIA | ✅ RISOLTA 27/04 (WU46 `41711bd` storage `data/telemetry/cicli.json` + hooks main.py + pannello dashboard `📚 storico cicli`. WU48 `6498d11` numerazione globale + run_id + auto-close stale `aborted=True`) |
| — | run_dashboard_prod.bat rotto (chiamava `dashboard_server.py` inesistente) | MEDIA | ✅ RISOLTA 27/04 (`eddefc6` corretto `uvicorn dashboard.app:app` + 7 modalità doc) |
| — | run_prod.bat senza commenti / modalità multiple | BASSA | ✅ RISOLTA 27/04 (`1a960c1` 9 modalità preconfigurate documentate, modalità #6 RIDOTTA RAM 4 istanze per memory pressure dev tools) |

> Aggiornare questa tabella ad ogni sessione insieme alla ROADMAP.

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
3. Aggiornamento ROADMAP (fix applicati, stato RT, issues aperti)
4. Aggiornamento tabella Issues aperti in CLAUDE.md se necessario
5. Aggiornamento SESSION.md con stato post-rilascio

---

## ROADMAP

- Aggiornare la ROADMAP a ogni sessione.
- Registrare: fix applicati, stato test runtime (RT-xx), issues aperti.
- La ROADMAP è la fonte di verità dello stato del progetto.

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
- Config: `C:\doomsday-engine\.claude\mcp_servers.json`
- Trasporto: stdio
- Python: `C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe`

### Avvio
Il server si avvia automaticamente quando Claude Code carica il progetto.
Non richiede avvio manuale.

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
