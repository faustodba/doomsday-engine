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

## Issues aperti (stato al 28/04/2026)

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
| 18-bis | `radar_tool/templates/` mancante (dev+prod) | BASSA | ✅ RISOLTA 28/04 (47 template copiati da V5 `C:/Bot-farm/radar_tool/templates/` a V6 dev+prod, smoke test `radar_tool/_smoke_test.py` OK: 12 icone rilevate su sample. RF classifier conf bassa <0.60 → fallback heuristic via nome template funzionante. Re-training RF rimandato — non bloccante per produzione) |
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
| 73 | Pannello tempi medi task con filtro outlier IQR | — | ✅ IMPLEMENTATA 28/04 (WU49 `7984478` — IQR Tukey k=1.5, esclude district_showdown, ordinamento desc per avg) |
| 74 | Raccolta fuori territorio per istanza (toggle dashboard) | — | ✅ IMPLEMENTATA 28/04 (WU50 `4012b70` flag `IstanzaOverride.raccolta_fuori_territorio`, WU52 `72f7b0e` sync su `instances.json`, `_nodo_in_territorio` ritorna True ⇒ no add a `BlacklistFuori`) |
| 75 | Modalità manutenzione bot — file flag + dashboard toggle | — | ✅ IMPLEMENTATA 28/04 (WU51 `2f1b9ea` `core/maintenance.py` + `data/maintenance.flag` + endpoint `/api/maintenance/{start,stop,status}` + auto-resume) |
| 76 | Istanze disabilitate read-only nella tabella | BASSA | ✅ RISOLTA 28/04 (WU52 `72f7b0e` `disabled_attr` su input/select riga quando `abilitata=False`, evita modifiche accidentali a istanze offline) |
| 77 | Detect popup MAINTENANCE gioco (auto-pause + OCR ETA) | ALTA | ✅ IMPLEMENTATA 28/04 (WU53 `c9f543f` skip istanza, WU54 `fcdad78`+`55d62c7` template `pin_game_maintenance_refresh/discord`, OCR countdown `(598,348,699,373)`, hook 3 punti `attendi_home`, `enable_maintenance_with_auto_resume(eta+30s)`). Verifica end-to-end pendente — popup sparito durante test |
| 78 | Data collection OCR slot HOME vs MAPPA — training AI agent | — | 🟡 IN CORSO 28/04 (WU55 `2c470ab` + WU55-bis `d451b8f` shadow OCR MAP in `_reset_to_mappa`. Modulo `shared/ocr_dataset.py`, hook 4 punti raccolta.py, toggle `/api/raccolta-ocr-debug/*`. Soglia spawn agente: 30+ pair complete; al restart 28/04 11:08 = 16 pair, 2 complete; ETA 1 ciclo) |
| 79 | Pannello produzione/ora storico 12h con sparkline | — | ✅ IMPLEMENTATA 28/04 (WU56 `39fdfcf`+`0490b18`+`a767201` layout 2-righe sparkline ASCII 14px + avg/min/max space-between, `get_produzione_storico_24h(hours=12)`, filter min>0) |
| 80 | RaccoltaFastTask — variante fast via tipologia istanza | — | ✅ IMPLEMENTATA 28/04 (WU57 `55d2e61` nuovo `tasks/raccolta_fast.py` 440 righe, delay -33%/-47% su tap_icona/CERCA, recovery 1-shot, switch via `tipologia=raccolta_fast` con runtime swap RaccoltaTask→RaccoltaFastTask in main.py preservando priority 15/interval/schedule e tutti gli altri task attivi) |
| — | UI rename tipologie istanza + colonna FT | BASSA | ✅ RISOLTA 28/04 (`27fd5d2` labels `completo`/`completo · fast`/`solo raccolta`, riordino opzioni, header colonna `⛯`→`FT`) |
| 81 | Update Version popup gioco — detect + gestione | ALTA | 🆕 APERTA 28/04 — pulsante "Update Version" + icona triangolo arancione "Up" appare in HOME riga eventi superiore quando client gioco ha nuova versione. Zona ~520-590, 40-95. Proposta: template `pin_update_version.png` + hook `attendi_home`, decisione skip istanza/alert dashboard/auto-pause se >=80% istanze. Pattern affine a #77 MAINTENANCE ma livello client. APK update richiede interazione utente (sideload/store) — bot non può autonomamente |
| 83 | Arena `_TAP_ULTIMA_SFIDA` cieco — freeze su righe "Watch" | ALTA | 🆕 APERTA 28/04 sera — coordinata fissa `(745,482)` in arena.py:58 V5 config. Tappa la "ultima riga" della lista 5 sfide indipendentemente dal pulsante (Challenge vs Watch). Su istanze con sfide già fatte oggi (post-reset state), l'ultima riga è "Watch" → entra in replay → screenshot ADB falliscono → cascade abort. **Conferma**: FAU_00 vergine 5/5 OK; FAU_01/10 con 1 sfida fatta stamattina freeze. Fix: match dinamico template `pin_btn_challenge_lista` invece di pixel fisso. Effort ~30 righe |
| 84 | Bug orchestrator: `entry.last_run` aggiornato anche su fail/abort | ALTA | 🆕 APERTA 28/04 sera — `core/orchestrator.py:316` setta `last_run=time.time()` SEMPRE dopo `task.run()` indipendentemente da `result.success`. Risultato: arena fallita 13/13 stamattina → `last_run` aggiornato → `e_dovuto_daily=False` → arena non riprova fino reset 01:00 UTC giorno dopo. Reset manuale state ha sbloccato 28/04 19:15. Fix: `if result.success or result.skipped: entry.last_run = time.time()`. Effort 2 righe + restart |
| — | Bot in modalità raccolta-only (28/04 19:45) | — | ⏸️ Tutti i task disabilitati da dashboard tranne `raccolta` (always) + `radar_census`. Modalità sicura mentre si indaga issue arena #83/#84. Ri-abilitare task uno alla volta dopo fix |
| — | Notte 28→29/04 maintenance mode 6h49m (motivo "aggiornamento") | — | ⚠️ Utente attiva manualmente maintenance da dashboard alle 22:56 28/04 (per aggiornare software MuMu) e dimentica di disattivarla. Bot in pausa fino kill+restart 05:46 29/04. 0 spedizioni rifornimento notturne |
| 58 | Dashboard mostra dati daily stale dopo pausa lunga | MEDIA | ✅ RISOLTA 29/04 (WU58 — `dashboard/services/stats_reader.py` 3 fix: `get_state_per_istanza`, `get_risorse_farm`, `_load_morfeus_state`. Check `data_riferimento != today_utc` → azzera in-memory totali daily + provviste residue + capienza morfeus. State file NON toccato — bot lo azzera al primo tick rifornimento) |
| 59 | Pannello "📚 storico cicli" colonna DATA | BASSA | ✅ RISOLTA 29/04 (WU59 — `CicloStorico.start_date` DD/MM UTC + colonna in tabella) |
| 60 | Settings lightweight client gioco (Graphics/Frame/Optimize LOW) | ALTA | ✅ IMPLEMENTATA 29/04 + INTEGRATA in launcher (WU60+WU61 — `core/settings_helper.py` `imposta_settings_lightweight(ctx)` 8 step Avatar→Settings→System→Graphics LOW→Frame LOW→check Optimize visuale→[tap se non attivo]→3 BACK. Hook in `core/launcher.py::attendi_home` post-`vai_in_home()` finale, try/except con lazy import. Coord calibrate via getevent FAU_01. Toggle stateful Optimize via template `pin_settings_optimize_low_active.png` ROI 108-198×317-357 soglia 0.70. Delay maggiorati PC lento NAV=3.0/TOGGLE=2.0/PRE_CHECK=1.5/BACK=2.0 ~22s totali) |
| — | Test FAU_03 reinstallato — settings + arena 5/5 OK 159.6s 31.9s/sfida | — | ✅ 29/04 13:19 (WU61 `c:\tmp\test_fau03_settings_arena.py`, pattern identico FAU_02). Issue #85 Glory NON validato (popup assente in entrambi gli hook PRE+post-Arena) |
| 87 | Audit debug PNG su disco + cleanup | MEDIA | ✅ RISOLTA 29/04 (WU63). 6 punti scrittura PNG identificati: 1 disabilitato (`raccolta_ocr_debug` toggle off in prod runtime_overrides), 1 mantenuto (`boot_unknown` discovery), 1 già off (boost commentato), 3 attivi solo su anomalia. Cleanup file accumulati: data/ocr_dataset 2040 file 445MB + debug_task/screenshots 1 file + debug_task/vai_in_home_unknown 3 file → **~448 MB liberati**. boot_unknown/ mantenuto (11 file 9MB). Hot-reload toggle al prossimo tick — niente restart richiesto |
| 86 | Nuovo task TRUPPE — addestramento automatico 4 caserme (Fanteria/Cavalleria/Arcieri/Macchine) | — | ✅ IMPLEMENTATA 29/04 (WU62 `tasks/truppe.py`). Tutte coord FISSE: pannello (30,247) → cerchio Train (564,382) → TRAIN giallo (794,471). Checkbox Fast Training SEMPRE OFF (R-mean box>110=ON, soglia 110). OCR counter X/4 cascade otsu→binary su zona (12,264,30,282) per coprire X=0 (otsu lo perde). 4 PIN estratti (pannello/train_btn/check_on/check_off) ma NON usati dal MVP. Flow: leggi X, se X==4 skip, altrimenti loop (4-X) cicli con delay 5s/step. Test reale FAU_05 4 cicli 0/4→4/4 OK, 4 tipi caserme tutte gestite con stesse coord. **Priority 18 periodic 4h** (subito dopo RaccoltaTask=15, prima di DonazioneTask=20: i primi 3 sono sempre Boost→Rifornimento→Raccolta), integrato in task_setup.json + main.py + TaskFlags + valid_tasks + pill UI dashboard (Row 3 con arena) |
| — | Pulizia + reinstallazione istanze MuMu (29/04 pomeriggio) | — | 🛠️ IN CORSO 29/04 — utente sta reinstallando le istanze MuMu (cascata ADB persistente FAU_02/03/04 durante test arena, FAU_00 stabile). Bot in pausa. Post-pulizia: validare ADB stabile + test settings lightweight + integrazione launcher + ri-test arena |
| 82 | Test arena standalone su FAU_02 reinstallato — 5/5 sfide OK 156s | — | ✅ 29/04 12:40 (`c:\tmp\test_fau02_arena_only.py` — coord fisse senza pin check, race cond #83 non riprodotta su istanza pulita). Pattern fragile, da non promuovere a prod senza match dinamico |
| 85 | Template `pin_arena_07_glory.png` ROI troppo piccola — match impossibile | ALTA | ✅ RISOLTA 29/04 sera (template attuale 225×35, ROI era 190×48 → cv2.matchTemplate impossibile (template>image). Fix `(380,410,570,458)→(345,405,615,465)` 270×60 in `tasks/arena.py::_ARENA_PIN["glory"]`. Match ora feasibile, popup tier-up Continue intercettabile) |
| WU64 | Pulizia cache giornaliera 1×/die in fase settings | — | ✅ IMPLEMENTATA 29/04 sera (state `data/cache_state.json`, hook in `core/settings_helper.imposta_settings_lightweight` post-BACK1, polling CLOSE template `pin_clear_cache_close.png` ogni 5s max 120s. Coord calibrate FAU_10: Help (570,235), Clear cache (666,375), Clear icon (480,200), CLOSE (480,445). Runtime FAU_10/FAU_00 c4: CLOSE detected dopo 6s, ~22s totale fix. Skip-on-already-done idempotente intra-day) |
| WU65 | Lettura giornaliera Total Squads + storico crescita | — | ✅ IMPLEMENTATA 29/04 sera (`core/troops_reader.py`, hook in `attendi_home` post-settings. OCR `_ZONA_TOTAL_SQUADS=(830,60,945,90)` cascade otsu→binary. Storage `data/storico_truppe.json` retention 365gg, atomic write, idempotenza intra-day. Runtime: FAU_10=112,848, FAU_00=2,665,764 registrati c4) |
| WU66 | Dashboard truppe — card istanza + storico 8gg | — | ✅ IMPLEMENTATA 29/04 sera (Layout A riga 🪖 + Δ7gg + sparkline ASCII 7-char in card produzione istanze; Layout B endpoint `/ui/partial/truppe-storico` + section index.html con tabella ordinata Δ% desc + riga TOTALE; HTMX refresh 60s. Funzioni `get_truppe_istanza`, `get_truppe_storico_aggregato` in stats_reader) |
| WU67 | Raccolta livello — reset+conta sostituito con delta diretto | MEDIA | ✅ RISOLTA 29/04 sera (era SEMPRE 7 meno + N piu = 7..13 tap. Ora delta = livello - livello_panel, |delta| tap nella direzione. Saving 1.5-2s/raccolta × ~100/die × 11 istanze ≈ ~25-35min/die totali. Mantiene reset classico se OCR pannello fallisce) |
| WU68 | Sanity OCR slot post-marcia — fallback HOME se sospetto | MEDIA | ✅ RISOLTA 29/04 sera (in `_aggiorna_slot_in_mappa`: se `attive_map < attive_pre` (deterministico, bot ha appena confermato +1 squadra) → fallback HOME singolo. Cattura caso patologico `5/5 letti come 4/5` opposto del 4↔7 cross-validation esistente. Costo 13-15s solo nel ~2-3% sospetto) |
| WU69 | Pattern slot pieni — 2× maschera_not_opened → break loop | MEDIA | ✅ RISOLTA 29/04 sera (flag `ctx._raccolta_mask_not_opened` settato in `_esegui_marcia` quando maschera retry fallisce. Counter `mask_not_opened_streak` in `_loop_invio_marce`. >=2 fallimenti consecutivi su tipi diversi → `ctx._raccolta_slot_pieni=True` + break. Saving 60-90s per ciclo patologico) |
| WU70 | OCR slot SX-only ensemble — risolve bug "5→7" | ALTA | ✅ RISOLTA 29/04 sera (proposta utente: tagliare "/" e cifra DX, leggere SOLO SX in ROI 10×24 isolata. Branch primario in `leggi_contatore_slot` quando `totale_noto>0`: 3 PSM 10/8/7 ensemble + sanity pre-vote `0≤v≤totale_noto` + majority vote. Totale=config deterministico. Validazione FAU_00 c6: pre-fix=0 inviate skip, post-fix=1 inviata pulita) |
| WU71 | Stabilizzazione HOME — polling 3s → 1s | BASSA | ✅ RISOLTA 29/04 sera (in `core/launcher.attendi_home` polling stable_count, sleep 3.0→1.0. Saving 5×2 = 10s/istanza × 11 = ~110s/ciclo. Trade-off 3× CPU screenshot+match al secondo durante stab. Attivo al prossimo restart spontaneo) |
| WU72 | Dashboard storico cicli — UTC raw vs locale (disallineamento card istanza + date sbagliate a cavallo mezzanotte UTC) | MEDIA | ✅ RISOLTA 30/04 notte (in `dashboard/services/telemetry_reader.get_storico_cicli`: helper `_ts_to_local_hhmm` + `_ts_to_local_date` convertono ISO UTC in ora locale via `datetime.fromisoformat().astimezone()`. Pre-fix: ciclo iniziato 22:58 UTC mostrato come `29/04 22:58` mentre card FAU_00 mostrava 01:02 locale. Post-fix: `30/04 00:58` coerente con card. Dashboard restartata) |
| WU73 | Dashboard storico truppe — ordinamento per indice istanza | BASSA | ✅ RISOLTA 30/04 notte (in `get_truppe_storico_aggregato`: sort key cambiato da `delta_pct desc` a `r["nome"]` alfabetico → FAU_00, FAU_01, ..., FAU_10, FauMorfeus. Più intuitivo per debug per-istanza) |
| WU74 | Arena skip checkbox — verifica solo 1×/sessione → check ad ogni sfida | ALTA | ✅ RISOLTA 30/04 mattina (in `tasks/arena.py:387` rimosso flag `run.skip_verificato`. **Root cause**: pulizia cache giornaliera WU64 reset checkbox skip al default + template `pin_arena_check.png` falso positivo su skip OFF reale (ROI identica a `pin_arena_no_check`). Su FAU_05 30/04: cache pulita 02:52 → arena 03:57 con `Skip già attivo` (false positive) → 5/5 battaglie timeout 60s. Post-fix: `_assicura_skip()` ad ogni sfida, costo +7.5s/ciclo, beneficio elimination timeout sistematico. Effetto collaterale: WU64 cache cleanup era il trigger ma il problema vero era logica skip in arena.py) |
| WU75 | Arena `_attendi_fine_battaglia` — polling 17 screenshot → sleep+1check | ALTA | ✅ RISOLTA 30/04 mattina (in `tasks/arena.py:528` refactor da `while polling ogni 3.5s` a `time.sleep(60s) + 1 screenshot final`. **Root cause**: 17 screencap consecutivi durante battaglia + 8 nella transizione post-Continue saturavano socket ADB di MuMu già stressato dalle animazioni 3D battle → cascade ADB su 8/11 istanze 30/04 (FAU_00, 01, 03, 04, 06, 07, 08, 10) con 6-17 screenshot falliti dopo battaglia. Pattern: la 1ª cascade scattava su `lista`/`purchase`/`challenge` template — durante transizione tra sfide, NON durante battaglia stessa. Saving: ~94% screencap durante battaglia (17→1). Trade-off: timeout 60s comunque rispettato, ma se skip è OFF reale battaglia >60s e check final fallisce — uguale a comportamento pre-fix per timeout) |
| WU76 | Screenshot pipeline in-memory (exec-out) — porting V5 v5.24 → V6 | ALTA | ✅ RISOLTA 30/04 mattina (refactor `_screenshot_raw` da screencap+pull (3 op disco) a exec-out (0 op). Saving I/O significativo per TUTTI i task. **Però NON risolve cascade arena**: test live FAU_10 30/04 09:36 → tap START CHALLENGE causa ADB offline ISTANTANEO, prima di qualsiasi screencap. WU76 utile come fix architetturale, cascade arena ha causa più profonda) |
| 88 | Cascade ADB durante arena — driver Vulkan MuMu | ALTA | ✅ RISOLTA 30/04 10:00 — test diagnostico approfondito su FAU_10: WU75 (no polling) + WU76 (no I/O) NON eliminavano cascade, ADB offline immediato al tap START CHALLENGE. Settings video LOW vs HIGH stesso esito. **Root cause vera**: driver **Vulkan** di MuMu Player crasha il bridge ADB su animazione 3D battle. **Soluzione**: switch driver da Vulkan a **DirectX** (manuale utente in MuMu Settings → Display). Test post-switch con monitor ADB ogni 0.5s: 271/271 polling ONLINE, 0 OFFLINE su 3 sfide consecutive (10:00-10:04). DA APPLICARE A TUTTE LE 11 ISTANZE MuMu (config manuale o batch script) |
| 89 | Template arena Failure/Continue/Victory stale — UI client ridisegnata | ALTA | 🟡 PARZIALE 30/04 10:10 (WU77) — con cascade ADB risolto da Issue #88, finalmente possibile vedere il post-battle: client gioco ha ridisegnato UI. **Failure**: era "Failure" arancione/viola in (414,94,544,146); ora "Failure" bianco grande su sfondo magenta in (380,42,535,88). **Continue**: era "Tap to Continue" pulsante in (410,443,547,487); ora testo corsivo in (380,503,535,530). **Victory**: ancora da catturare. WU77 sostituiti template + ROI per Failure (155×46 score 0.998) e Continue (155×27 score 0.996), validato runtime su 3 sfide FAU_10. Tap coord _TAP_CONTINUE_VICTORY/FAILURE entrambi (457,515) per nuovo design unificato. Victory rimane vecchio template per ora — sarà aggiornato quando capita Victory naturale |
| WU77 | Arena nuovi template Failure + Continue + ROI | ALTA | ✅ IMPLEMENTATA 30/04 10:10 (vedi Issue #89) |
| WU78 | Settings_helper bypass tap Graphics/Frame/Optimize | MEDIA | ✅ IMPLEMENTATA 30/04 10:11 — driver Vulkan→DirectX (Issue #88) elimina la necessità di settings video ULTRA-LOW. Bot rimuoveva manualmente HIGH/MID/HIGH dell'utente ad ogni avvio. Pre-fix: tap Graphics LOW + Frame LOW + Optimize check + tap. Post-fix: skip totale tap, mantenuta nav verso SETTINGS panel per cache cleaning (WU64) che richiede di essere lì |
| WU79 | Issue #84 orchestrator last_run aggiornato anche su fail | ALTA | ✅ RISOLTA 30/04 10:14 — in `core/orchestrator.py:316`: `entry.last_run = time.time()` veniva aggiornato SEMPRE (anche su result.success=False o eccezioni), bloccando retry fino al reset daily 24h dopo. Esempio FAU_00 30/04: arena fallita per cascade → last_run aggiornato → arena non ritenta fino al 01/05 02:35 UTC, perde 5 sfide/die. Fix: `if result.success or result.skipped: entry.last_run = time.time()`. Su fail → last_run invariato → retry al prossimo tick |
| WU80 | Arena tap dinamico Continue (loc match invece coord fisse) | ALTA | ✅ RISOLTA 30/04 10:25 — in `tasks/arena.py` post-battaglia: match dinamico template `pin_arena_05_continue.png` → `tap(cont_result.cx, cont_result.cy)`. Pre-fix: coord fisse `_TAP_CONTINUE_VICTORY`/`_FAILURE` (457,515). Live test FAU_00: Victory continue centro (457,469); FAU_01 Failure continue centro (457,516). Delta 47 pixel — coord fisse non sufficienti. Fallback su coord fissa solo se match fallisce |
| WU81 | Arena soglia victory/failure 0.80→0.90 (anti-falso positivo) | ALTA | ✅ RISOLTA 30/04 10:45 — su Failure il template `victory` matchava 0.847 (font/dimensioni simili) → falso positivo, bot avrebbe interpretato Failure come Victory. Live test FAU_00 sfida 2 Failure: victory=0.847, failure=0.995. Soglia 0.90 → Victory non scatta su Failure. Validato FAU_01: victory=0.591, failure=0.999 |
| WU82 | Arena wait battaglia 60s → 15s (DirectX skip ON veloce) | MEDIA | ✅ RISOLTA 30/04 11:30 — `_DELAY_BATTAGLIA_S=8→5` + `_MAX_BATTAGLIA_S=52→10`. Battaglie con skip ON + driver DirectX durano <10s. Saving 45s/sfida × 5 = 225s/ciclo arena (~3.75 min) |
| WU83 | Arena rebuild truppe pre-1ª sfida (1×/die UTC per istanza) | MEDIA | ✅ RISOLTA 30/04 12:25 — prima di tap START CHALLENGE alla 1ª sfida del giorno, rimuove tutte le N truppe schierate (coord 80,80/148/216/283/351) e ricarica via tap cella + READY (auto-deploy migliore composizione). Test live FAU_06 4 celle: power 431k → 685k (+59% truppe nuove). State `data/arena_deploy_state.json` granularità giornaliera UTC. N celle da `max_squadre` config (FAU_00/FauMorfeus=5, altre=4). 5ª cella lucchettata su FAU_06 ignorata silenziosamente. Costo +25-30s solo 1×/die |
| 88 | Cascade ADB durante arena — driver Vulkan MuMu | ALTA | ✅ RISOLTA 30/04 10:00 — bug noto MuMu driver Vulkan crash su animazione 3D battle. Test live FAU_10 con Vulkan: ADB offline immediato al tap START. Switch a **DirectX** → 5 sfide consecutive (FAU_00+FAU_01+FAU_10) totale 593/593 polling ADB ONLINE 0 OFFLINE. Manuale utente per ogni istanza MuMu in Settings → Display → Render mode |
| 89 | Template arena Failure/Victory/Continue stale — UI ridisegnata | ALTA | ✅ RISOLTA 30/04 10:42 — con cascade Issue #88 risolto, finalmente possibile vedere il post-battle. Client gioco ha ridisegnato UI: nuovi template estratti live FAU_00/FAU_10. **Failure**: bianco grande su sfondo magenta (380,42,535,88) score 0.998. **Victory**: bianco grande su sfondo dorato (380,42,535,88) score 1.000 (estratto FAU_00 30/04 10:42 rank 81→53). **Continue**: testo "Tap to Continue" corsivo bianco (380,503,535,530) score 0.996. ROI estese a (370,35,545,95) per tutti |

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
