# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

---

## Stato step pytest

| Step | File principali | Test | Note |
|------|----------------|------|------|
| 1-10 | `core/`, `shared/`, `config/` | ✅ | Infrastruttura base |
| 11 | `tasks/boost.py` | ✅ 35/35 | |
| 12 | `tasks/store.py` | ✅ 39/39 | VIP Store + mercante diretto |
| 13 | `tasks/messaggi.py` | ✅ 27/27 | |
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
| **nav** | `core/navigator.py` | ✅ 20/20 | tap_barra() TM barra inferiore |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Piano test runtime — Stato al 16/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01..05 | Infrastruttura, navigator, OCR, slot | ✅ | |
| RT-06 | VIP claim | ✅ | |
| RT-07 | Boost | ✅ | BoostState scheduling intelligente 16/04/2026 |
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

---

## Issues aperti (priorità)

### 1. Rifornimento — da mettere a punto (ALTA)
- **Stato:** fix applicati 14/04/2026 — pronto per test runtime RT-16.
- **Fix applicati:**
  - `_apri_resource_supply()`: `find()` → `find_one()` (API V6)
  - `run()`: deposito letto via OCR in mappa se non iniettato (come V5)
  - `_compila_e_invia()`: aggiunta verifica nome destinatario (come V5)
  - Navigazione HOME/MAPPA: `ctx.navigator.vai_in_home/mappa()` con fallback key
- **Prerequisiti test:**
  - Creare `runtime.json` con `DOOMS_ACCOUNT` e `RIFORNIMENTO_MAPPA_ABILITATO: true`
  - FAU_00 deve avere slot liberi e risorse sopra soglia

### 2. Arena — timeout battaglia (MEDIA)
- **Problema:** sfide 2 e 4 timeout — battaglia ancora in corso (animazioni > 38s).
- **Fix:** aumentare `_MAX_BATTAGLIA_S` da 30s a 52s (delay 8s + poll = 60s totali).
- **TODO pin mancanti:**
  - `pin_arena_video.png` — popup video introduttivo primo accesso
  - `pin_arena_categoria.png` — popup categoria settimanale (lunedì)

### 3. Zaino — deposito OCR (CHIUSA ✅ 14/04/2026)
- **Fix applicato:** `_leggi_deposito_ocr()` legge autonomamente via `ocr_risorse()`.
- **RT-20 ✅ 15/04/2026:** Architettura TM-based completa. Scan inventario via pin catalogo + greedy ottimale + esecuzione. Fix ADB timeout (device.py 20/30s). Fix KEYCODE_CTRL_A+DEL campo qty. Caution popup gestito. Test legno 20.9M e acciaio (gap 2M) confermati.

### 4. Radar Census — falso positivo zona UI (BASSA)
- **Problema:** bottone "Complete All" (basso-sx) riconosciuto come icona radar (`sconosciuto 0%`)
- **Fix:** restringere `RADAR_MAPPA_ZONA` da `(0,100,860,460)` escludendo angolo `~(0,400,150,460)`
- **Priorità:** dopo raccolta campioni aggiuntivi

### 5. Alleanza — tap_barra (BASSA)
- `COORD_ALLEANZA=(760,505)` ancora hardcoded.
- **Fix:** sostituire con `ctx.navigator.tap_barra(ctx, "alliance")` come
  fatto per Campaign in arena.py e arena_mercato.py.

### 6. Store NMS cross-template (BASSA)
- `pin_acciaio.png` = `pin_pomodoro.png` (stesso file) → stesso cx,cy.
  Risolvibile quando sarà disponibile il vero `pin_acciaio.png`.

### 7. Alleanza — swipe perde click durante claim (BASSA)
- Alcuni claim consecutivi atterrano sulla stessa coordinata
- Causa probabile: scroll lista non attende stabilizzazione UI
- Fix: aggiungere wait_stabilize dopo swipe in `_loop_claim()`

### 8. Radar — tap iniziale apre maschera laterale invece di icona radar (ALTA)
- Primo tap su pin_radar apre una maschera UI laterale inattesa
- Task va in loop e si blocca dopo 3 tentativi
- Causa probabile: coordinate tap_icona `(78,315)` non allineate
  o icona radar coperta da elemento UI
- Fix: verificare coordinate in screenshot reale + aggiungere
  dismiss maschera laterale prima del retry

---

---

## Fix applicati in sessione 17/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| attendi_home() loop BACK | `core/launcher.py` | Loop BACK+polling invece di sequenza rigida — gestisce banner multipli |
| chiudi_istanza() post-tick | `main.py` | Chiusura MuMu dopo ogni tick, non solo a Ctrl+C |
| _TASK_SETUP priorità | `main.py` | Riallineamento completo a ROADMAP — erano completamente invertite |
| Regole anti-disallineamento | `.claude/CLAUDE.md` | Sezione vincolante: _TASK_SETUP ↔ ROADMAP sempre allineati |

