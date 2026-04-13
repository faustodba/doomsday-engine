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
| 16 | `tasks/arena.py` | ✅ 10/10 | |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 57/57 | territorio + allocation gap V5 |
| 22 | `core/orchestrator.py` | ✅ 49/49 | |
| 23 | `dashboard/` | ✅ 30/30 | |
| 24-25 | Fix + refactoring | ✅ | |
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
| RT-12 | Tick completo FAU_01 | ✅ | Tick completo funzionante — vedi issues sotto |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dopo fix issues RT-12 |
| RT-14 | Full farm 12 istanze | ⏳ | |

---

## Issues aperti da RT-12 (priorità)

### 1. Arena mercato — navigazione sbagliata (ALTA)
- **Problema:** V6 `arena_mercato.py` usa `pin_arena_01_lista` per rilevare
  l'arena store, ma quel template è per la lista sfide — score sempre -0.038.
- **Fix:** Il mercato arena è accessibile con `TAP_CARRELLO=(905,68)` DENTRO
  la schermata arena (già aperta dopo `_naviga_a_arena`). NON serve secondo
  tentativo di navigazione. Riscrivere `arena_mercato.py` seguendo V5:
  `_naviga_a_arena()` → `tap carrello (905,68)` → acquisto pack 360/15 → BACK.
- **File V5 riferimento:** `arena_of_glory.py` → `run_mercato_arena()` +
  `_visita_mercato_arena()`. Template: `btn_360_open/close`, `btn_15_open/close`.
  Coordinate: `TAP_CARRELLO=(905,68)`, `TAP_PRIMO=(235,283)`,
  `TAP_MAX=(451,286)`, `TAP_PACK15=(788,408)`, `TAP_PACK15_MAX=(654,408)`.

### 2. Arena — timeout battaglia sfide 2 e 4 (MEDIA)
- **Problema:** Sfide 2 e 4 timeout dopo 38s — victory/failure non rilevati.
  La battaglia è probabilmente ancora in corso (animazioni > 38s).
- **Fix:** Aumentare `TIMEOUT_BATTAGLIA` da 38s a 60s. Verificare visivamente
  quanto durano le battaglie più lunghe su FAU_01.
- **TODO pin mancanti:**
  - `pin_arena_video.png` — popup video introduttivo primo accesso
  - `pin_arena_categoria.png` — popup categoria settimanale (lunedì)

### 3. Zaino — deposito non passato dall'orchestrator (MEDIA)
- **Problema:** `ZainoTask.run()` riceve `ctx` senza `deposito` OCR.
  Il deposito viene letto in `RaccoltaTask` ma non condiviso.
- **Fix:** Leggere `ocr_risorse()` nell'orchestrator PRIMA di eseguire i task,
  salvarlo in `ctx.state` e passarlo a Zaino. Alternativa: leggere in `ZainoTask.run()`.
- **Priorità:** dopo rifornimento e radar.

### 4. Rifornimento — da mettere a punto (ALTA)
- **Stato:** task disabilitato in runtime. Da verificare con log reale.
- **Azione:** abilitare `RIFORNIMENTO_ABILITATO=True` in `runtime.json`,
  lanciare tick su FAU_00 (che ha slot rifornimento), analizzare log.
- **File V5:** `rifornimento_mappa.py` — leggere prima di qualsiasi modifica V6.

### 5. Radar — da mettere a punto (ALTA)
- **Stato:** task esegue ma non logga nulla (skip silenzioso).
- **Azione:** leggere `radar_census.py` V5 + `radar.py` V6 per capire
  cosa manca. Il radar richiede istanza in MAPPA con radar aperto.
- **File V5:** `radar_census.py` — classifier Random Forest già trainato.

### 6. Store NMS cross-template (BASSA)
- `pin_acciaio.png` = `pin_pomodoro.png` (stesso file) → stesso cx,cy.
  Quando sarà disponibile il vero `pin_acciaio.png`, il NMS si risolve.

---

## Prossima sessione — Fix arena_mercato + rifornimento

