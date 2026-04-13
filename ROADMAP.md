# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

---

## Contesto di progetto

Stiamo riscrivendo il bot Doomsday da V5 (monolitico, `config.py` globale, ADB diretto)
a V6 (architettura modulare, `TaskContext`, `FakeDevice` testabile, zero ADB nei test).

Ogni task V6:
- Implementa `Task` ABC da `core/task.py`
- Riceve tutto via `TaskContext` (device, matcher, navigator, config, instance_name, state, log)
- E' testabile al 100% con `FakeDevice` + `FakeMatcher` — zero ADB reale
- Ha un file di test dedicato in `tests/tasks/`
- Ha un `deploy_stepN.bat` per xcopy file Python + xcopy PNG + git commit + push

---

## Struttura cartelle

```
doomsday-engine/
├── core/
│   ├── device.py          # FakeDevice + AdbDevice + MatchResult + Screenshot
│   ├── state.py           # InstanceState
│   ├── logger.py          # StructuredLogger
│   ├── navigator.py       # GameNavigator SINCRONO — toggle (38,505) pin_region/pin_shelter
│   ├── scheduler.py
│   ├── task.py            # Task ABC + TaskContext + TaskResult
│   └── orchestrator.py    # tick() con gate HOME obbligatorio pre-task
├── shared/
│   ├── ocr_helpers.py
│   ├── template_matcher.py
│   └── rifornimento_base.py
├── config/
│   ├── config.py
│   └── instances.json
├── tasks/
│   ├── boost.py, store.py, messaggi.py, alleanza.py
│   ├── vip.py
│   ├── arena.py, arena_mercato.py
│   ├── radar.py, radar_census.py
│   ├── zaino.py, rifornimento.py
│   └── raccolta.py
├── tests/
│   ├── unit/
│   └── tasks/
├── dashboard/
├── templates/pin/          # 40 PNG — vedi lista completa sotto
├── test_task_base.py       # Helper condiviso test isolati
├── test_task_vip.py        # ✅ RT-06 superato
├── test_task_boost.py      # ✅ RT-07 superato
├── test_task_arena.py      # ✅ RT-10 superato
├── test_task_store.py      # ✅ RT-09 superato
├── test_task_messaggi_alleanza.py  # ✅ RT-08 superato
├── test_task_raccolta.py   # ⏳ da eseguire
├── test_navigator.py       # ✅ RT-03 superato
├── smoke_test.py
├── main.py
└── runtime.json
```

---

## Stato step pytest

| Step | File principali | Test | Note |
|------|----------------|------|------|
| 1-10 | `core/`, `shared/`, `config/` | ✅ | Infrastruttura base |
| 11 | `tasks/boost.py` | ✅ 35/35 | |
| 12 | `tasks/store.py` | ✅ 39/39 | +5 test VIP Store + mercante diretto |
| 13 | `tasks/messaggi.py` | ✅ 27/27 | |
| 14 | `tasks/alleanza.py` | ✅ 24/24 | |
| 15 | `tasks/vip.py` | ✅ 30/30 | |
| 16 | `tasks/arena.py` | ✅ 10/10 | |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 54/54 | |
| 22 | `core/orchestrator.py` | ✅ 49/49 | |
| 23 | `dashboard/` | ✅ 30/30 | |
| 24 | Fix test step 11-17 | ✅ 170/170 | |
| 25 | Refactoring architettura sincrona | ✅ 170/170 | |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Fix applicati in sessione 12/04/2026

### Bug critici risolti

| File | Bug | Fix |
|------|-----|-----|
| `core/device.py` | `AdbDevice.screenshot()` usava `exec-out` — non funziona su MuMu12 TCP (returncode -1, 0 bytes) | Sostituito con `screencap -p /sdcard/` + `pull` con lock per porta — pattern identico V5 `adb.py` |
| `core/device.py` | `AdbDevice("127.0.0.1:16384")` generava `_serial="127.0.0.1:16384:16384"` (porta duplicata) | Fix costruttore: se `host` contiene `:` viene usato direttamente come serial |
| `core/navigator.py` | `device.screenshot_sync()` e `device.tap_sync()` non esistono in `AdbDevice` | Sostituiti con `device.screenshot()` e `device.tap(*coord)` |
| `tasks/boost.py` | `matcher.find()` non esiste — API e' `find_one()` | Sostituito con `matcher.find_one()` + controllo `.found` |
| `tasks/arena.py` | `ctx.matcher.match(screen, path, roi)` non esiste | Sostituito con `find_one(screen, path, zone=roi).score` |
| `tasks/arena_mercato.py` | Stesso bug `match()` in 4 metodi + `@property interval_hours` | Stessa correzione + rimosso `@property` |
| `tasks/radar.py` | `ctx.device.last_frame` non esiste | Helper `_frame_from_screenshot(screen)` che legge `screen.frame` |
| `tasks/store.py` | `pin/pin_home.png` non esiste — template si chiama `pin_region.png` | Corretto nome template |
| `core/orchestrator.py` | Nessun gate HOME prima dei task — sequenza cieca | Aggiunto gate `vai_in_home()` in `tick()` prima di ogni `run()` |