---

## Fix applicati in sessione 16/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| BoostState | `core/state.py` | Nuova classe: tipo, attivato_il, scadenza, disponibile. should_run() centralizzato. registra_attivo(tipo, now) / registra_non_disponibile(). Integrata in InstanceState |
| VipState | `core/state.py` | Nuova classe: cass_ritirata, free_ritirato, data_riferimento. should_run()=False se entrambe ritirate. segna_cass/free/completato(). Reset mezzanotte UTC |
| ArenaState | `core/state.py` | Nuova classe: esaurite, data_riferimento. should_run()=False se sfide esaurite. segna_esaurite(). Reset mezzanotte UTC |
| Boost scheduling | `tasks/boost.py` | should_run(): flag abilitazione + BoostState.should_run(). GIA_ATTIVO→registra "8h"; ATTIVATO_8H/1D→registra tipo; NESSUN_BOOST→registra_non_disponibile() |
| VipTask always-run | `tasks/vip.py` | should_run(): flag abilitazione + VipState.should_run(). run() aggiorna segna_cass/free dopo ogni esito |
| ArenaTask always-run | `tasks/arena.py` | should_run(): flag abilitazione + ArenaState.should_run(). run() chiama segna_esaurite() quando pin_arena_06_purchase rilevato |
| Gate should_run() | `core/orchestrator.py` | tick() chiama should_run() come gate dopo e_dovuto() e prima del gate HOME. Flag abilitazione + guard stato ora effettivi in produzione |
| _TASK_SETUP riordino | `main.py` | Nuovo ordine priorità: Raccolta ultima (110), Rifornimento penultima (100). interval=0.0 per Boost/Vip/Arena/Rifornimento/Raccolta (always-run con guard). Messaggi/Alleanza/Store→4h. ArenaMercato/Radar/RadarCensus→12h |
| Architettura documentata | `ROADMAP.md` | Catena di comando 5 livelli: Config→Scheduling→should_run()→HOME gate→run() |
| Pytest 258/258 | `tests/unit/` + `tests/tasks/` | Aggiornati test_state, test_orchestrator, test_boost, test_vip, test_arena, test_rifornimento. FakeMatcher.find_one, FakeNavigator, FakeState con BoostState/VipState, _MatchResult, gate should_run stub |
| core/launcher.py | NUOVO | Avvio/chiusura istanze MuMu: avvia_istanza(), attendi_home(), chiudi_istanza(). Path e timeout da global_config.json |
| config/config_loader.py | MumuConfig | Nuova dataclass per sezione mumu. GlobalConfig.mumu esposto |
| global_config.json | sezione mumu | Path MuMuManager, ADB, timeout avvio istanza |
| main.py | _thread_istanza() | Integrazione launcher: avvia_istanza() + attendi_home() pre-tick, chiudi_istanza() post-tick |
| core/launcher.py | fix path | nx_main\ aggiunto a tutti i candidati MuMuManager |
| core/launcher.py | fix Screen.UNKNOWN | Confronto enum corretto invece di stringa |
| `shared/ocr_helpers.py` | fix OCR mappa | fallback thresh_130 quando maschera_bianca < 15px. Risolve sovrastima slot in mappa |
| `tasks/rifornimento.py` | fix BUG-1 workaround | vai_in_home() prima di leggi_contatore_slot() nelle iterazioni successive |
| `tasks/raccolta.py` | fix rollback | vai_in_home() + leggi_contatore_slot() dopo ogni marcia fallita — riallinea attive_correnti con stato reale |
| `tasks/arena.py` | fix HOME | vai_in_home() post-BACK al termine sfide |

---

## Fix applicati in sessione 15/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Zaino TM-based | `tasks/zaino.py` | Architettura FASE1(scan TM)+FASE2(greedy)+FASE3(esecuzione). Eliminato bug icone_viste |
| Zaino svuota validata | `tasks/zaino.py` | Modalità svuota: sidebar+USE MAX testata su FAU_00. RT-20 chiuso |
| Raccolta upgrade V5 | `tasks/raccolta.py` | Step 1-6: OCR coord X_Y, ETA marcia, livello nodo, blacklist statica fuori territorio, interleaving sequenza, BlacklistFuori disco |
| Raccolta fix slot OCR | `shared/ocr_helpers.py` | psm=6 scale=2 maschera_bianca — calibrato con calibra_slot_ocr.py (6183/29400 combinazioni corrette) |
| Raccolta pin_return | `templates/pin/pin_return.png` | pin pulsante recall Squad Summary (futuro uso) |
| Tool calibrazione OCR | `calibra_slot_ocr.py` | Testa 29400 combinazioni parametri Tesseract su screenshot reale |
| device.py timeout | `core/device.py` | _run/_shell 15s→20s, screencap/pull 15s→30s |
| Raccolta upgrade V5 | `tasks/raccolta.py` | Step 1: OCR coord reali X_Y; Step 2: OCR ETA; Step 3: contatore post-marcia; Step 4: fuori territorio→blacklist; Step 5: livello nodo OCR; Step 6: BlacklistFuori su disco |
| Zaino pin catalogo | `templates/pin/` | pin_pom/leg/acc/pet tutte pezzature (26 file) + pin_caution.png |
| Zaino caution popup | `tasks/zaino.py` | `_gestisci_caution()` — tap check+OK, flag sessione, una volta per sessione |
| Zaino campo qty | `tasks/zaino.py` | KEYCODE_CTRL_A+DEL prima di input_text — azzera valore default=1 |
| Zaino _wait_ui_stabile | `tasks/zaino.py` | Polling diff pixel post-swipe — sostituisce sleep fisso, fix ADB timeout |
| ADB timeout | `core/device.py` | `_run/_shell` 15s→20s, screencap/pull 15s→30s |