### Step 1: Fix arena_mercato.py
Leggere `C:\doomsday-engine\tasks\arena_mercato.py` V6 attuale.
Riscrivere seguendo V5 `arena_of_glory.py → run_mercato_arena()`.
Flusso corretto:
1. `HOME → Campaign → Arena of Doom` (riusa `_naviga_a_arena`)
2. `tap carrello (905,68)` → attesa 2s → Arena Store aperto
3. Loop acquisto pack 360: `btn_360_open/close` → `tap (235,283)` → `tap (451,286)`
4. Se 360 esaurito → pack 15: `btn_15_open/close` → `tap (788,408)` → `tap (654,408) x34`
5. BACK → home

### Step 2: Rifornimento
```
Abilitare in runtime.json:
  "RIFORNIMENTO_ABILITATO": true
  "RIFORNIMENTO_MAPPA_ABILITATO": true
Lanciare: python main.py --istanze FAU_00 --tick-sleep 10
Analizzare log rifornimento.
```

---

## Fix applicati in sessione 13/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Porta FAU_01 | `instances.json` | 16448 → 16416 |
| VIP retry cassaforte | `vip.py` | wait_open_badge 2→3s + retry 1.5s se nessun pin |
| Raccolta skip neutro | `raccolta.py` | territorio FUORI → skip_neutro=True → fallimenti_cons invariato |
| Raccolta allocation | `raccolta.py` | logica gap V5 allocation.py integrata; OCR deposito → sequenza ottimale |
| Raccolta OCR slot | `raccolta.py` | leggi_contatore_slot() in run() — lettura slot reale da schermo |
| Raccolta pin_march | `raccolta.py` | pin_marcia → pin_march (nome corretto) |
| Raccolta delay livello | `raccolta.py` | 0.15s/tap MENO + 0.2s/tap PIU |
| Raccolta blacklist tipo | `raccolta.py` | chiave tipo_X invece di coordinate fisse |
| Raccolta territorio | `raccolta.py` | pixel check V5 zona(250,340,420,370) soglia 20px verdi |

---

## Coordinate di riferimento (960x540)

| Costante | Valore | Task |
|----------|--------|------|
| `TAP_TOGGLE_HOME_MAPPA` | `(38, 505)` | navigator |
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
| ARENA `tap_campaign` | `(584, 486)` | arena layout 1 |
| ARENA `tap_arena_of_doom` | `(321, 297)` | arena |
| ARENA `tap_ultima_sfida` | `(745, 482)` | arena |
| ARENA `tap_start_challenge` | `(730, 451)` | arena |
| ARENA `tap_skip_checkbox` | `(723, 488)` | arena |
| ARENA `tap_carrello` | `(905, 68)` | arena_mercato |
| ARENA `tap_primo_360` | `(235, 283)` | arena_mercato |
| ARENA `tap_max_360` | `(451, 286)` | arena_mercato |
| ARENA `tap_pack15` | `(788, 408)` | arena_mercato |
| ARENA `tap_pack15_max` | `(654, 408)` | arena_mercato |
| MSG `tap_icona_messaggi` | `(928, 430)` | messaggi |
| VIP `tap_badge` | `(85, 52)` | vip |
| ALLEANZA `coord_alleanza` | `(760, 505)` | alleanza |

---

## Standard architetturale V6 (vincolante)

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` |
| Navigator | `ctx.navigator.vai_in_home()` | `await ctx.navigator...` |
| Template matching | `matcher.find_one()`, `matcher.score()` | `matcher.match()`, `matcher.find()` |
| Screenshot frame | `screen.frame` | `device.last_frame` |

**REGOLA ASSOLUTA:** Leggere SEMPRE il file V5 corrispondente prima di
scrivere qualsiasi primitiva. Zone OCR, coordinate UI, template names,
logica di parsing — tutto è già calibrato in V5.

---

## Template disponibili in templates/pin/ (42 file)

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
```

**Template mancanti (TODO):**
- `pin_acciaio.png` — reale (attuale = pin_pomodoro)
- `pin_arena_video.png` — popup video primo accesso arena
- `pin_arena_categoria.png` — popup categoria settimanale arena (lunedì)
- Template arena mercato: `btn_360_open/close`, `btn_15_open/close`
