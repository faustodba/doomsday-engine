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

## Piano test runtime — Stato al 14/04/2026

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
| RT-15 | Arena + ArenaMercato | ⏳ | fix timeout 15s; da testare su FAU_01 |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dopo fix issues aperti |
| RT-14 | Full farm 12 istanze | ⏳ | |

---

## Issues aperti (priorità)

### 1. Rifornimento — da mettere a punto (ALTA)
- **Stato:** task disabilitato in runtime. Da verificare con log reale.
- **Azione:** abilitare `RIFORNIMENTO_ABILITATO=True` + `RIFORNIMENTO_MAPPA_ABILITATO=True`
  in `runtime.json`, lanciare tick su FAU_00 (ha slot rifornimento), analizzare log.
- **File V5:** `rifornimento_mappa.py` — leggere prima di qualsiasi modifica V6.

### 2. Arena — timeout battaglia ~~38s → 60s~~ (CHIUSA)
- **Risolto 14/04/2026:** skip checkbox attivo → animazione saltata → 8s delay sufficiente.
- `_MAX_BATTAGLIA_S` portato a **15.0** (totale 8s+15s=23s, abbondante con skip).
- **TODO pin mancanti:**
  - `pin_arena_video.png` — popup video primo accesso (non necessario: già skippato)
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

### Priorità 0 — RT-15 Arena + ArenaMercato
```
1. Copiare arena.py in C:\doomsday-engine\tasks\
2. Verificare runtime.json:
     "ARENA_ABILITATO": true
     "ARENA_MERCATO_ABILITATO": true
3. Lanciare: python main.py --istanze FAU_01 --tick-sleep 10
4. Monitorare log:
     [ARENA] [SKIP] Skip già attivo ✓
     [ARENA] fine battaglia in X.Xs totali
     [MERCATO-ARENA] loop completato — pack360=X pack15=X
5. Caricare log e aggiornare ROADMAP
```

### Priorità 1 — Rifornimento
```
1. Abilitare in runtime.json:
     "RIFORNIMENTO_ABILITATO": true
     "RIFORNIMENTO_MAPPA_ABILITATO": true
2. Lanciare: python main.py --istanze FAU_00 --tick-sleep 10
3. Analizzare log rifornimento completo
4. Upload rifornimento.py + rifornimento_mappa.py V6 se serve fix
```

### Priorità 2 — Rifornimento mappa
```
arena.py: _MAX_BATTAGLIA_S già fixato → 15.0
```

---

## Metodologia di lavoro (vincolante)

| # | Regola | Dettaglio |
|---|--------|-----------|
| 1 | **Versione locale** | Chiedere sempre il file locale prima di modificare se non si è certi di avere l'ultima versione |
| 2 | **Mai frammenti di codice** | Rilasciare sempre file completi, mai snippet parziali |
| 3 | **Batch release** | Ogni rilascio = copia file in `C:\doomsday-engine\tasks\` + commit+push su `faustodba/doomsday-engine` |
| 4 | **ROADMAP costante** | Aggiornare ROADMAP ad ogni sessione: fix applicati, stato RT, issues |
| 5 | **Fasi semplici** | Scomporre ogni processo in passi elementari |
| 6 | **Passo-passo** | Eseguire un passo alla volta, non anticipare |
| 7 | **Feedback** | Chiedere conferma dopo ogni passo prima di procedere |
| 8 | **Miglioramenti** | Proporre miglioramenti a fine sessione o quando rilevati |

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