---

## Fix applicati in sessione 14/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Zaino OCR deposito | `tasks/zaino.py` | `_leggi_deposito_ocr()` autonomo via `ocr_risorse()` + tap args fix + swipe |
| Zaino v5 modalità BAG | `tasks/zaino.py` | scan griglia BAG + OCR pannello destra + input qty + MAX se n==owned |
| Zaino v5 modalità SVUOTA | `tasks/zaino.py` | svuota completamente zaino da HOME senza controllo soglie |
| Zaino ZAINO_MODALITA | `config/config_loader.py` | nuova chiave "bag"\|"svuota" in GlobalConfig + _InstanceCfg |
| test_bag_ocr.py | `test_bag_ocr.py` | script calibrazione OCR pannello BAG (coordinate reali 14/04) |
| Radar coord V5 | `radar.py` | TAP_RADAR_ICONA (90,460)→(78,315), tutti parametri allineati V5 |
| Radar log | `radar.py` | logger.* → ctx.log_msg() — log visibile in run_task |
| RadarCensus V6 | `tasks/radar_census.py` | traduzione completa V5→V6: ctx.device, ctx.log_msg, Path da __file__ |
| radar_tool integrato | `radar_tool/` | copia fisica da Bot-farm → doomsday-engine |
| global_config census | `config/global_config.json` | radar_census: true per test |
| Config centralizzata Step A | `config/global_config.json` + `config/config_loader.py` | unica fonte verità, `load_global()`, `build_instance_cfg()` |
| Config centralizzata Step B | `main.py` + `run_task.py` | rimossa `_Cfg` hardcodata, usa `config_loader` |
| Rifornimento OCR deposito | `tasks/rifornimento.py` | `_leggi_deposito_ocr` usa `ocr_helpers.ocr_risorse()` |
| Rifornimento _vai_abilitato | `tasks/rifornimento.py` | usa `screen.frame` BGR invece di `Image.open(path)` |
| Rifornimento OCR maschera | `tasks/rifornimento.py` | `_leggi_provviste/tassa/eta` delegano a `rifornimento_base.*()` |
| Rifornimento sequenza tap | `tasks/rifornimento.py` | 300/300/600ms come V5 + `tap(879,487)` OK tastiera |
| Rifornimento slot reale | `tasks/rifornimento.py` | `leggi_contatore_slot()` da `ocr_helpers` |
| Rifornimento qta 999M | `config/global_config.json` | qta 1M → 999M, gioco adatta al massimo |
| Rifornimento coordinate | `config/global_config.json` + `config/config_loader.py` | rifugio (687,532) in tutti i posti |
| Rifornimento max_sped=0 | `tasks/rifornimento.py` | guard immediato per modalità selezionata |
| Rifornimento statistiche | `tasks/rifornimento.py` + `core/state.py` | snapshot pre/post VAI → qta reale, provviste residue, dettaglio giornaliero |
| Rifornimento modalità | `tasks/rifornimento.py` | architettura mappa/membri mutualmente esclusiva, mappa ha precedenza |
| Rifornimento via membri | `tasks/rifornimento.py` | navigazione lista alleanza V5 tradotta in API V6 |
| Rifornimento tap Alliance | `tasks/rifornimento.py` | `tap_barra(ctx, "alliance")` invece di coordinata fissa |
| Rifornimento fix defaults | `tasks/rifornimento.py` | `RIFORNIMENTO_MEMBRI_ABILITATO` + `AVATAR_TEMPLATE` in `_DEFAULTS` |
| Scheduling restart-safe | `core/state.py` + `main.py` | `ScheduleState` persiste `last_run` su disco, ripristinato all'avvio |
| Schedule ISO string | `core/state.py` | timestamps salvati come ISO string leggibile invece di Unix float |
| Schedule retrocompat | `core/state.py` | `from_dict()` converte vecchi float in ISO automaticamente |
| Schedule run_task | `run_task.py` | PASSO 4b: skip automatico task daily <24h; `--force` override; log ISO |
| .gitignore | `.gitignore` | esclude logs, state, cache, debug, runtime |
| ArenaMercato BACK | `arena_mercato.py` | `_torna_home()` BACK×3 → BACK×2 |
| Runner isolato | `run_task.py` | nuovo file per test singolo task |

