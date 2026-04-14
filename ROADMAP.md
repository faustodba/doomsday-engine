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

## Piano test runtime — Stato al 13/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01..05 | Infrastruttura, navigator, OCR, slot | ✅ | |
| RT-06 | VIP claim | ✅ | |
| RT-07 | Boost | ✅ | |
| RT-08 | Messaggi + Alleanza | ✅ | |
| RT-09 | Store | ✅ | 18 acquistati + Free Refresh |
| RT-10 | Arena | ✅ | 5 sfide + skip checkbox |
| RT-11 | Raccolta | ✅ | 4/4 FAU_00; territorio FUORI FAU_01 OK |
| RT-12 | Tick completo FAU_01 | ✅ | Tick completo funzionante |
| RT-tap | tap_barra barra inferiore | ✅ | score=1.000 tutti 5 bottoni su FAU_01 |
| RT-15 | Arena + ArenaMercato | ✅ | Arena: 5/5 sfide 8.4s/sfida; ArenaMercato: pack360=5; fix BACK×2 |
| RT-16 | Rifornimento | ⏳ | fix applicati; prerequisiti: runtime.json con DOOMS_ACCOUNT + slot liberi FAU_00 |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dopo fix issues aperti |
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

### 2. Arena — timeout battaglia 38s → 60s (MEDIA)
- **Problema:** sfide 2 e 4 timeout — battaglia ancora in corso (animazioni > 38s).
- **Fix:** aumentare `_MAX_BATTAGLIA_S` da 30s a 52s (delay 8s + poll = 60s totali).
- **TODO pin mancanti:**
  - `pin_arena_video.png` — popup video introduttivo primo accesso
  - `pin_arena_categoria.png` — popup categoria settimanale (lunedì)

### 3. Zaino — deposito non passato dall'orchestrator (MEDIA)
- **Problema:** `ZainoTask.run()` riceve `ctx` senza `deposito` OCR.
- **Fix:** leggere `ocr_risorse()` nell'orchestrator PRIMA dei task, salvare in
  `ctx.state`, passare a Zaino. Alternativa: leggere direttamente in `ZainoTask.run()`.
- **Priorità:** dopo rifornimento.

### 4. Radar — skip silenzioso (ALTA)
- **Stato:** task esegue ma non logga nulla.
- **Azione:** leggere `radar_census.py` V5 + `radar.py` V6. Richiede istanza
  in MAPPA con radar aperto.

### 5. Alleanza — tap_barra (BASSA)
- `COORD_ALLEANZA=(760,505)` ancora hardcoded.
- **Fix:** sostituire con `ctx.navigator.tap_barra(ctx, "alliance")` come
  fatto per Campaign in arena.py e arena_mercato.py.

### 6. Store NMS cross-template (BASSA)
- `pin_acciaio.png` = `pin_pomodoro.png` (stesso file) → stesso cx,cy.
  Risolvibile quando sarà disponibile il vero `pin_acciaio.png`.

---

## Fix applicati in sessione 14/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Arena timeout | `arena.py` | `_MAX_BATTAGLIA_S` 30.0 → 15.0 (skip attivo, 23s totali sufficienti) |
| ArenaMercato BACK | `arena_mercato.py` | `_torna_home()` BACK×3 → BACK×2 (percorso reale: Store→Lista→HOME) |
| Runner isolato | `run_task.py` | nuovo file per test singolo task |
| Rifornimento find_one | `rifornimento.py` | `find()` → `find_one()` in `_apri_resource_supply()` |
| Rifornimento deposito OCR | `rifornimento.py` | deposito letto via OCR in mappa se non iniettato (come V5) |
| Rifornimento verifica nome | `rifornimento.py` | aggiunta `_verifica_nome_destinatario_v6()` come V5 |
| Rifornimento navigator | `rifornimento.py` | HOME/MAPPA via `ctx.navigator` con fallback key |
| Config Step A | `config/global_config.json` | unica fonte verità parametri globali |
| Config Step A | `config/config_loader.py` | `load_global()` + `build_instance_cfg()` |
| Config Step B | `main.py` | rimossa `_Cfg` hardcodata → usa `build_instance_cfg()` |
| Config Step B | `run_task.py` | rimossa `_build_cfg` → usa `build_instance_cfg()` |
| Rifornimento OCR fix | `rifornimento.py` | `_leggi_deposito_ocr` usa `ocr_helpers.ocr_risorse()` |
| Rifornimento verifica fix | `rifornimento.py` | `_verifica_nome_destinatario_v6` usa `rifornimento_base.verifica_destinatario()` |
| Rifornimento codice orphan | `rifornimento.py` | rimosso blocco codice duplicato in `_verifica_nome_destinatario_v6` |

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

