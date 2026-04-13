# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

---

## Contesto di progetto

Stiamo riscrivendo il bot Doomsday da V5 (monolitico, `config.py` globale, ADB diretto)
a V6 (architettura modulare, `TaskContext`, `FakeDevice` testabile, zero ADB nei test).

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
│   ├── ocr_helpers.py     # OCR risorse + leggi_contatore_slot()
│   ├── template_matcher.py  # TemplateMatcher + FakeMatcher
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
├── tests/tasks/
├── dashboard/
├── templates/pin/          # 42 PNG
├── test_task_base.py       # Helper condiviso (pulisce log prima del run)
├── test_task_raccolta.py   # ✅ RT-11 FAU_00
├── test_task_raccolta_FAU01.py  # ✅ RT-11 FAU_01
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
| 12 | `tasks/store.py` | ✅ 39/39 | VIP Store + mercante diretto |
| 13 | `tasks/messaggi.py` | ✅ 27/27 | |
| 14 | `tasks/alleanza.py` | ✅ 24/24 | |
| 15 | `tasks/vip.py` | ✅ 30/30 | |
| 16 | `tasks/arena.py` | ✅ 10/10 | |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 57/57 | territorio + FakeMatcher |
| 22 | `core/orchestrator.py` | ✅ 49/49 | |
| 23 | `dashboard/` | ✅ 30/30 | |
| 24 | Fix test step 11-17 | ✅ 170/170 | |
| 25 | Refactoring architettura sincrona | ✅ 170/170 | |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Fix sessione 13/04/2026

### Store (RT-09)
- Tap mercante diretto su `find_one(pin_mercante).cx/cy` preciso
- Merchant check doppio match `pin_merchant` vs `pin_merchant_close` (VIP Store)
- Nuovi template: `pin_merchant_close.png`
- **Risultato:** 18 acquistati + Free Refresh

### Arena (RT-10)
- `_TAP_CAMPAIGN (760,505)` → `(584,486)` — era coordinata Alleanza
- `_TAP_ARENA_OF_DOOM (480,270)` → `(321,297)`
- `_TAP_ULTIMA_SFIDA (480,350)` → `(745,482)`
- `_TAP_START_CHALLENGE (730,460)` → `(730,451)`
- Aggiunto skip checkbox `(723,488)` con `pin_arena_check/no_check.png`
- **Risultato:** 2 vittorie + esaurite rilevato

### Raccolta (RT-11)
- `KEYCODE_MAP/HOME` → `navigator.vai_in_mappa/home()` con verifica
- Coordinate V5: TAP_LENTE(38,325) TAP_RACCOGLI(230,390) TAP_SQUADRA(700,185) TAP_MARCIA(727,476)
- `TAP_ICONA_TIPO` separato: Campo(410,450) Segheria(535,450) Acciaio(672,490) Petrolio(820,490)
- `_verifica_tipo()`: find_one su pin_field/sawmill/steel_mill/oil_refinery + retry+reset
- `_tap_nodo_e_verifica_gather()`: tap TAP_NODO + verifica pin_gather ROI(60,350,420,420)
- `_nodo_in_territorio()`: pixel check V5 zona(250,340,420,370) soglia 20px verdi
- `pin_marcia` → `pin_march` (nome corretto)
- Reset livello 7x MENO con delay 0.15s + 5x PIU con delay 0.2s
- Blacklist chiave `tipo_X` per tipo indipendente
- `FakeMatcher` aggiunta in `template_matcher.py`
- Log positivi maschera+marcia
- Pulizia log all'avvio in `test_task_raccolta.py`
- **Risultato FAU_00:** 4/4 squadre inviate
- **Risultato FAU_01:** 0/4 — territorio FUORI rilevato correttamente (pixel_verdi=0)

---

## Piano test runtime — Stato al 13/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01 | Connessione ADB | ✅ | |
| RT-02 | Avvio engine + 12 task | ✅ | 12/12 task caricati |
| RT-03 | Navigator HOME/MAPPA | ✅ | score 0.990/0.989 |
| RT-04 | OCR risorse + diamanti | ✅ | 5/5 valori |
| RT-05 | Contatore slot (X/Y) | ✅ | 0/5, 2/5, 3/5 testati |
| RT-06 | VIP claim | ✅ | cass=OK free=OK |
| RT-07 | Boost attivazione | ✅ | boost_gia_attivo + nessun_boost OK |
| RT-08 | Messaggi + Alleanza | ✅ | icona fix + pin_claim.png |
| RT-09 | Store | ✅ | 18 acquistati + Free Refresh |
| RT-10 | Arena | ✅ | 2 vittorie + esaurite |
| RT-11 | Raccolta | ✅ | 4/4 FAU_00; territorio FUORI FAU_01 OK |
| RT-12 | Tick completo FAU_00 | ⏳ | **PROSSIMO** |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dipende da RT-12 |
| RT-14 | Full farm 12 istanze | ⏳ | dipende da RT-13 |

---

## Prossima sessione — RT-12 Tick completo FAU_00