---

## Fix applicati in sessione 13/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Porta FAU_01 | `instances.json` | 16448 → 16416 |
| VIP retry cassaforte | `vip.py` | wait_open_badge 2→3s + retry 1.5s |
| Raccolta skip neutro | `raccolta.py` | territorio FUORI → skip_neutro=True |
| Raccolta allocation | `raccolta.py` | logica gap V5; OCR deposito → sequenza ottimale |
| Raccolta OCR slot | `raccolta.py` | leggi_contatore_slot() in run() |
| Raccolta pin_march | `raccolta.py` | pin_marcia → pin_march |
| Raccolta delay livello | `raccolta.py` | 0.15s/tap MENO + 0.2s/tap PIU |
| Raccolta blacklist tipo | `raccolta.py` | chiave tipo_X invece coordinate fisse |
| Raccolta territorio | `raccolta.py` | pixel check V5 zona(250,340,420,370) soglia 20px |
| arena_mercato struttura | `arena_mercato.py` | check lista + tap carrello in _loop_acquisti |
| arena tap_barra | `arena.py` | _naviga_a_arena usa tap_barra("campaign") |
| navigator tap_barra | `navigator.py` | TM ROI(546,456,910,529), 5 pin, fallback coord |
| FakeMatcher test | `test_arena.py`, `test_arena_mercato.py` | find_one() delega a match(), _MatchResult stub |

---

## Prossima sessione

### Priorità 0 — RT-18 completamento test scheduling
```
Test mancanti (in ordine):
1. Task periodic — raccolta o rifornimento:
     python run_task.py --istanza FAU_00 --task raccolta
     → deve eseguire e salvare ISO in schedule.raccolta
     → rilancia subito: deve eseguire ancora (periodic non blocca in run_task)
     → verifica schedule.raccolta aggiornato

2. --force su task daily:
     python run_task.py --istanza FAU_00 --task vip --force
     → deve eseguire ignorando schedule (vip già eseguito oggi)
     → log: "[SCHEDULE] --force attivo — schedule ignorato"

3. restore_to_orchestrator al riavvio main.py:
     python main.py --istanze FAU_00 --tick-sleep 10
     → log: "Schedule ripristinato: {vip: 2026-04-14T..., ...}"
     → verifica che VIP NON venga rieseguito nel primo tick
```

### Priorità 1 — RT-21 Boost BoostState runtime
```
Test BoostState scheduling intelligente:
1. Primo avvio (nessuno state):
     python run_task.py --istanza FAU_00 --task boost
     → boost entra (scadenza=None → should_run=True)
     → log: "[BOOST] stato: mai attivato"
     → se GIA_ATTIVO: registra 8h, state/FAU_00.json boost.scadenza = now+8h
     → se ATTIVATO_8H: registra 8h
     → se NESSUN_BOOST: disponibile=False

2. Secondo avvio subito dopo (boost attivo):
     python run_task.py --istanza FAU_00 --task boost
     → log: "[BOOST] stato: tipo=8h scadenza=... ATTIVO (+7hXXm)"
     → should_run=False → task skippato

3. Verifica state/FAU_00.json:
     "boost": { "tipo": "8h", "attivato_il": "...", "scadenza": "...", "disponibile": true }
```

### Priorità 2 — Ripristino config produzione rifornimento
```
global_config.json da ripristinare a produzione:
  rifornimento_mappa.abilitato  = true
  rifornimento_membri.abilitato = false
  max_spedizioni_ciclo          = 5
  petrolio_abilitato            = true
  soglie normali 5.0/5.0/2.5/3.5
```

### Priorità 3 — Dashboard radiobutton mappa/membri
- Radiobutton che scrive `rifornimento_mappa.abilitato` / `rifornimento_membri.abilitato` su `global_config.json`
- Sezione statistiche rifornimento: `inviato_oggi`, `provviste_residue`, `dettaglio_oggi`

### Priorità 4 — Issue #4 Radar skip silenzioso

### Priorità 5 — RT-13 Multi-istanza FAU_00+FAU_01

---

## Metodologia di lavoro (vincolante)

### Startup sessione
1. Leggi sempre ROADMAP da GitHub: `https://raw.githubusercontent.com/faustodba/doomsday-engine/main/ROADMAP.md`
2. Se non sei certo di avere l'ultima versione di un file → chiedi il file locale prima di modificare
3. **Nota cache GitHub:** raw.githubusercontent.com può servire versioni cachate.
   Se il contenuto sembra vecchio → chiedere upload diretto del file.