### Priorità 0 — RT-16 Rifornimento (in corso)
```
1. Verificare che config/global_config.json abbia rifugio_x=687, rifugio_y=532
2. Lanciare: python run_task.py --istanza FAU_00 --task rifornimento
3. Atteso nei log: "tap VAI" → "spedizione 1"
4. Caricare log e aggiornare ROADMAP
```

### Priorità 1 — Rifornimento issue aperta
- Issue #3 Zaino: deposito non passato dall'orchestrator
- Issue #4 Radar: skip silenzioso

### Priorità 2 — RT-13 Multi-istanza
```
python main.py --istanze FAU_00,FAU_01 --tick-sleep 10
```

---

## Metodologia di lavoro (vincolante)

### Startup sessione
1. Leggi sempre ROADMAP da GitHub: `https://raw.githubusercontent.com/faustodba/doomsday-engine/main/ROADMAP.md`
2. Se non sei certo di avere l'ultima versione di un file → chiedi il file locale prima di modificare

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

### Runner isolato — `run_task.py` (da usare per RT-15 e oltre)
```
cd C:\doomsday-engine
python run_task.py --istanza FAU_01 --task arena
python run_task.py --istanza FAU_01 --task arena_mercato
python run_task.py --istanza FAU_00 --task raccolta
python run_task.py --istanza FAU_00 --task rifornimento
```
- Esegue un singolo task direttamente, senza orchestrator né scheduler
- Log a schermo con timestamp + file in `debug_task/<task>/run_task.log`
- Esito finale: exit code 0 = OK, 1 = FAIL
- `should_run()` viene chiamato ma non blocca l'esecuzione

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

## Architettura V6 — Dettaglio classi

### Struttura directory
```
C:\doomsday-engine\
  main.py                    ← entry point — usa load_global() + build_instance_cfg()
  run_task.py                ← runner isolato singolo task (test)
  config/
    global_config.json       ← UNICA fonte di verità parametri globali (letto ad ogni tick)
    config_loader.py         ← load_global(), build_instance_cfg(), save_global()
    instances.json           ← parametri per-istanza (nome, porta, profilo, max_squadre...)
  core/
    task.py                  ← Task ABC + TaskContext + TaskResult
    orchestrator.py          ← Orchestrator (register, tick, stato)
    navigator.py             ← GameNavigator (vai_in_home, vai_in_mappa, tap_barra)
    device.py                ← AdbDevice + FakeDevice + Screenshot + MatchResult
    logger.py                ← StructuredLogger + get_logger + close_all_loggers
    state.py                 ← InstanceState (load, save)
  shared/
    template_matcher.py      ← TemplateMatcher + TemplateCache + FakeMatcher + get_matcher()
    ocr_helpers.py           ← ocr_risorse(), leggi_contatore_slot(), prepara_otsu/crema()
    rifornimento_base.py     ← verifica_destinatario(), leggi_provviste/tassa/eta()
                                vai_abilitato(), COORD_CAMPO, OCR_*, QTA_DEFAULT
                                NOTA: compila_e_invia() è async — NON usare nei task V6
  tasks/
    arena.py                 ← ArenaTask (daily, priority=80)
    arena_mercato.py         ← ArenaMercatoTask (periodic 12h, priority=90)
    boost.py                 ← BoostTask (periodic 8h, priority=5)
    raccolta.py              ← RaccoltaTask (periodic 4h, priority=10)
    rifornimento.py          ← RifornimentoTask (periodic 1h, priority=20)
    zaino.py                 ← ZainoTask (periodic 168h, priority=30)
    vip.py                   ← VipTask (daily, priority=40)
    messaggi.py              ← MessaggiTask (periodic 1h, priority=50)
    alleanza.py              ← AlleanzaTask (periodic 1h, priority=60)
    store.py                 ← StoreTask (periodic 8h, priority=70)
    radar.py                 ← RadarTask (periodic 12h, priority=100)
    radar_census.py          ← RadarCensusTask (periodic 24h, priority=110)
  templates/pin/             ← tutti i template PNG (47 file + avatar.png)
  state/                     ← stato persistito per istanza (JSON)
  logs/                      ← log JSONL per istanza (+ .bak)
  debug_task/<task>/         ← screenshot e log run_task.py
```