### Root cause

**I primi 10 step V6 sono stati scritti senza leggere nessun file V5.** Tutto e' stato inventato: nomi metodi, API, pattern screenshot. Ogni bug in questa sessione deriva da questo errore metodologico.

**Regola assoluta da rispettare:** prima di scrivere qualsiasi primitiva V6, leggere il file V5 corrispondente (`adb.py`, `stato.py`, `ocr.py`, il task corrispondente).

---

## Fix applicati in sessione 13/04/2026

### Messaggi + Alleanza (RT-08)

| File | Bug | Fix |
|------|-----|-----|
| `tasks/messaggi.py` | `tap_icona_messaggi=(930,13)` — coordinata errata | Corretto in `(928,430)` da V5 config |
| `tasks/messaggi.py` | Chiusura con `n_back_close=3` BACK fissi | Sostituito con `navigator.vai_in_home()` post-chiusura |
| `tasks/alleanza.py` | Loop Rivendica con heuristica cromatica — click fisso | Sostituito con `matcher.find_one(pin_claim.png)` + tap dinamico `(cx,cy)` |

**Nuovo template:** `pin_claim.png` in `templates/pin/`.

### Store (RT-09)

| File | Bug | Fix |
|------|-----|-----|
| `tasks/store.py` | Logica mercante diretto tappava `(cx_store,cy_store)` invece di `(cx_merc,cy_merc)` | `find_one(pin_mercante)` → tap preciso su coordinate restituite |
| `tasks/store.py` | Merchant check singolo — non distingueva VIP Store da Mysterious Merchant | Doppio match `pin_merchant.png` vs `pin_merchant_close.png` — vince il piu' alto sopra soglia |
| `tasks/store.py` | `TaskResult.ok(acquistati=..., refreshed=...)` — kwargs non supportati | Sostituito con `data={"acquistati": ..., "refreshed": ...}` |

**Nuovi template:** `pin_merchant_close.png`.
**Risultato RT-09:** 18 acquistati + Free Refresh eseguito.

### Arena (RT-10)

| File | Bug | Fix |
|------|-----|-----|
| `tasks/arena.py` | `_TAP_CAMPAIGN=(760,505)` — coordinata Alleanza, non Campaign | Corretto in `(584,486)` da V5 `config.py` |
| `tasks/arena.py` | `_TAP_ARENA_OF_DOOM=(480,270)` — centro schermo | Corretto in `(321,297)` da V5 `config.py` |
| `tasks/arena.py` | `_TAP_ULTIMA_SFIDA=(480,350)` — inventata | Corretto in `(745,482)` da V5 `config.py` |
| `tasks/arena.py` | `_TAP_START_CHALLENGE=(730,460)` — inventata | Corretto in `(730,451)` da V5 `config.py` |

**Aggiunta:** verifica skip checkbox `(723,488)` con `pin_arena_check.png` / `pin_arena_no_check.png` — eseguita una volta per sessione prima della prima sfida.
**Nuovi template:** `pin_arena_check.png`, `pin_arena_no_check.png`.
**Risultato RT-10:** 2 vittorie + esaurite rilevato correttamente.

---

