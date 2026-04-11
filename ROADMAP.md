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
- È testabile al 100% con `FakeDevice` + `FakeMatcher` — zero ADB reale
- Ha un file di test dedicato in `tests/tasks/`
- Ha un `deploy_stepN.bat` per xcopy file Python + xcopy PNG + git commit + push

---

## Struttura cartelle

```
doomsday-engine/
├── core/
│   ├── device.py          # FakeDevice + MatchResult + Screenshot (Step 25 + fix)
│   ├── state.py           # InstanceState (Step 1-10)
│   ├── logger.py          # StructuredLogger (Step 1-10)
│   ├── navigator.py       # GameNavigator SINCRONO (Step 25)
│   ├── scheduler.py
│   ├── task.py            # Task ABC + TaskContext + TaskResult SINCRONI (Step 25)
│   └── orchestrator.py    # Step 22 + fix _tname callable
├── shared/
│   ├── ocr_helpers.py
│   ├── template_matcher.py
│   └── rifornimento_base.py
├── config/
│   ├── config.py
│   └── instances.json     # 12 istanze MuMu (FAU_00-FAU_10 + FauMorfeus)
├── tasks/
│   ├── boost.py           # Step 11+25 ✅
│   ├── store.py           # Step 12+25 ✅
│   ├── messaggi.py        # Step 13+25 ✅
│   ├── alleanza.py        # Step 14+25 ✅
│   ├── vip.py             # Step 15+25 ✅
│   ├── arena.py           # Step 16+25 ✅
│   ├── arena_mercato.py   # Step 17+25 ✅
│   ├── radar.py           # Step 18 ✅ — should_run da verificare
│   ├── radar_census.py    # Step 18 ✅ — should_run da verificare
│   ├── zaino.py           # Step 19 ✅ — should_run da verificare
│   ├── rifornimento.py    # Step 20 ✅ — should_run da verificare
│   └── raccolta.py        # Step 21 ✅ — should_run da verificare
├── tests/
│   ├── unit/
│   │   ├── test_orchestrator.py
│   │   ├── test_main.py           # 31/31
│   │   └── test_dashboard_server.py # 30/30
│   └── tasks/
│       ├── conftest.py
│       ├── test_boost.py         # 35/35
│       ├── test_store.py         # 34/34
│       ├── test_messaggi.py      # 27/27
│       ├── test_alleanza.py      # 24/24
│       ├── test_vip.py           # 30/30
│       ├── test_arena.py         # 10/10
│       ├── test_arena_mercato.py # 10/10
│       ├── test_radar.py         # 16/16
│       ├── test_zaino.py         # 39/39
│       ├── test_rifornimento.py  # 47/47
│       └── test_raccolta.py      # 54/54
├── dashboard/
│   ├── dashboard_server.py  # Step 23 ✅ 30/30
│   └── dashboard.html       # Step 23 ✅
├── state/                   # runtime state per istanza (InstanceState JSON)
├── logs/                    # log strutturati per istanza (JSONL)
├── templates/pin/           # template PNG (copiati da C:\Bot-farm\templates\pin)
├── smoke_test.py            # smoke test pipeline dry-run
├── main.py                  # entry point V6 ✅ funzionante
└── runtime.json             # config hot-reload (compatibile con V5)
```

---

## Stato step

| Step | File principali | Test | Note |
|------|----------------|------|------|
| 1–10 | `core/`, `shared/`, `config/` | ✅ | Infrastruttura base |
| 11 | `tasks/boost.py` | ✅ 35/35 | |
| 12 | `tasks/store.py` | ✅ 34/34 | |
| 13 | `tasks/messaggi.py` | ✅ 27/27 | |
| 14 | `tasks/alleanza.py` | ✅ 24/24 | |
| 15 | `tasks/vip.py` | ✅ 30/30 | |
| 16 | `tasks/arena.py` | ✅ 10/10 | |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 54/54 | |
| 22 | `core/orchestrator.py` | ✅ 49/49 | fix _tname callable |
| 23 | `dashboard/` | ✅ 30/30 | dashboard_server.py + dashboard.html |
| 24 | Fix test step 11–17 | ✅ 170/170 | conftest.py + fix arena setUp |
| 25 | Refactoring architettura sincrona | ✅ 170/170 | core+7 task+test |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | Funzionante — vedi pendenti |

**Totale suite: 61/61 verdi**

---

## Pendenti per il run reale

### 1. AdbDevice mancante in `core/device.py`
`core/device.py` contiene solo `FakeDevice`, `MatchResult`, `Screenshot`.
Manca `AdbDevice` (classe reale che parla con MuMu via ADB).
Errore attuale: `cannot import name 'AdbDevice' from 'core.device'`

Da fare: implementare `AdbDevice` con:
- `__init__(host, port)` — connessione ADB MuMu
- `screenshot()` → `Screenshot` (exec-out o screencap+pull)
- `tap(x, y)`
- `swipe(x1, y1, x2, y2, duration_ms)`
- `back()` / `key(keycode)`
- `input_text(text)`

### 2. 5 task con `should_run` astratto
I seguenti task non implementano `should_run()` (metodo abstract di Task ABC):
- `tasks/raccolta.py`
- `tasks/rifornimento.py`
- `tasks/zaino.py`
- `tasks/radar.py`
- `tasks/radar_census.py`

Errore attuale: `Can't instantiate abstract class XxxTask without an implementation for abstract method 'should_run'`

Da fare: caricare i 4 file mancanti (raccolta.py già acquisito) e aggiungere `should_run()` a ciascuno.