### API shared — dettaglio

**`shared/template_matcher.py`**
```
get_matcher(template_dir)          → TemplateMatcher (singleton per dir)
matcher.find_one(screen, path,     → MatchResult(found, score, cx, cy)
    threshold, zone)
matcher.find_all(screen, path,     → list[MatchResult]
    threshold, zone, cluster_px)
matcher.exists(screen, path)       → bool
matcher.score(screen, path)        → float (grezzo, ignora soglia)
matcher.find_first_of(screen,      → (nome|None, MatchResult)
    [path1, path2, ...])
FakeMatcher                        → per test, set_result()/set_score()
```

**`shared/ocr_helpers.py`**
```
ocr_risorse(screenshot)            → RisorseDeposito(pomodoro,legno,acciaio,petrolio,diamanti)
                                     valori float assoluti, -1 se OCR fallisce
leggi_contatore_slot(screenshot,   → (attive, totale) — es. (2, 4)
    totale_noto)                     (0, totale_noto) se nessuna squadra
                                     (-1, -1) se lettura fallita
ocr_zona(img, zone, config,        → str testo grezzo
    preprocessor)
prepara_otsu(img, zone, scale)     → np.ndarray binarizzato
prepara_crema(img, zone, scale)    → np.ndarray binarizzato
estrai_numero(testo)               → int | None (gestisce K/M/B)
```

**`shared/rifornimento_base.py`**
```
verifica_destinatario(screen,      → (ok: bool, testo_ocr: str)
    nome_atteso)
leggi_provviste(screen)            → int (≥0) | -1
leggi_tassa(screen)                → float (0.0-1.0) | TASSA_DEFAULT
leggi_eta(screen)                  → int secondi | 0
leggi_capacita_camion(screen)      → int | 0
vai_abilitato(screen)              → bool (True = VAI giallo)
COORD_CAMPO                        → dict risorsa → (x, y) campi maschera
OCR_NOME_DEST/PROVVISTE/TASSA/     → tuple zone OCR maschera
    CAMION/TEMPO
QTA_DEFAULT                        → dict risorsa → quantità default
ATTENZIONE: compila_e_invia()      → async — NON usare in task V6 sincroni
                                     usare _compila_e_invia() in rifornimento.py
```

### Interfacce chiave

**TaskContext** (`core/task.py`)
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

### Scheduling task in main.py (_TASK_SETUP)
| Classe | Priority | Interval | Schedule |
|--------|----------|----------|----------|
| BoostTask | 5 | 8h | periodic |
| RaccoltaTask | 10 | 4h | periodic |
| RifornimentoTask | 20 | 1h | periodic |
| ZainoTask | 30 | 168h | periodic |
| VipTask | 40 | 24h | daily |
| MessaggiTask | 50 | 1h | periodic |
| AlleanzaTask | 60 | 1h | periodic |
| StoreTask | 70 | 8h | periodic |
| ArenaTask | 80 | 24h | daily |
| ArenaMercatoTask | 90 | 24h | daily |
| RadarTask | 100 | 12h | periodic |
| RadarCensusTask | 110 | 24h | periodic |

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
| BARRA `campaign` | `(584, 507)` | navigator tap_barra |
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
```

**Template mancanti (TODO):**
- `pin_acciaio.png` — reale (attuale = pin_pomodoro)
- `pin_arena_video.png` — popup video primo accesso arena
- `pin_arena_categoria.png` — popup categoria settimanale (lunedì)