### Codice
- Mai frammenti — solo file completi, coerenti, eseguibili
- Prima di implementare qualsiasi primitiva → leggere SEMPRE il file V5 corrispondente
- Non rompere funzionalità già testate e funzionanti in V5

### Esecuzione
- Scomponi in step semplici
- Procedi step-by-step
- Nessuna modifica complessa senza validazione sintassi (`ast.parse`)

### Rilascio (batch obbligatorio)
Ogni rilascio deve produrre un file `.bat` che esegue:
1. Copia file nelle cartelle di progetto (`C:\doomsday-engine\`)
2. `git add` dei file modificati
3. `git commit -m "..."`
4. `git push origin main`
5. Il bat deve includere SEMPRE il `ROADMAP.md` aggiornato

### ROADMAP
- Aggiornare ad ogni sessione: fix applicati, stato RT, issues aperti
- Il ROADMAP su GitHub è la fonte di verità — viene letto all'avvio di ogni sessione
- Aggiornare anche l'albero architetturale quando cambiano classi/moduli

### Interazione
- Chiedere feedback dopo ogni fase rilevante
- Attendere conferma prima di step critici
- Proporre ottimizzazioni tecniche/architetturali quando rilevate

### Regression
- Verificare sempre compatibilità con V5
- Se serve → richiedere classi/componenti V5 prima di implementare

### Runner isolato — `run_task.py` (da usare per RT e test singoli task)
```
cd C:\doomsday-engine
python run_task.py --istanza FAU_01 --task arena
python run_task.py --istanza FAU_01 --task arena_mercato
python run_task.py --istanza FAU_00 --task raccolta
python run_task.py --istanza FAU_00 --task rifornimento
python run_task.py --istanza FAU_00 --task vip --force   ← forza ignorando schedule
```
- Esegue un singolo task direttamente, senza orchestrator né scheduler
- PASSO 4b: skip automatico se task daily già eseguito nelle ultime 24h
- `--force`: ignora schedule, forza esecuzione
- Log a schermo con timestamp + file in `debug_task/<task>/run_task.log`
- Esito finale: exit code 0 = OK/SKIP, 1 = FAIL

### Runner completo — `main.py` (per RT-13, RT-14)
```
python main.py --istanze FAU_01 --tick-sleep 10
python main.py --istanze FAU_00,FAU_01 --tick-sleep 10
```
- Usa orchestrator + scheduler completo
- Tutti i task abilitati vengono eseguiti in sequenza per priorità

### Flag abilitazione task
I flag sono in `config/global_config.json` sezione `task` — letti ad ogni tick.

| Flag | Default | Task |
|------|---------|------|
| `raccolta` | `true` | raccolta |
| `rifornimento` | `true` | rifornimento |
| `zaino` | `false` | zaino |
| `vip` | `true` | vip |
| `alleanza` | `true` | alleanza |
| `messaggi` | `true` | messaggi |
| `arena` | `true` | arena |
| `arena_mercato` | `true` | arena_mercato |
| `boost` | `true` | boost |
| `store` | `true` | store |
| `radar` | `true` | radar |
| `radar_census` | `false` | radar_census |

Per modificare: editare `config/global_config.json` — effetto al prossimo tick senza restart.

---

---

## Architettura V6 — Catena di comando

### Livello 1 — Configurazione (strato statico)

**File:** `config/global_config.json` + `config/config_loader.py`

Unica fonte di verità per la configurazione. Riletta ad ogni tick — modifiche dalla dashboard hanno effetto immediato senza restart.

```
global_config.json
  └─ task.{nome}              → bool  abilita/disabilita il task globalmente
  └─ rifornimento_mappa.abilitato  → bool  modalità mappa
  └─ rifornimento_membri.abilitato → bool  modalità membri
  └─ rifornimento_comune.*    → soglie, quantità, max_spedizioni_ciclo
  └─ zaino.*                  → modalità, soglie
  └─ raccolta.*               → livello_nodo, allocazioni
```

`load_global()` → `GlobalConfig` tipizzato
`build_instance_cfg(ist, gcfg)` → `_InstanceCfg` per istanza con:
- `task_abilitato(nome)` → bool (flag on/off funzionalità)
- `get(key, default)` → valore configurazione

**Nota rifornimento:** `task_abilitato("rifornimento")` = `mappa_abilitato OR membri_abilitato`

---

### Livello 2 — Scheduling (strato temporale)

**File:** `main.py` (`_TASK_SETUP`) + `core/orchestrator.py`

Decide **quando** un task deve girare nel tempo.

```
_TASK_SETUP = [(class_name, priority, interval_hours, schedule_type), ...]

interval_hours = 0.0  → always-run (nessun vincolo temporale)
schedule_type  = "periodic" → ogni N ore dall'ultimo run
schedule_type  = "daily"    → una volta al giorno (reset 01:00 UTC)
```

`Orchestrator.tick()` per ogni task registrato:
```
e_dovuto(entry) → interval scaduto? / daily non ancora eseguito oggi?
  NO  → skip silenzioso (last_run non aggiornato)
  SI  → procedi al livello successivo
```

---

### Livello 3 — Abilitazione + Guard stato (strato logico)

**File:** `tasks/*.py` → `should_run(ctx)`
**Chiamato da:** `Orchestrator.tick()` dopo `e_dovuto()` — GATE obbligatorio

`should_run()` ha **due sole responsabilità**:

**A) Flag abilitazione** — configurazione statica da `global_config.json`:
```python
if not ctx.config.task_abilitato("nome"):
    return False   # operatore ha disabilitato la funzionalità
```

**B) Guard stato persistente** — condizione di business giornaliera da `state/<ISTANZA>.json`:
```python
if not ctx.state.XXXState.should_run():
    return False   # condizione di gioco non soddisfatta oggi
```

| Task | Flag abilitazione | Guard stato persistente |
|------|-------------------|------------------------|
| BoostTask | `task_boost` | `BoostState.should_run()` — boost non ancora scaduto |
| VipTask | `task_vip` | `VipState.should_run()` — entrambe le ricompense già ritirate |
| ArenaTask | `task_arena` | `ArenaState.should_run()` — sfide già esaurite oggi |
| RifornimentoTask | `mappa OR membri abilitati` | `RifornimentoState.provviste_esaurite` (TODO) |
| MessaggiTask | `task_messaggi` | nessuna |
| AlleanzaTask | `task_alleanza` | nessuna |
| StoreTask | `task_store` | nessuna |
| ArenaMercatoTask | `task_arena_mercato` | nessuna |
| ZainoTask | `task_zaino` | nessuna |
| RadarTask | `task_radar` | nessuna |
| RadarCensusTask | `task_radar_census` | nessuna |
| RaccoltaTask | `task_raccolta` | nessuna (slot liberi verificati in run) |

**Regola:** `should_run()` NON fa I/O, NON fa screenshot, NON fa OCR.
Legge solo `ctx.config` e `ctx.state` — entrambi già in memoria.

---

### Livello 4 — Gate HOME (strato navigazione)

**File:** `core/orchestrator.py`

Prima di ogni `run()`, l'orchestrator verifica che il navigator sia in HOME.
Se il gate fallisce → task saltato, `last_run` NON aggiornato → riprova al tick successivo.

```
nav.vai_in_home()
  FAIL → TaskResult(gate_home=False), continua con il prossimo task
  OK   → procedi a run()
```

Task che non richiedono HOME: `requires_home = False` (nessuno attualmente).

---

### Livello 5 — Esecuzione (strato operativo)

**File:** `tasks/*.py` → `run(ctx)`

Esecuzione effettiva del task. Contiene:
- Guard operative runtime (slot liberi, soglie risorse, DOOMS_ACCOUNT) — verificate via OCR/device
- Logica di gioco (tap, screenshot, template matching)
- Aggiornamento stato persistente post-esecuzione (`ctx.state.XXX.segna_*()`)
- Ritorno `TaskResult.ok() / .skip() / .fail()`

**Regola:** `run()` aggiorna sempre `ctx.state` quando rileva condizioni
significative (boost attivato, sfide esaurite, provviste=0, ricompense ritirate).

---

### Flusso completo per tick

```
main.py tick loop
  │
  ├─ load_global()                    [Livello 1 — rilegge config]
  ├─ build_instance_cfg()             [Livello 1 — merge per istanza]
  │
  └─ Orchestrator.tick()
       │
       ├─ per ogni task (in ordine priorità):
       │    │
       │    ├─ e_dovuto()?             [Livello 2 — interval/daily scaduto?]
       │    │    NO → skip
       │    │
       │    ├─ should_run(ctx)?        [Livello 3 — abilitato? guard stato?]
       │    │    NO → skip (last_run non aggiornato → riprova)
       │    │
       │    ├─ gate HOME               [Livello 4 — navigator in HOME?]
       │    │    FAIL → skip (last_run non aggiornato → riprova)
       │    │
       │    └─ task.run(ctx)           [Livello 5 — esecuzione]
       │         └─ aggiorna ctx.state
       │
       └─ ctx.state.save()            [persistenza su disco]
```

---

### Stato persistente per istanza (`state/<ISTANZA>.json`)

```json
{
  "schedule":      { "task_name": "ISO timestamp ultimo run" },
  "boost":         { "tipo": "8h", "scadenza": "ISO", "disponibile": true },
  "vip":           { "cass_ritirata": false, "free_ritirato": false, "data": "YYYY-MM-DD" },
  "arena":         { "esaurite": false, "data_riferimento": "YYYY-MM-DD" },
  "rifornimento":  { "spedizioni_oggi": 3, "provviste_esaurite": false, "data": "YYYY-MM-DD" },
  "metrics":       { ... },
  "daily_tasks":   { ... }
}
```

Tutte le sezioni con `data_riferimento` si resettano automaticamente a mezzanotte UTC.
`ScheduleState` non si resetta — persiste i timestamp per il restart-safe scheduling.

---

## Architettura V6 — Dettaglio classi

### TaskContext (`core/task.py`)
```
ctx.instance_name   str
ctx.config          _Cfg (vedi flag sopra)
ctx.device          AdbDevice
ctx.matcher         TemplateMatcher
ctx.navigator       GameNavigator
ctx.state           InstanceState
ctx.log_msg(msg)    ← UNICO metodo di logging nei task
```

**Task ABC** (`core/task.py`)
```
task.name()         → str
task.should_run(ctx)→ bool
task.run(ctx)       → TaskResult
```

**TaskResult** (`core/task.py`)
```
result.success      bool
result.message      str
result.data         dict
result.skipped      bool
TaskResult.ok(msg)  / TaskResult.fail(msg) / TaskResult.skip(msg)
```

**GameNavigator** (`core/navigator.py`)
```
nav.vai_in_home()              → bool
nav.tap_barra(ctx, "campaign") → bool
  voci barra: campaign, bag, alliance, beast, hero
```

**TemplateMatcher** (`shared/template_matcher.py`)
```
matcher.find_one(screen, path, threshold=0.8, zone=(x1,y1,x2,y2)) → _MatchResult
matcher.score(screen, path)    → float
_MatchResult.found             bool
_MatchResult.score             float
_MatchResult.cx, .cy           int  (centro match)
```

**AdbDevice** (`core/device.py`)
```
device.screenshot()            → Screenshot | None
device.tap(x, y)               → None
device.back()                  → None
Screenshot.frame               → np.ndarray (BGR)
```

**Orchestrator** (`core/orchestrator.py`)
```
orc.register(task, priority)   → None
orc.tick()                     → list[TaskResult]
orc.stato()                    → dict
orc.task_names()               → list[str]
orc.n_dovuti()                 → int
```

**InstanceState** (`core/state.py`)
```
state.schedule.get(task_name)  → float (Unix ts, 0.0 se mai eseguito)
state.schedule.set(task_name, float) → salva come ISO string leggibile
state.schedule.timestamps      → dict {task_name: "2026-04-14T16:45:39+00:00"}
state.schedule.restore_to_orchestrator(orc) → ripristina last_run all'avvio
state.schedule.update_from_stato(orc.stato()) → sync dopo ogni tick
state.boost.should_run()             → bool (boost non ancora scaduto)
state.boost.registra_attivo(tipo, now)→ salva tipo+"8h"|"1d" + scadenza
state.boost.registra_non_disponibile()→ disponibile=False, riprova al tick
state.boost.log_stato()              → str descrittiva per log
state.vip.should_run()               → bool (False se entrambe ricompense ritirate)
state.vip.segna_cass()               → cassaforte ritirata
state.vip.segna_free()               → claim free ritirato
state.vip.log_stato()                → str descrittiva per log
state.arena.should_run()             → bool (False se sfide esaurite oggi)
state.arena.segna_esaurite()         → sfide esaurite, skip fino a mezzanotte UTC
state.arena.log_stato()              → str descrittiva per log
state.rifornimento.provviste_esaurite→ bool (TODO: da aggiungere)
```

### Scheduling task in main.py (_TASK_SETUP)
| Classe | Priority | Interval | Schedule | Note |
|--------|----------|----------|----------|------|
| BoostTask | 5 | — | periodic | always-run con BoostState guard |
| VipTask | 10 | 24h | daily | |
| MessaggiTask | 20 | 4h | periodic | |
| AlleanzaTask | 30 | 4h | periodic | |
| StoreTask | 40 | 8h | periodic | |
| ArenaTask | 50 | 24h | daily | |
| ArenaMercatoTask | 60 | 24h | daily | |
| ZainoTask | 70 | 168h | periodic | |
| RadarTask | 80 | 12h | periodic | |
| RadarCensusTask | 90 | 24h | periodic | disabilitato default |
| RifornimentoTask | 100 | 1h | periodic | penultima: consuma slot squadre |
| RaccoltaTask | 110 | — | always | always-run se slot liberi |

---

## Coordinate di riferimento (960x540)

| Costante | Valore | Task |
|----------|--------|------|
| `TAP_TOGGLE_HOME_MAPPA` | `(38, 505)` | navigator |
| `_BARRA_ROI` | `(546,456,910,529)` | navigator tap_barra |
| `_ZONA_TESTO_SLOT` | `(890,117,946,141)` | slot OCR |
| `TAP_LENTE` | `(38, 325)` | raccolta |
| `TAP_NODO` | `(480, 280)` | raccolta |
| `TAP_RACCOGLI` | `(230, 390)` | raccolta |
| `TAP_SQUADRA` | `(700, 185)` | raccolta |
| `TAP_MARCIA` | `(727, 476)` | raccolta |
| `TERRITORIO_BUFF_ZONA` | `(250,340,420,370)` | raccolta |
| `TAP_ICONA campo` | `(410, 450)` | raccolta |
| `TAP_ICONA segheria` | `(535, 450)` | raccolta |
| `TAP_ICONA acciaio` | `(672, 490)` | raccolta |
| `TAP_ICONA petrolio` | `(820, 490)` | raccolta |
| ARENA `tap_campaign` | `tap_barra("campaign")` → `(584,507)` | arena/arena_mercato |
| ARENA `tap_arena_of_doom` | `(321, 297)` | arena |
| ARENA `tap_ultima_sfida` | `(745, 482)` | arena |
| ARENA `tap_start_challenge` | `(730, 451)` | arena |
| ARENA `tap_skip_checkbox` | `(723, 488)` | arena |
| ARENA `tap_carrello` | `(905, 68)` | arena_mercato |
| ARENA `tap_primo_360` | `(235, 283)` | arena_mercato |
| ARENA `tap_max_360` | `(451, 286)` | arena_mercato |
| ARENA `tap_pack15` | `(788, 408)` | arena_mercato |
| ARENA `tap_pack15_max` | `(654, 408)` | arena_mercato |
| RIFORNIMENTO `rifugio` | `(687, 532)` | rifornimento mappa (FauMorfeus) |
| RIFORNIMENTO `tap_lente_mappa` | `(334, 13)` | rifornimento mappa |
| RIFORNIMENTO `tap_campo_x/y` | `(484,135)/(601,135)` | rifornimento mappa |
| RIFORNIMENTO `tap_conferma_lente` | `(670, 135)` | rifornimento mappa |
| RIFORNIMENTO `tap_castello_center` | `(480, 270)` | rifornimento mappa |
| RIFORNIMENTO `tap_ok_tastiera` | `(879, 487)` | rifornimento compilazione |
| RIFORNIMENTO `coord_vai` | `(480, 448)` | rifornimento VAI |
| MSG `tap_icona_messaggi` | `(928, 430)` | messaggi |
| VIP `tap_badge` | `(85, 52)` | vip |
| ALLEANZA `coord_alleanza` | `(760, 505)` | alleanza (TODO → tap_barra) |
| RADAR `tap_icona` | `(78, 315)` | radar |
| RADAR `mappa_zona` | `(0,100,860,460)` | radar |
| BARRA `bag` | `(656, 506)` | navigator tap_barra |
| BARRA `alliance` | `(727, 506)` | navigator tap_barra |
| BARRA `beast` | `(798, 506)` | navigator tap_barra |
| BARRA `hero` | `(869, 504)` | navigator tap_barra |

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
| Schedule timestamp | ISO string `"2026-04-14T16:45:39+00:00"` | Unix float `1776177939.78` |

**REGOLA ASSOLUTA:** Leggere SEMPRE il file V5 corrispondente prima di
scrivere qualsiasi primitiva. Zone OCR, coordinate UI, template names,
logica di parsing — tutto è già calibrato in V5.

---

## Template disponibili in templates/pin/ (47 file)

```
pin_region, pin_shelter
pin_vip_01..07 (7 file)
pin_boost, pin_manage, pin_speed, pin_50_, pin_speed_8h, pin_speed_1d, pin_speed_use
pin_gather, pin_march
pin_field, pin_sawmill, pin_steel_mill, pin_oil_refinery
pin_store, pin_store_attivo, pin_mercante, pin_merchant, pin_merchant_close, pin_carrello
pin_banner_aperto, pin_banner_chiuso
pin_legno, pin_pomodoro, pin_acciaio (= pin_pomodoro — TODO rimpiazzare)
pin_free_refresh, pin_no_refresh
pin_arena_01..07 (7 file)
pin_arena_check, pin_arena_no_check
pin_360_open, pin_360_close, pin_15_open, pin_15_close
pin_msg_02..04, pin_claim
btn_resource_supply_map
pin_campaign, pin_bag, pin_alliance, pin_beast, pin_hero  ← NUOVO (barra inferiore)
pin_caution  ← NUOVO (popup warehouse)
pin_pom_1000..5000000 (7 file), pin_leg_1000..1500000 (6 file)  ← NUOVO (zaino BAG)
pin_acc_500..2500000 (7 file), pin_pet_200..300000 (6 file)  ← NUOVO (zaino BAG)
```

**Template mancanti (TODO):**
- `pin_acciaio.png` — reale (attuale = pin_pomodoro)
- `pin_arena_video.png` — popup video primo accesso arena
- `pin_arena_categoria.png` — popup categoria settimanale (lunedì)