## Piano test runtime — Stato al 13/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01 | Connessione ADB | ✅ | `adb connect` auto in AdbDevice |
| RT-02 | Avvio engine + 12 task | ✅ | 12/12 task caricati |
| RT-03 | Navigator HOME/MAPPA | ✅ | toggle (38,505), score 0.990/0.989 |
| RT-04 | OCR risorse + diamanti | ✅ | HOME e MAPPA identici, 5/5 valori |
| RT-05 | Contatore slot (X/Y) | ✅ | 0/5, 2/5, 3/5 testati |
| RT-06 | VIP claim | ✅ | cass=OK free=OK |
| RT-07 | Boost attivazione | ✅ | boost_gia_attivo (0.924) + nessun_boost_disponibile OK |
| RT-08 | Messaggi + Alleanza | ✅ | MSG icona fix + chiusura vai_in_home(); Alleanza pin_claim.png dinamico |
| RT-09 | Store | ✅ | 18 acquistati + Free Refresh; mercante diretto fix; VIP Store detection |
| RT-10 | Arena | ✅ | 2 vittorie + esaurite rilevato; 4 coordinate corrette da V5; skip checkbox |
| RT-11 | Raccolta | ⏳ | `python test_task_raccolta.py` — BLOCCATO: pin_gather.png score 0.377 |
| RT-12 | Tick completo FAU_00 | ⏳ | dipende da RT-11 |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dipende da RT-12 |
| RT-14 | Full farm 12 istanze | ⏳ | dipende da RT-13 |

---

## Prossima sessione — RT-11 Raccolta

**Blocco critico:** `pin_gather.png` score 0.377 su tutti i nodi — template non matcha il pulsante Gather nel popup nodo.

**Azione richiesta:** screenshot del popup lente con nodo selezionato (campo o segheria) per rifare il template.

```bat
cd C:\doomsday-engine
python test_task_raccolta.py
```

---

## Script test isolati disponibili

| Script | Task | Uso |
|--------|------|-----|
| `test_task_vip.py` | VIP | ✅ funzionante |
| `test_task_boost.py` | Boost | ✅ funzionante |
| `test_task_messaggi_alleanza.py` | Messaggi + Alleanza | ✅ funzionante |
| `test_task_store.py` | Store | ✅ funzionante |
| `test_task_arena.py` | Arena | ✅ funzionante |
| `test_task_raccolta.py` | Raccolta | ⏳ bloccato pin_gather.png |

Ogni script: connette ADB → aspetta INVIO con istanza in HOME → lancia solo quel task → log in `logs/FAU_00.jsonl`.

---

## Problemi aperti

| Problema | Task | Priorita' | Nota |
|----------|------|-----------|------|
| `pin_gather.png` score 0.377 su tutti i nodi | raccolta | ALTA | Template non matcha il pulsante Gather nel popup nodo. Serve screenshot dal pannello lente con nodo selezionato |
| NMS cross-template: pin_acciaio + pin_pomodoro stessa (cx,cy) | store | MEDIA | find_all multi-template non ha NMS globale — stessa coordinata rilevata da template diversi. Fix prima di RT-12 |
| `pin_speed_use` score -1.000 | boost | MEDIA | Template non matcha il pulsante USE nel pannello boost. Serve screenshot con pannello boost aperto |
| `pin_oil_refinery.png` score 0.08-0.29 | raccolta | BASSA | Template da rifare — nodo petrolio comunque fuori territorio sistematicamente |

---

## Principio fondamentale (appreso in sessione 12/04)

> **Leggere SEMPRE i file V5 prima di scrivere qualsiasi primitiva.**
> Zone OCR, coordinate UI, template names, logica di parsing, metodi ADB —
> tutto e' gia' calibrato e funzionante in V5. Reinventare senza leggere causa
> bug evitabili e spreco di tempo e denaro.
>
> **File V5 da leggere prima di ogni primitiva:**
> `adb.py`, `config.py`, `ocr.py`, `stato.py`, il task corrispondente.

---

## Standard architetturale V6 (Step 25 — vincolante)

```python
class XxxTask(Task):

    def name(self) -> str:
        return "xxx"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("xxx")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        def log(msg): ctx.log_msg(f"[XXX] {msg}")
        return TaskResult.ok("completato")
```