### 3. `ctx.log(msg)` nei task
Alcuni task chiamano `ctx.log(msg)` direttamente (es. `raccolta.py`).
`ctx.log` è un `StructuredLogger` — non callable direttamente.
L'API corretta è `ctx.log_msg(msg)`.
Da verificare in tutti e 5 i task pendenti.

---

## Fix applicati in sessione 11/04/2026

| Fix | File | Problema |
|-----|------|---------|
| `_TaskWrapper` | `main.py` | `@property` non settabile per `schedule_type`/`interval_hours` |
| `cfg.get()` | `main.py` | task usano `ctx.config.get(key, default)` — mancava il metodo |
| `_tname()` | `core/orchestrator.py` | `task.name` callable vs string — enable/disable/set_last_run rotti |
| `ctx.log_msg` | `core/orchestrator.py` | `ctx.log(msg)` → `StructuredLogger` non callable |
| `TaskContext` firma | `main.py` | `instance_id` → `instance_name` + aggiunto `state` e `log` obbligatori |
| `MatchResult`+`Screenshot` | `core/device.py` | mancavano — richiesti da `shared/template_matcher.py` |
| ASCII `->` | `dashboard/dashboard_server.py` | carattere `→` non codificabile in CP1252 Windows |
| `AdbDevice` import | `core/device.py` | **ANCORA APERTO** |
| `should_run` abstract | 5 task | **ANCORA APERTO** |

---

## Come riprendere in una nuova chat

```
1. Allegare questa ROADMAP.md come primo messaggio
2. Dire quale pendente affrontare
3. Caricare i file richiesti dal PC
4. Claude: legge → scrive → pytest → corregge → consegna
```

**Prossima sessione — file da caricare:**
- `tasks/rifornimento.py`
- `tasks/zaino.py`
- `tasks/radar.py`
- `tasks/radar_census.py`
- (opzionale) `core/device.py` dal repo per aggiungere `AdbDevice`

---

## Standard architetturale V6 (Step 25 — vincolante)

```python
class XxxTask(Task):

    def name(self) -> str:           # SEMPRE metodo, mai @property
        return "xxx"

    def should_run(self, ctx: TaskContext) -> bool:  # SEMPRE implementato
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("xxx")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:   # SEMPRE sincrono
        def log(msg): ctx.log_msg(f"[XXX] {msg}")
        # logica con time.sleep() — mai asyncio.sleep()
        return TaskResult.ok("completato")
```

**Regole — nessuna eccezione:**

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` / `ctx.log.info()` |
| Navigator | `ctx.navigator.vai_in_home()` (sync) | `await ctx.navigator...` |
| `name()` | `def name(self) -> str` | `@property def name` |
| `should_run()` | sempre implementato | mai omesso |

---

## Struttura deploy_stepN.bat (4 sezioni FISSE)

```bat
@echo off
setlocal
echo [Step N] Deploy nome
echo.
:: [1/4] Copia file Python
echo [1/4] Copia file Python...
set ROOT=C:\doomsday-engine
set SRC=%~dp0
xcopy /Y "%SRC%nome.py" "%ROOT%\tasks\"
echo.
:: [2/4] Template PNG (o skip)
echo [2/4] Nessun template PNG — skip.
echo.
:: [3/4] git add + commit
echo [3/4] Git add + commit...
cd /d %ROOT%
git add tasks/nome.py
git add tests/tasks/test_nome.py
git commit -m "feat: Step N -- tasks/nome.py (X/X verdi)"
if errorlevel 1 ( echo ERRORE commit & exit /b 1 )
echo.
:: [4/4] git push
echo [4/4] Git push...
git push origin main
if errorlevel 1 ( echo ERRORE push & exit /b 1 )
echo.
echo [Step N] Completato.
endlocal
```

**Regole bat:** `%~dp0` come SRC, mai `REM` in for/if, [2/4] sempre presente anche se skip.

---

## Principi generali V6

1. Ordine step vincolante — ogni layer dipende dal precedente
2. Nessun task senza test verde — mai consegnare rosso
3. File sempre completi — mai patch o snippet
4. Prima di modificare un file: richiedere versione aggiornata dal PC
5. Ogni step = 1 commit: `feat: Step N -- descrizione (X/X verdi)`
6. MuMu only — BlueStacks rimosso
7. Porta ADB = da `instances.json` (non formula fissa)
8. Thread per istanza — niente asyncio nei task
9. Template PNG — tutti in `templates/pin/`, path con prefisso `pin/`

---

## Coordinate di riferimento (960×540)

| Costante | Valore | Task |
|----------|--------|------|
| `RIFUGIO_X/Y` | `702 / 534` (da runtime.json) | rifornimento |
| `TAP_CAMPAIGN` | `(760, 505)` | arena, arena_mercato |
| `TAP_GLORY_CONTINUE` | `(471, 432)` | arena, arena_mercato |
| `TAP_RADAR_ICONA` | `(90, 460)` | radar |
| `COORD_ALLEANZA` | `(760, 505)` | alleanza |
| `COORD_DONO` | `(877, 458)` | alleanza |
| `TAP_PACK15` | `(788, 408)` | arena_mercato |

---

## Bug / note aperte V5

- `pin_oil_refinery.png`: score basso (0.08–0.29) — serve nuovo template
- Nodo petrolio `(727,537)`: fuori territorio sistematico — limitazione permanente
- Overlay irrecuperabile: `tap(480,270)+KEYCODE_HOME+relaunch` — pending V5