Obiettivo: eseguire un tick completo dell'orchestrator su FAU_00 con tutti i task
in sequenza reale, incluso OCR contatore slot via `leggi_contatore_slot()`.

**Prerequisiti da integrare:**
- `leggi_contatore_slot()` da `ocr_helpers.py` in `RaccoltaTask.run()` per slot reali
- Verifica orchestrator gate HOME prima di ogni task
- Tutti i task RT-06..RT-11 deployati ✅

**Funzionalita' V5 da integrare in RT-12:**
- Lettura contatore slot reale (`leggi_contatore_slot()` — gia' in `ocr_helpers.py`)
- ETA marcia da maschera invio (OCR)
- Blacklist con coordinate reali nodo (richiede OCR popup lente coord)

---

## Problemi aperti

| Problema | Task | Priorita' | Nota |
|----------|------|-----------|------|
| Slot reale non letto da OCR | raccolta | MEDIA | RT-12: integrare leggi_contatore_slot() |
| ETA marcia sempre None | raccolta | MEDIA | RT-12: OCR maschera invio |
| Blacklist chiave approssimata | raccolta | BASSA | Coordinate reali richiedono OCR popup |
| `pin_speed_use` score -1.000 | boost | MEDIA | Template da rifare |
| `pin_oil_refinery.png` score basso | raccolta | BASSA | Template da rifare |
| NMS cross-template store | store | MEDIA | pin_acciaio+pin_pomodoro stessa cx,cy |

---

## Principio fondamentale

> **Leggere SEMPRE i file V5 prima di scrivere qualsiasi primitiva.**
> Zone OCR, coordinate UI, template names, logica di parsing, metodi ADB —
> tutto e' gia' calibrato e funzionante in V5.
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

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` |
| Navigator | `ctx.navigator.vai_in_home()` | `await ctx.navigator...` |
| Template matching | `matcher.find_one()`, `matcher.score()` | `matcher.match()`, `matcher.find()` |
| Screenshot frame | `screen.frame` | `device.last_frame` |

---

## Template disponibili in templates/pin/ (42 file)

```
pin_region.png          pin_shelter.png
pin_vip_01..07.png      (7 file VIP)
pin_boost.png           pin_manage.png
pin_speed.png           pin_50_.png
pin_speed_8h.png        pin_speed_1d.png        pin_speed_use.png
pin_gather.png          pin_march.png
pin_field.png           pin_sawmill.png
pin_steel_mill.png      pin_oil_refinery.png
pin_store.png           pin_store_attivo.png    pin_mercante.png
pin_merchant.png        pin_merchant_close.png  pin_carrello.png
pin_banner_aperto.png   pin_banner_chiuso.png
pin_legno.png           pin_pomodoro.png        pin_acciaio.png
pin_free_refresh.png    pin_no_refresh.png
pin_arena_01..07.png    (7 file arena)
pin_arena_check.png     pin_arena_no_check.png
pin_360_open/close.png  pin_15_open/close.png
pin_msg_02..04.png      pin_claim.png
btn_resource_supply_map.png
```

---

## Coordinate di riferimento (960x540)

| Costante | Valore | Fonte V5 | Task |
|----------|--------|----------|------|
| `TAP_TOGGLE_HOME_MAPPA` | `(38, 505)` | `config.py` | navigator |
| `_ZONA_TESTO_SLOT` | `(890,117,946,141)` | `ocr.py` | slot |
| `TAP_LENTE` | `(38, 325)` | `config.py` | raccolta |
| `TAP_NODO` | `(480, 280)` | `config.py` | raccolta |
| `TAP_RACCOGLI` | `(230, 390)` | `config.py` | raccolta |
| `TAP_SQUADRA` | `(700, 185)` | `config.py` | raccolta |
| `TAP_MARCIA` | `(727, 476)` | `config.py` | raccolta |
| `TERRITORIO_BUFF_ZONA` | `(250,340,420,370)` | `verifica_ui.py` | raccolta |
| `TAP_ICONA campo` | `(410, 450)` | `config.py` | raccolta |
| `TAP_ICONA segheria` | `(535, 450)` | `config.py` | raccolta |
| `TAP_ICONA acciaio` | `(672, 490)` | `config.py` | raccolta |
| `TAP_ICONA petrolio` | `(820, 490)` | `config.py` | raccolta |
| ARENA `tap_campaign` | `(584, 486)` | `config.py` V5 layout 1 | arena |
| ARENA `tap_arena_of_doom` | `(321, 297)` | `config.py` V5 | arena |
| ARENA `tap_ultima_sfida` | `(745, 482)` | `config.py` V5 | arena |
| ARENA `tap_start_challenge` | `(730, 451)` | `config.py` V5 | arena |
| ARENA `tap_skip_checkbox` | `(723, 488)` | screenshot reale | arena |
| MSG `tap_icona_messaggi` | `(928, 430)` | `config.py` V5 | messaggi |
| VIP `tap_badge` | `(85, 52)` | `vip.py` V6 | vip |
| ALLEANZA `coord_alleanza` | `(760, 505)` | `alleanza.py` V5 | alleanza |