**Regole — nessuna eccezione:**

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` |
| Navigator | `ctx.navigator.vai_in_home()` | `await ctx.navigator...` |
| `name()` | `def name(self) -> str` | `@property def name` |
| `interval_hours()` | `def interval_hours(self) -> float` | `@property interval_hours` |
| `should_run()` | sempre implementato | mai omesso |
| Template matching | `matcher.find_one()`, `matcher.score()`, `matcher.exists()` | `matcher.match()`, `matcher.find()` |
| Screenshot frame | `screen.frame` (da `device.screenshot()`) | `device.last_frame` |

---

## Struttura deploy_stepN.bat (4 sezioni FISSE)

```bat
@echo off
setlocal
echo [Step N] Deploy nome
echo.
set ROOT=C:\doomsday-engine
set SRC=%~dp0
echo [1/4] Copia file Python...
xcopy /Y "%SRC%nome.py" "%ROOT%\tasks\"
echo.
echo [2/4] Nessun template PNG -- skip.
echo.
echo [3/4] Git add + commit...
cd /d %ROOT%
git add tasks/nome.py
git diff --cached --quiet
if not errorlevel 1 (
echo Nessuna modifica staged -- skip commit.
goto push
)
git commit -m "feat: Step N -- tasks/nome.py (X/X verdi)"
if errorlevel 1 ( echo ERRORE commit & exit /b 1 )
:push
echo.
echo [4/4] Git push...
git push origin main
if errorlevel 1 ( echo ERRORE push & exit /b 1 )
echo.
echo [Step N] Completato.
endlocal
```

**Regole bat:** `%~dp0` come SRC, mai `REM` in for/if, sezione [2/4] sempre presente anche se skip, niente caratteri UTF-8 (solo ASCII).

---

## Template disponibili in templates/pin/ (40 file)

```
pin_region.png          pin_shelter.png
pin_vip_01_store.png    pin_vip_02_cass_chiusa.png
pin_vip_03_cass_aperta.png  pin_vip_04_free_chiuso.png
pin_vip_05_free_aperto.png  pin_vip_06_popup_cass.png
pin_vip_07_popup_free.png
pin_boost.png           pin_manage.png
pin_speed.png           pin_50_.png
pin_speed_8h.png        pin_speed_1d.png        pin_speed_use.png
pin_gather.png
pin_store.png           pin_store_attivo.png    pin_mercante.png
pin_merchant.png        pin_merchant_close.png  pin_carrello.png
pin_banner_aperto.png   pin_banner_chiuso.png
pin_legno.png           pin_pomodoro.png        pin_acciaio.png
pin_free_refresh.png    pin_no_refresh.png
pin_arena_01_lista.png  pin_arena_02_challenge.png
pin_arena_03_victory.png    pin_arena_04_failure.png
pin_arena_05_continue.png   pin_arena_06_purchase.png
pin_arena_07_glory.png
pin_arena_check.png     pin_arena_no_check.png
pin_360_open.png        pin_360_close.png
pin_15_open.png         pin_15_close.png
pin_msg_02_alliance.png pin_msg_03_system.png   pin_msg_04_read.png
pin_claim.png
btn_resource_supply_map.png
```

---

## Coordinate di riferimento (960x540)

| Costante | Valore | Fonte V5 | Task |
|----------|--------|----------|------|
| `TAP_TOGGLE_HOME_MAPPA` | `(38, 505)` | `config.py` | navigator |
| `_ZONA_TESTO_SLOT` | `(890, 117, 946, 141)` | `ocr.py` | raccolta/slot |
| `TAP_LENTE_COORD` | `(380, 18)` | `config.py` | raccolta |
| `TAP_NODO` | `(480, 280)` | `config.py` | raccolta |
| `TAP_RACCOGLI` | `(230, 390)` | `config.py` | raccolta |
| `TAP_SQUADRA` | `(700, 185)` | `config.py` | raccolta |
| `TAP_MARCIA` | `(727, 476)` | `config.py` | raccolta |
| `RIFUGIO_X/Y` | `702/533` | `config.py` | rifornimento |
| `TAP_RADAR_ICONA` | `(78, 315)` | `config.py` | radar |
| MSG `tap_icona_messaggi` | `(928, 430)` | `config.py` V5 | messaggi |
| VIP `tap_badge` | `(85, 52)` | `vip.py` V6 | vip |
| VIP `tap_claim_cassaforte` | `(830, 160)` | `vip.py` V6 | vip |
| VIP `tap_claim_free` | `(526, 444)` | `vip.py` V6 | vip |
| VIP `tap_chiudi_reward_free` | `(456, 437)` | `vip.py` V6 | vip |
| ALLEANZA `coord_alleanza` | `(760, 505)` | `alleanza.py` V5 | alleanza |
| ALLEANZA `coord_dono` | `(877, 458)` | `alleanza.py` V5 | alleanza |
| ARENA `tap_campaign` | `(584, 486)` | `config.py` V5 layout 1 | arena |
| ARENA `tap_arena_of_doom` | `(321, 297)` | `config.py` V5 | arena |
| ARENA `tap_ultima_sfida` | `(745, 482)` | `config.py` V5 | arena |
| ARENA `tap_start_challenge` | `(730, 451)` | `config.py` V5 | arena |
| ARENA `tap_skip_checkbox` | `(723, 488)` | screenshot reale | arena |
