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
| 26 | `dashboard/` V6 rewrite | ✅ | FastAPI+HTMX, 6 test client, commit `9773de3` |
| **nav** | `core/navigator.py` | ✅ 20/20 | tap_barra() TM barra inferiore |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Piano test runtime — Stato al 21/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01..05 | Infrastruttura, navigator, OCR, slot | ✅ | |
| RT-06 | VIP claim | ✅ | |
| RT-07 | Boost | ✅ | BoostState scheduling 16/04/2026. RIAPERTO 19/04 (tap non responsivo) → RISOLTO 19/04 (tap `speed_cx/speed_cy`, cy<400 responsivo, polling `pin_speed_use` 4s). Verificato FAU_00 test isolato ore 18:12 + FAU_01 ciclo completo da freddo: boost 8h attivato entrambi. |
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
| RT-22 | Ciclo notte prod 20→21/04 | 🟡 | 25 cicli 22:30→05:51, raccolta 24OK/6ERR. Rifornimento validato 11/11 istanze → **68 spedizioni, ~140.7M risorse** a FauMorfeus (legno 91.8M, petrolio 31.8M, pomodoro 17.1M). **Aperti:** arena 5 istanze KO (Issue #14), engine_status stale (#15), OCR legno anomalo FAU_10 (#16). |

---

## Issues aperti (priorità)

### Issue chiuse — Sessione 03/05 notte (WU101-104 — Master istanza generalizzato + Fix raccolta + Predictor 5-invii)

#### Issue trovata: tutte le istanze skippano raccolta dopo modifica dashboard ✅ (Fix A + B)

**Sintomo**: dalle 18:23 UTC del 03/05, tutti i tick mostravano `Orchestrator: [raccolta] should_run=False → saltato`. Validato su FAU_01 ciclo 18:45-18:48 (rifornimento OK, raccolta SKIP).

**Root cause**: il modello Pydantic `TaskFlags` ([dashboard/models.py:40-78](dashboard/models.py)) **non aveva il campo `raccolta`** (commentato "non controllabile, gira sempre"). Conseguenza: ogni `_save_ov(ov)` chiamato da PUT /globals, /rifornimento, /zaino, /allocazione, /istanze, PATCH toggle, ecc. faceva `model_dump()` serializzando solo i 15 task **senza** raccolta. La chiave veniva quindi rimossa da `runtime_overrides.json::globali.task` ad ogni salvataggio. Fallback su `global_config.json::task.raccolta = false` (baseline reset WU94) → raccolta disabilitata su tutte le istanze.

**Fix A (immediato, hot-reload)**: aggiunta `"raccolta": true` direttamente in `runtime_overrides.json::globali.task` per ripristinare al prossimo tick.

**Fix B (root cause)**: aggiunto `raccolta: bool = True` al modello `TaskFlags`. UI non lo espone come toggle (resta sempre ON), ma la chiave è preservata nel JSON ad ogni `_save_ov`.

**Validazione**: `TaskFlags().raccolta = True`, `model_fields` include `raccolta`. Da prossimo restart dashboard, ogni save preserva la chiave automaticamente.

#### WU101. Master istanza — flag config-driven generalizzato ✅

**Obiettivo**: marcare un'istanza come "rifugio destinatario" (riceve risorse via rifornimento ma non invia) per escluderla dagli aggregati ordinari (telemetria, predictor, ranking dashboard). Generalizzato per supportare N master, non solo FauMorfeus.

**Componenti** (1 modulo nuovo + 9 punti di esclusione + UI):

1. **`shared/instance_meta.py`** (NEW ~115 righe) — helper config-driven:
   - `is_master_instance(nome) → bool` (cache 30s)
   - `get_master_instances() → frozenset[str]`
   - `filter_ordinary(istanze) → list[str]`
   - `invalidate_cache()` per forzare refresh dopo PATCH
   - Lettura: `instances.json::[].master` (default statico) + `runtime_overrides.json::istanze.<nome>.master` (override hot, prevale)

2. **Schema config esteso**:
   - `IstanzaOverride.master: bool = False` ([dashboard/models.py:222](dashboard/models.py))
   - `InstanceStats.master: bool = False` ([dashboard/models.py:374](dashboard/models.py))
   - `instances.json::[].master` persistito da `save_instances_fields` (allowed_fields esteso)

3. **9 punti di esclusione lato server**:
   - `core/skip_predictor.py::predict()` — early return `should_skip=False, reason="master_instance"`
   - `tools/predictor_shadow.py` — filtra master nel grouping
   - `dashboard/services/stats_reader.py::get_truppe_storico_aggregato` — espone master in campo dedicato `master_row`
   - `dashboard/services/stats_reader.py::get_all_stats(include_master=False)` — esclusione opt-in
   - `dashboard/services/stats_reader.py::get_produzione_istanze` — esclude master da card produzione
   - `dashboard/services/stats_reader.py::get_risorse_farm` — non somma master ai totali
   - `dashboard/services/stats_reader.py::get_produzione_storico_24h` — esclude master da sparkline 12h
   - `dashboard/services/telemetry_reader.py::_compute_trend_7gg` — esclude master da sum giornalieri
   - `core/telemetry.py::_build_rollup_from_events` — esclude master da `live.json::per_instance/per_task/totals/anomalies`

4. **Dashboard UI**:
   - `config_global.html` tabella istanze: colonna "M" toggle + ★ accanto al nome
   - `partials/card_istanza.html`: ★ + class `card-master`
   - `app.py::partial_truppe_storico`: riga master con sfondo dorato `#f5c542` separata dal totale

5. **Cache invalidation**: `invalidate_cache()` chiamato automaticamente in PUT `/api/config/istanze` quando il flag master può essere cambiato.

6. **Migrazione**: FauMorfeus.master=true sia dev che prod, sia in instances.json che in runtime_overrides.json. Tutte le altre istanze hanno `master: false` esplicito.

**Smoke test 7/7 verdi**:
- `is_master_instance('FauMorfeus')=True`, `is_master_instance('FAU_00')=False`
- `predict('FauMorfeus').reason=master_instance, should_skip=False`
- `get_produzione_istanze()` → 11 istanze (no FauMorfeus)
- `get_truppe_storico_aggregato()` → per_istanza len=11 + master={nome:FauMorfeus,...}
- `InstanceStats(FauMorfeus).master=True`

#### WU102. TaskFlags.raccolta — fix root cause Bug A ✅

Vedi sezione "Issue trovata" sopra. Modifica minima (1 campo aggiunto al modello Pydantic) con docstring dettagliata che spiega il bug storico per evitare regressione futura.

#### WU103. Predictor 5-invii target + rifornimento metrics ✅

**Estensione skip predictor** per valutare cicli combinando raccolta + rifornimento.

1. **Hook rifornimento metrics** ([core/istanza_metrics.py](core/istanza_metrics.py)):
   ```python
   aggiungi_invio_rifornimento(istanza, risorsa, qta_netta, eta_residua_s)
   ```
   Hook in `tasks/rifornimento.py` (mappa+membri) post-`registra_spedizione`. Schema record esteso con `rifornimento.invii[]` accanto a `raccolta.invii[]`.

2. **Nuova regola predictor** `_rule_low_total_invii` ([core/skip_predictor.py](core/skip_predictor.py)):
   - `TARGET_INVII_CICLO = 5` (configurable tunable)
   - `LOW_INVII_AVG_RATIO = 0.5` → soglia avg = 2.5
   - Logica: ultimi 3 cicli, se avg(raccolta.invii + rifornimento.invii) < 2.5 → skip suggerito (score 0.60)
   - **Guard**: regola disattiva se nessun ciclo della finestra ha rifornimento (copre già `_rule_trend_magro`)

3. **Tool predictor_shadow esteso** con sezione "Valutazione rifornimento":
   ```
   istanza    cicli rif_on rif_off avg_inv_on avg_inv_off  delta
   ```
   Confronta avg_total_invii con/senza rifornimento per stimare ROI del task.
   Pre-restart: 426 record/3gg → tutti `rif_off=N, rif_on=0` (rifornimento.invii non era tracciato). Post-restart: la sezione si popolerà con dati reali.

#### Issue BASSE chiuse in batch — sessione 03/05 notte tarda ✅

5 issue BASSE chiuse contemporaneamente:

- **#5 Alleanza coord hardcoded — WU111** (correzione 03/05 sera, wontfix iniziale errato). Pre-fix: `_esegui_alleanza` usava `device.tap(*coord_alleanza)` coord fissa (760, 505). Pattern obsoleto: gli altri task (donazione/rifornimento/arena/arena_mercato) usano `nav.tap_barra(ctx, "alliance")` con template matching dinamico (`pin_alliance.png`). Su istanze con barra inferiore con meno bottoni il bottone Alliance shifta → tap fisso falliva. **Fix**: `_esegui_alleanza(ctx, device, ...)` ora prima tenta `nav.tap_barra(ctx, "alliance")`, fallback a coord fissa se navigator None o tap_barra ritorna False. Pattern coerente con altri task. Note: 15 test pre-esistenti in test_alleanza.py falliscono per `cfg.coord_rivendica` obsoleto (debt pre-esistente, no regressione fix).

- **#19 stdout race buffer** — fix `set PYTHONUNBUFFERED=1` aggiunto a `run_prod.bat`. Stdout line-buffered → no race finale ciclo. Effetto al prossimo restart bot.

- **#21 gitignore + rifornimento_mappa.py legacy** — verificato: `.gitignore` 0 duplicati (61 righe), `rifornimento_mappa.py` legacy file inesistente, riferimenti residui solo in commenti storici. **Bonus fix**: `index.html` schema legacy (`cfg.rifornimento_mappa.abilitato`/`rifornimento_membri.abilitato`) migrato a schema unificato (`cfg.rifornimento.mappa_abilitata`/`membri_abilitati`) post-WU40/WU94. Pannello rifornimento overview ora rispecchia config reale.

- **#23 smoke_test GlobalConfig dict vs dataclass** — `smoke_test.py::check_ctx` passava `{}` (dict) a `_build_ctx(ist, gcfg, ...)` → `gcfg.livello_nodo` falliva con `'dict' object has no attribute`. Fix: `gcfg = load_global()` + carica `runtime_overrides.json` per `ist_overrides` per-istanza + assert `task_abilitato` `isinstance bool` invece di `is True` (post-WU94 baseline reset task default OFF). Validato: 12/12 istanze TaskContext OK.

- **#25 Tracciamento diamanti nello state** — pre-fix: `ProduzioneSession.diamanti_iniziali` salvato in `apri_sessione`, ma `chiudi_sessione_e_calcola(risorse_finali, ts_fine)` non riceveva `diamanti_finali` → delta mai calcolato. Fix: aggiunti campi `diamanti_finali: int = -1` + `diamanti_delta: int = 0` a `ProduzioneSession` (with `from_dict`/`to_dict`), parametro `diamanti_finali` opzionale in `chiudi_sessione_e_calcola`, chiamata in `main.py` ora passa `rd.diamanti`. Smoke test: round-trip OK, delta calcolato correttamente (test +20 diamanti accumulati).

#### WU89-Step4. Skip Predictor live hook (flag-driven) ✅

**Obiettivo**: portare in produzione il predictor implementato in shadow-only Step 3 (03/05). Permette di **skippare cicli inefficaci** prima dell'avvio MuMu (saving ~600s/skip).

**Vincolo utente**: nessuna modifica struttura/funzionalità bot — comportamento attuale invariato di default. Attivazione controllata da flag.

**Architettura 3-stati** (controllata da 2 flag in `globali`):

| `enabled` | `shadow_only` | Comportamento |
|-----------|---------------|---------------|
| **False** | * | No-op completo. Bot identico ad oggi (default deploy) |
| **True** | **True** | Predict + log + telemetria, **no skip applicato** |
| **True** | **False** | Predict + log + telemetria + **applica skip** se `should_skip=True` |

**Hook position** (`main.py::_thread_istanza`):

```
1. Setup contatori, ctx, orchestrator
2. Restore schedule
3. ★ NUOVO: Skip Predictor hook (early-return su skip)
4. Avvio MuMu (avvia_istanza)
5. Boot HOME + tick task
```

Posizione strategica: PRIMA di `avvia_istanza` → se skip applicato evitiamo TUTTO il costo del boot (settings, attendi_home, banner dismissal, task).

**Componenti aggiunti** (`main.py` solo):

1. **Module-level state** (~5 righe):
```python
_predictor_states: dict = {}              # IstanzaSkipState per nome
_predictor_decisions_lock = threading.Lock()
```

2. **Helper telemetria** `_append_predictor_decision(nome, decision, mode, applied)` (~25 righe):
   - Append JSONL a `data/predictor_decisions.jsonl`
   - Schema: `{ts, instance, mode, should_skip, reason, score, signals, growth_phase, guardrail, applied}`
   - `applied=True` solo se LIVE + should_skip + no guardrail block
   - Best-effort (silent on I/O error)

3. **Hook block** in `_thread_istanza` post-restore-schedule (~50 righe):
   - Read flag `gcfg.skip_predictor_enabled` → no-op se False
   - `predict(nome, history, state=skip_state)` con history da `load_metrics_history(last_n=20)`
   - Log decisione `[PREDICTOR-{mode}] should_skip=... reason=...`
   - Append a JSONL
   - Se `applied`: increment `last_skip_count_consec`, chiama `chiudi_tick(outcome="skipped_by_predictor")`, aggiorna stato istanza, **early return**
   - Se non skip: reset `last_skip_count_consec=0`, increment `cicli_totali`
   - Try/except attorno tutto: errore predictor = continua flow normale

**Failsafe**:
- `gcfg.skip_predictor_enabled=False` (default) → 0 impact, hook no-op
- Try/except: errore predictor non blocca bot
- Reset state count su no-skip
- Guardrail già implementato in `predict()` Step 3 (max 3 skip consec → forza retry, RE_EVAL_CICLI=6, COOLDOWN_POST_RETRY_CICLI=2)
- Master istanze sempre `should_skip=False` (early return in `predict()`)

**Smoke test 3/3 scenari**:
- proceed shadow (no skip) → applied=False, log mode=SHADOW
- skip live applied → applied=True, log mode=LIVE, early return
- skip shadow not applied → applied=False, log mode=SHADOW

**Telemetria** (`data/predictor_decisions.jsonl` NEW):
```json
{"ts": "2026-05-04T...", "instance": "FAU_09", "mode": "LIVE",
 "should_skip": true, "reason": "low_total_invii", "score": 0.6,
 "signals": {"avg_3": 1.8, "target": 5}, "growth_phase": false,
 "guardrail": null, "applied": true}
```

Alimenta Step 5 (dashboard precision/recall) in futuro.

**Workflow operativo attivazione**:

1. **Deploy + restart bot** → flag default `enabled=False` → bot invariato
2. **Test shadow** (1-2 giorni): da dashboard config setta `enabled=True, shadow_only=True` → tick successivo logga decisioni senza tagliare. Hot-reload, no restart richiesto.
3. **Analizza** dopo 6-12 cicli: leggi `predictor_decisions.jsonl`. Verifica:
   - Quante "skip suggested" sono effettivamente cicli inutili (precision)
   - Quanti cicli inutili NON sono identificati (recall)
   - Se `guardrail_triggered` blocca pattern utili
4. **Attiva live**: se metrics OK → setta `shadow_only=False` → predictor inizia a tagliare cicli inefficaci. Saving stimato: ~480-600s × N skip/giorno.

#### WU-CycleAccuracy. Cycle Predictor recorder + accuracy fine-ciclo + drilldown what-if ✅

Background task in dashboard `lifespan` esegue ogni 15 min:
1. **`record_snapshot()`**: append `data/predictions/cycle_snapshots.jsonl` con
   `{ts, cycle_numero, elapsed_min, predicted_min, n_istanze, confidence,
     input_context: {istanze_abilitate, task_globali_abilitati,
                     tasks_per_istanza_due, per_istanza_predicted_s,
                     tick_sleep_s}}`. Auto-correlazione cycle_numero
   leggendo `cicli.json::ciclo in corso`.
2. **`evaluate_cycles()`**: per cicli completati non ancora valutati
   calcola `actual_min = end - start` + per ogni snapshot
   `error_pct = |predicted - actual| / actual × 100`. Output
   `data/predictions/cycle_accuracy.jsonl`.

**Pagina dedicata `/ui/predictor`** (NEW): 3 sezioni:
- Cycle Predictor: stima corrente schedule-aware + drilldown
  what-if (T_ciclo se skippo istanza X) + accuracy storica
- Skip Predictor: live decisions stream + futuro accuracy panel
- Configurazione: link a toggle home + tool CLI

**File**: `core/cycle_predictor_recorder.py` (NEW ~210), endpoint
`/ui/partial/cycle-snapshot-detail` + `/ui/partial/cycle-accuracy`,
`dashboard/templates/predictor.html` (NEW), nav link in `base.html`,
pannelli predictor rimossi da `/ui/telemetria` (consolidamento).

**Use-case what-if**: per ogni istanza la riga del drilldown mostra
"T_ciclo skip" = T_ciclo - T_istanza, con saving in min e %. Permette
decisioni informate su quale istanza disabilitare temporaneamente.

#### WU-CycleDur. Cycle Duration Predictor — stima durata ciclo bot schedule-aware ✅

**Obiettivo**: predire `T_ciclo` del bot (come gap_atteso per skip
predictor + planning + tuning tick_sleep_min).

**Modello**: `T_ciclo = Σ_istanza (boot_home_median + Σ task_due_median) + tick_sleep_s`.

**Schedule-aware (strict_schedule=True)**:
- Lettura `state[istanza].schedule[task]` = ISO last_run
- Lettura `task_setup.json` per `interval_hours` + schedule type
- `_is_task_due(task, entry, last_run, now_utc)`:
  - `schedule="always"` o `interval=0` → sempre
  - `last_run=None` → primo run, gira
  - `elapsed_h < interval_h` → no skip
  - Edge `main_mission`: gate UTC≥20 (WU91)
- Per tipologia istanza: raccolta_only/raccolta_fast/full filtrata

**Rolling stats**: median ultimi 20 record da `istanza_metrics.jsonl`.
Cache TTL 30min.

**Output prod 04/05**:
```
STRICT  T_ciclo: 81.5 min   (rispetta schedule)
OLD     T_ciclo: 125.7 min  (sovrastimata)
Delta:  44.2 min eliminati
```

**Confidence**: alta (≥10 samples), media (3-9), bassa (<3).

**Tool CLI**: `python tools/predict_cycle.py --prod [--verbose] [--istanza X]`.

**Vincolo memoria**: aggiunta/modifica task richiede aggiornamento
sincrono di `core/cycle_duration_predictor.py::CLASS_TO_TASK_NAME` +
edge cases in `_is_task_due` (memoria `feedback_cycle_predictor_sync`).

**File**: `core/cycle_duration_predictor.py` (NEW ~360),
`tools/predict_cycle.py` (NEW ~100), `config/predictor_t_l_max.json`
(NEW baseline 11 istanze × 3 livelli + multiplier per-istanza FAU_00=1.0,
default=1.3, FAU_09=1.5, FAU_10=1.4).

**Refactor `core/skip_predictor.py::_rule_squadre_fuori`**:
da threshold statico `2 × avg_eta + 30s` a modello empirico
`T_min_rientro vs gap_atteso` dinamico:
```
T_marcia[i]    = 2 × eta_i + sat_i × T_L_max[livello_i, istanza]
sat_i          = load_squadra_i / cap_nominale_L_max[livello_i, tipo_i]
T_min_rientro  = min(T_marcia[i] for i in invii)
gap_atteso     = predict_cycle_duration() / 60   # via cycle predictor

SE attive_post=totali AND T_min_rientro > gap_atteso → SKIP score 0.90
```

#### WU121. Master FauMorfeus ripristino + ★ marker uniforme dashboard ✅

**Diagnosi utente**: master indicator FauMorfeus assente in dashboard — verifica `is_master_instance("FauMorfeus") = False`, `get_master_instances() = frozenset()` vuoto.

**Root cause**: flag perso da config (probabile artefatto save dashboard recente con Pydantic che setta default `master=False` per chiavi non esplicitamente passate).

**Fix**:
- `instances.json` (prod) — `FauMorfeus.master = true` (dev era già OK)
- `runtime_overrides.json` (prod) — `istanze.FauMorfeus.master = true` (dev OK)
- Cache invalidata via `shared.instance_meta.invalidate_cache()`
- `dashboard/app.py::partial_ist_table` ([app.py:660+](dashboard/app.py)) aggiunto ★ marker accanto al nome se `is_master_instance(nome)` — era l'unico pannello che mancava (gli altri 4: produzione-istanze cards, truppe-storico, ist-table /ui/config/global, copertura-cicli avevano già la logica).

**Validazione**: 4/4 pannelli renderizzano ★+FauMorfeus correttamente.

**Effetto**: i 9 punti di esclusione server-side (predictor, telemetry, rollup farm, copertura squadre) tornano a operare. FauMorfeus non più sommata con istanze produttive nei totali farm.

#### WU120. Bug tick_sleep unit mismatch — campo secondi, save minuti ✅

**Sintomo utente**: dashboard mostra `tick sleep 1800` (= 30 min) inaspettato dopo save.

**Root cause** ([dashboard/templates/index.html:43-46](dashboard/templates/index.html) pre-fix):
- Display: `value="{{ cfg.sistema.tick_sleep }}"` → SECONDI (es. 1800)
- Label: `tick sleep (s)`
- Save: `sistema: {tick_sleep_min: gi('g-sleep')}` → backend `SistemaOverride.tick_sleep_min` (MINUTI, ge=0 le=1440)

→ Utente inserisce 30 (intendendo 30 secondi per debug rapido) → backend salva 30 minuti → al refresh display mostra 30×60=1800 secondi → confusione.

**Fix**: campo unificato in MINUTI:
```jinja
value="{{ ((cfg.tick_sleep|int) // 60) }}"
min="1" max="1440" step="1"
title="intervallo tra cicli bot in minuti (1-1440)"
```
+ label `tick sleep (min)`.

`config_global.html` (pagina `/ui/config/global`) NON toccata — usa schema baseline `tick_sleep` in secondi direttamente, già coerente.

**Bonus diagnosi**: prod aveva `tick_sleep_min=300` (5h!) — artefatto dello stesso bug. Post-fix display mostra "300 min", utente correggerà a 5 (validato `feedback_tick_sleep_rifornimento.md`) o 15 (post-rifornimento attivato).

#### WU119. Riordino risorse uniformato pomodoro/legno/acciaio/petrolio ✅

**Sintomo utente**: card rifornimento/zaino non rispettavano l'ordine canonico richiesto `🍅 pomodoro → 🪵 legno → ⚙ acciaio → 🛢 petrolio`. Pre-fix: alcuni pannelli mostravano `... petrolio/acciaio` (swap).

**Fix coerente in 3 file**:
- `dashboard/templates/index.html` — 5 modifiche: rifornimento card (line 91), zaino card (171), sidebar res-totali sezioni "raccolto" e "nodi" (277, 285), ora-tbl header (305), JS `updateAllocTotal` array (418)
- `dashboard/templates/config_global.html` — 3 modifiche: rifornimento card (95), zaino card (156), JS `gcUpdateAllocTotal` array (361)
- `dashboard/services/stats_reader.py` — `_RISORSE_STANDARD` tuple + tupla locale `_load_storico_farm_today`

**Validazione automatica**: 7/7 endpoint check posizione emoji nell'HTML rendered:
```
/ui              order ok ✓ (🍅<🪵<⚙<🛢)
/ui/config/global order ok ✓
/ui/partial/res-totali order ok ✓
+ /ui/telemetria, /ui/partial/res-oraria, /ui/partial/produzione-istanze, /ui/partial/copertura-cicli
```

#### WU118. Refactor dashboard — telemetria/storico pagine separate + copertura squadre + report ciclo ✅

**Pre-refactor**: home `/ui` con 8 tel-card + storico eventi + cards istanze + cfg4 + tabella istanze + sidebar — pagina overcrowded.

**Refactor 7-step**:

1. **`dashboard/templates/telemetria.html`** (NEW ~120 righe) — pagina dedicata con 8 tel-card spostate da home: telemetria task, storico cicli, health 24h, ciclo corrente, tempi medi 7gg, storico truppe, debug screenshot per task, **+ copertura squadre 5 cicli** (NEW)

2. **`dashboard/templates/storico.html`** (NEW ~50 righe) — pagina dedicata con sola tabella storico eventi (filtri istanza+task, refresh 30s)

3. **Routes nuove** in `dashboard/app.py`:
   - `GET /ui/telemetria` → render `telemetria.html`
   - `GET /ui/storico` → render `storico.html`

4. **Nav link** in `dashboard/templates/base.html` topbar:
   ```
   home | telemetria | storico | config | api
   ```

5. **Pannello copertura squadre** (semantica WU116 load_squadra):
   - `dashboard/services/stats_reader.py::get_copertura_ultimi_cicli(n=5)` — aggrega da `data/istanza_metrics.jsonl`, esclude master, ordine fisso pomodoro/legno/acciaio/petrolio
   - `dashboard/app.py::partial_copertura_cicli` endpoint `GET /ui/partial/copertura-cicli`
   - `dashboard/templates/partials/copertura_cicli.html` (NEW) — tabella `cov-tbl` con riga per istanza, 5 colonne cicli + 4 colonne totali tipo
   - CSS `.cov-tbl/.cov-cell/.cov-tipo` con color-coding ok/warn/bad
   - Soglia "satura": `load_squadra >= cap_nodo × 0.95`

6. **Trend 7gg spostato** da pagina telemetria a sidebar destra di home (semantica produzione storica). Posizione: TOP della sezione "risorse farm". CSS override `.res-block .tel-table` con `table-layout:fixed` + colonne 38/30/18/14% per evitare overflow orizzontale.

7. **Estensione `core/istanza_metrics.py::aggiungi_invio_raccolta`** con param `load_squadra: int = -1` opzionale (backward compat). `tasks/raccolta.py` passa `ctx._raccolta_load_squadra` stashed da WU116.

**Tool CLI** (`tools/report_copertura_ciclo.py` NEW):
```
python tools/report_copertura_ciclo.py [--prod] [--days N] [--istanza X] [--last N]
```
Output per istanza × ciclo con SATURA/NON SATURA per ogni invio + aggregato ciclo + riepilogo globale.

**Effetto operativo**: dashboard home alleggerita. Restano: cards produzione istanze, cfg4 sistema/rifornimento/zaino/allocazione, tabella istanze mumuplayer, sidebar farm (trend 7gg top + res-totali + res-oraria).

#### WU117. Arena tap prima sfida invece di ultima — robustezza lista incompleta ✅

**Sintomo**: bug latente potenziale segnalato dall'utente — la coord `_TAP_ULTIMA_SFIDA=(745,482)` ([tasks/arena.py:67](tasks/arena.py) pre-fix) puntava all'**ultima riga** della lista sfide arena (5° rigo). Se la lista mostra meno di 5 righe (account low-level con pochi opponenti, opponenti già sfidati nello stesso giorno), il tap cade su area vuota o su elemento adiacente non desiderato → fail silenzioso o comportamento errato.

**Fix**: rinominata costante `_TAP_PRIMA_SFIDA=(745,250)` calibrata visivamente su FAU_01 04/05 (vedi `c:/tmp/maschera_inv/marker_5_rows.png` con 5 cerchi colorati su righe candidate). La **prima riga è sempre presente** quando la lista contiene almeno 1 sfida → tap robusto indipendentemente dal numero di righe visibili.

**File modificato**:
- `tasks/arena.py:67` — costante rinominata
- `tasks/arena.py:403` — unico call site aggiornato

**Test**: rinviato a produzione 05/05 (sfide arena giornaliere FAU_01 esaurite dal test arena_mercato + dalla navigazione manuale di calibrazione).

#### WU116. OCR carico squadra (Load) + dataset copertura squadre + tool analisi ✅

**Obiettivo**: rilevare istanze con squadra **underprovisioned** (poche truppe) → la squadra non riempie il nodo → il nodo resta aperto, non rigenera al max → spreco efficienza farm globale.

**Razionale gameplay**: con `RACCOLTA_TRUPPE=0` (modalità auto, default), il gioco determina automaticamente il minimo numero di truppe necessarie per saturare il nodo. Se la squadra non ha abbastanza truppe → `load_squadra < cap_nodo` → la marcia raccoglie solo `load` (truppe complete) → cap residuo > 0 → un'altra istanza/giocatore deve "chiudere" il nodo prima che possa rigenerare al massimo nominale.

**4 file modificati**:

**1. `shared/ocr_helpers.py`** — funzione OCR + ROI calibrata
- `_ZONA_LOAD_SQUADRA = (610, 420, 780, 455)` — 170×35 px, sopra MARCH btn
- `leggi_load_squadra(img)` — cascade `raw → binv150` con regex `_LOAD_RE` per estrarre primo gruppo digit-comma (resiste a rumore timer ETA sottostante)
- Validato 8/8 test FAU_01: cifre 5-9 caratteri, popup gather no falsi positivi
- `binv200` scartato: distorce cifre piccole ("5"→"9" su petrolio 90,153)

**2. `shared/cap_nodi_dataset.py`** — schema esteso
- `registra_cap_sample()` accetta param opzionale `load_squadra: int = -1` (backward compat)
- Schema record JSONL: `{ts, instance, tipo, livello, capacita, load_squadra}`
- `load_squadra=-1` → marcia non eseguita / OCR fallita

**3. `tasks/raccolta.py`** — hook
- `_esegui_marcia` legge load post-`_leggi_eta_marcia` e stash su `ctx._raccolta_load_squadra`
- Registrazione differita al post-marcia → 1 record per invio invece di 2
- Su marcia FAIL: `load=-1`, ma cap (popup gather) comunque registrato

**4. `tools/analisi_cap_nodi.py`** — nuova sezione analisi
- **Sezione 4 "Copertura squadra"** per (istanza, tipo) = `load_squadra / cap_nodo`
- Verdetti: `OK satura ≥95% / marginale 75-94% / ⚠ underprovisioned <75%`
- Aggregato per istanza con copertura media tutti i tipi

**Smoke test**: dataset finto con 8 record validati. FAU_09 con load=708,822/1,200,000 → 50% copertura → riconosciuto correttamente come "⚠ underprovisioned".

**Esempio output reale atteso post-restart**:
```
istanza      campo  segheria  acciaio  petrolio   media   verdetto
FAU_00      100%     100%     100%     100%       100%   ✓ OK satura
FAU_05       97%      94%      99%     100%        97%   ✓ OK satura
FAU_09       58%      62%      55%      60%        59%   ⚠ truppe insufficienti
```

**Effetto operativo**: dopo restart bot, ogni invio raccolta genera record completo. Il KPI copertura guida la decisione di training truppe nelle istanze deboli (priorità task `truppe`).

#### WU115. Sistema debug screenshot unificato — hot-reload + dashboard toggle ✅

**Obiettivo**: architettura debug screenshot indipendente dal funzionamento del bot, attivabile/disattivabile per ogni task **senza riavviare** via dashboard. Sostituisce i 3 toggle modulo-level (`_DEBUG_REBUILD_DUMP`, `_DEBUG_MERCATO_DUMP`, `_DEBUG_STORE_FAIL_DUMP`) con sistema generalizzato a 17 task.

**Componenti** (Steps A→E):

**A — `shared/debug_buffer.py`** (~220 righe NEW)
- `DebugBuffer.for_task(task_name, instance_name)` factory
- `buf.snap(label, screen)` / `buf.snap_array(label, frame)` — accumula in-memory
- `buf.flush(success, force, log_fn)` — scrive su disco condizionale
- `is_debug_enabled(task)` / `get_all_debug_status()` / `set_debug_enabled(task, enabled)` — API config
- `invalidate_cache()` — refresh manuale (chiamato dopo PATCH)
- `cleanup_old(days=7)` — pulizia automatica file vecchi

**Logica flush** (key insight):
| success | force | flush? | uso tipico |
|---|---|:-:|---|
| True | False | NO | task ok, no anomalie → save disk |
| False | * | SI | task fail tecnico → debug |
| True | True | SI | success ma anomalia logica (es. acquisti=0) |

**B — Schema config**
- `dashboard/models.py::GlobaliOverride.debug_tasks: Dict[str,bool] = {}`
- `config/config_loader.py::GlobalConfig.debug_tasks: dict = {}`
- Merge propagato in `_merge_globali` + lettura in `_from_raw`

Path config: `runtime_overrides.json::globali.debug_tasks.{task_name}`

**C — Migrazione 3 task** (arena, arena_mercato, store)
- Rimossi 3 toggle modulo-level + 2 classi `_StoreDebugBuf`/`_MercatoDebugBuf` (~130 righe legacy)
- Sostituiti con `DebugBuffer.for_task()` pattern (~37 righe nuove)
- `arena._rebuild_truppe`: snap a 5+(N×2) punti, flush sempre (force=True)
- `arena_mercato.run`: snap a 4 punti, flush condizionale (force=acquisti=0)
- `store.run`: snap a punti chiave, flush condizionale (force=esito!=COMPLETATO)

**D — Endpoint API JSON** (`dashboard/routers/api_debug.py` NEW ~95 righe)
- `GET /api/debug-tasks` → `{known_tasks, status, active_count}` (JSON)
- `PATCH /api/debug-tasks/{task}/{enable|disable}` → toggle + invalidate cache (JSON)

**E — Endpoint UI HTML** (`dashboard/app.py` +75 righe)
- `GET /ui/partial/debug-tasks` → render pannello con pill toggle
- `PATCH /ui/debug-tasks/{task}/{action}` → toggle + ritorna partial aggiornato (HTMX swap)
- Pannello "🐛 debug screenshot per task" in `index.html` (sostituisce posizione del rimosso "🧠 banner appresi" WU110)

**Storage**: `data/{task}_debug/{istanza}_{ts}_{idx:02d}_{label}.png`
**Cache TTL**: 30s (sync con typical refresh dashboard)
**Cleanup**: 7gg (chiamare `cleanup_old()` da main.py o launcher)

**Smoke test**: 5/5 API JSON + 5/5 UI HTML + 10/10 pytest arena_mercato. Test debt pre-esistenti (store 5 fail, arena 9 fail) invariati.

**Aggiungere debug a un nuovo task** (effort ~5 righe):
```python
from shared.debug_buffer import DebugBuffer
debug = DebugBuffer.for_task("nome_task", instance_name)
debug.snap("00_start", screen)
# ... lavoro ...
debug.flush(success=ok, force=anomalia)
```
Poi aggiungere `"nome_task"` a `_KNOWN_TASKS` in `api_debug.py` per visibilità in dashboard.

**Step F — Espansione 14 task** (03/05 sera, ordine utente)

Migrazione progressiva del pattern DebugBuffer ai task rimanenti, con **anomalia logic** specifica per ognuno:

| # | Task | Snap (esempio) | Anomalia (force=...) |
|---|------|---------------|---------------------|
| 1 | `vip` | 4 (pre/post_open, post_cass, post_free) + 99_exception | `cass_ok=False AND free_ok=False` |
| 2 | `messaggi` | 4 (alliance, system, post_claim) + 99_exc | `not alliance_ok AND not system_ok` |
| 3 | `boost` | 4 (pre_tap, popup_manage, scroll_speed, frame_use) + 99_exc | `outcome ∈ {POPUP_NON_APERTO, SPEED_NON_TROVATO, ERRORE}` |
| 4 | `alleanza` | 5 (pre_tap, post_dono, pre_claim, post_claim, post_raccogli) + 99_exc | `rivendiche=0` |
| 5 | `donazione` | 3 (pre_naviga, post_tech, post_dona) + 99_naviga + 99_exc | `donate_count=0` |
| 6 | `radar` | 3 (badge_check, post_open, post_loop) + 99_exc | `pallini_tappati=0 AND no errore` |
| 7 | `radar_census` | 2 (pre_census, post_detect) | `matches vuoto` |
| 8 | `truppe` | 3 (counter_read, post_loop, ciclo_fail) + 99_exc | `ok < iterazioni` |
| 9 | `zaino` | 2 (pre_zaino, post_bag) + 99_exc | `bool(da_caricare) AND totale_caricato=0` |
| 10 | `main_mission` | 3 (pre_open, post_open, post_claim) + 99_exc | tutti claim=0 |
| 11 | `raccolta` (+ chiusura sub-classe) | 2 (pre, post) — usa `self.name()` per distinguere | `bool(libere) AND inviate_totali=0` |
| 12 | `rifornimento` | 2 (pre, post) | `max_sped>0 AND spedizioni=0` |
| 14 | `district_showdown` | 4 (pre_ds, pre_loop, post_loop_<esito>, 99_icona/99_auto_roll) | `esito ∈ {timeout, errore}` |

**Totale tasks coperti**: **17/17** (3 originali Step C — arena, arena_mercato, store — + 14 da Step F).

**Lista completa `_KNOWN_TASKS`** ([dashboard/routers/api_debug.py](dashboard/routers/api_debug.py)):
```
arena, arena_mercato, store, vip, messaggi, boost, alleanza, donazione,
radar, radar_census, truppe, zaino, main_mission, raccolta, raccolta_chiusura,
rifornimento, district_showdown
```

**Effetto operativo**: utente abilita debug per un task via dashboard (toggle pill) → al **prossimo run** del task su qualsiasi istanza, screenshot di tutti i punti chiave salvati su `data/{task}_debug/`. Disabilita → no più screenshot. Hot-reload (TTL cache 30s).

**Convenzioni snap label**: `00_pre_*`, `01_*`, `02_*`, `99_*` (terminale anomalo o exception). Il buffer accoda in memoria; il flush condizionale evita scrittura su disco quando il task riesce senza anomalia.

#### WU110. BannerLearner cleanup — deprecato, default disable ✅

**Diagnosi**: WU93 implementata 02/05 con `auto_learn_banner=True` di default. Verifica 03/05 sera:
- `data/learned_banners.json` **non esiste** (mai creato)
- `0 eventi [LEARNER]` in tutti i log (.jsonl + .bak)
- 6 `_unmatched_tap_x` dismiss in 4h (opportunità mancate)
- 311 snapshot `boot_unknown/` su disco (input dataset sprecato)

**Root cause** ([shared/ui_helpers.py:446](shared/ui_helpers.py)):
```python
if enable_learner and not counts:
    # ... pipeline learn ...
```

L'ordine di esecuzione del loop in `dismiss_banners_loop`:
1. Match catalog statico → tap → counts popolato → break
2. Se nulla:
   - Step A1 fallback `pin_btn_x_close` (X cerchio dorato) → tap → `counts["_unmatched_tap_x"]+=1` → continue
   - Step A2 fallback `pin_btn_back_arrow` → tap → `counts["_unmatched_tap_back"]+=1` → continue
   - Step B HOME/MAP check
   - Step LEARNER → **SKIPPATO** perché `counts` non vuoto

Il fallback X cerchio dorato ha priorità sul learner. La pipeline learn non scatta in pratica.

**Fix opzione B** (cleanup):

1. **Default `False`** in 4 punti:
   - `dashboard/models.py::GlobaliOverride.auto_learn_banner` → False
   - `config/config_loader.py::GlobalConfig.auto_learn_banner` → False
   - `config/global_config.json::auto_learn_banner` → False (dev+prod)
   - `config/runtime_overrides.json::globali.auto_learn_banner` → False (prod)

2. **Docstring DEPRECATO** in 2 moduli (lasciati per git history):
   - `shared/banner_learner.py`
   - `shared/learned_banners.py`

3. **Pannello dashboard rimosso** da `index.html` (sostituito con commento HTML + motivazione). Endpoint server-side `/ui/partial/learned-banners` lasciato attivo (compat).

**Smoke test 4/4 verdi**:
- merge_config con runtime_overrides → top-level `auto_learn_banner=False`
- `GlobalConfig._from_raw` → `auto_learn_banner=False`
- Syntax check sui 4 file modificati
- 311 snapshot boot_unknown intatti (no cleanup automatico)

**Riattivazione futura**: refactor `learn-after-fallback` (~50 righe) — modificare il check `if enable_learner and not counts:` per attivarsi anche dopo `_unmatched_tap_x>=2` per stessa istanza, salvando `pre_frame` PRIMA del fallback.

#### WU109. Telemetry pattern detector — esclusione raccolta_chiusura ✅

**Sintomo**: pattern detector flaggava 15 esecuzioni `raccolta_chiusura` come outlier (max 225s, severity high) ma erano comportamento legittimo.

**Analisi**: il task ha **distribuzione bimodale**:
- **Skip mode** (mediana 3.4s): "Slot OCR letti → 0 libere → return immediato"
- **Work mode** (60-225s): "Slot libere → invio 1-4 marce raccolta"

Tutti i 29 outlier osservati nelle ultime 7gg avevano `invii ≥ 1` (lavoro reale). La soglia `mediana × 3` dell'algoritmo fallisce su distribuzioni bimodali (la mediana 3s × 3 = 9s mentre il work-mode è naturalmente 60s+).

**Fix** ([core/telemetry.py:594-597](core/telemetry.py)):
```python
EXCLUDED_TASKS_TIMEOUT = {"raccolta_chiusura"}
for task_name, evs in by_task.items():
    if task_name in EXCLUDED_TASKS_TIMEOUT:
        continue
    ...
```

Modifica cosmetica: non incide sul comportamento del bot, solo sul detector → live.json. La detection per gli altri task resta attiva e legittima (es. raccolta principale ha distribuzione più gaussiana, alert utili).

**Validazione**: pre-fix 2 entries (raccolta + raccolta_chiusura), post-fix 1 entry (solo raccolta count=8 max=332s severity high). raccolta_chiusura escluso correttamente.

#### WU108. DistrictShowdown ignora flag dashboard — fix veto esplicito ✅

**Sintomo (utente)**: District Showdown disabilitato dalla dashboard, ma il task girava comunque. Verifica live.json: 201 esecuzioni, 0% ok, last_err `"icona evento non trovata"`. Costo: 5.6s × 201 ≈ 19 min/die sprecati.

**Root cause** ([tasks/district_showdown.py:158-169](tasks/district_showdown.py)):
```python
def should_run(self, ctx) -> bool:
    if ctx.device is None or ctx.matcher is None:
        return False
    # auto-WU17 (27/04): gate temporale OVERRIDE del flag manuale.
    return self._is_in_event_window()   # ← ignora task_abilitato
```

Il commento storico citava "evita rischio flag dimenticato disabilitato durante evento" — ma genera il problema opposto: l'utente non può disabilitare il task neanche volendo (es. evento saltato settimana, account low-level che non vede icona, popup promo che copre l'icona).

**Fix**: aggiunto check `task_abilitato("district_showdown")` come **VETO esplicito** prima della window check:
```python
def should_run(self, ctx) -> bool:
    if ctx.device is None or ctx.matcher is None:
        return False
    if hasattr(ctx.config, "task_abilitato"):
        if not ctx.config.task_abilitato("district_showdown"):
            return False   # flag dashboard come veto esplicito
    return self._is_in_event_window()
```

**Logica risultante**:
- Flag OFF → skip immediato (utente sa cosa fa)
- Flag ON + fuori window → skip (autoregolazione temporale)
- Flag ON + in window → run (esegue task)

**Smoke test**: 2/2 verdi (flag=False → should_run=False; flag=True → dipende da window).

**Effetto**: hot-reload al prossimo tick di ciascuna istanza. Da prossimo ciclo, DS skip immediato → -5.6s × 11 = ~60s/ciclo recuperati. Dashboard ora autoritativa.

#### WU107. Tick_sleep dashboard ignorato dal bot — fix conversione + lettura config ✅

**Sintomo (utente)**: dashboard mostra `tick_sleep_min=5` (5 minuti tra cicli), ma il bot reale girava ogni **60 secondi** (1 minuto).

**Verifica oggettiva**: gap fra fine ciclo N e inizio ciclo N+1 da `data/telemetry/cicli.json`:
```
ciclo 119→120: 60s
ciclo 120→121: 60s
ciclo 121→122: 60s
... (uniforme)
```
Confermato 60s = `--tick-sleep 60` da `run_prod.bat`, indipendente dal config dashboard.

**Doppio bug**:

1. **`config_loader._merge_globali`** ([config_loader.py:282-284](config/config_loader.py)) faceva alias `tick_sleep_min → tick_sleep` **senza conversione minuti→secondi**:
   ```python
   key = "tick_sleep" if k == "tick_sleep_min" else k
   merged["sistema"][key] = v   # 5 (min) salvato come 5 (sec)
   ```

2. **`main.py::SLEEP_CICLO`** ([main.py:1065](main.py)) usava SOLO `args.tick_sleep` da CLI, **ignorando completamente il merged config**. Quindi anche se il config_loader avesse fatto la conversione corretta, il valore non sarebbe stato letto.

**Fix combinato**:

a) **`config_loader.py`** — conversione esplicita `tick_sleep_min × 60 → tick_sleep_secondi`:
   ```python
   if k == "tick_sleep_min":
       merged["sistema"]["tick_sleep"] = int(v) * 60
   else:
       merged["sistema"][k] = v
   ```

b) **`main.py`** — argparse default `--tick-sleep=-1` (sentinel "leggi da config") + risoluzione priorità:
   ```python
   if args.tick_sleep < 0:
       _tick_cfg = merged.get("sistema", {}).get("tick_sleep")
       args.tick_sleep = _tick_cfg if _tick_cfg >= 0 else 300
       _log("MAIN", f"tick_sleep da config: {args.tick_sleep}s (={args.tick_sleep/60:.1f}min)")
   else:
       _log("MAIN", f"tick_sleep CLI esplicito: {args.tick_sleep}s")
   ```

c) **`run_prod.bat`** — rimosso `--tick-sleep 60` esplicito (lascia che il config decida). CLI override resta disponibile per test/debug.

**Priorità risolta**: CLI esplicito (positivo) > config (`tick_sleep_min × 60`) > default 300s.

**Validazione**: smoke test `merge_config` su prod conferma `runtime_overrides.tick_sleep_min=5` → `merged.sistema.tick_sleep=300`. Effetto al prossimo restart bot.

#### WU106. Cap istanza rifornimento — cattura giornaliera alla prima spedizione ✅

**Obiettivo**: scoprire e persistere il cap di invio individuale di ogni istanza (il `provviste_residue` letto al popup compila è la capacità giornaliera DI INVIO dell'istanza, separato dal cap di RICEZIONE del rifugio FauMorfeus pari a 200M netti). Permette stime di quote dinamiche per istanza senza dover dipendere solo dal cap globale.

**Modifiche** ([core/state.py](core/state.py) + [tasks/rifornimento.py](tasks/rifornimento.py)):

1. **`RifornimentoState`** — 2 nuovi campi:
   - `cap_invio_iniziale_oggi: int = -1` — NETTO, primo `provviste_residue` letto del giorno
   - `qta_max_invio_lordo: int = -1` — LORDO max per singolo invio (input clamped al popup compila)

2. **`_controlla_reset()`** — azzera entrambi a `-1` al cambio giorno UTC

3. **`registra_cap_giornaliero(cap_invio, qta_max_lordo)`** — metodo nuovo, idempotente (scrive solo se attuale `<0`). Cristallizza i valori alla prima esposizione del giorno.

4. **Hook in task** (rami MAPPA + MEMBRI): alla prima spedizione (`spedizioni_oggi==0`), prima di `registra_spedizione`, chiama `registra_cap_giornaliero(provviste_lette, qta_lordo)`. Log:
   ```
   Rifornimento: [WU106] cap istanza giornaliero=22.5M netti | qta max singolo invio=1.56M lordo
   ```

5. **Persistenza** — `to_dict`/`from_dict` con compat legacy (default `-1` per state pre-WU106).

**Esempio dati attesi** (post-restart, primi cicli del 04/05 UTC):
- FAU_09: cap ~22.5M netti, qta_max ~1.56M lordo
- FAU_10: cap ~26M netti, qta_max ~1.55M lordo
- FAU_08: cap ~22M netti, qta_max ~1.55M lordo
- ecc.

**Vantaggi**:
- Distinguiamo le istanze con cap diverso (livello edificio Embassy/HQ?)
- Predictor può stimare `target_sped_ciclo = (cap_residuo / qta_max_lordo) / cicli_rimanenti`
- Dashboard può mostrare "cap giornaliero usato: X / Y M (Z%)" sulla card istanza
- Analisi storica di crescita dei cap (correla con upgrade edifici)

**Smoke test**: idempotenza OK, reset OK, round-trip serializzazione OK.

#### WU105. Rifornimento — bug "1 spedizione invece di 5" ✅

**Sintomo**: FAU_09 ciclo 18:27 con `slot liberi=1` ha inviato 1 sola spedizione invece delle 5 di default. Pattern riproducibile su tutte le istanze con slot iniziale basso (1-2 squadre libere mentre le altre erano fuori per raccolta del ciclo precedente).

**Log incriminante**:
```
slot liberi=1
spedizione 1 inviata
slot liberi=0
slot 0 — attendo 86s        ← attende rientro
nessun slot libero dopo attesa — stop   ← BUG: esce sempre
```

**Root cause** ([tasks/rifornimento.py:1328-1338](tasks/rifornimento.py)): il branch `if slot == 0` chiamava `time.sleep(attesa)` + `_aggiorna_coda(coda_volo)` per attendere il rientro, ma poi faceva `break` **incondizionatamente**, senza ricontrollare lo slot. La squadra rientrava ma il loop usciva.

**Fix**: dopo `time.sleep(attesa) + _aggiorna_coda`, fa `continue` invece di `break`. Il prossimo giro del while legge lo slot OCR (ora libero) e procede con la prossima spedizione. Caso `coda vuota + slot=0` rimane `break` (squadre fuori per altri task, no rientro previsto).

**Modo "membri"** non impattato: assume `_MAX_SWIPE_TOP` slot, non legge UI.

**Saving atteso**: con slot iniziale 1-2, le istanze passano da 1-2 spedizioni/ciclo a 4-5 (limite max_sped). ~3-4 spedizioni in più × 11 istanze × 12 cicli/giorno = ~30-50 spedizioni in più/die. Daily Receiving Limit FauMorfeus rimane il vero bottleneck, ma sfruttiamo meglio gli slot tornati durante il ciclo.

#### WU104. run_prod.bat — pre-kill bot orfani via PowerShell ✅

**Problema**: lanciando `run_prod.bat` con un bot precedente già in esecuzione, c'era una finestra di ~10-15s di import Python in cui due bot scrivevano simultaneamente su `engine_status.json`, `state/`, `logs/`. Il bot ha già `_cleanup_orfani_processi_startup` ([main.py:209-301](main.py)) che killa orfani al boot, ma agisce dopo che l'import è iniziato.

**Fix**: pre-kill nel batch PRIMA di lanciare il nuovo Python:
```bat
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -notlike '*-m uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul
```

Esclusione `-m uvicorn` per non killare la dashboard se mai lanciata da Python con argomenti misti. 2s di grace per release file handle prima del nuovo lancio. Doppia rete: se qualcosa scappa, `_cleanup_orfani_processi_startup` al boot lo recupera.

---

### Issue chiuse — Sessione 03/05 sera (WU89-Step3 Skip Predictor + tick_sleep validato + config istanze update)

#### WU89-Step3. Skip Predictor — modulo flag-driven, no side-effect ✅

**Obiettivo**: predire se un'istanza dovrebbe essere skippata al prossimo
tick basandosi su metriche storiche, senza modificare la struttura del bot.

**Componenti** (3 file nuovi + 4 modifiche config):

1. **`core/skip_predictor.py`** (NEW ~270 righe) — pure function:
   ```python
   predict(istanza, history, state) → SkipDecision(
     should_skip, reason, score, signals, growth_phase, guardrail_triggered
   )
   ```

2. **5 regole** (in ordine priorità):
   - `squadre_fuori` (0.85): slot saturi + ritorno bot prematuro (<2×ETA+30s)
   - `trend_magro` (0.65): last 3 cicli avg_inv < 0.5
   - `recovery` (0.75): outcome ultimo='degraded' + gap < 5min
   - `low_prod` (0.55): produzione <100K/h cumulativo + min 5 cicli + prod>0
   - `proceed` (default): no skip

3. **Growth phase protection**: truppe < 100K → blocca regola low_prod
   (preserva loop raccolta→risorse→truppe→raccoglitori). Gestisce caso
   FAU_09 (truppe basse, in fase di crescita).

4. **Guardrail anti-stallo** (l'istanza non muore mai):
   - Max 3 skip consecutivi → 4° tick forza retry
   - Re-evaluation ogni 6 cicli (anche se predictor dice skip)
   - Cooldown 2 cicli post-retry

5. **`tools/predictor_shadow.py`** (NEW ~110 righe) — CLI replay:
   ```bash
   python tools/predictor_shadow.py --prod --days 3
   python tools/predictor_shadow.py --prod --istanza FAU_03 --verbose
   ```

6. **Flag config** (default OFF, shadow first):
   - `skip_predictor_enabled: false` in runtime_overrides + global_config
   - `skip_predictor_shadow_only: true`
   - Aggiunti a `GlobaliOverride` Pydantic + `GlobalConfig` dataclass

**Validazione shadow** (416 record / 3 giorni):
- 33 skip suggeriti (7.9% delle decisioni)
- 44 guardrail-blocked (anti-stallo attivo)
- Saving stimato: 116 min se applicato live
- Pattern: FAU_10 32 guardrail-blocked (low_prod ricorrente)
- FAU_09 protetta da growth_phase (truppe <100K)

**Step 4-5 NON implementati** (decisi insieme all'utente):
- Step 4: hook orchestrator in `main.py` (consumer del predictor)
- Step 5: pannello dashboard shadow/live

Validazione step 3 in modalità shadow per accumulo dati prima di
decidere se procedere con step 4-5.

#### tick_sleep_min 1 → 5 (validato 03/05)

`runtime_overrides.json::globali.sistema.tick_sleep_min` da 1 a 5 (60s →
300s). Effetto misurato in 5 ore post-cambio:
- Raccolta efficacy: 64% → **74%** (+9pp aggregato)
- FAU_03: 29% → 75% (+46pp, big win)
- FAU_06: 57% → 75% (+18pp)
- 0 cascade ADB, 0 home FALLITO
- Throughput orario raccolta: ~10 → ~14 squadre/h (+40%)

**Caveat (memoria salvata)**: validato SOLO con rifornimento OFF. Se
riattivato ricalcolare (probabile 8-15 min).

#### Config istanze update (utente, da dashboard)

`runtime_overrides.json::istanze` modificato:
- **FAU_00..FAU_05 + FauMorfeus**: livello 7 (era solo FAU_00 a lvl 7)
- **FAU_06..FAU_10**: livello 6 (invariate)
- **FauMorfeus**: abilitata (era false). Tipologia `raccolta_only`,
  max_squadre 5, lvl 7

Implicazioni:
- 12 istanze attive nel ciclo bot (era 11)
- Cap nodi medi: 6 istanze su nodi L7 (1.04M avg) + 5 su L6 (0.95M avg)
- Tempo raccolta su nodi L7 leggermente maggiore (×1.10)

---

### Issue chiuse — Sessione 02/05 mattina+pomeriggio (WU90-99)

#### WU99. Dashboard config — layout 4-card identico overview ✅

**Richiesta utente** (con screenshot di riferimento): "le configurazioni nel
menù config devo avere lo stesso layout di home". L'overview ha già un blocco
"configurazione" con 4 card affiancate (`cfg4` grid: Sistema · Rifornimento ·
Zaino · Allocazione) con stile compatto e intuitivo. La pagina
`/ui/config/global` aveva invece il layout `tel-card` standard.

**Modifiche al template `config_global.html`**:

- Sostituite le sezioni Sistema · Flag globali · Rifornimento · Zaino ·
  Allocazione con un blocco `cfg4` clonato da `index.html` (4 col-box).
- Card **Sistema** include: max_parallel · tick_sleep · 16 task baseline
  (checkbox 2-col) · 2 flag globali (auto_learn_banner, raccolta_ocr_debug).
- Card **Rifornimento** identica overview ma con coord rifugio dal nuovo
  schema unificato (`rifugio.coord_x/y`).
- Card **Zaino** identica.
- Card **Allocazione** include `livello_nodo` + 4 percentuali con totale e
  barra visiva.
- ID prefissati con `gc-` per evitare collisioni con la sezione overview
  inclusa nello stesso DOM (anche se solo overview ha la propria sezione,
  prevenzione futura).
- Funzioni JS dedicate `gcSalvaSistema/Rifornimento/Zaino/Allocazione/Istanze`
  che chiamano nuovo endpoint `PATCH /api/config/global`.

**Tabella istanze** rimasta invariata sotto la sezione configurazione.

**Mumu read-only** in fondo.

**Nuovo endpoint** `PATCH /api/config/global` (`api_config_global.py`):

- Merge incrementale top-level: ogni card invia solo la sua sezione, il
  resto del file è preservato.
- Scrive dict raw (no round-trip via `GlobalConfig._from_raw → to_dict()`)
  perché il dataclass perde campi nuovi (rifugio, rifornimento unificato,
  auto_learn_banner, raccolta_ocr_debug, soglia_allocazione).
- `_save_global_raw()` helper: scrittura atomica tmp + replace.

**Validazione**: PATCH `{sistema: {tick_sleep: 90}}` aggiorna solo sistema,
preserva rifugio/rifornimento/raccolta.allocazione (35/35/20/10
percentuali)/auto_learn_banner/raccolta_ocr_debug.



#### WU98. Pagina /ui/config eliminata — unica config = /ui/config/global ✅

**Osservazione utente**: la pagina `/ui/config` era completamente ridondante:
- task flags + tabella istanze duplicano la overview
- sistema · flag globali · rifornimento · zaino · allocazione duplicano
  `/ui/config/global`

**Decisione**: tenere solo `/ui/config/global` come unica pagina di
configurazione, con tutte le sezioni più una nuova per le istanze di default.

**Modifiche**:
1. **Redirect** `GET /ui/config` → 302 `/ui/config/global`
2. **Menu nav semplificato** (`base.html`): rimossa voce "config", lasciata
   solo "config" → punta a `/ui/config/global`
3. **Template** `config_overrides.html` rinominato `.legacy` (backup)
4. **Nuova sezione** "🤖 istanze (default statici)" in `config_global.html`:
   - Tabella editabile: nome+porta (RO) · tipologia · max_squadre · livello ·
     layout · truppe · fuori_territorio · abilitata
   - JS `__saveIstanze()` raccoglie i campi `name="istanze__{nome}__{campo}"`
     e fa PUT `/api/config/istanze` (scrive su `instances.json` +
     `runtime_overrides.json::istanze`)
5. **Endpoint UI** `/ui/config/global` aggiornato per passare anche
   `instances` + `overrides` al template

**Pagina finale `/ui/config/global`** (6 sezioni, 60KB):
- Sistema · Flag globali
- Task — baseline (default reset = tutti OFF)
- Rifornimento (modalità · rifugio · risorse)
- Zaino · Allocazione raccolta
- **Istanze (default statici)** ← NEW
- Mumu — sola lettura



#### WU97. Dashboard config — rimozione duplicate con overview ✅

**Osservazione utente post-restart**: la pagina `/ui/config` "sembra una
duplicazione della overview". Verifica conferma: 2 sezioni replicate.

**Sezioni rimosse**:
1. **Task flags** — già visibile nell'overview come pill `task-flags-v2`
   (riga 51 `index.html`)
2. **Istanze (abilitazione rapida)** — già visibile nell'overview come
   tabella `ist-table` (riga 243 `index.html`) con stessi controlli toggle

**Sezioni rimaste in `/ui/config`** (config-specific, non duplicate):
- Sistema (`max_parallel`, `tick_sleep_min`)
- Flag globali (`auto_learn_banner` toggle, `raccolta_ocr_debug` toggle)
- Rifornimento (modalità · rifugio · risorse · soglie)
- Zaino (modalità · usa · soglie)
- Allocazione raccolta (4 percentuali)

**Footnote** in fondo pagina rimanda alla overview per task flags e istanze.

**Saving**: page size 38KB → 19KB (-50%), rendering più veloce + niente
confusione utente sul "perché due pagine ripetono le stesse cose".



#### WU96. Dashboard config + global config — layout uniforme ✅

**Obiettivo**: rendere `/ui/config` e `/ui/config/global` coerenti col layout
della dashboard principale (`index.html`) e chiarire visivamente la differenza
tra le due pagine.

**Pattern unificato applicato a entrambe**:

```
<div class="section">
  <div class="sec-label">titolo sezione</div>
  <div class="tel-grid">
    <div class="tel-card">
      <div class="tel-head">🔧 nome card</div>
      ...form/contenuto...
      <div class="tel-foot">descrizione/info</div>
    </div>
    ...più card affiancate...
  </div>
</div>
```

**Banner top esplicativo** (entrambe le pagine):
- `/ui/config` → "config = override `runtime_overrides.json` · HOT-RELOAD
  al prossimo tick. Per la baseline statica vedi global config (richiede
  riavvio bot)."
- `/ui/config/global` → "global config = baseline statica `global_config.json` ·
  richiede RIAVVIO bot. È la configurazione di reset (cancellando
  runtime_overrides.json il bot riparte da qui). Per modifiche hot-reload
  usa config."

**Modernizzazione `config_global.html`**: era id-based + JS save manuale
legacy → ora HTMX nested via listener `htmx:configRequest` (riusato da WU95).
Hidden input per `mumu[*]` paths e `rifornimento_comune[qta_*]` per non
perderli al save (il dataclass `_from_raw` userebbe i default sostituendo
i valori utente).

**Sezioni global_config**: sistema · flag globali · task baseline ·
rifornimento (modalità+rifugio+risorse) · zaino · allocazione raccolta ·
mumu (sola lettura).

**Verifica rendering**:
- GET `/ui/config`: 38KB · 5 sec-label, 7 tel-card, 5 tel-grid, 7 tel-head
- GET `/ui/config/global`: 27KB · 5 sec-label, 7 tel-card, 5 tel-grid, 7 tel-head
- Layout count identico in entrambe le pagine.



#### WU95. Dashboard config_overrides.html — sezioni complete riallineate ✅

**Pre-fix**: la pagina `/ui/config` esponeva solo `task flags` + sub-form
rifornimento parziale (3 campi) + tabella istanze. Mancavano molte sezioni
del global_config statico.

**Sezioni aggiunte**:

1. **Sistema** — form `max_parallel` + `tick_sleep_min` → PUT /api/config/globals
2. **Rifornimento completo** — modalità (mappa/membri) + rifugio (coord_x/y) +
   comune (account, max spedizioni, 4 risorse × {abilitata, soglia})
   → PUT /api/config/rifornimento
3. **Zaino** — modalità (bag/svuota) + 4 risorse × {usa, soglia}
   → PUT /api/config/zaino
4. **Allocazione raccolta** — 4 percentuali (somma 100)
   → PUT /api/config/allocazione
5. **Flag globali** — toggle `auto_learn_banner` (WU93) +
   `raccolta_ocr_debug` (WU55) con descrizione e color-coded status
6. **Task flags** + **Istanze** (preesistenti)

**Helper JS in `base.html`**: listener `htmx:configRequest` globale che:
- Parsa nomi form `name="sezione[campo]"` → object nested
  (es. `sistema[max_parallel]: "60"` → `{sistema: {max_parallel: 60}}`)
- Coerce string → bool/number (`"true"` → `True`, `"60"` → `60`)
- Serializza JSON con `Content-Type: application/json` per form
  `hx-ext="json-enc"` (l'estensione non era shipped — ricostruita inline)

**Validazione**: smoke test GET `/ui/config` → status 200, tutte le 7 sezioni
presenti nel rendering. Pydantic payload validation OK su tutti gli endpoint.



#### WU94. global_config.json baseline reset ✅

**Obiettivo**: rendere `config/global_config.json` la baseline neutra di reset
configurazione. Allineato a tutti i task implementati + valori dashboard +
schema unificato.

**Modifiche**:

1. **`task` — tutti default `false`** (16 task: raccolta, rifornimento,
   zaino, vip, alleanza, messaggi, arena, arena_mercato, boost, store, radar,
   radar_census, donazione, main_mission, district_showdown, truppe). Reset
   = partenza neutra, utente attiva esplicitamente solo quelli desiderati.
2. **`sistema`**: `tick_sleep=60` (1 minuto), `max_parallel=1`.
3. **`rifornimento_comune.acciaio_abilitato`**: `false → true` (allineato a
   dashboard).
4. **`rifornimento`**: schema unificato (`mappa_abilitata`, `membri_abilitati`,
   `provviste_max`) — Issue #40. Rimosse legacy `rifornimento_mappa` e
   `rifornimento_membri`.
5. **`zaino`**: identico dashboard.
6. **`raccolta.allocazione`**: percentuali 0-100 (35/35/20/10) come dashboard
   (era frazioni 0-1).
7. **`raccolta.soglia_allocazione`**: aggiunto (default 3).
8. **`rifugio`**: aggiunta sezione (`coord_x=680, coord_y=531`).
9. **`raccolta_ocr_debug`**: aggiunto (default false).
10. **`auto_learn_banner`**: aggiunto (default true) — WU93.

**Verifica reset (runtime_overrides vuoto)**:
- 16/16 task = false
- sistema = (1, 60s)
- auto_learn_banner = true
- Tutto il resto coerente

**Backup precedente**: `global_config.json.bak.20260502_pre_reset` in dev+prod.



#### WU93. BannerLearner — auto-apprendimento banner non catalogati ✅

**Obiettivo**: sistema di riconoscimento automatico (no-AI) di X di chiusura
in alto a destra di popup non catalogati. Quando il bot incontra un dialog
sconosciuto, deve:
1. Catturare la X di chiusura via heuristic OpenCV (color masks + edge density)
2. Validare il tap con visual_diff_score + classify HOME/MAP
3. Aggiornare catalog dinamico in `data/learned_banners.json`
4. Riconoscere il dialog ai prossimi incontri tramite catalog runtime

**Componenti** (3 nuovi moduli + 2 hook + 1 pannello dashboard):

1. **`shared/banner_learner.py`** (NEW) — Detection heuristic OpenCV:
   - `detect_x_candidates(img, roi)` → lista `XCandidate` ordinate per score
   - Maschere colore per classi tipiche X (rosso/bordeaux + giallo/oro + magenta)
   - Filtro shape (40-65px lato, aspect 0.7-1.4) + edge density (X interna)
   - `crop_template_x()` + `crop_title_zone()` + `visual_diff_score()` + `template_similarity()`

2. **`shared/learned_banners.py`** (NEW) — Storage JSON persistente:
   - `LearnedBanner` dataclass (name, paths, coords, hit/success/fail counts)
   - Schema `data/learned_banners.json` versionato
   - `register_new()`, `record_outcome()`, `set_enabled()`, `delete()`
   - `find_duplicate()` con similarity threshold 0.85 (dedup)
   - LRU eviction quando supera MAX_ENTRIES=25
   - Auto-disable dopo 3 fail streak consecutivi
   - `load_learned_as_specs()` → `list[BannerSpec]` per inclusione runtime
     in `BANNER_CATALOG` con priority 4

3. **Hook in `shared/ui_helpers.dismiss_banners_loop`**:
   - Nuovo parametro `enable_learner=False`
   - Step LEARNER prima del break Step C: detect + tap top-3 candidate +
     valida con (a) visual_diff >= 0.10 AND (b) score_home/map >= 0.70
   - Tracking `_last_dismissed_learned` per record_outcome success/fail
     a seconda dell'esito iter successivo

4. **Hook in `core/launcher.attendi_home`**:
   - `_enable_learner = unknown_streak >= 4` (= ~14s di blocco persistente)
   - Passato a `dismiss_banners_loop()` solo dopo soglia per evitare tap
     aggressivi durante transizioni normali

5. **Dashboard "🧠 banner appresi (auto)"**:
   - Toggle ON/OFF globale del processo learner in cima al pannello
     (riflette `globali.auto_learn_banner` in runtime_overrides.json)
   - Endpoint `/ui/partial/learned-banners` — tabella con preview X +
     coord + hit/success rate + fail streak + last_used + stato + azioni
   - Endpoint `/learned-template/{name}/{x|title}` — serve PNG anteprima
   - Endpoint `POST /api/learned-banners/{name}/{enable|disable|delete}`
   - Endpoint `POST /api/banner-learner/{enable|disable}` — toggle globale
   - HTMX refresh 30s + bottoni inline per gestione
   - Inserito in `index.html` dopo "📊 storico truppe"

6. **Configurazione statica (`globali.auto_learn_banner`)**:
   - Default `True` in `runtime_overrides.json`, `dashboard/models.py::GlobaliOverride`,
     `config/config_loader.py::GlobalConfig`
   - Hook in `core/launcher.py::attendi_home`: `_enable_learner = unknown_streak >= 4
     and ctx.config.auto_learn_banner` — flag spegne il processo runtime senza
     modificare codice
   - Persistenza via dashboard toggle: rilettura immediata al prossimo tick

**Validazione heuristic** su screenshot reale Equipment Report:
- Ground truth X tag: cx=825, cy=54
- Detection: cx=824, cy=53 (errore 1px), score 0.649
- Falsi positivi su HOME pulita: 0/100% accurate

**Effetto runtime atteso**:
- Primo encounter di un nuovo dialog → ~5s extra per detection+validazione
  (3 tap × 1.5s wait), ma sblocca al primo tap valido invece di 57s freeze
- Encounter successivi → riconoscimento istantaneo via catalog dinamico
- Cap dataset 25 entry, dedup automatico, auto-disable degli entry
  patologici

#### WU92. Banner catalog — Equipment Report popup IAP ✅

**Discovery**: bot prod 02/05 mattina osservato pattern UNKNOWN persistente
~57s su FAU_02 (09:04 UTC) e FAU_03 (09:10 UTC). Banner-loop "nessun banner
riconosciuto" → fallback `_unmatched_tap_x` cerchio dorato (WU66) sblocca
con 2 tap a (870,97). Cattura via `_save_discovery_snapshot` esistente
(streak 3/4 → `debug_task/boot_unknown/FAU_02_*streak4_20260502_094902.png`).

**Diagnosi visiva**: popup IAP gioco "Equipment Report" — titolo arancione
su carta beige, lista 6 icone equipment, CTA "€19,99 / instantly receive
1750x". Chiusura via piccolo cartellino bordeaux a forma di diamante con X
bianca/oro in alto-destra del popup (zona ~800-855 × 25-80) + graffetta
metallica adiacente. NON è la stessa X cerchio dorato di `pin_btn_x_close`
(forma diversa, sfondo rosso, dimensione diversa).

**File aggiunti**:
- `templates/pin/pin_equipment_report_title.png` (34×340) — titolo
- `templates/pin/pin_btn_x_tag_diamond.png` (51×55) — X tag chiusura

**Modifica**: `shared/banner_catalog.py` — entry `equipment_report` priority 2:
```python
BannerSpec(
    name="equipment_report",
    template="pin/pin_equipment_report_title.png",
    roi=(40, 20, 410, 70),
    threshold=0.80,
    dismiss_action="tap_template",
    dismiss_template="pin/pin_btn_x_tag_diamond.png",
    dismiss_template_roi=(780, 15, 880, 90),
    dismiss_template_soglia=0.75,
    wait_after_s=1.5,
    priority=2,
)
```

**Effetto atteso**: al prossimo popup, log `[BANNER-LOOP] equipment_report
chiuso (score=0.XX) tap_template@(cx,cy)` invece di 57s di freeze.

**Saving stimato**: ~55s per istanza × N occorrenze al giorno. Il pattern
era ricorrente su FAU_02/03 al boot.

#### WU90. DonazioneTask — periodic 8h invece di always ✅

**Motivazione**: il task girava ad ogni tick (avg 23 donate/run × 7 cicli/notte
× 11 istanze = ~58 min/notte di tempo bot). I dati mostrano 100% efficacy ma
il throughput è bound dal rate di rigenero del gioco (cap pool 30, 1 donate
ogni 20 min = 3 donate/h). Eseguire più frequente del necessario non aumenta
il throughput totale, sprega solo tempo bot.

**Calcolo finestra ottima**: target pickup 20-25 donate/run.
- 20 donate × 20 min = 400 min = 6h 40min
- 25 donate × 20 min = 500 min = 8h 20min
- 30 (cap) × 20 min = 600 min = 10h (saturazione → no donate persi finché non
  passa altro tempo)

**Scelta**: `interval_hours: 8.0` → pickup atteso ~24 donate/run,
range reale 8-10h (perché orchestrator scatta al primo tick disponibile dopo
soglia, non in tempo reale) → 24-30 donate/run.

**Saving stimato**: ~47 min/giorno di tempo bot, throughput donate invariato.

**Validazione post-restart**: osservare `donate_count` nei log:
- 24-30 consistente → tuning OK
- Spesso 30 + log "cap raggiunto" → scendi a 7h
- Sotto 22 spesso → sali a 9h

#### WU91. MainMissionTask — daily con guard 20:00 UTC ✅

**Motivazione**: il task girava ogni 12h, ma le ricompense mission si
accumulano durante la giornata e vanno raccolte una sola volta (no benefit
nel raccoglierle a metà giornata vs fine). Inoltre molte ricompense hanno
senso a fine-giornata quando il count milestone è massimizzato (es.
chest milestone con AP elevato).

**Modifiche**:

1. `config/task_setup.json:7` — schedule `periodic 12h` → `daily 24h`
2. `tasks/main_mission.py:222-231` — `should_run()` ora include guard:
   ```python
   if datetime.now(timezone.utc).hour < 20:
       return False
   ```

**Effetto combinato**:
- Schedule `daily` con reset 01:00 UTC = max 1×/die
- Guard `hour < 20 UTC` = blocca esecuzioni prima delle 20:00 UTC
- Finestra utile: 20:00 UTC → 01:00 UTC = **5 ore** per scattare 1 volta
- Se bot fermo nella finestra → salta quel giorno (accettato dall'utente)

**Comportamento atteso**: 1 esecuzione per istanza tra le 20:00 e le 01:00
UTC, con tutte le ricompense accumulate del giorno (Chapter + Main + Daily +
chest milestone).

#### Bonus: tabella `_TASK_SETUP` riallineata
Aggiunto `MainMissionTask` (era stato dimenticato in WU88 nella tabella
ROADMAP), aggiornati DonazioneTask e MainMissionTask con i nuovi valori.

---

### Issue chiuse — Sessione 01/05 sera (WU86-89 — dashboard cicli + storico fix + metriche per-istanza)

#### WU90. DonazioneTask — periodic 8h invece di always ✅

**Motivazione**: il task girava ad ogni tick (avg 23 donate/run × 7 cicli/notte
× 11 istanze = ~58 min/notte di tempo bot). I dati mostrano 100% efficacy ma
il throughput è bound dal rate di rigenero del gioco (cap pool 30, 1 donate
ogni 20 min = 3 donate/h). Eseguire più frequente del necessario non aumenta
il throughput totale, sprega solo tempo bot.

**Calcolo finestra ottima**: target pickup 20-25 donate/run.
- 20 donate × 20 min = 400 min = 6h 40min
- 25 donate × 20 min = 500 min = 8h 20min
- 30 (cap) × 20 min = 600 min = 10h (saturazione → no donate persi finché non
  passa altro tempo)

**Scelta**: `interval_hours: 8.0` → pickup atteso ~24 donate/run,
range reale 8-10h (perché orchestrator scatta al primo tick disponibile dopo
soglia, non in tempo reale) → 24-30 donate/run.

**Saving stimato**: ~47 min/giorno di tempo bot, throughput donate invariato.

**Validazione post-restart**: osservare `donate_count` nei log:
- 24-30 consistente → tuning OK
- Spesso 30 + log "cap raggiunto" → scendi a 7h
- Sotto 22 spesso → sali a 9h

#### WU91. MainMissionTask — daily con guard 20:00 UTC ✅

**Motivazione**: il task girava ogni 12h, ma le ricompense mission si
accumulano durante la giornata e vanno raccolte una sola volta (no benefit
nel raccoglierle a metà giornata vs fine). Inoltre molte ricompense hanno
senso a fine-giornata quando il count milestone è massimizzato (es.
chest milestone con AP elevato).

**Modifiche**:

1. `config/task_setup.json:7` — schedule `periodic 12h` → `daily 24h`
2. `tasks/main_mission.py:222-231` — `should_run()` ora include guard:
   ```python
   if datetime.now(timezone.utc).hour < 20:
       return False
   ```

**Effetto combinato**:
- Schedule `daily` con reset 01:00 UTC = max 1×/die
- Guard `hour < 20 UTC` = blocca esecuzioni prima delle 20:00 UTC
- Finestra utile: 20:00 UTC → 01:00 UTC = **5 ore** per scattare 1 volta
- Se bot fermo nella finestra → salta quel giorno (accettato dall'utente)

**Comportamento atteso**: 1 esecuzione per istanza tra le 20:00 e le 01:00
UTC, con tutte le ricompense accumulate del giorno (Chapter + Main + Daily +
chest milestone).

#### Bonus: tabella `_TASK_SETUP` riallineata
Aggiunto `MainMissionTask` (era stato dimenticato in WU88 nella tabella
ROADMAP), aggiornati DonazioneTask e MainMissionTask con i nuovi valori.

---

### Issue chiuse — Sessione 01/05 sera (WU86-89 — dashboard cicli + storico fix + metriche per-istanza)

#### WU86. Pannello dashboard "ultimi 5 cicli" per istanza ✅

In card produzione istanze nuova sezione che mostra gli ultimi 5 tick completi
della singola istanza (avvio→chiusura, durata, outcome ok/cascade/abort).
Dato letto da `data/telemetry/cicli.json` filtrato per istanza + ordinamento
desc per timestamp avvio. HTMX refresh 60s.

#### WU87. Storico eventi dashboard — durata 0 + filtro non persistente ✅

3 bug nel pannello storico eventi:

1. **Durata sempre 0** — `main.py:840` usava `max(orc._entries)` che restituiva
   sempre l'ultimo task ordinato (raccolta_chiusura priority 200) quindi solo
   quello veniva loggato e con durata 0 perché non tracciata. Fix: itera tutte
   le entry con `last_run >= _tick_start_ts` e ne logga la durata.

2. **Campo durata mancante** — `_TaskEntry` non aveva il tracking della durata.
   Fix in `core/orchestrator.py`: aggiunto `last_duration_s: float = 0.0`,
   wrappato `task.run()` con `_run_start = time.time()` + `entry.last_duration_s
   = time.time() - _run_start` (anche su exception).

3. **Filtro non persistente** — HTMX refresh 30s azzerava i select istanza/task.
   Fix nei template: aggiunto `name="istanza"` e `name="task"` ai select +
   `hx-include="#f-istanza, #f-task"` sulla sezione hx-trigger. Dropdown task
   esteso con `main_mission`.

**Storico truppe**: parallelo, mancava FauMorfeus perché `get_truppe_storico_aggregato`
iterava solo le chiavi presenti in storico. Fix: itera da `load_instances()` per
includere tutte le istanze configurate (anche disabilitate / senza dati) +
dedup con keys storico.

#### WU89. Persistenza metriche per-istanza per-ciclo (foundation skip predictor) ✅

**Obiettivo**: accumulare dataset analitico per istanza × ciclo che permetta in
futuro di stimare se un'istanza ha ancora raccoglitori in marcia/raccolta e
quindi se conviene saltarla per accorciare il ciclo globale.

**Modulo**: `core/istanza_metrics.py`. Buffer in-memory thread-safe per istanza,
flush atomic JSONL su `chiudi_tick`. Best-effort: errori I/O silenziati per
non rompere il bot.

**Schema record JSONL** (`data/istanza_metrics.jsonl`):
```json
{
  "ts": "ISO UTC fine ciclo",
  "instance": "FAU_07",
  "cycle_id": 123,
  "boot_home_s": 142.3,
  "tick_total_s": 487.2,
  "raccolta": {
    "attive_pre": 0, "attive_post": 4, "totali": 4,
    "invii": [{"tipo": "campo", "livello": 6, "cap_nodo": 1200000, "eta_marcia_s": 95}]
  },
  "task_durations_s": {"raccolta": 95.3, "donazione": 21.5, ...},
  "outcome": "ok" | "cascade" | "abort"
}
```

**Hook** (5 punti minimal):
- `main.py::_thread_istanza` start → `inizia_tick(nome, cycle_id)`
- `main.py::_thread_istanza` end → `chiudi_tick(nome, outcome, tick_total_s)` +
  propagazione `last_duration_s` di ogni entry orchestrator a `imposta_task_duration`
- `core/launcher.py` post-HOME raggiunto → `imposta_boot_home(nome, secondi)`
- `tasks/raccolta.py` post-`_esegui_marcia` OK → `aggiungi_invio_raccolta(...)`
- `tasks/raccolta.py` end `RaccoltaTask.run()` → `imposta_raccolta_slot(...)`

**Tool analisi**: `tools/analisi_istanza_metrics.py [--prod] [--days N]` con
5 sezioni statistiche (Boot HOME, Tick totale, Task durata, Raccolta n_invii/sat,
ETA marcia per tipo). Avg/std/min/max/count per ogni metrica.

**Validazione first records** (3 record in 5 minuti):
- FAU_03 c0 340s 2 invii pomodoro+legno
- FAU_04 c0 491s 3 invii
- FAU_05 c0 290s 0 invii (slot già pieni — utile signal)

**Step proposti (NON implementati, attendere accumulo dati ~5-10 cicli)**:
- Step 3: `core/skip_predictor.py` — modulo con pesi configurabili. Input:
  storico per istanza × tipo, ETA medi marcia, durata media raccolta, ts ultimo
  invio. Output: `skip_probability ∈ [0, 1]` + reason string.
- Step 4: hook `main.py::main_loop` pre-`_thread_istanza` → consultazione
  predittore, log decisione (skip/proceed) anche se sotto soglia per audit.
- Step 5: pannello dashboard predizioni vs realtà (precision/recall, falsi
  positivi/negativi).

**Memoria**: `project_skip_predictor.md` con spec completa.

---

### Issue chiuse — Sessione 01/05 mezzogiorno (nuovo task Main Mission + dashboard fix)

#### WU88. Nuovo task `main_mission` — Main + Daily + chest milestone ✅

Aggiunto un nuovo task giornaliero (in realtà schedulato ogni 12h) per recuperare le
ricompense delle Main Mission, Daily Mission e dei chest milestone bonus.

**Pattern UI client**:
- Pannello accessibile da HOME tap (33, 398) — icona laterale sinistra
- 2 tab verticali a sinistra: "Main Missions" (50, 100) e "Daily Missions" (50, 185)
- Default all'apertura: Daily Missions attivo
- Pulsante CLAIM verde (80×35 px) appare a destra di ogni missione completata
- Daily Missions ha barra progresso "Current AP" 0-100 con 5 chest milestone
  alle soglie 20/40/60/80/100 (chest 140 visibile ma scroll, escluso dal task)
- Ogni claim apre popup reward "Congratulations! You got" con risorse
- Chiusura popup: tap su "empty space" del popup

**Censimento capacità chest** (validato FAU_01 30/04 sera):
| chest | coord | soglia AP |
|-------|-------|----------:|
| 20 | (397, 160) | 20 |
| 40 | (517, 160) | 40 |
| 60 | (633, 160) | 60 |
| 80 | (751, 160) | 80 |
| 100 | (873, 160) | 100 |

**Flow operativo** (validato live FAU_00 + FAU_02 01/05):
1. tap apri pannello (33, 398)
2. tap tab Main (50, 100)
3. loop CLAIM Main: find_one in ROI (790,265,880,305), tap fisso (832,284)
   con auto-scroll lista del client, close popup (480, 80)
4. tap tab Daily (50, 185)
5. loop CLAIM Daily: find_one in ROI ampia (810,210,895,460), **tap dinamico
   sul match** (cx, cy) — niente auto-scroll garantito
6. **OCR Current AP DOPO i claim daily** (importante: i claim aggiungono punti)
7. per ogni chest milestone <= AP: tap coord, close popup
8. BACK x1

**OCR Current AP** ROI `(180, 130, 240, 175)` — upscale 3x cubic + grayscale
+ threshold>200 + PSM7 whitelist `0123456789`. Validato 9/9 test.

**Template CLAIM**: `pin/pin_btn_claim_mission.png` 80×35 px verde
(diverso dal `pin/pin_claim.png` di alleanza — score basso 0.50 cross-match).
Validato find_all 2/2 score 0.99-1.00 a soglia 0.80.

**Bug collaterale risolto** durante test:
- Pre-fix `tap_chiudi_popup = (480, 270)` centro pannello: se popup non c'era,
  il tap cliccava una missione random e chiudeva il pannello (popup aperto su
  Search nodo invece di reward), perdendo OCR AP successivo
- Post-fix `(480, 80)` zona alta vuota — safe, sempre no-op se popup assente

**Errore precedente sulle coord**: l'utente aveva inizialmente fornito coord
errate per i tab (62, 109 + 862, 187) ma test live ha mostrato che:
- (50, 100) = tab Main Mission (sx alto)
- (50, 185) = tab Daily Mission (sx basso, default attivo)

**Logica chest in funzione di AP**: tappare chest con `milestone <= AP`. Le chest
già claimate hanno alone dorato (no-op silente al tap). Le non raggiunte sono
dim (popup di errore chiuso silentemente da tap_chiudi_popup successivo).

**Schedulazione**: priority=22 (dopo donazione=20, prima zaino=25),
**periodic 12h** (utente ha richiesto 12h vs daily 24h iniziale per coprire
2 esecuzioni nelle 24h, copre tutti i fusi reset evento).

**File toccati** (8 file):
- `tasks/main_mission.py` NEW (267 righe)
- `templates/pin/pin_btn_claim_mission.png` NEW (80×35 verde)
- `main.py` — `_catalogue` + `("tasks.main_mission", "MainMissionTask")`
- `config/task_setup.json` — entry priority 22 periodic 12h
- `config/runtime_overrides.json` — `"main_mission": true`
- `config/config_loader.py` — 3 punti: DEFAULT_GLOBAL, GlobalConfig dataclass,
  task_abilitato mapping
- `dashboard/models.py` — TaskFlags `main_mission: bool = True`
- `dashboard/app.py` — ORDER pill + ABBREV `"mainM"`

**Validazione runtime**:
- FAU_00 01/05 11:35: AP=50 letto, chest 20+40 tappati, pannello chiuso correttamente
- FAU_02 01/05 11:54: 1 daily claim a (850, 306) score 0.978, AP 0→50 post-claim,
  chest 20+40 tappati al 2° run

**Delay**: PC lento richiede valori conservativi 3s/2.5s/2s/3s/2s
(apri/tab_switch/post_tap/post_claim/back).

---

### Issue chiuse — Sessione 01/05 mattina (store debug screenshot)

#### WU85. Store debug screenshot buffer ✅

Issue: notte 30/04→1/05 store ha avuto **68% fail/skip** (15/22). Pattern bimodale
temporale (peggio sera/notte 23:00-00:30, ok alba 04:50-05:50). Tre modalità di
fail distinte:
- 6× `Store non trovato nella griglia` (scan grid fallisce)
- 9× `Merchant non confermato` (post-tap mercante UI sbagliata)
- 1× `Label non trovata`, 1× `Carrello non trovato`

**Implementazione**: buffer in-memory `_StoreDebugBuf` accumula screenshot ai
punti chiave durante esecuzione. Flush su disco SOLO se outcome != COMPLETATO
(no spreco disco sui ~30% successi).

Punti snap (8 totali):
- `_esegui_store`: pre-banner, post-banner, no-candidates, rematch-fail
- `_gestisci_negozio`: pre-tap-mercante, post-tap, label-fail, carrello-fail, merch-open-close

Path output: `data/store_debug/{istanza}_{ts}_{idx:02d}_{label}.png`.
Toggle `_DEBUG_STORE_FAIL_DUMP=True` (disattivare dopo analisi).

Decisione: data district_showdown ha cadenza mensile (non bug, fail nei giorni
fuori finestra) e bug `livello = -1` lasciato in pending.

---

### Issue chiuse — Sessione 30/04 sera (cap nodi dataset + analisi saturazione)

#### WU84. Cap nodi dataset — telemetry capacità OCR popup gather ✅

Dato che l'utente ha osservato pattern molto diversi di saturazione raccolta tra
istanze (es. FAU_06 87.5% slot pieni vs FAU_09 14.3%), serviva una metrica
oggettiva per discriminare se la causa è (a) livello target alto, (b) marcia
lunga, (c) capacità nominale, o (d) raccolta parziale di altri.

**Censimento manuale 30/04** su FAU_07 (validato 9/9 OCR test):

| Tipo (icona) | L6 | L7 |
|---|---:|---:|
| Pomodoro (Field) | 1,200,000 | 1,320,000 |
| Legno (Sawmill) | 1,200,000 | 1,320,000 |
| Acciaio (Steel Mill) | 600,000 | 660,000 |
| Petrolio (Oil Refinery) | 240,000 | 264,000 |

Pattern: **L7 = L6 × 1.10** (esatto). Pomodoro = Legno = base 100%,
Acciaio = 50%, Petrolio = 20%.

**Implementazione (4 file)**:
- `shared/ocr_helpers.py` — `leggi_capacita_nodo(img)` con ROI fissa
  `(270, 280, 420, 320)` (popup si apre sempre al centro mappa).
  Cascade PSM 6 raw RGB → fallback PSM 6 binv (threshold 150). Validato 9/9
  su screen reali FAU_07 (incluso nodo residuo 903,714 da raccolta in corso).
- `shared/cap_nodi_dataset.py` — modulo nuovo, `registra_cap_sample(instance,
  tipo, livello, capacita)` → append JSONL `data/cap_nodi_dataset.jsonl`.
  Best-effort, silent on I/O error. Lock thread-safe.
- `tasks/raccolta.py` — hook subito dopo `_leggi_livello_nodo` ([raccolta.py:1719](tasks/raccolta.py#L1719)).
  Chiama OCR + registra sample anche su nodi sotto livello_min (copertura
  completa dataset). `try/except` esterno: nessun impatto su tick raccolta.
- `tools/analisi_cap_nodi.py` — script CLI, sezioni: capacità per (tipo,liv) /
  campioni per istanza / residuo medio per (istanza,tipo). Flag `--prod` `--days N`.

**Anche**: `sync_prod.bat` esteso con riga `xcopy tools/*.py` (mancava).

**Use case**:
- Capacità < max ⇒ nodo già parzialmente raccolto da altri
- Massima osservata per (tipo, livello) = capacità nominale runtime
- % residuo medio per istanza → indicatore sano competizione territorio
- Sviluppi futuri: confronto load_squadra vs capacità → saturazione invio

Memoria: `reference_capacita_nodi.md`. Sync prod + restart bot 30/04 19:18.

---

### Issue chiuse — Sessione 30/04 mattina (arena fix completi + WU82-83)

#### WU83. Arena rebuild truppe pre-1ª sfida del giorno ✅

L'utente osservava che a inizio giornata le truppe arena potevano essere
sub-ottimali (squadre rimaste della sera prima, magari livelli vecchi
post-training notturno). Decisione: 1×/die UTC alla 1ª sfida del giorno,
**rimuovi tutte le truppe + ricarica via READY auto-deploy** che il client
sceglie con composizione migliore disponibile.

**Mappatura coord live FAU_06 (4 celle) + FAU_00 (5 celle)**:
- Rimozione `−`: (80, 80) / (80, 148) / (80, 216) / (80, 283) / (80, 351)
- Apertura cella `+`: (42, 100) / (42, 170) / (42, 240) / (42, 310) / (42, 380)
- READY auto-deploy: (723, 482)
- 5ª cella su istanze 4-cella è LUCCHETTATA → ignorata silenziosamente

**N celle dinamico** = `ctx.config.max_squadre` (5 per FAU_00/FauMorfeus, 4 altre).

**Flow WU83**:
```python
if run.sfide_eseguite == 0 and not _deploy_done_today(nome):
    n = max_squadre
    for i in range(n):
        tap(_TAP_REMOVE_TRUPPA[i])          # rimuovi
    for i in range(n):
        tap(_TAP_OPEN_CELLA[i])             # apri selettore
        tap(_TAP_READY_DEPLOY)              # auto-deploy
    _mark_deploy_done(nome)                 # 1×/die marker
    re-check START CHALLENGE post-rebuild
```

**State**: `data/arena_deploy_state.json` con `{"FAU_00": "2026-04-30", ...}`,
atomic write tmp+os.replace.

**Validazione runtime**:
- FAU_06 (4 celle): power 431k → empty 12k → deploy 685k (**+59% truppe nuove**)
- FAU_00 (5 celle): power 17.0M → empty 7.8M → deploy 17.0M (composizione invariata, già max)

**Costo**: ~25-30s solo 1×/die UTC per istanza. Su run successivi del giorno
skip per check `_deploy_done_today`.

#### WU82. Arena wait battaglia 60s → 15s ✅

Con driver DirectX (Issue #88) + skip ON garantito (WU74), battaglie con
animazione skippata durano <10s. Il `time.sleep(60s)` di WU75 era
sovradimensionato.

**Fix**: in `tasks/arena.py:86-88`:
- `_DELAY_BATTAGLIA_S`: 8.0 → 5.0
- `_MAX_BATTAGLIA_S`: 52.0 → 10.0

Totale wait: 60s → **15s** per sfida.

**Saving**: 45s/sfida × 5 sfide = **225s/ciclo arena** (~3.75 min).



#### Issue #88. Cascade ADB durante arena — driver Vulkan MuMu ✅

**Bug osservato 30/04** durante test live arena FAU_10: ADB offline
**immediato** al tap START CHALLENGE. WU75 (no polling) + WU76 (in-memory)
NON eliminavano cascade — il problema scattava prima di qualsiasi screencap.

**Test esclusione**:
- Settings video LOW vs HIGH stesso esito (cascade)
- WU76 in-memory benchmark più lento (1526ms vs 1185ms legacy) → I/O non era bottleneck

**Root cause**: driver **Vulkan** di MuMu Player crasha il bridge ADB su
animazione 3D battle. Bug noto MuMu/Hyper-V/Doomsday Last Survivors specifico.

**Soluzione**: switch driver da **Vulkan → DirectX** (manuale utente in
MuMu Settings → Display → Render mode).

**Validazione runtime**:
- FAU_10: 271/271 polling ADB ONLINE in 3 sfide consecutive
- FAU_00: 432/432 ONLINE in 2 sfide
- FAU_01: 161/161 ONLINE in 1 sfida
- **Totale 864/864 ONLINE, 0 OFFLINE** (vs cascade endemica pre-fix)

**Da applicare**: tutte le 11 istanze MuMu (manuale utente).

#### Issue #89. Template arena Failure/Victory/Continue stale ✅

Con cascade ADB risolto da Issue #88, finalmente visualizzabile il
popup post-battle. Client gioco ha **ridisegnato la UI**: tutti e 3 i
template esistenti (del 30 marzo) sono stale.

**Estrazione live**:
- **Failure** FAU_10: testo bianco grande su sfondo magenta in
  (380,42,535,88), 155×46 px. Score 0.998
- **Victory** FAU_00 (rank 81→53): testo bianco grande su sfondo dorato,
  155×46 px stesse coord. Score 1.000 self-match
- **Continue** "Tap to Continue" corsivo bianco posizione VARIABILE:
  - Victory: centro (457, 469)
  - Failure: centro (457, 516)
  - Delta 47 pixel → coord fisse non valide (vedi WU80)

**ROI nuove**: (370, 35, 545, 95) per Victory + Failure (per ROI ≥ template).
ROI Continue (370, 495, 545, 540).

**Soglia**: 0.80 → 0.90 (vedi WU81 per anti-falso positivo).

#### WU80. Arena tap dinamico Continue (loc match) ✅

Pre-fix: coord fisse `_TAP_CONTINUE_VICTORY` (457,462) e `_FAILURE` (457,509).
Issue #89 ha rivelato che il pulsante "Tap to Continue" è in posizione
diversa tra Victory (y=469) e Failure (y=516) — coord fisse non risolvono.

**Fix**: in `tasks/arena.py` post-battaglia, match template `continue` su
zone (370, 495, 545, 540) e `tap(cont_result.cx, cont_result.cy)` su loc
del match. Fallback coord fisse solo se match fallisce.

#### WU81. Arena soglia victory/failure 0.80 → 0.90 ✅

Su FAU_00 sfida 2 (Failure reale), il template `victory` matchava score
**0.847** (>0.80 soglia) — falso positivo strutturale (font/dimensioni
simili). Logica del bot `if victory: ... elif failure:` avrebbe
interpretato Failure come Victory.

Soglia rinforzata a **0.90**. Discriminazione validata:
- FAU_00 sfida 2 Failure: victory=0.847 (no), failure=0.995 (sì) ✓
- FAU_01 sfida 1 Failure: victory=0.591 (no), failure=0.999 (sì) ✓

#### WU78-rev. Settings_helper coord HIGH/MID/HIGH calibrate live ✅

Issue #88 risolto rende inutili settings ULTRA-LOW (Graphics LOW + Frame
LOW + Optimize LOW). Bot ora imposta HIGH/MID/HIGH (matching FAU_10 manuale).

**Coord calibrate live FAU_00 30/04** (utente provided):
- `_TAP_GRAPHICS_HIGH = (809, 123)` — slider HIGH
- `_TAP_FRAME_MID = (717, 209)` — radio MID
- `_TAP_OPTIMIZE_HIGH = (229, 330)` — pulsante HIGH

Coord fisse cross-istanza (le settings sono nello stesso layout su tutte le istanze).

---

### Issue chiuse — Sessione 29/04 sera

#### WU64. Pulizia cache giornaliera (1×/die per istanza) ✅

Estensione di `core/settings_helper.imposta_settings_lightweight`. Dopo
i toggle Graphics/Frame/Optimize, esegue 1×/die UTC per istanza:
Avatar→Settings→**Help (570,235)→Clear cache (666,375)→Clear icon (480,200)
→polling CLOSE template ogni 5s (max 120s)→CLOSE (480,445)**→back-extra→2 BACK.

- **Stato persistito** in `data/cache_state.json` (granularità giornaliera UTC).
  Skip-on-already-done idempotente. State path env-aware (`DOOMSDAY_ROOT`).
- **Template estratto** `templates/pin/pin_clear_cache_close.png` (140×34, soglia
  0.85). Validato score: HOME no-popup 0.022, popup pre-clear 0.028,
  popup post-clear 1.000 (margine 0.97).
- **Coord calibrate FAU_10** 29/04 19:11 con tap-test live ADB.
- **Runtime FAU_10 c4 19:42**: CLOSE rilevato dopo 6s primo polling
  (score 1.000). Settings totale 61.1s (35s base + 22s pulizia + 4s nav).
  Idempotenza confermata FAU_00 c5: "cache già pulita oggi → skip".

#### WU65. Lettura giornaliera Total Squads + storico crescita 365gg ✅

Nuovo modulo `core/troops_reader.py`. Hook in `core/launcher.attendi_home`
post-settings, **1×/die UTC** per istanza:

```
HOME → tap Avatar (48,37) → tap Squads (895,509) → OCR _ZONA_TOTAL_SQUADS
(830,60,945,90) → append data/storico_truppe.json[nome] → 2 BACK
```

- **OCR cascade** otsu→binary, sanity range `1.000≤val≤999.000.000`.
- **Storage**: `data/storico_truppe.json` schema
  `{"FAU_00": [{"data": "YYYY-MM-DD", "total_squads": N, "ts": "ISO"}]}`,
  retention 365gg, atomic write tmp+os.replace, idempotenza intra-day.
- **Runtime FAU_10 c4**: `total_squads=112,848` registrato in 16.8s.
- **FAU_00 c5**: `total_squads=2,665,764` (24× FAU_10 — istanza grande).

#### WU66. Dashboard truppe — Layout A (card) + Layout B (storico 8gg) ✅

**Layout A** — riga truppe in `partial_produzione_istanze` per ogni istanza:
```
🪖 truppe: 112,848   Δ7gg —   sparkline ······▁
```

- Δ7gg verde se positivo, rosso se negativo, grigio se mancano dati 7gg fa
- Sparkline 7 char (oggi-6..oggi), tooltip valori esatti
- Color coding adattivo

**Layout B** — nuovo endpoint `/ui/partial/truppe-storico` + section in
`templates/index.html`. Tabella con colonne: istanza | oggi | 7gg fa |
Δ (Δ%) | trend 8gg sparkline. Riga TOTALE in fondo. Ordinamento per
delta_pct desc (chi cresce più sopra). HTMX refresh 60s.

**Funzioni nuove** in `dashboard/services/stats_reader.py`:
- `_load_storico_truppe()` — load JSON
- `get_truppe_istanza(nome)` — Layout A (oggi, 7gg fa, delta, delta_pct, serie_7d)
- `get_truppe_storico_aggregato(days=8)` — Layout B (per_istanza ordinato + totale)

#### Issue #85. Glory popup tier-up — fix ROI 270×60 ✅

**ROOT CAUSE**: template `pin_arena_07_glory.png` è 225×35 px, ROI in
`tasks/arena.py::_ARENA_PIN["glory"]` era `(380,410,570,458)` = 190×48 →
**`cv2.matchTemplate` rifiuta perché template > image, match sempre impossibile**.

**Fix**: ROI espansa a `(345,405,615,465)` = 270×60 (centro ~480 ±135, y 405-465).

**Conseguenza pre-fix**: il popup Glory comparso a fine season (cambio rank
Bronze→Silver→...) bloccava arena perché bot non riusciva a tappare Continue.

#### WU67. Raccolta livello — reset+conta sostituito con delta diretto ✅

Pre-fix: ogni raccolta che chiede livello diverso da quello corrente faceva
**SEMPRE 7 tap meno (reset Lv.1) + N tap piu (conta da Lv.1 a target)** =
7..13 tap, 1.5-3s.

Post-fix: legge livello pannello via OCR (`_leggi_livello_panel` esistente),
calcola delta = target - panel, fa solo `|delta|` tap nella direzione giusta:

```python
delta = livello - livello_panel
if delta > 0: tap_piu × delta
else:         tap_meno × abs(delta)
```

- **Saving**: 1.5-2s/raccolta × ~100 raccolte/die × 11 istanze ≈ ~25-35min/die
- Mantiene il branch `livello_panel == -1` (OCR fail) come fallback reset+conta

#### WU68. Sanity OCR slot post-marcia: `attive_map < attive_pre` → fallback HOME ✅

In `tasks/raccolta.py::_aggiorna_slot_in_mappa` aggiunto sanity check
deterministico DOPO la lettura OCR MAP:

```python
# attive_pre = pre_marcia + 1 (bot ha appena confermato +1 squadra)
if 0 <= attive_map < attive_pre:
    # Sospetto bug OCR (es. "5"→"4") OPPURE squadra rientrata (~15s, raro).
    # Fallback HOME (più stabile) per disambiguare.
    return _reset_to_mappa(ctx, obiettivo)
```

- **Cattura il caso `5/5 letti come 4/5`** (opposto del 4↔7 già coperto da
  cross-validation `attive>totale`).
- **Costo**: ~13-15s per fallback HOME, solo nel ~2-3% sospetto.

#### WU69. Pattern detection slot pieni — 2× maschera_not_opened → break ✅

Quando il client gioco rifiuta l'apertura della maschera invio (slot pieni
reali), il bot vedeva `maschera NON aperta score=0.38` e procedeva ad altri
tipi sprecando 60-90s in 3 tentativi.

**Fix**: nuovo flag `ctx._raccolta_mask_not_opened` settato in `_esegui_marcia`
quando maschera non si apre 2× (e pin_no_squads NON trovato). Counter
`mask_not_opened_streak` in `_loop_invio_marce`:

```python
if ctx._raccolta_mask_not_opened:
    mask_not_opened_streak += 1
    if mask_not_opened_streak >= 2:
        ctx._raccolta_slot_pieni = True
        break  # esci dal for, then while
```

In `RaccoltaTask.run` controllo flag dopo `_loop_invio_marce` → break dal
while esterno + log "slot pieni dedotti — chiusura istanza".

- **Saving**: 60-90s per ciclo patologico (3 tentativi × 20-30s → 1 + uscita)
- Reset streak su invio OK / tipo_bloccato / skip_neutro (causa diversa)

#### WU70. OCR slot SX-only ensemble — risolve bug "5→7" ✅

**Root cause confermata su FAU_00 c5** (max_squadre=5): tesseract con flow
`_ocr_zona_intera_slot` (psm 6/7/13 sul pattern X/Y intero) confonde
`5/5 → 7/5`. La cross-validation esistente `a8fb4ca` cattura `attive>totale`
(skip conservativo) ma NON recupera il valore corretto.

**Fix proposto dall'utente**: tagliare il "/" e l'intera cifra DX,
leggere SOLO la SX in ROI isolata 10×24px, totale dalla config.

Implementato come **branch primario** in `shared/ocr_helpers.leggi_contatore_slot`
quando `totale_noto > 0`:

```python
crop_sx = pil_img.crop(_ZONA_CIFRA_SX)  # 10×24 isolato
attive_psm10 = _ocr_cifra_singola_slot(crop_sx, psm=10)
attive_psm8  = _ocr_cifra_singola_slot(crop_sx, psm=8)
attive_psm7  = _ocr_cifra_singola_slot(crop_sx, psm=7)

# Sanity pre-vote: scarta valori >totale_noto (impossibili)
plausibili = [v for v in (attive_psm10, attive_psm8, attive_psm7)
              if 0 <= v <= totale_noto]
if plausibili:
    attive = Counter(plausibili).most_common(1)[0][0]  # majority vote
    return (attive, totale_noto)  # totale deterministic
# else fallthrough flow legacy
```

- ROI piccola (cifra singola) → no disturbi da "/" o DX a confondere SX
- 3 PSM in ensemble (10 single-char, 8 single-word, 7 single-line)
- Sanity rigorosa scarta `7` quando max=5 (anche se 1/3 PSM legge giusto vince)
- Costo: 3× tesseract calls ~200-300ms (trascurabile vs 1.5s sleep)
- Fallback flow legacy se tutti i PSM ritornano valori non plausibili

**Validazione runtime FAU_00 c6** (29/04 21:29):
- Pre-fix c5: `OCR slot anomalo attive=7>totale=5 → skip conservativo` (0 inviate)
- Post-fix c6: `slot OCR — attive=5/5 libere=0` corretto, **1 squadra inviata**
  + `slot pieni — uscita` pulito.

#### WU76. Screenshot pipeline in-memory (port V5 v5.24 → V6) ✅

**Bug osservato 30/04 mattina** — analizzando perché il `tap START
CHALLENGE` causava ADB offline immediato anche con WU75 attivo (no
polling 17 screencap), scoperto che `core/device.py::_screenshot_raw`
faceva I/O su disco per ogni screenshot:

```python
# Pre-fix V6 (3 operazioni I/O per screencap):
adb shell screencap -p /sdcard/v6_screen.png    # 1) write su sdcard device
adb pull remote local                            # 2) read+write su disco host
cv2.imread(local)                                # 3) read da disco host
os.remove(local)                                 # 4) delete da disco host
```

V5 ha già la pipeline in-memory dal commit v5.24
("Aggiunta pipeline screenshot in-memoria (exec-out)") con saving
documentato "150-300ms per chiamata". V6 non l'ha mai portato.

**Fix WU76**: refactor `_screenshot_raw` in `core/device.py`:

```python
# Post-fix WU76 (0 operazioni I/O):
result = subprocess.run(
    [adb, "-s", port, "exec-out", "screencap", "-p"],
    capture_output=True, timeout=15,
)
png_bytes = result.stdout
arr = np.frombuffer(png_bytes, dtype=np.uint8)
frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
```

**Caratteristiche**:
- Sanity check PNG header (`b"\x89PNG"`) prima di imdecode
- Fallback legacy `screencap+pull` se exec-out fallisce (compat ADB vecchio)
- Lock per-porta + lock globale invariati

**Saving**:
- I/O disco: 3-4 op/screen → 0 op
- Latenza: ~300-500ms → ~50-200ms (-66%/-83% V5 commento)
- Carico ADB durante burst (arena, raccolta): saturazione eliminata

**Effetto atteso su cascade ADB**: dovrebbe sparire o ridursi >>50%.
Combinato con WU74+WU75, arena dovrebbe diventare stabile.

**Smoke test 30/04**: 5/5 screencap consecutivi via exec-out su FAU_10
ritornano frame `(540, 960, 3)` valido. Latenza misurata 1.1-2.4s su
istanza appena riavviata (CPU/RAM stressate post-boot) — sotto regime
normale dovrebbe essere molto più veloce.

**Validazione runtime**: pendente, attivo al prossimo restart bot.

#### WU75. Arena — sleep passivo battaglia + 1 check final (era 17 polling) ✅

**Bug osservato 30/04 mattina** dall'utente analizzando cascade ADB pattern:
8/11 istanze il 30/04 con cascade ADB durante arena (FAU_00, 01, 03, 04, 06,
07, 08, 10 — da 6 a 17 screenshot falliti). FAU_02, FAU_05, FAU_09 senza
cascade. La cascade NON era correlata al timeout battaglia (FAU_05 5/5
timeout, 0 cascade) ma scattava DOPO battaglia, durante transizione tra
sfide su template `lista`/`purchase`/`challenge`.

**Root cause**: il polling durante battaglia faceva 17 screencap (ogni 3.5s
× 60s) + 8 screencap nella transizione post-Continue (glory + lista×3 +
purchase×2 + challenge). 25 screencap in burst rate ~1/2s saturavano il
socket ADB di MuMu già stressato dalle animazioni 3D battle.

**Fix**: refactor `_attendi_fine_battaglia` da polling a `sleep(60s) +
1 screencap`:

```python
# Pre-fix: while polling ogni 3.5s × 60s = 17 screencap
while time.time() - t_start < 60:
    screencap → match victory + failure
    time.sleep(3.5)

# Post-fix WU75: sleep passivo + 1 check
time.sleep(60.0)
screen = ctx.device.screenshot()
victory = match victory
failure = match failure
```

- **Saving**: ~94% screencap durante battaglia (17→1)
- **Trade-off**: timeout 60s comunque rispettato; se skip OFF reale (WU74
  false positive non risolto) battaglia >60s → check final fallisce → timeout
- **Combinazione con WU74**: skip ON ad ogni sfida + sleep passivo + 1 check
  = battaglie pulite senza cascade ADB
- **Validazione**: pendente, attivo al prossimo restart bot

#### WU74. Arena — check skip checkbox ad ogni sfida (era 1×/sessione) ✅

**Bug osservato 30/04 mattina** dall'utente analizzando i timeout arena: 5/8
istanze avevano timeout battaglia 60s sistematici (FAU_05 5/5 timeout, FAU_09
3/5, FAU_01 3/5). Pattern non spiegato dai template victory/failure (lo score
0.14-0.20 era corretto durante battaglia in corso).

**Root cause**: in `tasks/arena.py:387` flag `run.skip_verificato` causava
verifica skip checkbox SOLO alla 1ª sfida. Per sfide 2-5 nessun re-check.

**Trigger scoperto**: la pulizia cache giornaliera WU64 (eseguita prima
di arena su tutte le istanze il 30/04 UTC) **resetta al default visivo**
il checkbox skip nel client. Poi:
- FAU_02: bot rileva `OFF→tap` → skip attivato → 0 timeout su 5 sfide ✓
- FAU_05: bot rileva `Skip già attivo` (FALSO POSITIVO) → no tap → skip
  resta OFF reale → 5/5 timeout 60s

Il template `pin_arena_check.png` matcha anche con skip OFF perché ROI
`(700,470,760,510)` identica a `pin_arena_no_check.png` — discriminazione
fragile su pixel marginali.

**Fix**: rimosso flag, `_assicura_skip()` chiamato ad ogni sfida.

```python
# Pre-fix
if not run.skip_verificato:
    self._assicura_skip(ctx)
    run.skip_verificato = True

# Post-fix WU74
self._assicura_skip(ctx)  # ad ogni sfida
```

- **Costo**: +1.5s/sfida × 5 = +7.5s/ciclo arena (trascurabile vs ~5min totali)
- **Beneficio**: skip sempre realmente attivo, eliminazione timeout sistematico
- **Validazione**: pendente, attivo al prossimo restart bot

#### WU73. Dashboard storico truppe — ordinamento alfabetico ✅

In `get_truppe_storico_aggregato`: sort key cambiato da `delta_pct desc` a
`r["nome"]` → ordine FAU_00, FAU_01, ..., FAU_10, FauMorfeus. Più intuitivo
per debug per-istanza (richiesta utente 30/04 notte).

#### WU72. Dashboard storico cicli — UTC raw vs ora locale ✅

**Bug osservato 30/04 notte** dall'utente: pannello "📚 storico cicli" mostrava
ciclo #43 con `start=22:58` (UTC raw) mentre la card istanza FAU_00 mostrava
avvio `01:02` (ora locale). Disallineamento di 2h confonde la lettura.

**Bug aggiuntivo a cavallo mezzanotte UTC**: ciclo iniziato `2026-04-29T22:58 UTC`
veniva visualizzato `data=29/04` mentre era già il `30/04` ora locale (`00:58`).

**Root cause**: in [`dashboard/services/telemetry_reader.get_storico_cicli`](dashboard/services/telemetry_reader.py)
slicing `ts_start[11:16]` e `ts_start[8:10]/[5:7]` estraeva direttamente i
caratteri della stringa ISO UTC senza conversione in fuso locale.

**Fix**: nuove helper `_ts_to_local_hhmm()` e `_ts_to_local_date()` con
`datetime.fromisoformat(ts).astimezone().strftime(...)` che converte in ora
locale del server. Coerente con card istanza (già in locale).

**Validazione runtime** post-restart dashboard:
- ciclo #43: pre `data=29/04 start=22:58` → post `data=30/04 start=00:58` ✓
- ciclo #42: end correctly mostrato a cavallo mezzanotte (`23:34→00:57`)

#### WU71. Stabilizzazione HOME — polling 3s → 1s ✅

In `core/launcher.attendi_home::stabilizzazione`, ridotto `time.sleep(3.0)
→ 1.0` nel polling stable_count consecutive HOME.

- **Saving**: 5 stable × 2s = 10s/istanza × 11 istanze ≈ **110s/ciclo**
- Trade-off: 3× screenshot+template-match al secondo durante stab (window
  max 60s). Su PC lento il costo CPU è bilanciato dal saving wallclock.
- **Stato**: deployed, attivo al prossimo restart spontaneo.

---

### Issue chiuse — Sessione 29/04 pomeriggio (continua 3)

#### WU63. Audit debug PNG su disco + cleanup ✅

**Audit completo** dei punti che scrivono PNG durante runtime bot prod:

| File | Funzione | Trigger | Stato post-audit |
|------|----------|---------|------------------|
| `shared/ocr_dataset.py:106-118` | `salva_ocr_pair` (WU55) | flag `raccolta_ocr_debug` | ❌ **SPENTO 29/04** (era `true` in prod, ora `false`) |
| `core/launcher.py:679-695` | `_save_discovery_snapshot` | UNKNOWN streak {5,10,15,20} | ✅ MANTENUTO (utile per banner discovery, cap 4/ciclo) |
| `shared/ocr_helpers.py:414-415` | OCR slot fail debug | psm 6/7/13 tutti KO | ✅ ATTIVO (2 file fissi sovrascritti, trascurabile) |
| `tasks/raccolta.py:546` `_salva_debug_verifica` | anomalia score `pin_verifica_*` | trigger anomalia | ✅ ATTIVO (mai scattato finora) |
| `tasks/raccolta.py:920` `_salva_debug_lv_panel` | livello panel | cap interno MAX_DEBUG_FILES | ✅ ATTIVO (cap interno) |
| `tasks/boost.py:78` `_salva_debug_shot` | — | chiamate commentate | ❌ DISABILITATO (Issue #59) |

**Cleanup file PNG già accumulati in PROD** (29/04):
- `data/ocr_dataset/` — 2040 file, **445 MB** → cancellati
- `debug_task/screenshots/` — 1 file 2 MB → cancellato (test manuale 28/04)
- `debug_task/vai_in_home_unknown/` — 3 file 2 MB → cancellati (cartella deprecata Issue #63)
- `debug_task/boot_unknown/` — 11 file 9 MB → **MANTENUTO** (utile discovery)

**Totale liberato**: ~448 MB su disco prod. Toggle `raccolta_ocr_debug` ora
`false` in `runtime_overrides.json` prod (hot-reload prossimo tick — niente
restart richiesto).

#### WU62. Nuovo task TRUPPE — addestramento automatico 4 caserme ✅

**Scenario**: 4 caserme fisse per tipologia (Fanteria / Cavalleria / Arcieri /
Macchine). Il client gioco espone nella colonna sx HOME un'icona scudo+2 fucili
con counter `X/4` dove X = caserme attualmente in addestramento.

**Comportamento utile scoperto in test**: tap sull'icona pannello porta
*automaticamente* alla prossima caserma libera (skip automatico di quelle
già in addestramento). Niente scan mappa necessario per individuare le
caserme. Decisione: **niente template matching dinamico per il MVP** —
tutte le coord sono FISSE.

**Coord calibrate su FAU_05** (960×540):

| Step | Coord | Tipo |
|------|-------|------|
| Pannello caserme (col sx HOME) | `(30, 247)` | FISSA |
| Cerchio "Train" del menu mappa post-(30,247) | `(564, 382)` | FISSA |
| Pulsante TRAIN giallo (Squad Training screen) | `(794, 471)` | FISSA |
| Checkbox "Fast Training" tap | `(687, 508)` | FISSA |
| Box pixel checkbox per stato | `(676, 497)→(699, 518)` | FISSA |
| Zona OCR counter X/4 | `(12, 264, 30, 282)` | FISSA |

**OCR counter cascade** (`shared/ocr_helpers.ocr_cifre`):
- Preprocessor primario `otsu` → funziona per X ∈ {1,2,3,4}
- Fallback `binary` → necessario per X==0 (otsu lo perde per contrasto basso)
- Validato su 5 stati 0/4..4/4 in test reale

**Vincolo Fast Training**: checkbox SEMPRE OFF (premium-free). Stato letto
via R-mean del box pixel: `R > 110 → ON`. Soglia derivata dal confronto
sample: OFF ≈ RGB(88,65,45), ON ≈ RGB(134,97,65).

**Test reale FAU_05** (29/04 14:55-15:10):
4 cicli consecutivi 0/4 → 4/4, tutti OK. Checkbox sempre OFF in tutti i
4 cicli. 4 tipi caserme gestite con stesse coord: Infantry (Ruffian),
Rider (Iron Cavalry), Ranged (Ranger), Engine (Rover).

**Flow MVP** (`tasks/truppe.py`):
1. `vai_in_home()`
2. Leggi counter X via OCR cascade
3. Se X==4 → skip (TaskResult.skip)
4. Per (4-X) volte:
   a. tap `(30, 247)` → sleep 5s
   b. tap `(564, 382)` → sleep 5s [apre Squad Training]
   c. verifica box checkbox; se R-mean>110 → tap `(687, 508)` → sleep 5s
   d. tap `(794, 471)` → sleep 5s [TRAIN avviato]
5. Re-leggi counter (best effort, log)
6. `tap_barra("city")` → ritorno HOME

**Integrazione**:
- `tasks/truppe.py` — NUOVO file
- `config/task_setup.json` — aggiunta `TruppeTask` priority **18**, periodic **4h**
  (subito dopo `RaccoltaTask=15`, prima di `DonazioneTask=20`. Logica: i primi 3
  task sono sempre Boost→Rifornimento→Raccolta, gli altri seguono)
- `main.py::_import_tasks` — aggiunto import
- `dashboard/models.py::TaskFlags` — flag `truppe: bool = True`
- `dashboard/routers/api_config_overrides.py` — `truppe` in `valid_tasks`
- `dashboard/app.py::partial_task_flags_v2::ORDER` — `truppe` aggiunto alla
  pill UI (Row 3 con `arena`); `district_showdown` orfano in ultima riga

**Template estratti** (in `templates/pin/`, **non usati dal MVP**, riserva
per robustezza futura template matching):
- `pin_truppe_pannello.png` (55×36) — icona scudo+fucili
- `pin_truppe_train_btn.png` (100×29) — pulsante TRAIN giallo
- `pin_truppe_check_off.png` (23×21) — checkbox vuoto
- `pin_truppe_check_on.png` (23×21) — checkbox con spunta dorata

**Stato sync prod**: NUOVO file `tasks/truppe.py` + 4 PNG + modifiche
config/main/dashboard. **Bot prod da riavviare** per attivare il nuovo task.

### Issue chiuse — Sessione 29/04 pomeriggio (continua 2)

#### WU61. Test FAU_03 reinstallato + integrazione settings_helper in launcher ✅

**Test FAU_03** (29/04 13:16-13:19, porta ADB 16480):
Script: `c:\tmp\test_fau03_settings_arena.py`. Sequenza:
PRE-Glory dismiss → FASE 1 settings → FASE 2 Campaign / Arena of Doom /
Glory check (opt) / 5 sfide.

| Fase | Esito | Note |
|------|-------|------|
| PRE Glory dismiss | ⚠️ NON esercitato | popup non visibile all'avvio test |
| FASE 1 Settings | ✅ 22.5s | Optimize template score 0.998 |
| Glory post-Arena of Doom | ⚠️ NON esercitato | popup non comparso nel flow |
| FASE 2 Arena 5 sfide | ✅ 159.6s — 31.9s/sfida | Identico a FAU_02 |

**Issue #85 NON validato** in questa sessione (popup Glory assente in entrambi
gli hook). PNG nuovo + ROI espansa rimangono in posizione. Validazione end-to-end
rimandata al prossimo cambio tier in produzione.

**FAU_03 stabile post-reinstallazione**: ADB stabile, no cascade, no freeze,
arena 5/5 = pattern identico FAU_02. Conferma efficacia pulizia/reinstallazione
istanze MuMu come fix per cascata ADB persistente.

**Integrazione `imposta_settings_lightweight()` in `core/launcher.py`**:

Hook in `attendi_home()` dopo `nav.vai_in_home()` finale (HOME confermata).
Try/except con lazy import → errori non bloccano avvio istanza, solo log warn.
`_SettingsCtx` minimale (device + matcher + navigator).

**Effetto runtime**: ad ogni avvio istanza, dopo HOME stabile, applica
sequenza Avatar→Settings→System→Graphics LOW→Frame LOW→Optimize check→3 BACK
(~22s/istanza). Idempotente per Optimize (template check ROI 108-198×317-357).
Costo aggregato: 12 istanze × 22s × 2 cicli/h = ~9 min/h aggiuntivi.

**Stato sync prod**: `core/launcher.py`, `core/settings_helper.py`,
`tasks/arena.py`, `templates/pin/pin_arena_07_glory.png`,
`templates/pin/pin_settings_optimize_low_active.png`. Bot prod **da riavviare**
manualmente per attivare l'integrazione (decisione utente — bot in pausa,
modalità raccolta-only).

### Issue chiuse — Sessione 29/04 pomeriggio

#### WU60. Settings lightweight client gioco — `core/settings_helper.py` ✅

**Motivazione**: Cascata ADB persistente su FAU_02/03/04 durante test arena
diretto (FAU_00 stabile). Ipotesi: settings client gioco non lightweight
+ MuMu out-of-date → instabilità rendering. Verifica manuale FAU_01:
con Graphics LOW + Frame Rate LOW + Optimize Mode LOW il flow regge.

**Implementazione**: nuovo modulo `core/settings_helper.py` con
`imposta_settings_lightweight(ctx, log_fn)`:
- Sequenza 8 step: Avatar→Settings→System→Graphics LOW→Frame LOW→
  check Optimize visuale→[tap se non attivo]→3 BACK.
- Coordinate calibrate via `getevent /dev/input/event4` su FAU_01
  (960×540 display).
- Toggle stateful Optimize Mode: pre-screenshot + match template
  `pin_settings_optimize_low_active.png` (ROI 108-198 × 317-357,
  soglia 0.70). Skip tap se già attivo (idempotenza forzata via vista).
- Delay maggiorati per PC lento (utente conferma checkbox match instabile):
  `_DELAY_NAV=3.0s`, `_DELAY_TOGGLE=2.0s`, `_DELAY_PRE_CHECK=1.5s`,
  `_DELAY_BACK=2.0s`. Tempo totale ~22s/istanza.

**Stato**: modulo creato e validato su FAU_01 (score Optimize 1.000).
Test FAU_02 (settings OK, arena KO) → settings da soli non risolvono cascata
ADB; necessaria reinstallazione istanza. **Integrazione in `launcher.py`
RIMANDATA** post-pulizia istanze.

### Issue chiuse — Sessione 29/04 mattina

#### WU58. Dashboard mostra dati daily stale dopo pausa lunga (29/04) ✅

**Sintomo**: dopo pausa 22:56-05:46 in modalità manutenzione + task
rifornimento OFF da ieri sera, dashboard mostrava `inviato_oggi` e
`provv. lorde/nette` con valori di ieri come se fossero di oggi.

**Causa**: `state/FAU_*.json::rifornimento` mantiene `data_riferimento` +
totali daily aggiornati solo quando il task rifornimento gira (chiamando
`_controlla_reset` che azzera al cambio giorno).

**Fix** in `dashboard/services/stats_reader.py` — 3 funzioni:
1. `get_state_per_istanza()`: se `data_riferimento != today_utc` azzera
   in-memory spedizioni, inviato netto/lordo, tassa, dettaglio, provviste.
2. `get_risorse_farm()`: stessa logica per pannello aggregato.
3. `_load_morfeus_state()`: se `ts[:10] != today_utc` → `daily_recv_limit=-1`
   (dashboard mostra "capienza morfeus —").

State file NON toccato: il bot lo azzera al primo tick rifornimento di oggi.

#### WU59. Pannello "📚 storico cicli" — colonna DATA ✅

**Sintomo**: dopo pausa 28→29/04 i cicli di ieri/oggi indistinguibili
(dashboard mostrava solo HH:MM → HH:MM).

**Fix**:
- `CicloStorico.start_date` (formato DD/MM UTC) in `telemetry_reader.py`.
- Colonna "data" tra "ciclo" e "finestra" in `partial_telemetria_storico_cicli`.

### Issue aperte — Arena Watch/Challenge + Orchestrator last_run

#### 83. Arena `_TAP_ULTIMA_SFIDA` cieco — freeze su righe "Watch" (28/04 sera)

**Sintomo:** dopo reset arena schedule (state azzerato 28/04 19:15), arena
parte ma blocca dopo 0-1 sfide su istanze con sfide già combattute oggi.

**Root cause:** `tasks/arena.py:58` ha `_TAP_ULTIMA_SFIDA = (745, 482)` —
coordinata fissa V5. Tappa la "ultima riga" della lista 5 sfide
indipendentemente dal pulsante presente. Ogni riga ha pulsante variabile:
- "Challenge" (sfida nuova) → entra in popup Challenge Info → bot trova pin
  `challenge` 0.993 → tap START CHALLENGE → battaglia OK
- "Watch" / replay (sfida già combattuta oggi) → entra in **modalità
  visualizzazione battaglia** → schermata transitoria senza pin riconoscibili
  → screenshot ADB iniziano a fallire (gioco bloccato in stato non gestito)
  → cascata abort ADB unhealthy.

**Conferma sperimentale (28/04 sera, 3 istanze):**

| Istanza | Stato sfide pre-reset | Esito post-reset |
|---|---|---|
| FAU_00 | 0/5 ieri (last_run 27/04 12:58) → 5 nuove "Challenge" | ✅ 5/5 success in 2 min |
| FAU_10 | 1/5 stamattina → 1 "Watch" + 4 "Challenge" | ❌ 1V poi freeze sfida 2 |
| FAU_01 | 1/5 stamattina → 1 "Watch" + 4 "Challenge" | ❌ freeze sfida 1 (la "Watch" era già in cima) |

**Fix candidati:**
1. **Match dinamico button "Challenge"** — `matcher.find_one()` su template
   `pin_btn_challenge_lista.png` filtrato in ROI lista, scegliere coordinata
   del primo match invece di pixel fisso.
2. **Scroll/filter "Watch"** — swipe o filtro UI per nascondere sfide
   completate prima del tap.
3. **Try-and-back con sentinel** — tappare (745,482), screenshot post 1.5s,
   se trova `pin_replay` invece di `pin_challenge` → BACK + tap riga superiore.

**Effort:** ~30 righe Python (fix #1, più robusto). Richiede screenshot
template `pin_btn_challenge_lista.png` da estrarre dalla UI corrente.

**Bot in modalità minima (28/04 19:45)**: utente ha disabilitato dashboard
tutti i task tranne raccolta. Solo `raccolta` (always) + `radar_census`
attivi. Modalità sicura mentre si studia la sequenza arena. Riabilitare
arena/store/altri dopo fix.

#### 84. Bug orchestrator: `entry.last_run` aggiornato anche su fail/abort

**Sintomo:** arena fallita stamattina 13/13 esecuzioni, MA `last_run` è
stato aggiornato comunque in `state/FAU_XX.json`. Risultato: orchestrator
considera arena "fatta oggi" → `e_dovuto_daily=False` → arena non riprova
fino al reset 01:00 UTC del giorno dopo.

**Codice problematico:** `core/orchestrator.py:316`:
```python
entry.last_run    = time.time()
entry.last_result = result
```
Eseguito SEMPRE dopo `task.run()`, anche se `result.success=False` o
exception capturata.

**Fix proposto:**
```python
if result.success or result.skipped:
    entry.last_run = time.time()
entry.last_result = result
```

**Effort:** 2 righe + restart bot. Da fare insieme al fix #83.

#### 82. Radar census — bootstrap templates + smoke test (CHIUSA ✅ 28/04)

**Issue #18-bis** chiusa: `radar_tool/templates/` mancante in V6.

Step eseguiti:
1. Copia 47 template PNG da V5 (`C:\Bot-farm\radar_tool\templates\`) a V6
   dev+prod. Lista tipi unici: 19, auto, av1-av18, avatar*, bot, camion, card,
   fiamma, frecce, para, ped, pedone, skull, soldati.
2. `.gitignore` esteso con `!radar_tool/templates/*.png` per tracciare i 47
   template (analogo a `templates/pin/*.png`).
3. Smoke test offline (`radar_tool/_smoke_test.py`) verificato:
   - load_templates: 47/47 ✓
   - classifier RF: caricato, trained=True ✓
   - detect su `map_full.png` archive V5: **12 icone rilevate** (auto×3,
     av17×2, pedone_2×2, camion, para×2, pedone_1, skull) con conf_tmpl 0.65-1.00 ✓

**RF accuracy bassa** (~0.25-0.35 su tutti i sample, predice sempre
"paracadute"): dataset training V5 limitato (~28 etichette) → modello
underfitted. Fallback `_categoria_da_template()` heuristic via parsing nome
template funziona (es. `pin_skull → skull`, conf_tmpl >= 0.80 → ready=True),
quindi la catalogazione produce output utile in produzione.

**Re-training RF**: rimandato — non bloccante. Richiede sessione GUI con
`radar_tool/labeler.py` + `train.py` per costruire dataset con label V6
estese (numero, bottiglia + esistenti).

**Sblocco**: il task `RadarCensusTask` ora può essere riabilitato. Output
in `radar_archive/census/YYYYMMDD_HHMMSS_FAU_XX/{map_full.png,
map_annotated.png, census.json, crops/}`. Catalogazione tramite template
heuristic + RF fallback. Pronto per "altre funzionalità" che useranno
coordinate + categoria icone (es. caccia mostri, raccolta auto,
eliminazione skull).

---

### Issue aperte — gestione aggiornamento software gioco

#### 81. Update Version popup gioco — detect + gestione (NUOVA 🆕 28/04/2026)

**Sintomo**: quando il client del gioco ha una nuova versione disponibile,
appare un pulsante "**Update Version**" sulla HOME (icona triangolo arancione
"Up" + testo) nella riga eventi superiore (accanto a Beast Search, Treasure
Island Trip, ecc.). Posizione approssimativa screenshot 960×540: zona
centro-alta, attorno a x=520-590, y=40-95.

**Problema**: il bot oggi NON rileva questo pulsante e procede con la HOME
normale. Conseguenze potenziali:
- Se l'utente lo cliccasse manualmente partirebbe il download APK → emulator
  riavvio → bot crash mid-tick.
- Se il gioco forza l'update (server obbliga), tutte le funzioni tap che
  presuppongono UI standard potrebbero fallire silenziosamente (es. tap
  alleanza apre invece popup update) → cascata fallimenti tipo "lente NON
  aperta".
- Pattern affine a #77 (MAINTENANCE detect) ma livello CLIENT non server.

**Proposta soluzione** (analoga a WU54 maintenance):
1. Estrarre template `pin_update_version.png` da screenshot istanza con
   pulsante visibile (zona ~70×50px).
2. Hook detect in `core/launcher.py:attendi_home()` o gate pre-tick:
   - Se score >= 0.85 → pulsante rilevato.
   - Decisione: (a) skip istanza ciclo corrente con flag persistente
     `data/update_pending.flag` per evitare retry, (b) alert dashboard
     `update_required[<istanza>]` con timestamp, (c) opzione auto-update se
     l'utente abilita flag (rischioso — emulator riavvio non gestito da bot).
3. Gestione globale: se >= 80% istanze hanno pulsante → enable_maintenance
   automatico (analogo a WU54) con motivo "client update required" finché
   utente non aggiorna manualmente APK su MuMu.

**Note**:
- L'update va scaricato sull'APK del gioco — il bot NON può eseguirlo
  autonomamente (richiede interazione store/Google Play o sideload).
- Eventi rari ma critici: bloccano farm completa finché non risolti.
- Screenshot di riferimento fornito dall'utente 28/04 ore 11:46 contenente:
  pulsante "Update Version" in alto + banner "General Notice V20.5.0".

**Priorità**: ALTA (regressione potenziale su tutte le istanze quando il
gioco rilascia nuova versione, evento ~settimanale storico).

---

### Sessione 28/04/2026 — Maintenance bot/gioco + Data collection OCR + Raccolta Fast

Sessione lunga focalizzata su 4 filoni: (1) toggle modalità manutenzione bot,
(2) detect popup MAINTENANCE lato gioco con auto-pause, (3) data collection
OCR slot HOME vs MAPPA per training futuro AI agent, (4) variante fast del
task raccolta. 12 commit `7984478` → `27fd5d2`.

#### 49. Pannello tempi medi task con filtro outlier IQR (CHIUSA ✅ 28/04 — WU49)

Nuovo pannello dashboard `⏱ tempi medi task`. Aggrega `events.jsonl` per
nome task, calcola media durata in secondi con filtro outlier via metodo
**IQR (Tukey fences, k=1.5)**. Esclude `district_showdown` (durata variabile
per design — battaglie fund-raid). Mostra: nome task, samples (post-filter),
avg, min, max, std. Layout tabella compatta 5-col in sidebar destra.
Ordinamento desc per avg → spot rapido task lenti.

Commit: `7984478`.

#### 50. Raccolta fuori territorio per istanza (CHIUSA ✅ 28/04 — WU50)

Issue: in alcune fasi del gioco il castle/rifugio è in zone dove ogni nodo
risulta fuori territorio → blacklist globale satura → raccolta non parte.
Soluzione: flag `raccolta_fuori_territorio: bool` su `IstanzaOverride` +
`instances.json` (WU52 sync). Quando attivo: `_nodo_in_territorio()` ritorna
True per tutti i nodi, NESSUN add a `BlacklistFuori` globale. Toggle dashboard
nella tabella istanze (colonna `FT` — WU UI rename).

Commit: `4012b70` (logica) + `72f7b0e` (sync instances.json).

#### 51. Modalità manutenzione bot (CHIUSA ✅ 28/04 — WU51)

File flag `data/maintenance.flag` JSON con `{enabled, motivo, set_da,
auto_resume_ts}`. Modulo `core/maintenance.py`: `enable_maintenance()`,
`enable_maintenance_with_auto_resume(eta_seconds)`, `wait_if_maintenance()`
(blocking poll 5s, log heartbeat ogni 60s). Hook nel main loop pre-tick.
Dashboard: pannello `🔧 Manutenzione` con 3 endpoint
`/api/maintenance/{start,stop,status}` + partial banner `/ui/partial/maintenance-banner`.

Commit: `2f1b9ea`.

#### 52. Istanze disabilitate read-only nella tabella (CHIUSA ✅ 28/04 — WU52)

Quando `abilitata=False`, tutti gli input/select della riga ricevono attributo
`disabled` (truppe/sq/prof/lv/FT/fascia oraria). Solo il toggle abilitazione
resta cliccabile. Evita modifiche accidentali a istanze offline. Esteso WU50:
flag `raccolta_fuori_territorio` ora persistito anche su `instances.json` (non
solo override) per coerenza con max_squadre/livello/layout.

Commit: `72f7b0e`.

#### 53/54. Popup MAINTENANCE gioco — detect + auto-pause (CHIUSA ✅ 28/04)

Issue: quando i server del gioco vanno in manutenzione, TUTTE le istanze
mostrano popup "Maintenance · server time HH:MM:SS · REFRESH/Discord". Il bot
prima ciclava skip istanze inutilmente. Ora:

- **Detect**: 2 template `pin_game_maintenance_refresh.png` (174×35 zona
  554-728 × 400-435) + `pin_game_maintenance_discord.png` (174×35 zona
  293-467 × 400-435), match score >= 0.85 entrambi → conferma popup.
- **OCR countdown**: zona `(598,348,699,373)` per leggere `HH:MM:SS` →
  `eta_seconds` → `enable_maintenance_with_auto_resume(eta+30s)` (margine
  sicurezza 30s sul boot server).
- **Hook in 3 punti** di `core/launcher.py:attendi_home()`: Fase 4 Live Chat
  polling, Fase 5 sub-loop splash wait, e in cima al while Fase 5 (PRIORITARIO).
- **OCR fail fallback**: se countdown illeggibile → retry ogni 600s (10min).
- **Auto-resume**: bot riprende automaticamente quando `now > auto_resume_ts`.

Verifica funzionale via test python diretto (popup live sparito durante test
end-to-end perché server tornato online — codice validato in unit). Issue
parziale risolta — pattern detection robusto, da osservare in prossima
manutenzione reale.

Commit: `c9f543f` (WU53 detect+skip), `fcdad78` (WU54 auto-pause+OCR ETA),
`55d62c7` (WU54 fix path template + hook 3 posizioni).

#### 55. Data collection OCR slot HOME vs MAPPA (IN CORSO 🟡 28/04 — WU55+bis)

**Obiettivo**: training futuro AI agent per stabilizzare lettura slot in MAPPA
(zona OCR identica a HOME `(890,117,946,141)` ma fail più frequenti per
banner/animazioni mappa).

**Pipeline data collection**:
- Modulo `shared/ocr_dataset.py`: `new_pair_id()`, `save_home_sample()`,
  `save_map_sample()`. Storage `data/ocr_dataset/<istanza>_<pair_id>/`
  (screen + crop + crop_otsu + meta.json).
- Hook in `tasks/raccolta.py` 3 punti:
  1. Pre-mappa (riga 2058) — OCR HOME pre-batch + ctx._ocr_pair → save HOME
  2. Post-`vai_in_mappa()` (riga 2180) — shadow OCR MAP → save MAP
  3. Post-marcia HOME (riga 1147) — OCR slot post-marcia → save HOME
- **WU55-bis** (`d451b8f`): hook aggiunto in `_reset_to_mappa` (riga 1212+) per
  catturare MAP appaiata al HOME post-marcia. Risultato: per ogni marcia OK
  ora si genera 1 pair completa HOME+MAP (1 pre-batch + N post-marcia, dove
  N = slot riempiti).

**Toggle dashboard**: `/api/raccolta-ocr-debug/{on|off|status}` + flag
`runtime_overrides.globali.raccolta_ocr_debug` propagato via `merge_config()`
(fix root-level globali → `_InstanceCfg.RACCOLTA_OCR_DEBUG`).

**Stato dataset al restart 28/04 11:08**: 16 pair (2 complete, 14 home-only).
Soglia per analisi agente AI: 30+ pair complete. ETA: 1-2 cicli con WU55-bis
attivo (~60 pair complete per ciclo stimati).

**Obiettivo finale WU55** (chiarito 28/04 sessione AI agent):
Validare che OCR MAP sia affidabile come HOME → permettere **refactor del flusso
raccolta** rimuovendo `_reset_to_mappa` (vai_in_home → OCR HOME → vai_in_mappa)
dopo ogni marcia OK. Oggi questo passaggio esiste perché la regola CLAUDE.md
"lettura iniziale slot OCR deve essere fatta in HOME" era stata stabilita
quando MAP causava falsi positivi (es. caso `7/5` letto al posto di `4/5`,
auto-corretto dal sanity check `attive>totale` → skip conservativo).

**Risparmio stimato**: ~10-15s × 4-5 marce = **40-75s per tick raccolta**, ×12
istanze = **8-15 min per ciclo**.

**1° run agente AI** (dataset 13 complete, eseguito 28/04 12:00):
- 12/13 pair `match_home=true` (OCR MAP coincide con HOME)
- 1/13 edge case: HOME `0/5` (no counter, by-design) ↔ MAP `-1/-1` (transizione
  schermata, pre-check pixel ≥ soglia ma OCR cifre fallisce)
- L'agente ha mal-classificato i casi `0/N` come "garbage" perché non aveva il
  contesto di `leggi_contatore_slot()` (pre-check pixel < soglia → return
  `(0, totale_noto)` per design)
- Conclusione preliminare: **OCR MAP sembra già stabile** sui sample esistenti

**TODO**:
1. Aspettare dataset >= 50 pair complete (~1 ciclo aggiuntivo)
2. 2° run agente AI **con codice `shared/ocr_helpers.py:leggi_contatore_slot`
   come contesto** per classificazione corretta dei casi `0/N`
3. Se `match_home=true` >= 95% sui sample con contatore visibile → procedere
   con refactor flusso raccolta (rimozione `_reset_to_mappa` post-marcia OK,
   sostituito da OCR diretto in mappa)

Commit: `2c470ab` (WU55), `d451b8f` (WU55-bis).

#### 56. Pannello produzione/ora storico 12h con sparkline (CHIUSA ✅ 28/04 — WU56)

Pannello `⚡ produzione/ora · farm aggregata` arricchito con storico delle
ultime 12h (ridotto da 24h iniziale per leggibilità in sidebar 260px).
Layout 2-righe per risorsa: icona+sparkline ASCII (▁▂▃▄▅▆▇█, 14px font) +
sotto avg/min/max in space-between. Aggregazione su bins orari di
`storico_farm.json`. Filtra valori > 0 per il min (evita 0 spurious).

Backend: `dashboard/services/stats_reader.py:get_produzione_storico_24h(hours=12)`
ritorna `{bins, media, min, max, samples, window_h}` per pomodoro/legno/
petrolio/acciaio/totale.

Iter UI: layout 5-col tabella → centrato con min/max → 2-righe finale (richiesto
user "scritta non centrata, introduci max/min" + "non si vedono i dati min e max,
riduci a 12h").

Commit: `39fdfcf` (initial 24h), `0490b18` (footer centrato + min/h),
`a767201` (layout 2-righe + finestra 12h).

#### 57. RaccoltaFastTask — variante fast via tipologia istanza (NUOVA 🆕 28/04 — WU57)

Nuovo task `RaccoltaFastTask` (file `tasks/raccolta_fast.py`, 440 righe).
Filosofia: **niente verifiche parziali per ogni marcia, solo verifica finale
post-batch**. Riusa helper di `tasks/raccolta.py` (_cerca_nodo,
_leggi_coord_nodo, _nodo_in_territorio, Blacklist, BlacklistFuori).

**Flow**:
1. OCR slot HOME pre-batch → libere=N (1-5)
2. `vai_in_mappa()`
3. Loop N marce: `_tenta_marcia` (CERCA + tap_nodo + popup gather + territorio
   check + invio fast senza retry intermedi). Recovery 1-shot su fail
   (BACK + vai_in_home + vai_in_mappa).
4. Post-batch: `vai_in_home` + OCR slot → confronto vs `attive_pre`.

**Delay ridotti vs raccolta standard**:
| Step                  | Standard | Fast | Delta |
|-----------------------|----------|------|-------|
| TAP icona tipo        | 1.8s     | 1.2s | -33%  |
| CERCA / lente         | 1.5s     | 0.8s | -47%  |
| SQUADRA selezione     | 1.8s     | 1.2s | -33%  |
| MARCIA conferma       | 1.5s     | 1.2s | -20%  |
| Post-marcia stabilizz.| —        | 2.5s | +nuovo|

**Switch via tipologia istanza** (no doppia esecuzione):
- `dashboard/models.py`: enum `TipologiaIstanza.raccolta_fast`
- `main.py`: runtime swap RaccoltaTask → RaccoltaFastTask quando
  `tipologia=="raccolta_fast"`. Mantiene priority 15/interval/schedule e
  TUTTI gli altri task attivi (a differenza di `raccolta_only` che limita
  ai due raccolta task).
- Dashboard select: option `completo · fast` (UI rename WU separato).

**A/B testing pronto**: flaggare 1-2 istanze fast vs 9-10 standard, confronto
durata tick raccolta. Rollback immediato cambiando tipologia in dashboard.

Commit: `55d2e61`.

#### UI rename — tipologie istanza + colonna FT (28/04)

Refactor labels select tipologia per chiarezza semantica (richiesto user
"non è una nomenclatura corretta è fuorviante"):

| Value (invariato)     | Label vecchia    | Label nuova       |
|-----------------------|------------------|-------------------|
| `full`                | full             | **completo**      |
| `raccolta_fast`       | raccolta fast    | **completo · fast** |
| `raccolta_only`       | raccolta         | **solo raccolta** |

Riordinate opzioni: `completo` + `completo · fast` consecutive (varianti),
poi `solo raccolta` (profilo separato). Visivamente "fast" è una sotto-modalità
del completo, non un upgrade del raccolta_only.

Header colonna fuori territorio: glifo `⛯` → testo `FT` (più leggibile,
coerente con stile colonne lv./sq./prof.). Title hover preservato.

Commit: `27fd5d2`.

---

### Sessione 27/04/2026 — serata — Cicli persistenti + race state + dashboard fix

Sessione serale focused su gap dashboard telemetria + race condition state.
6 commit `8b0091f` → `6498d11`.

#### 49. Cicli persistenti + numerazione globale (CHIUSA ✅ 27/04/2026 — WU46/48)

**Problema duplice rilevato dall'utente**:
1. Dashboard mostrava **CICLO #0** (counter `engine_status.ciclo` mai aggiornato dal bot), `in_corso_da=4h` (calcolato da `storico[0].ts` rolling, non start ciclo), durate per istanza sempre 0
2. **Storico cicli mancante** — nessun pannello dashboard, info esisteva solo in bot.log come pattern `MAIN CICLO N` / `Ciclo N completato`
3. Counter ciclo del bot **riparte da 1 ad ogni restart** → 3× "CICLO 1 in corso" stale visivi nello storico

**Design originale Issue #53 violato**: avevo inizialmente parsato bot.log da reader (file volatile, ruota a 5MB → dati persi). Refactor completo:

- **WU46** (`41711bd`): API persistenza in `core/telemetry.py` — `record_cicle_start/end(numero)` + `record_istanza_tick_start/end(istanza, esito)`. Storage `data/telemetry/cicli.json` (atomic write, retention ultimi 100, lock thread-safe). Hooks in `main.py` ai punti CICLO N / Avvio istanza X / Istanza X completata / Ciclo N completato. Backfill one-shot da bot.log via `backfill_cicli_from_botlog()` per dati storici (idempotente, dedup su start_ts). Pannello dashboard `📚 storico cicli` con tabella ultimi 15 cicli + ciclo corrente con durate per istanza dai timestamp registrati.

- **WU48** (`6498d11`): numerazione globale crescente — `numero` = `max(cicli.numero) + 1`, mai più reset. `run_id` = boot ts UTC del processo bot (singleton per-process). `run_local` = numero locale del bot preservato per debug. `_find_current_cicle(cicli)` matching su run_id (non più su numero). Auto-close cicli stale di run precedenti come `aborted=True` quando un nuovo `record_cicle_start` parte. Dashboard 3 icone: ✓ COMPL / ▸ IN CORSO / ⊘ ABORT. Tag `·N` accanto al numero ciclo = run_local. Utility `renumber_cicli_globally()` per migration legacy.

**Verifica runtime**: bot riavviato 21:26:14, CICLO 4 (run.1, globale) registrato live, 7 istanze tracciate con durate (FAU_01 8.1m, FAU_02 8.0m, FAU_03 3.7m, FAU_04 5.0m, FAU_05 6.7m, FAU_06 4.6m, FAU_07 in corso).

#### 47. Pannello produzione/ora — farm aggregata sempre vuoto (CHIUSA ✅ 27/04/2026 — WU47)

- **Bug**: `MetricsState.aggiorna_risorse()` mai invocato da nessun caller. `chiudi_sessione_e_calcola()` calcolava `prod_ora` per la sessione MA lo salvava SOLO in `sess.produzione_oraria` (campo della singola sessione). Risultato: tutti gli `state/FAU_*.json` avevano `metrics.{pomodoro,legno,petrolio,acciaio}_per_ora=0.0` per sempre. Il pannello sommava 0+0+...+0 → "in attesa del primo ciclo raccolta" perpetuo.
- **Fix** (`aeaa6fb`): in `chiudi_sessione_e_calcola()` aggiunta propagazione `self.metrics.aggiorna_risorse(...)` se `durata_sec >= 300s` (filtro tick brevissimi che darebbero swing spurious).
- **Verifica runtime**: dopo restart bot 21:26, prima sessione FAU_05 chiusa con durata 4451s ha popolato metrics. Pannello laterale mostra ora **1.4M/h pomodoro + 1.4M/h legno** aggregati.

#### 46. Race state.rifornimento azzerato post-restart (CHIUSA ✅ 27/04/2026 — WU45)

- **Sintomo**: card FAU_00 mostrava `spediz=0 / inv.netto=0 / inv.lordo=0 / tassa=0 / provv.lorde=— / provv.nette=—` anche se il bot aveva fatto 9 spedizioni nella mattina (verificato via telemetry events FAU_00: 4 spedizioni alle 10:11 UTC).
- **Causa root**: race con `_controlla_reset()` post-restart. Lo state `state/FAU_00.json` viene resettato per data_riferimento mismatch durante un tick post-restart, perdendo `inviato_oggi`/`spedizioni_oggi`.
- **Fix dashboard fallback** (`8b0091f`): in `dashboard/services/stats_reader.py:get_produzione_istanze()`, se `state.rifornimento` è vuoto AND non `provviste_esau` → fallback automatico su `data/storico_farm.json[today][istanza]`. `storico_farm.json` è scritto ad ogni spedizione (sopravvive ai reset state) — fonte di verità daily più robusta. Recovera spedizioni, inviato per risorsa, provviste_residue.
- **Verifica**: card FAU_00 ora mostra `spediz=9 / inv.netto=31.5M / provv.lorde=33.2M / provv.nette=25.6M`.
- **Note**: `inv.lordo` e `tassa` restano 0 perché `storico_farm.json` non traccia campi WU34. Si popolano alle prossime spedizioni post-restart con state nuovo. Issue root del reset spurious resta da indagare separatamente.

#### Note operative sessione

- **Memory pressure** segnalato dall'utente: VS Code (2.5GB) + Claude (900MB) + bot 12 istanze MuMu (~10-12GB) → ~17GB su sistema 16GB → swap intensivo (Memory Compression 992MB). Documentato in `run_prod.bat` modalità #6 "RIDOTTA RAM (4 istanze)" come workaround per dev concomitante.
- **`run_prod.bat`** rifattorizzato (`1a960c1`) con header documentato + 9 modalità preconfigurate commentate.
- **`run_dashboard_prod.bat`** prod era ROTTO (chiamava `dashboard_server.py` inesistente). Fix (`eddefc6`) con corretto `uvicorn dashboard.app:app` + cleanup porta 8765 + 7 modalità documentate.

### Sessione 27/04/2026 — Telemetria pipeline + Morfeus OCR + Risorse netto

Maxi-sessione che ha chiuso **Issue #53** (telemetria) e **Issue #44/45** (semantica
risorse netto/lordo + capienza destinatario). 12 commit pushati `efec7e6` → `399eba0`.

#### 53. Telemetria task & dashboard analytics — pipeline 8/8 step (CHIUSA ✅ 27/04/2026)

MVP completo `project_telemetria_arch.md`:

| WU | Step | Componente | Commit |
|----|------|------------|--------|
| WU38 | 1 | `core/telemetry.py` — `TaskTelemetry` dataclass + storage 3-tier (events/rollup/live) + writer thread-safe + helpers (`_short_uuid`, `_iso_now`, `_iso_to_epoch`) + `record()` + `cleanup_old_events()` | `5153733` |
| WU38 | 2 | Hook in `core/orchestrator.py:tick()` — auto-record TaskTelemetry per ogni `task.run()` (success/skip/fail/abort + ADBUnhealthyError tagged adb_unhealthy + cycle da `ctx.extras["cycle"]` + failsafe try/except blanket) | `5153733` |
| WU38 | 3 | Migration TaskResult.data per 6 task: `rifornimento` (mode/provviste/tassa_pct_avg/spedizioni_oggi), `raccolta` (slot_attive/totali/tentativi/tipologie_bloccate), `boost` (outcome/durata), `donazione` (donate_count), `district_showdown` (fase1_esito/fasi_reward), `arena` (sfide_eseguite/esaurite/errore). Già OK: `vip`, `zaino`, `alleanza` (kwargs su `.ok()` finiscono in data). | `5153733` |
| WU40 | 4 | Rollup engine giornaliero: `compute_rollup(date)` → `data/telemetry/rollup/rollup_<date>.json` con `totals/per_task/per_instance/anomalies_global`. Aggregator generico `_aggregate_outputs` (bool→counter, num→sum+max, str→categorico). Percentili p50/p95 in pure-Python. CLI `tools/build_rollup.py`. Retention 365gg. | `1572e25` |
| WU41 | 5 | Live writer thread: `compute_live_24h()` sliding window (legge events oggi+ieri, filtra ts ≥ now-24h) + `live_writer_loop(stop_event, refresh_s=60)` daemon. Hook in `main.py` accanto a StatusWriter. Refactor `_build_rollup_from_events()` condiviso DRY. | `c8081a3` |
| WU42 | 6 | Reader API dual-source `dashboard/services/telemetry_reader.py`: `live.json` primaria con fallback automatico al log scan WU37 se telemetry non attiva. `last_ts` (max ts_end) + `last_err` (msg ultimo fail/abort) aggiunti al rollup. Health panel: anomalies da telemetry + tag_labels mapping + tick success rate + bot.log launcher patterns. | `cc09aa9` |
| WU43 | 7 | Backfill retroattivo `tools/backfill_telemetry.py` da `logs/FAU_*.jsonl`. Parsa coppie "Orchestrator: avvio task X" + "...completato/fallito" → TaskTelemetry sintetici. Idempotente (dedup su ts_start+task+instance). Inferisce anomalies per ADB UNHEALTHY + eccezioni. **76 eventi storici già caricati a ciclo 1.** | `815d824` |
| WU44 | 8 | Anomaly pattern detector: `detect_anomaly_patterns(events)` rileva 4 sequenze multi-evento: `adb_cascade` (3+ abort entro 5min), `rifornimento_skip_chain` (3+ skip consecutivi), `task_timeout_recurring` (2+ duration > 3× mediana), `home_stab_loop` (3+ home_stab_timeout entro 30min). Severity low/med/high. **Pattern reale rilevato: `raccolta_chiusura` 2 outlier max 174.9s vs mediana 2.8s.** | `399eba0` |

**Test coverage:** 19/19 passati (`tests/unit/test_telemetry_rollup.py` + `tests/unit/test_orchestrator_telemetry.py`).
**Storage:** `data/telemetry/{events/,rollup/,live.json}` retention 30gg/365gg/sempre.
**Pipeline failsafe:** ogni livello cattura eccezioni (telemetria silenziosa, mai blocca task).

#### 39. OCR "Daily Receiving Limit" FauMorfeus + dashboard (CHIUSA ✅ 27/04/2026)

- **Problema:** dashboard non aveva visibilità sulla capienza giornaliera residua del destinatario (FauMorfeus può saturare → spedizioni inutili).
- **Soluzione:**
  - `shared/rifornimento_base.py` — nuova zone OCR `OCR_DAILY_RECV_LIMIT = (547,146,666,173)` + helper `leggi_daily_recv_limit()`. Coordinate calibrate visivamente su screenshot reale catturato dal monitor `tools/capture_invio_mask.py`.
  - `shared/morfeus_state.py` (nuovo) — storage globale `data/morfeus_state.json` (atomic write) con schema `{daily_recv_limit, ts, letto_da, tassa_pct}`. Last-write-wins.
  - `tasks/rifornimento.py:_compila_e_invia()` — chiamata OCR + save dopo `leggi_provviste`.
  - Dashboard: riga "capienza morfeus" nel pannello RISORSE FARM con color coding (0=red+⚠ saturo, <5M=yellow, ≥5M=accent). Tooltip ts + nome istanza.
- **Commit:** `ef81639`.

#### 38. Risorse netto/lordo/tassa schema + dashboard cleanup (CHIUSA ✅ 27/04/2026 — WU34/35/36)

- **WU34** (commit `efec7e6`): `core/state.py` `RifornimentoState` esteso con `inviato_lordo_oggi`, `tassa_oggi`, `tassa_pct_avg` (running average 90/10). `registra_spedizione()` accetta `qta_lorda` e `tassa_amount`. `_controlla_reset()` reset LORDO+TASSA daily, tassa_pct_avg si conserva. `tasks/rifornimento.py` aggiorna entrambi i call sites (mappa + membri). Dashboard card: 6 key-value rows.
- **WU35** (commit `4b630c8`): pannello RISORSE FARM aggregator pulito a NETTO. `RifornimentoIstanza` esteso con `provviste_residue_netta` + `tassa_pct_avg`. Totale e dettaglio istanze mostrano netto, lordo OCR esposto solo in tooltip.
- **WU36** (commit `7283c4b`): CSS spacing — `.res-row` gap 6→10px, `.res-name` width 52→64px (visual readability).

### 78. DistrictShowdown — gate temporale override flag (RISOLTA ✅ 27/04/2026)

**Contesto**: il gate `should_run()` controllava `task_abilitato("district_showdown")` PRIMA di `_is_in_event_window()`. Conseguenza: se l'utente disabilitava il flag durante l'evento, il task saltava — rischio dimenticanza.

**Fix WU-#78** ([tasks/district_showdown.py:158](tasks/district_showdown.py#L158)):
- `should_run()` ora ritorna esclusivamente `_is_in_event_window()`. Il flag `task_abilitato` è effettivamente ignorato per DS — il task auto-attiva durante l'evento (Ven 00:00 → Lun 00:00 UTC) e auto-disattiva fuori.
- Step 5 (Fund Raid) sub-gate `_is_in_fund_raid_window()` invariato: Dom 20:00 UTC → Lun 00:00 UTC (fine evento).

**Razionale**: il task DS è completamente time-driven, non ha senso permettere disable manuale.

---

### 77. Raccolta — rotazione lenta FAU_02/05/07/10 (APERTA — bassa)

**Sintomo**: 4 istanze su 12 trovano slot raccolta non tutti vuoti al ciclo successivo (avg libere 2.2-2.7 su 4 totali). Le altre 8 trovano slot tutti vuoti (libere=tot).

**Diagnosi**: ETA marce raccolta > durata ciclo (≈1h30). Probabilmente:
- Nodi a maggiore distanza dal castello (livello 7 vs 6, o diramazioni mappa lontane)
- Coda blacklist piena → re-tentativi su nodi con ETA peggiore

**Da fare**: profilare ETA medio per istanza e mappare distanza/livello nodi. Eventuale shift `RACCOLTA_LIVELLO` 7→6 sulle istanze problematiche per nodi più vicini.

---

### 76. FAU_07/09/10 — tick netto +150-200s vs baseline (APERTA — media)

**Sintomo** (da ciclo notte 27/04): tick durata netta (escluso rifornimento) media:
- Baseline FAU_02..06: ~470s
- FAU_07: 617s, FAU_09: 647s, FAU_10: 698s
- FauMorfeus (raccolta_only): 355s = floor

Le 3 outlier hanno overhead ~150-200s extra non spiegato dal solo rifornimento.

**Da indagare**: profilare quale task occupa tempo extra:
- Raccolta più lenta (più swipe, blacklist più piena)?
- Stab HOME instabile (#52a)?
- Banner extra non catalogati?

**Memoria**: linkata a #52d (FAU_07 deficit notte 26/04 — pre-esistente).

---

### 75. radar_census 0/11 fail confermato (APERTA — alta cleanup)

**Sintomo**: il task `radar_census` ha success rate 0% su 11 esecuzioni (3 cicli notte 27/04). Tutte le esecuzioni falliscono (probabilmente `radar_tool/templates/` mancante in dev+prod, già nota Issue #18-bis).

**Fix immediato**: disabilitare in `runtime_overrides.json` (`globali.task.radar_census = false`). Era erroneamente abilitato durante setup "tutti i task tranne arena".

**Fix definitivo**: popolare templates radar mancanti o rimuovere il task dal catalog se non più necessario.

---

### 74-66 (RISOLTE 26/04-27/04 — bundle WU24)

Commit attivi `ba1480c`, `0428596`, `97e9824`, `ac0277a`, `cfbc024`, `ff18261`, `9746330`:

| # | Fix | Commit |
|---|-----|--------|
| 66 | Banner_eventi_laterale disabled — DS icon visibile post-startup (3/7 → 0/0 skip rate) | `9746330` |
| 73 | Launcher fg-check pre-BACK + monkey preventivo (cooldown 15s) | `ba1480c` |
| 74 | Boost row-alignment 8h/1d ↔ USE — registrazione corretta della durata effettivamente attivata | `ba1480c` |
| — | Store soglia_store_attivo 0.75 → 0.65 + carrello DELAY UI 2.0s + stability check open>close | `ba1480c` + `97e9824` |
| — | Donate anti-ban random 15-30 tap per block | `ba1480c` |
| — | Raccolta skip-reset livello pannello via OCR (auto-WU13 ROI fix y-30 + regex Level) | `0428596` + `ac0277a` |
| — | Fund raid burst 30 tap/block (~28× speedup) + stop OCR last_num | `cfbc024` + `ff18261` |

---

### 65. Wait > 60s rifornimento — anticipare task successivi (APERTA — feature)

**Contesto**: Issue #64 step 1 (implementato) fa wait passivo fino al rientro dell'ultima spedizione rifornimento prima di leggere slot raccolta. Quando wait > 60s, lo sleep è uno spreco — il bot non fa nulla mentre potrebbe avanzare i task post-raccolta.

**Step 2 (proposta)**: quando wait > 60s, **anticipare i task post-raccolta** (donazione, zaino, vip, alleanza, messaggi, arena, ds, store, radar) prima di tornare a raccolta. Dopo aver eseguito i task anticipati, **verificare il tempo trascorso** vs `eta_rientro_ultima`:

```
wait_s = eta_rientro_ultima - now
if wait_s > 60:
    log "anticipo task post-raccolta — recupero tempo morto"
    # Esegui i task con priority > raccolta in ordine, MA salta raccolta_chiusura
    for task in tasks_dovuti_post_raccolta_escluso_chiusura:
        run_task(task)
    # Ora verifica se rientro è avvenuto
    elapsed = now - inizio_anticipo
    if elapsed >= wait_s:
        # rientro avvenuto durante anticipo — leggi slot e procedi raccolta
        run_raccolta()
    else:
        # ancora wait residuo
        sleep(wait_s - elapsed)
        run_raccolta()
```

**Implicazioni**:
- L'orchestrator dovrebbe permettere riordino dinamico dell'esecuzione (saltare raccolta, fare gli altri, tornare a raccolta)
- Oppure: RaccoltaTask gestisce l'anticipo internamente chiamando direttamente altri task instances (più invasivo)
- Approccio chirurgico: nuovo flag in TaskContext (es. `defer_raccolta=True`) → orchestrator riordina

**Vantaggio**: recupero potenziale 30-180s/tick su istanze con rifornimento ETA lungo (rifugio distante).

**Issue da affrontare**:
- Sequenza task post-raccolta: rispettare priority ordering originale
- `RaccoltaChiusuraTask` (priority 200, Issue #62) deve restare ULTIMA
- Eventuale stato `wait_in_corso` per evitare doppia esecuzione

**Memoria**: linkata a Issue #64 step 1.

---

### 64. Raccolta legge slot mentre rifornimento ancora in volo (RISOLTA ✅ 26/04/2026)

**Sintomo**: dopo task rifornimento (5 spedizioni, ~10 min), task raccolta legge slot squadra. MA le spedizioni rifornimento utilizzano slot squadra fino al rientro al castello (ETA andata+ritorno tipica 100-200s/spedizione). Quindi la lettura OCR slot risulta:

```
Stato reale: 0/4 occupati
Stato bot:   2-3/4 occupati (ultime 2-3 spedizioni rifornimento ancora in volo)
→ libere: 1-2 invece di 4 → squadre non inviate
```

**Fix WU-#64 (step 1)**:

1. **`RifornimentoState.eta_rientro_ultima: str | None`** ([core/state.py:114](core/state.py#L114)) — ISO timestamp atteso rientro ultima spedizione. Salvato a fine `RifornimentoTask.run()` come `now + eta_residua_sec`.

2. **`RaccoltaTask.run()`** all'inizio ([tasks/raccolta.py:1722](tasks/raccolta.py#L1722)):
   ```python
   eta_iso = ctx.state.rifornimento.eta_rientro_ultima
   wait_s = (datetime.fromisoformat(eta_iso) - now).total_seconds()
   if wait_s > 0:
       actual_wait = min(wait_s + 2, 600.0)  # cap 10min safety
       sleep(actual_wait)
   ```

**Wait sempre fino al rientro**: nessuna soglia. Cap di sicurezza 600s (10min) protegge da `eta_rientro_ultima` corrotto. Step 2 (Issue #65) propone ottimizzazione per wait > 60s anticipando task post-raccolta.

**File modificati**:
- `core/state.py` — campo `eta_rientro_ultima`
- `tasks/rifornimento.py` — save in state post-loop
- `tasks/raccolta.py` — wait condizionale all'inizio run

**Sync prod**: ✅. Attivo al prossimo restart manuale.

---

### 62. Riordino priorità task + chiusura raccolta slot pieni (RISOLTA ✅ 26/04/2026)

**Richiesta operativa**: ottimizzare ordine task per massimizzare throughput:
1. **BoostTask** (priority 5) — primo, garantisce gathering speed attivo
2. **RifornimentoTask** (priority 10) — invio risorse al rifugio prima che si accumulino
3. **RaccoltaTask** (priority 15) — invio squadre raccoglitrici
4. resto dei task (donazione, zaino, vip, alleanza, messaggi, arena, ds, store, radar, ...)
5. **RaccoltaChiusuraTask** (priority 200) — re-run raccolta come ULTIMO task del tick

**Razionale chiusura raccolta**: durante l'esecuzione degli altri task possono essersi liberati slot squadra (marce concluse, attacchi finiti). Riprovare a chiusura tick massimizza il numero di nodi attivi/giorno.

**Nuovo `task_setup.json` ordering**:

| priority | class | schedule |
|----------|-------|----------|
| 5 | BoostTask | periodic |
| 10 | RifornimentoTask | always |
| 15 | RaccoltaTask | always |
| 20 | DonazioneTask | always |
| 25 | ZainoTask | periodic 168h |
| 30 | VipTask | daily |
| 35 | AlleanzaTask | periodic 4h |
| 40 | MessaggiTask | periodic 4h |
| 50 | ArenaTask | daily |
| 60 | ArenaMercatoTask | daily |
| 70 | DistrictShowdownTask | always |
| 80 | StoreTask | periodic 8h |
| 90 | RadarTask | periodic 12h |
| 100 | RadarCensusTask | periodic 12h |
| **200** | **RaccoltaChiusuraTask** | **always** |

**Implementazione**:

1. **`RaccoltaChiusuraTask`** in `tasks/raccolta.py` — sottoclasse di `RaccoltaTask`, override solo `name() → "raccolta_chiusura"`. Eredita `run()` completo. Se slot pieni, esce in <2s con "nessuna squadra libera".

2. **`main.py:_import_tasks()`** — registra anche `RaccoltaChiusuraTask` nel catalogo task.

3. **`main.py` filtro `raccolta_only`** — esteso a `("RaccoltaTask", "RaccoltaChiusuraTask")` per istanze raccolta-only.

4. **`task_setup.json`** — riordino completo + nuova entry priority 200.

**Smoke test**: ordering verificato, RaccoltaChiusuraTask sottoclasse di RaccoltaTask, name distinto ("raccolta_chiusura").

**Sync prod**: ✅. Attivo al prossimo restart manuale.

---

### 60. Foreground check falso positivo post-restart bot — penalità 43s/istanza (RISOLTA ✅ 26/04/2026)

**Sintomo osservato 26/04/2026 13:53-13:55 FAU_08** (post-restart bot WU24):

```
13:53:26 am start gioco (tentativo 1/3) — am start OK
13:53:29 monkey launcher (porta UI al top)
13:53:40 gioco verificato in foreground       ← FALSO POSITIVO
13:54:41-13:55:25 polling 43s schermata=Screen.UNKNOWN  ← bloccato su HOME Android
13:55:25 monkey recovery (UNKNOWN 8 cicli)    ← safety-net interviene
13:55:45 [SPLASH] Live Chat rilevato (score=1.000) — gioco finalmente in caricamento
```

Discovery screenshot a streak5 mostra **HOME del MuMu Player Android** (launcher con icone MuMu Store, App Cloner, Gadget, Doomsday) — gioco NON aperto nonostante "verificato in foreground".

**Root cause**: `_gioco_in_foreground()` ([core/launcher.py:133-145](core/launcher.py#L133)) usava `pkg in dumpsys_output` da `dumpsys activity top`. Match testuale generico. Il commento del codice ammetteva esplicitamente:

> "check NON STRETTO — può dare falso positivo se pkg appare come task background. Safety-net reale è il monkey recovery in attendi_home"

Dopo kill+restart bot, MuMu rebootato fresh ha il pacchetto gioco visibile nell'output `dumpsys activity top` come **recent task / background**, non come app in primo piano.

**Fix applicato**: `_gioco_in_foreground()` ora usa `dumpsys window | mCurrentFocus`:

```python
out = _adb_cmd(porta, "shell", "dumpsys", "window", adb_exe=adb_exe)
for line in out.splitlines():
    if "mCurrentFocus" in line and pkg in line:
        return True
return False
```

`mCurrentFocus` è la window correntemente focusata (UNA SOLA per volta, quella visibile + interattiva). Esempio output post-fix verificato live FAU_08:
```
mCurrentFocus=Window{ec1c0f8 u0 com.igg.android.doomsdaylastsurvivors/com.gpc.sdk.unity.GPCSDKMainActivity}
```

**Stima impatto**:
- Pre-fix: ~43s extra/istanza × 12 istanze al 1° ciclo post-restart = **~9 min penalità per ogni restart bot**
- Post-fix: 0s (am start verifica corretta → 2°/3° tentativo se serve, no attesa monkey recovery)

**File modificato**: `core/launcher.py:_gioco_in_foreground()` (8 righe)

**Sync prod**: ✅. Smoke test live FAU_08 OK. Attivo al prossimo restart manuale.

---

### 57. State save per task — fine-grained persistence (RISOLTA ✅ 26/04/2026 — WU25)

**Sintomo osservato 26/04/2026 FAU_04**:
- 10:31:01 tick FAU_04 inizia
- 10:31:26 BoostTask attiva boost → `registra_attivo()` → scadenza memoria=18:31:26 (8h)
- 10:40:52 cascata ADB persistente (Issue #56) → tick non termina mai
- `ctx.state.save()` a fine tick ([main.py:816](main.py#L816)) **mai raggiunto**
- 12:52 restart bot → rilegge state stale `scadenza=09:44:44` (vecchia)
- 10:59 boost ri-attivato → spreco di un item boost

**Root cause architetturale**: `state.save()` chiamato **una sola volta** a fine tick. Tutti i task che modificano state (boost, rifornimento, vip, store, arena) sono a rischio se il tick crasha o blocca.

**Fix WU25**: `core/orchestrator.py` chiama `ctx.state.save(state_dir=_state_dir())` **dopo OGNI task completato** (success o fail). Save è atomico (tmp+fsync+os.replace) → no race con dashboard reader.

```python
# in orc.tick() dopo entry.last_run = time.time(); results.append(result)
try:
    if hasattr(self._ctx, "state") and self._ctx.state is not None:
        self._ctx.state.save(state_dir=_state_dir())
except Exception as exc:
    self._ctx.log_msg(f"Orchestrator: save state post-'{task_name}' fallito: {exc}")
```

`_state_dir()` resolve via env `DOOMSDAY_ROOT` (settata in run_prod.bat) o cwd come fallback. State dir convenzione `{root}/state/`.

**Impatto**: ~5-10 save extra/tick (file system load <1ms each su SSD). Beneficio: nessuna perdita stato in caso di crash/blocco.

**Stato file FAU_04 pre-fix**:
| Istanza | Scadenza state (stale) | Scadenza memoria (persa) |
|---------|------------------------|--------------------------|
| FAU_04 | 2026-04-26T09:44:44 | 2026-04-26T18:31:26 |

**File modificati**:
- `core/orchestrator.py` — import `os`, helper `_state_dir()`, save block post-task

**Sync prod**: ✅ — sarà attivo al prossimo restart manuale (regola: chiusura istanza naturale).

---

### 56. Cascata ADB persistente — recovery emergenziale (RISOLTA ✅ 26/04/2026 — WU24)

**Sintomo osservato 26/04/2026 FAU_04** (cascata ~12 min sterile):

```
10:40:29 raccolta squadra confermata 4/4
10:40:33 vai_in_home tentativo 1/8 — screen=MAP
10:40:52 [NAV] screenshot None — UNKNOWN
10:41:44 [NAV] screenshot None 3x — tento reconnect ADB
10:41:55 [NAV] reconnect ADB OK — retry vai_in_home
10:42:07 [NAV] screenshot None — UNKNOWN  ← reconnect cosmetico
...
10:52:20+ ABORT → reconnect → ABORT loop persistente
```

**Pattern diagnostico**: `reconnect ADB OK` seguito da `screenshot None` ripetuto **non transitorio** — l'emulator stesso è freezato, non il socket ADB. Il bot loopa all'infinito perché:
1. `vai_in_home()` ABORT ritorna False → task riprova
2. Nessun timeout di tick
3. Nessuna logica di skip globale dopo N ABORT consecutivi

**Stima durata uscita naturale (pre-fix)**: 5-10 minuti minimo dopo cascata, raramente recupera.

**Fix WU24 — 3 layer**:

**Layer 1 — Navigator** ([core/navigator.py](core/navigator.py)):
- Nuova classe `ADBUnhealthyError(RuntimeError)`
- Counter `_reconnect_failures` persistente sull'istanza Navigator
- Trigger Tier 1: dopo `reconnect ADB OK` se nuovo screenshot ancora None per 2 cicli consecutivi → raise `ADBUnhealthyError`
- Reset counter su HOME success

**Layer 2 — Orchestrator** ([core/orchestrator.py](core/orchestrator.py)):
- Cattura `ADBUnhealthyError` sia nel gate HOME sia in `task.run()`
- Setta `ctx.adb_unhealthy = True`, abort tick, ritorna results parziali

**Layer 3 — Main** ([main.py](main.py)):
- Post-tick check `getattr(ctx, "adb_unhealthy", False)` → log `[ERRORE] reset emergenziale ADB unhealthy` + flag stato `ultimo_errore=adb_unhealthy`
- Chiusura istanza standard (`_launcher.chiudi_istanza`) + ciclo successivo restart pulito via `reset_istanza`

**Effetto atteso**:
- Pre-fix: cascata 6-12 min sterile (osservato FAU_04)
- Post-fix: ~40s (2 ABORT post-reconnect) → raise → abort tick + chiudi → ciclo dopo restart pulito

**File modificati**:
- `core/navigator.py` — `ADBUnhealthyError` + counter `_reconnect_failures` + raise condizionato
- `core/orchestrator.py` — try/except `ADBUnhealthyError` in 2 punti
- `main.py` — flag `adb_unhealthy` post-tick handling

**Sync prod**: ✅. Bot **riavviato** alle 12:52 con WU24 attivo.

---



**Sintomo osservato 26/04/2026 09:34 FAU_00**:
```
[STORE] passo 06 → score=0.658 *** match ***
[STORE] passo 07 → score=0.764 *** match ***
[STORE] passo 08 → score=0.768 *** match ***  ← MAX
[STORE] passo 21 → score=0.735 *** match ***
[STORE] passo 22 → score=0.739 *** match ***
[STORE] Best step=8 score=0.768 — delta swipe (-300,-300)
[STORE] Re-match al best: score=0.439 (97,311)  FALLITO
[STORE] Outcome='store_non_trovato' → fail
```

Best step correttamente identificato (max score 0.768), ma dopo delta swipe il re-match cade a 0.439 (sotto soglia 0.65) → store_non_trovato → run perso.

**Root cause**: `swipe(±p)` NON è idempotente sui bordi della mappa di gioco. Cumulative del passo 24 (fine spirale) = (+600, +600) = angolo estremo. Lo swipe `-300, -300` viene parzialmente assorbito dal bordo (mappa non si scrolla oltre limiti) → bot resta in posizione mappa diversa da quella del passo 8 → re-match cade su altro edificio.

Pattern condiviso con FAU_08 notte scorsa (best step=22 cumulative `(0, +600)` bordo). Tasso store_non_trovato osservato ~10%.

**Fix proposto multi-candidate**:

1. Durante scan, salvare TUTTI i match `>= soglia_store` (non solo best):
```python
candidates = []  # [(step_n, score, cum_x, cum_y), ...]
for n, (dx, dy) in enumerate(cfg.griglia):
    if result.score >= cfg.soglia_store:
        candidates.append((n, result.score, cum_x, cum_y))
candidates.sort(key=lambda c: -c[1])
```

2. Try in ordine score decrescente:
```python
for cand_step, cand_score, tgt_x, tgt_y in candidates:
    delta_x = tgt_x - end_x
    delta_y = tgt_y - end_y
    apply_swipes(delta_x, delta_y)
    end_x, end_y = tgt_x, tgt_y  # update
    result = matcher.find_one(...)
    if result.found and result.score >= cfg.soglia_store:
        break
    log(f"Re-match fallito step={cand_step} — provo successivo")
else:
    return _Esito.STORE_NON_TROVATO
```

**Stima impatto**:
- Tasso store_non_trovato: 10% → ~2%
- +1 store run/giorno per istanza ≈ +18 acquisti/istanza/giorno
- Costo: +15s solo nei casi fallback

**File**: `tasks/store.py:209-308` `_esegui_store()` riscrittura del match-tracking single→multi.

**Memoria**: `.claude/projects/c--doomsday-engine/memory/project_store_multi_candidate.md`

---

### 54. Banner catalog & dismissal pipeline — boot stabilization (APERTA — feature)

**Problema misurato**: 573 polls UNKNOWN cumulativi nella vita del bot (~48 min CPU/ADB sprecati). Avg 10.1 polls/cycle, max 28. Variabilità FAU_00 (15.2) vs FAU_06 (4.6) → 3× differenza per popup non catalogati.

Sistema attuale: solo `pin_banner_aperto/chiuso` gestito da `comprimi_banner_home`. Tutto il resto coperto da `loop BACK` cieco in `attendi_home`. Alcuni popup (News feed, Daily login) NON chiudono con BACK — serve tap X specifico.

**Proposta MVP (~5h)**:

1. `shared/banner_catalog.py` con `BannerSpec` dataclass (template, ROI, threshold, dismiss_action: back/tap_x/tap_center/tap_coords, priority)
2. Catalogo iniziale: daily_login_calendar, welcome_back, news_feed, event_modal, update_optional, banner_eventi_laterale (esistente)
3. `dismiss_banners_loop(ctx, max_iter=8)` in `shared/ui_helpers.py` — itera screenshot+match+dismiss finché trova banner
4. Integrazione `attendi_home`: dopo splash naturale 10s, PRIMA del polling cieco. Ridurre `timeout_carica_s` 180→60s
5. **Discovery prerequisito**: salvare screenshot quando `unknown_streak == 5` in `debug_task/boot_unknown/` per 1 ciclo → catalogazione manuale + template extraction
6. Telemetria: `{banner_name: count}` aggregato per istanza

**Stima impatto**:
- UNKNOWN polls: 10.1 → 5.0 (-50%)
- Boot stabilization: 170s → 110s (-35%)
- Cycle median: 12.3 → 10.5 min
- Throughput: 8 → 10 cycle/giorno (+25%)

**Memoria dettagliata**: `.claude/projects/c--doomsday-engine/memory/project_banner_catalog.md`

---

### 53. Telemetria task & dashboard analytics — architettura (APERTA — feature)

**Problema**: persistence sparsa, KPI non aggregabili, dashboard solo status. Per analisi notturna richiesto parsing regex manuale del bot.log.

**Proposta MVP** (~12h):

1. **Schema** `core/telemetry.py` con dataclass `TaskTelemetry` (ts_start/end, task, instance, duration_s, success, outcome, output:dict, anomalies, retry_count)
2. **Storage 3-tier** in `data/telemetry/`:
   - `events/events_YYYY-MM-DD.jsonl` append-only (retention 30gg)
   - `rollup/rollup_YYYY-MM-DD.json` daily aggregate (retention 365gg)
   - `live.json` rolling 24h (refresh 60s)
3. **Wrapper** `Task.run_with_telemetry(ctx)` in `core/task.py` chiamato dall'orchestrator. Try/except blanket per non rompere hot path
4. **Migration**: `TaskResult.output_data: dict` aggiunto, ogni task popola con dati specifici (vip→cass_ok/free_ok, raccolta→squadre/tipi, rifornimento→spedizioni/qty, ...)
5. **Reader API** `dashboard/services/telemetry_reader.py`: kpi_live, history(days=7), events_recent, anomalies, benchmark_compare
6. **UI** sezione "📊 Telemetria" con tabella KPI 24h, anomalie raggruppate, sparkline trend 7gg, drill-down istanza
7. **Backfill** script one-shot estrae da bot.log storico → events JSONL retro
8. **Anomaly detector** (bonus): pattern matcher su events log → genera evento anomaly + alert UI

**Storage estimate**: ~120 KB/giorno events + 4 KB rollup = ~10 MB/anno totale (retention attiva).

**Compat**: `storico_farm.json` mantenuto 30gg per backward-compat, poi migrare consumer a rollup.

**Vantaggi**: visibility totale, KPI standardizzati, anomaly detection automatica, append-only events (no contention con state hot path).

**Memoria dettagliata**: `.claude/projects/c--doomsday-engine/memory/project_telemetria_arch.md`

---

### 52. Issues notturne 26/04/2026 — analisi performance

Da analisi notte 25-26/04 (~9h, 44 cycle, 11 istanze + FauMorfeus):

#### 52a. WU14 produzione_corrente non popolata in state files (MEDIA)
- **Sintomo**: `state/FAU_*.json` per tutte le 11 istanze ha `produzione_corrente=null` e `produzione_storico=[]`
- I `[PROD]` log nel bot.log esistono e mostrano risorse castello correttamente, ma lo state non si aggiorna
- **Impatto**: dashboard non può popolare la card "produzione oraria" — feature WU14 implementata ma non funzionale end-to-end
- **Da indagare**:
  - `apri_sessione` viene chiamato in main.py (post comprimi_banner)?
  - Hooks in `tasks/rifornimento.py`, `tasks/raccolta.py`, `tasks/zaino.py` invocati con `ctx.state.produzione_corrente.aggiungi_*`?
  - `chiudi_sessione_e_calcola` triggered a fine cycle (orchestrator end)?
- **Stima**: 30 min audit + fix mancante

#### 52b. Stabilizzazione HOME timeout ricorrente — 88% boot (MEDIA)
- **Sintomo**: 38/43 boot misurati (88%) finiscono in `stabilizzazione timeout — procedo comunque` dopo 40s
- Solo 6/43 raggiungono `HOME stabile 3/3` (target nominale)
- 35 occorrenze `HOME stabile 1/3`, 29 reset `HOME instabile (UNKNOWN)`
- **Causa**: banner eventi animato + transizioni UI fanno fluttuare lo score `pin_home_template` sotto soglia 0.7 ad ogni transizione
- **Impatto**: ~30s/boot perso in attesa timeout × 38 boot = ~19 min/notte
- **Fix candidato**: tollerare 1 reset entro 30s (algoritmo "2/3 con 1 reset"), oppure spostare `comprimi_banner_home` PRIMA di `attendi_home` invece che dopo
- **File**: `core/launcher.py:attendi_home`

#### 52c. ARENA recovery `_doppio_tap_centro + back×4` rompe ADB (ALTA)
- **Sintomo**: 8/10 istanze in cui ARENA fallisce entrano in cascade `screenshot None` per il resto del cycle
- 50 occorrenze `ARENA-PIN screenshot fallito` notturne, 16 `errore sfida` totali
- `WU3 ADB reconnect` riporta "OK" ma screencap successivo resta None
- **Pattern temporale**: cycle 7 (~01:30-04:00 UTC) = finestra ADB cascade nightly
- **Impatto**: 27% raccolta skipped post-arena, ~6 task skipped/cycle quando triggerato
- **Fix candidato**: sostituire in `tasks/arena.py:315-324` la sequenza `_doppio_tap_centro + back×4` con `navigator.vai_in_home()` puro (screenshot-based, adattivo)
- **Già documentato**: `.claude/AUTONOMOUS_CHANGES.md` issue notte (non risolto)

#### 52d. FAU_07 deficit netto risorse + acciaio overflow castelli (BASSA)
- **Sintomo FAU_07**: tutti tassi netti M/h negativi (pom -0.55, leg -0.04, pet -0.18)
- **Sistema acciaio**: castelli +7.92 M/h cumulati (FAU_05 +4.37 / FAU_09 +3.41 dominanti), rifugio FauMorfeus -7.64 M/h
- `RIFORNIMENTO_ACCIAIO_ABILITATO=False` → mai spedito → accumulo ~190M/giorno proiettato
- **Da decidere**:
  - FAU_07: audit config (training in corso? livello rifugio? attività in deficit)
  - Acciaio: abilitare `RIFORNIMENTO_ACCIAIO_ABILITATO=True` con `RIFORNIMENTO_SOGLIA_ACCIAIO_M=5.0`?

#### Constraint operativi misurati (riferimento)
- Cycle singolo per istanza: **median 12.3 min** (range 5-20 min)
- Round completo (12 istanze sequenziali): **~150 min**
- Sleep tra round: ~30 min → cycle totale **~3h**
- Throughput proiettato: **~8 cycle/giorno** per istanza
- Boot phase: 41s avvio + 170s stabilization = **~3.9 min/istanza**
- Output notte (per estrapolazione): 83 squadre raccolta, 31 spedizioni rifornimento (~80M risorse), 11 boost attivati, 22 letture messaggi+alleanza, 11 VIP claim, 109 acquisti store, 570 tap donate, 6/11 ARENA degraded

### 1. Rifornimento — da mettere a punto (CHIUSA ✅ 20/04/2026)
- **Stato:** validato in produzione su 8 istanze il 20/04/2026.
- **Fix finale (20/04/2026):** `_centra_mappa` → tap castello `time.sleep(2.0)` (era `0.3`),
  `_apri_resource_supply` `time.sleep(1.5)` (era `0.3`), `_compila_e_invia`
  retry OCR nome destinatario su stringa vuota con nuovo screenshot.
  Commit fix: `tasks/rifornimento.py` (3 delay + retry OCR).
- **Fix precedenti (14/04/2026):**
  - `_apri_resource_supply()`: `find()` → `find_one()` (API V6)
  - `run()`: deposito letto via OCR in mappa se non iniettato (come V5)
  - `_compila_e_invia()`: aggiunta verifica nome destinatario (come V5)
  - Navigazione HOME/MAPPA: `ctx.navigator.vai_in_home/mappa()` con fallback key
- **Attivazione runtime:** via `runtime_overrides.json`:
  - `globali.task.rifornimento: true`
  - `globali.task.rifornimento_mappa: true`
  - `globali.rifugio: {coord_x: 680, coord_y: 531}` (propagato da `merge_config`
    in `rifornimento_mappa.rifugio_x/y` fix `2b33efc`)

### 2. Arena — timeout battaglia (RISOLTA ✅ 19/04/2026 — F2 hard timeout 300s commit `3c959cf`)
- **Problema:** sfide 2 e 4 timeout — battaglia ancora in corso (animazioni > 38s).
  Issue estesa: FAU_10 hang indefinito su arena → kill manuale ciclo 19/04.
- **Fix applicato:** hard timeout globale `ARENA_TIMEOUT_S=300` in `tasks/arena.py`.
  `_MAX_BATTAGLIA_S` già aumentato a 52s in precedenza.
- **TODO pin mancanti (residuo):**
  - `pin_arena_video.png` — popup video introduttivo primo accesso
  - `pin_arena_categoria.png` — popup categoria settimanale (lunedì)

### 2bis. Dashboard V6 (CHIUSA ✅ 20/04/2026 — commit `9773de3`)
- **Problema:** dashboard precedente (`dashboard/dashboard_server.py` + `dashboard.html`)
  scriveva su `runtime.json` orfano (mai letto dal bot). Le modifiche non avevano
  effetto. Architettura monolitica `http.server` stdlib + vanilla JS + polling manuale.
- **Fix applicato:** rewrite completo `dashboard/` con FastAPI + Jinja2 + HTMX:
  - `dashboard/app.py` (FastAPI, 5 router, 13 endpoint API, lifespan hook)
  - `dashboard/services/` (config_manager, stats_reader, log_reader — read/write atomico)
  - `dashboard/models.py` (Pydantic: RuntimeOverrides, InstanceStats, EngineStatus, …)
  - `dashboard/routers/` (api_status, api_stats, api_config_global,
    api_config_overrides, api_log)
  - `dashboard/templates/` (Jinja2 base + overview + instance + config + 3 partials)
  - `dashboard/static/style.css` (dark mode industrial con IBM Plex Mono/Sans)
  - HTMX polling: card istanze 10s, status bar 5s, log viewer 15s
- **Collegamento bot:** `main.py` + `config/config_loader.py` ora usano
  `load_overrides()` + `merge_config()` + `GlobalConfig._from_raw(_merged_raw)` —
  gli override scritti dalla dashboard hanno finalmente effetto sul bot al tick successivo.
- **runtime.json eliminato**, sostituito da `config/runtime_overrides.json` (letto dal bot).
- **Avvio:** `run_dashboard.bat` → `http://localhost:8765/`

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

### 9. Raccolta — selezione icona tipo fallisce su istanze specifiche (ALTA)
- `[VERIFICA] tipo` score scende a 0.05-0.23 su FAU_01/FAU_02 (tutti i tipi)
- Su FAU_00: score > 0.99 costantemente
- **NON è parallelismo**: confermato da test notturno 18/04/2026 in modalità sequenziale
- **PARZIALMENTE RISOLTA 18/04/2026**: flush frame cached risolve il problema.
  Score torna >0.99 su FAU_00. FAU_01/FAU_02 migliorati ma instabili.
  Fix skip_neutri_per_tipo evita loop su nodo in blacklist.

### 10. Lock globale screencap — starvation con 3+ istanze (ALTA)
- `_screencap_global_lock` serializza tutti gli screenshot
- Con FAU_02 che esegue 12 task, FAU_00/FAU_01 non riescono
  a fare screenshot per tutta la durata del tick FAU_02
- Fix: rimuovere il lock globale, investigare causa vera del problema

### 11. Stabilizzazione HOME — ancora instabile su FAU_01/FAU_02 (MEDIA)
- FAU_00: converge in 9s (3/3 poll). FAU_01/FAU_02: raggiungono max 1-2/3 poi timeout
- Causa: popup/banner alternano HOME↔UNKNOWN ogni 5s durante caricamento
- Fix applicato: rimosso BACK dal loop (causava apertura menu uscita)
- Fix residuo: investigare quali banner causano instabilità su FAU_01/FAU_02
  (potrebbero essere diversi da FAU_00 per livello account o evento attivo)

### 12. Stabilizzazione HOME FAU_01 non converge (MEDIA — NON BLOCCANTE)
- Identica natura dell'Issue #11 ma confermata 19/04: dopo attendi_home()
  timeout 30s, FAU_01 non raggiunge 3/3 poll consecutivi
- **NON BLOCCANTE**: il task prosegue comunque con `vai_in_home()` finale
  e completa il ciclo regolarmente (boost/raccolta funzionano)
- Impatto: ~15-20s per tick persi in attesa stabilizzazione non convergente
- Rimandata a post-RT-22 (rifornimento): non impedisce produzione

### 13. Boost — `gathered` non riconosciuto (CHIUSA ✅ 20/04/2026)
- **Fix applicato:** `BoostConfig.wait_after_tap_speed: 2.0s` (era `1.0s`),
  parametrizzato da `tasks/boost.py:310`. Allineato alla regola DELAY UI.
- **Validazione:** ciclo notte 20→21/04 senza errori boost sulle istanze attive.

### 14. Arena — START CHALLENGE non visibile su 5 istanze (ALTA — NUOVA 21/04)
- Pattern ricorrente notte 20→21: `[ARENA] [PRE-CHALLENGE] START CHALLENGE non visibile → abort`
  su FAU_02/03/04/07/08. Seguono `screenshot None` ciclici + `vai_in_home ABORT (ADB unhealthy)`.
- Tutti e 3 i tentativi arena falliscono, poi ADB si riprende e raccolta torna OK.
- Ipotesi: UI gioco cambiata, template `pin_start_challenge` obsoleto, oppure entry
  flow arena modificato (popup intermedi non gestiti).
- Fix: aggiornare template + investigare se esiste pin intermedio saltato.

### 26. Allocazione raccolta non collegata al bot (CHIUSA ✅ 23/04/2026 — commit `424b440`)
- **Problema:** dashboard salva allocazione in runtime_overrides.json ma raccolta.py
  usava `_RATIO_TARGET_DEFAULT` hardcodato — non leggeva mai `ctx.config.ALLOCAZIONE_*`.
- **Fix applicato:**
  1. `config_loader.py _from_raw`: normalizza percentuali → frazioni 0-1
     (`_al_div = 100 if max(al.values()) > 1 else 1`) per tutti e 4 `allocazione_*`
  2. `raccolta.py _loop_invio_marce`: costruisce `ratio_cfg` da
     `ctx.config.ALLOCAZIONE_*` con mapping risorsa→tipo (pomodoro→campo, legno→segheria)
  3. Passa `ratio_target=ratio_cfg` a `_calcola_sequenza_allocation()`
- **Catena end-to-end ora funzionante:**
  UI dashboard → `runtime_overrides.json` → `merge_config` → `_from_raw` (normalize) →
  `ctx.config.ALLOCAZIONE_*` (frazioni) → `ratio_cfg` (mapping) → `_calcola_sequenza_allocation`

### 51. DistrictShowdown — gate readiness popup fase 3/4/5 (APERTA — alta priorità)
- **Contesto**: il flusso attuale tap icona → `sleep(delay_foray=5s)` → tap
  coord fissa all'interno del popup NON garantisce che il popup sia caricato.
  Su MuMu lento (come osservato su FAU_03 ciclo 24/04) il tap "interno"
  cade su schermata non ancora aggiornata → apre elemento sbagliato (es.
  icona WARFARE/Rally della HOME invece di claim chiave Influence) →
  il bot finisce bloccato in schermata che BACK non chiude →
  tutti i task successivi falliscono gate HOME → tick istanza perso.
- **Osservazione FAU_03 24/04 21:22**:
  - `tap (918,30)` icona Influence Rewards OK
  - `sleep 5s` → popup NON ancora aperto (gioco lento)
  - `tap (781,148)` cade sulla HOME del gioco → apre schermata WARFARE
  - `back x2` non chiude WARFARE (non è popup modal)
  - `vai_in_home()` score HOME 0.43-0.56 (parziale sotto WARFARE, sotto soglia 0.7)
  - Tick: 10 task dovuti, **tutti saltati** per "gate HOME FALLITO"
- **Fix proposto (analogo a `_wait_template_ready(pin_dado)` in `_apri_evento`)**:
  Per ciascun popup prima di tappare coord interne, gate su **sentinel template**:
  - **Fase 3 Influence**: aggiungere `pin_alliance_influence.png` (titolo popup).
    Prima di `tap (781,148)` chiave → `_wait_template_ready(pin_alliance_influence, max_wait=10s, stable_polls=2)`.
    Se None → skip (popup non aperto, no tap a vuoto).
  - **Fase 4 Achievement**: aggiungere `pin_achievement_rewards.png` (titolo popup).
    Prima di `tap (882,129)` Claim All → gate readiness.
  - **Fase 5 Fund Raid**: aggiungere `pin_alliance_list.png` (titolo Alliance List) +
    `pin_vs_fund_raid.png` (schermata VS). Due gate:
    - prima di `tap (802,161)` Select → gate `pin_alliance_list`
    - prima di `tap (443,450)` Raid + loop OCR → gate `pin_vs_fund_raid`
- **Template PNG richiesti** (da catturare via screenshot ADB):
  - `pin_alliance_influence.png`
  - `pin_achievement_rewards.png`
  - `pin_alliance_list.png`
  - `pin_vs_fund_raid.png`
- **Stessa logica già funzionante per mappa DS**: `pin_dado` sentinel in
  `_apri_evento` via `_wait_template_ready` risolve il problema analogo di
  "maschera non ancora stabilizzata dopo tap icona". Estendere il pattern
  ai popup interni = robustezza end-to-end.
- **Impatto**: risolve i tick persi su istanze "lente" (MuMu/VM rallentati)
  dove il delay 5s non basta. Atteso: 0 task SALTATO per gate HOME FALLITO
  post-fase 3/4/5 anche su hardware lento.

### 50. DistrictShowdown — finestre temporali evento (CHIUSA ✅ 24/04/2026)
- **Contesto**: l'evento District Showdown è attivo solo durante il weekend
  (Ven 00:00 → Lun 00:00 UTC = 3 giorni esatti). Il bot NON deve cercare
  l'evento fuori dalla finestra (spreco di tick + log rumorosi).
- **Finestre implementate in `tasks/district_showdown.py`**:
  - **Task completo**: attivo `Venerdì 00:00 UTC → Lunedì 00:00 UTC`
    (esclusi lunedì già dalle 00:00). Fuori → `should_run()` ritorna False
    → task saltato dall'orchestrator.
  - **Fase 5 Fund Raid**: attivo `Domenica 20:00 UTC → Lunedì 00:00 UTC`
    (ultime 4 ore dell'evento, quando Fund Raid si apre in-game).
    Fuori → `_fund_raid()` logga "fuori finestra" e skip.
- **Conversione ora Italia** (UTC+2 ora legale / UTC+1 ora solare):
  - Task DS: **IT Ven 02:00 → IT Lun 02:00** (legale) / Ven 01:00 → Lun 01:00 (solare)
  - Fund Raid: **IT Dom 22:00 → IT Lun 02:00** (legale) / Dom 21:00 → Lun 01:00 (solare)
- **Config in `DistrictShowdownConfig`** (UTC):
  ```python
  ds_start_weekday        = 4    # venerdì (Python weekday)
  ds_start_hour           = 0    # 00:00 UTC
  ds_end_weekday          = 0    # lunedì
  ds_end_hour             = 0    # 00:00 UTC (lunedì escluso)
  fund_raid_start_weekday = 6    # domenica
  fund_raid_start_hour    = 20   # 20:00 UTC
  ```
- **Helper**: `_is_in_event_window()` + `_is_in_fund_raid_window()` in
  `DistrictShowdownTask`. Usano `datetime.now(timezone.utc)`.

### 49. Ottimizzazioni startup istanza (APERTA — bassa priorità)
- **Contesto**: misurato ciclo 24/04 tipico avvio istanza → `Tick --`:
  - Happy path: ~130-150s
  - Medio: ~180-210s
  - Lento: ~240-270s
  - Bottleneck: `attesa caricamento fissa 60s` (step 8) + polling MuMu 5s
- **Ottimizzazioni candidate (non applicate)**:
  1. `DELAY_POLL_S` 5s → 2s in `core/launcher.py` (poll Android started)
     → guadagno ~3s per istanza
  2. Stabilizzazione HOME `stable_polls` 3 → 2 in `attendi_home`
     → guadagno ~5-8s per istanza
  3. `delay_carica_iniz_s` 60s → polling adattivo da 15s (già parziale ma
     spesso non converge presto) → potenziale -30s per istanza su path veloci
- **Impatto stimato**: -8s × 11 istanze = ~90s per ciclo (trascurabile vs
  durata tick). Non bloccante — rimandata per ridurre rischio di regressioni
  in fase di collaudo district_showdown.
- **Quando applicare**: dopo stabilizzazione district_showdown + Foray + Influence.

### 48. DistrictShowdown — skip animation check + early-exit loop (CHIUSA ✅ 24/04/2026)
- **Problema A — loop infinito**: `_loop_monitoring` in district_showdown loggava
  "auto in corso" indefinitamente quando il gioco usciva dalla maschera (crash/background/HOME),
  senza nessuno dei 3 pin trigger rilevato. Il task restava in loop fino a
  `max_monitoring_cicli=200 (~50 min)` sprecando il tick dell'istanza.
- **Problema B — animazione lenta**: il toggle "Skip animation" del gameplay District
  Showdown non veniva attivato; i 20 dadi impiegavano tempo eccessivo per animarsi.
- **Fix applicato (`tasks/district_showdown.py`):**
  1. **Early-exit `_loop_monitoring`**: nuovo contatore `unknown_streak`. Se per
     3 cicli consecutivi (~45s) nessun pin (gang_leader/access_prohibited/item_source/autoplay)
     è rilevato → return `"uscita_rilevata"` → graceful exit task.
  2. **Nuovo caso `pin_autoplay` visibile**: se il pin_autoplay della maschera
     evento è ancora visibile (`.found`) ma nessuno dei 3 trigger, significa
     che siamo ancora nell'evento con Auto Roll attivo → reset streak.
  3. **Check skip animation in `_apri_evento`**: dopo stabilizzazione maschera,
     verifica `pin_check_auto_roll` in ROI `(810, 340, 870, 400)`. Se non trovato
     → tap fisso `(840, 371)` per attivare il toggle. Velocizza l'intero gameplay.
- **Validato**: FAU_07 24/04 ciclo 3, uscita_rilevata dopo 5 cicli streak (poi ridotto
  a 3 per reattività maggiore) — task esce in ~45s invece di loopare 50 min.

### 47. DistrictShowdown — tap dinamico su coord match (CHIUSA ✅ 24/04/2026)
- **Problema**: `_attiva_auto_roll` tappava coordinate hardcoded (473, 389) sul
  pulsante Start, ma il popup Auto Roll ha posizione leggermente diversa su
  layout/risoluzioni diverse. Risultato: il tap cadeva in zona morta, Auto Roll
  non avviato, poi pin_item_source (falso positivo) concludeva "dadi esauriti"
  con 0 dadi rollati.
- **Fix applicato (`tasks/district_showdown.py`):**
  1. `_attiva_auto_roll`: tap su `has_start.cx, has_start.cy` dal match (score=1.000
     garantisce posizione corretta). Fallback hardcoded solo se `find_one` fallisce.
  2. Stesso fix in `_reenable_auto` per coerenza dopo gang_leader/access_prohibited.
  3. Tap su `pin_autoplay` (39, 151) → dinamico: cerca pin_autoplay nello screenshot
     e tappa il match, fallback hardcoded.
  4. **Attesa adattiva `_wait_template_ready`**: nuova primitiva helper che poll
     lo screenshot fino a quando un template appare stabilmente. Sostituisce i
     `time.sleep(X)` fissi con wait semantico (max_wait=15s, stable_polls=2).
- **Validato**: FAU_01 24/04 — `Auto Roll avviato — tap (479,387)` (coord match,
  non più 473,389), 17s dopo primo Gang Leader → re-enable → multiple cicli
  correttamente gestiti, poi "dadi esauriti" legittimo dopo 20 dadi.

### 46. Launcher — post-check gioco foreground + monkey fallback (CHIUSA ✅ 24/04/2026)
- **Problema**: `am start -n GAME_ACTIVITY` ritornava "OK" ma frequentemente il
  gioco restava in background (schermo mostra HOME Android MuMu invece del
  gioco). Il launcher vedeva `am start OK` + processo vivo → dichiarava
  successo → `attendi_home()` poi falliva per 180s perché il gioco non era
  realmente in foreground.
- **Fix applicato (`core/launcher.py`):**
  1. Nuova `_gioco_process_vivo(porta, adb)` — check ps pkg (ritorna True se
     processo esiste).
  2. Nuova `_gioco_in_foreground(porta, adb)` — check `dumpsys activity top`
     per pkg (ritorna True se l'app è l'activity top visibile).
  3. `_avvia_gioco()` ridisegnata:
     - am start
     - SEMPRE `monkey -p pkg -c LAUNCHER 1` (idempotente: porta UI al top)
     - `_gioco_in_foreground()` → se True OK, altrimenti retry (max 3)
  4. **Monkey recovery in `attendi_home`**: durante il loop BACK + polling
     schermata, se dopo `MONKEY_EVERY_N=6` cicli UNKNOWN consecutivi (~42s)
     la schermata non è stata ancora rilevata → rilancia monkey (cooldown 30s)
     per forzare foreground.
  5. Polling rilassato: sleep tra back e screenshot `1.5s → 5.5s` (ciclo totale
     ~7s invece di ~3s) — meno stress I/O.
- **Validato**: istanze dopo il fix hanno sempre rilevato foreground vs pre-fix
  che falliva su ~30% delle istanze con HOME Android persistente.

### 45. DistrictShowdown — MatchResult.found pattern (CHIUSA ✅ 24/04/2026)
- **Problema**: `MatchResult` è un `@dataclass` senza `__bool__` custom →
  `bool(MatchResult(found=False, score=0.589))` è sempre True. Il task
  district_showdown usava `if has_stop:` / `if result is None:` / `is not None`
  che danno risultati errati: `if has_stop:` sempre vero anche con score sotto
  threshold → branch "Auto Roll già attivo" triggerato su falsi positivi.
- **Osservato**: `Auto Roll già attivo (score=0.589)` — score sotto soglia 0.88
  ma il codice lo interpretava come trovato.
- **Fix applicato (`tasks/district_showdown.py`):** 10 check convertiti
  sistematicamente al pattern corretto:
  - `if result is None:` → `if not result.found:`
  - `if has_stop:` → `if has_stop.found:`
  - `if not has_start:` → `if not has_start.found:`
  - `matcher.find_one(...) is not None` → `matcher.find_one(...).found`
  (in `_apri_evento`, `_attiva_auto_roll`, `_verifica_toggle`, `_loop_monitoring`,
  `_gestisci_gang_leader`, `_reenable_auto`)

### 44. DistrictShowdown — conformità V6 API (CHIUSA ✅ 24/04/2026)
- **Problema**: il task `tasks/district_showdown.py` committato dal secondo PC
  aveva 6 bug V6 API che lo facevano crashare al primo tick:
- **Fix applicati:**
  1. `@property def name` → metodo `def name(self) -> str`
  2. `ctx.config.task.district_showdown` (non esiste in V6) →
     `ctx.config.task_abilitato("district_showdown")`
  3. `def e_dovuto(self)` senza ctx → `def e_dovuto(self, ctx: TaskContext)`
  4. `TaskResult(note=...)` → `TaskResult(message=...)` (V6 campo è `message`)
  5. `matcher.find_one(screen.frame, ...)` → `matcher.find_one(screen, ...)`
     (in V6 il matcher accetta Screenshot direttamente)
  6. `matcher.find_one(..., roi=...)` → `matcher.find_one(..., zone=...)`
     (parametro si chiama zone, non roi)
- **Supplementari**:
  - `main.py _import_tasks._catalogue`: aggiunto `DistrictShowdownTask`
  - `config/task_setup.json` sync dev→prod (entry priority 107 mancava in prod)
  - `config_loader.py`:
    - `GlobalConfig` dataclass: + `task_donazione`, `task_district_showdown`
    - `_InstanceCfg.task_abilitato()` mappa: + `donazione`, `district_showdown`
    - Defaults + `_from_raw` + `to_dict` aggiornati coerentemente
  - Template PNG dal secondo PC: 4 file con doppia estensione `.png.png`
    rinominati, poi 5 pin aggiuntivi sync dev→prod

### 43. Integrazione DistrictShowdownTask nella dashboard (CHIUSA ✅ 24/04/2026)
- **Obiettivo**: rendere `DistrictShowdownTask` (nuovo task evento mensile
  Gold Dice auto-roll) controllabile via pill UI e integrato in tutto lo stack.
- **Fix applicato:**
  1. `dashboard/models.py` TaskFlags: `+ district_showdown: bool = False`
     (default OFF, evento mensile, 3 giorni durata)
  2. `api_config_overrides.py` toggle_task valid_tasks: `+ district_showdown`
  3. `dashboard/app.py` `partial_task_flags_v2` ORDER: inserito dopo `arena_mercato`
  4. Template pin catalogo (10 file): `pin_district_showdown, pin_autoplay,
     pin_check_auto_roll, pin_no_check_auto_roll, pin_start_auto_roll,
     pin_stop_auto_roll, pin_gang_leader, pin_access_prohibited,
     pin_item_source, pin_assistance_progress`
  5. `sync_prod.bat` patch: include `templates/` (prima non sincronizzato)
- **Validato**: pill renderizzata, toggle on/off funzionante, task registrato
  nell'orchestrator priority=107 (tra rifornimento=100 e raccolta=110).

### 42. Donazione — ramo "pin_marked non trovato" non chiude Technology (CHIUSA ✅ 23/04/2026)
- **Problema:** quando `_cerca_e_dona` esce con `pin_marked non trovato al primo scan`
  (scenario più frequente — quando l'alleanza non ha tech marked), il task NON
  eseguiva `device.back()` prima del `break`. Il successivo `vai_in_home()`
  nel `run()` tentava 8 volte con score HOME 0.39-0.46 (ancora in Technology)
  e falliva → il gate HOME della task successiva (raccolta) saltava.
- **Sintomo visibile:** il task riapriva/ri-interpretava schermate Technology
  (l'utente ha osservato "apre maschera, non clicca, chiude, riapre più volte"),
  segno di `vai_in_home()` che fa BACK/polling senza progressi.
- **Osservato su FAU_04 ciclo 2 (21:40 locale):** `donate=0 success=True` ma
  raccolta successiva skipped (HOME FALLITO), perdita slot di raccolta del tick.
- **Fix applicato (`tasks/donazione.py:179-191`):** aggiunto back x3 nel branch
  "pin_marked non trovato" (coerente con i branch `research` / `non_riconosciuto`
  già presenti). Chiude Technology + Alliance menu prima del break.
- **Hot-reload:** richiede restart bot (Python import-cache).

### 41. Integrazione DonazioneTask nella dashboard (CHIUSA ✅ 23/04/2026)
- **Obiettivo:** rendere il nuovo `DonazioneTask` controllabile via pill UI come gli altri task.
- **Fix applicato:**
  1. `dashboard/models.py` TaskFlags: aggiunto `donazione: bool = True`
  2. `api_config_overrides.py` `toggle_task` valid_tasks: `+ donazione`
  3. `dashboard/app.py` `partial_task_flags_v2` ORDER: `donazione` inserito dopo `alleanza`
- **Validato:** pill renderizzata, PATCH toggle on/off funziona, flag persistito
  su `runtime_overrides.json`, hot-reload al prossimo tick del bot.

### 40. Flag rifornimento_mappa duplicato — sub-mode incoerente (CHIUSA ✅ 23/04/2026)
- **Problema:** la sub-mode del rifornimento (mappa vs membri) era rappresentata
  da 3 flag ridondanti (`task.rifornimento_mappa`, `rifornimento.mappa_abilitata`,
  merged `rifornimento_mappa.abilitato`) con source-of-truth inconsistente:
  - `toggle_task` scriveva solo `task.rifornimento_mappa`
  - `set_rifornimento_mode` scriveva tutti e 3 coerentemente
  - Dashboard render leggeva `rifornimento.mappa_abilitata`
  - Bot leggeva (via merge) `task.rifornimento_mappa`
  Disallineamento osservato: dashboard mostrava `mappa=True` ma bot aveva
  `task.rifornimento_mappa=False` → rifornimento non eseguito in mappa.
- **Semantica corretta:** `task.rifornimento` = master on/off; se True
  si sceglie SOLO una sub-mode in `rifornimento.mappa_abilitata` o
  `rifornimento.membri_abilitati` (mutuamente esclusive).
- **Fix applicato:**
  1. `config/config_loader.py:300-307`: propagazione cambia source
     `task.rifornimento_mappa` → `rifornimento.mappa_abilitata`
  2. `dashboard/models.py:48`: rimosso `rifornimento_mappa: bool` da TaskFlags
  3. `dashboard/routers/api_config_overrides.py`:
     - `set_rifornimento_mode` non scrive più `task.rifornimento_mappa`
     - `save_rifornimento` non scrive più `task.rifornimento_mappa`
     - `toggle_task` valid_tasks non contiene più `rifornimento_mappa`
  4. Cleanup `runtime_overrides.json` (dev + prod): rimosso
     `globali.task.rifornimento_mappa`
- **Validazione:** switch mode mappa↔membri via PATCH endpoint mantiene stato
  coerente; merged config `rifornimento_mappa.abilitato` riflette
  correttamente `rifornimento.mappa_abilitata`; `ctx.config.RIFORNIMENTO_MAPPA_ABILITATO`
  end-to-end dalla UI al task runtime.

### 39. Flag `abilitata` applicato solo a fine ciclo (fino ~2h ritardo) (CHIUSA ✅ 23/04/2026)
- **Problema:** `_carica_istanze_ciclo` è chiamato una sola volta all'inizio
  del ciclo. Se l'utente disabilita un'istanza dalla dashboard a ciclo in corso,
  l'istanza continua a essere avviata perché la lista era già "congelata".
  Caso osservato: FauMorfeus con `abilitata=False` (saved 14:40:20) avviato
  regolarmente alle 15:30:58 come parte di CICLO 2 iniziato alle 14:15:57.
- **Fix applicato (`main.py`, for istanze_ciclo loop):**
  Prima di `_scrivi_checkpoint` e `_launcher.reset_istanza` per ogni istanza,
  rilettura di `runtime_overrides.json` per recuperare il flag `abilitata`
  aggiornato. Se False → skip con log `--- Skip {nome} (abilitata=False runtime) ---`.
  Costo: 1 read JSON extra per istanza (~10ms). Effetto immediato del flag.
- **Validazione attesa:** disabilitare un'istanza mid-ciclo deve causare skip
  immediato al suo turno, non avvio launcher + game.

### 38. Dashboard leggeva stato/config da dev invece di prod (CHIUSA ✅ 23/04/2026)
- **Problema:** la sezione "risorse farm" e la card "stato" mostravano valori vuoti
  (`—`, `0`, `unknown`) anche con il bot prod regolarmente attivo e state files popolati
  in `C:\doomsday-engine-prod\state\`.
- **Causa:** `dashboard/services/config_manager.py` calcolava `_ROOT` solo da
  `__file__` e NON onorava `DOOMSDAY_ROOT` (a differenza di `stats_reader.py`
  che invece lo usa). Risultato: se la dashboard veniva avviata dal repo dev
  (es. `uvicorn ... --reload` lanciato manualmente), i path config puntavano
  alla cartella dev vuota anche con `DOOMSDAY_ROOT=prod` settato.
  Concausa: uvicorn era stato riavviato in modalità dev (cwd=dev, no env var)
  perdendo quindi l'allineamento a prod.
- **Fix applicato (`dashboard/services/config_manager.py`):**
  ```python
  _ROOT      = Path(__file__).parent.parent.parent
  _PROD_ROOT = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
  _GLOBAL_CONFIG_PATH = _PROD_ROOT / "config" / "global_config.json"
  _OVERRIDES_PATH     = _PROD_ROOT / "config" / "runtime_overrides.json"
  _INSTANCES_PATH     = _PROD_ROOT / "config" / "instances.json"
  ```
  Ora `config_manager` segue la stessa regola di `stats_reader`: se
  `DOOMSDAY_ROOT` è settato usa quello, altrimenti fallback su `__file__`.
- **Validazione:** dashboard relanciata via `run_dashboard_prod.bat`:
  pomodoro 94.7M, legno 59.7M, petrolio 11.5M, 93 spedizioni, provviste 128.4M,
  card stato `running` uptime 0h 34m.

### 25. Tracciamento diamanti nello state (BASSA)
- **Problema:** `ocr_risorse()` legge già `.diamanti` ma nessun task lo persiste.
- **Fix:**
  1. `tasks/rifornimento.py` — dopo OCR deposito: `ctx.state.metrics["diamanti"] = deposito.diamanti`
  2. `core/state.py` — verificare che `metrics` sia dict libero (probabilmente ok)
  3. `stats_reader.py` — aggregare `diamanti` in `RisorseFarm` + `get_risorse_farm()`
  4. `app.py` — `partial_res_totali` popola `diamond-row` con valore reale
- **Prerequisito:** verificare che `rifornimento.py` chiami già `ocr_risorse()` e dove.

### 19. Emulator orfani dopo kill unclean del bot (CHIUSA ✅ 23/04/2026)
- **Problema:** kill unclean del bot (SIGKILL, Ctrl+C durante tick, crash) lascia
  emulator MuMuPlayer dell'istanza in corso APERTO. Al restart del bot il vecchio
  emulator resta attivo finché il nuovo bot non arriva al turno di quella istanza
  (ore dopo). Intanto la dashboard mostra lo stato stale e possono verificarsi
  conflitti ADB/port.
- **Fix applicato (`main.py`):**
  - Nuova `_cleanup_tutti_emulator(istanze, dry_run)` che itera `reset_istanza`
    per tutte le 12 istanze configurate.
  - Chiamata all'**avvio del bot** (prima del primo ciclo) e all'**inizio di
    ogni ciclo** (prima del for istanze).
  - Ogni reset protetto da try/except — un'istanza che fallisce il reset non
    blocca il cleanup delle altre.
- **Trade-off:** ~12×3s = ~36s di overhead per ciclo. Mitigato dal fatto che
  `reset_istanza` su emulator già spento è rapido (MuMuManager restituisce
  immediatamente).
- **Validazione:** log `[MAIN] Cleanup emulator orfani (startup)` e
  `(pre-ciclo)` a ogni ciclo.

### 14-bis. Raccolta No Squads — loop esterno e check universale (CHIUSA ✅ 22/04/2026)
- **Problema:** FAU_10 generava ~40 detection "No Squads" per tick (408 su 10 tick).
  Il check F3 (`pin_no_squads`) funzionava (407 break eseguiti) ma il `break`
  interno usciva solo dal `for tipo`, lasciando il `while tentativi_ciclo < 3`
  esterno a ripetere 3× l'intera navigazione (rilettura slot, vai_in_mappa, for tipi).
- **Bug secondario:** il check `pin_no_squads` scattava SOLO se la maschera
  non si apriva (retry fallito). Caso "maschera aperta ma overlay No Squads
  visibile" non gestito → tap MARCIA → `marcia FALLITA — rollback`.
- **Fix applicato:**
  - `tasks/raccolta.py:1544-1552`: `tentativi_ciclo = MAX_TENTATIVI_CICLO` prima del break
  - `tasks/raccolta.py:1095-1113`: check `pin_no_squads` universale dopo verifica apertura
- **Effetto atteso:** da ~40 detection/tick → 1 detection/tick, ~3 navigazioni mappa in meno.

### 15. `engine_status.json` stale writer (ALTA — NUOVA 21/04)
- File timestamp fermo alle 03:51:57 mentre log istanze continuano fino 05:51.
- Campo `ciclo: 0` mai incrementato per tutta la notte.
- Dashboard mostra stato obsoleto (FAU_08 risulta `running` ma è passato ad altri task).
- Ipotesi: `_status_writer_loop` thread ha preso eccezione silente oppure fd stale.
- Fix: try/except + log in `_scrivi_status_json`, periodic heartbeat check.

### 14-ter. Raccolta No Squads — loop while interno (CHIUSA ✅ 22/04/2026)
- **Problema:** fix precedente (break dal `for tipo` + `tentativi_ciclo=MAX`) non bastava.
  `_loop_invio_marce` ha un **while interno proprio** (riga 1501) che rientrava dopo il break del for,
  ri-eseguiva il for, ri-detectava No Squads → loop infinito fino a `invii_totali >= max_invii`.
- **Fix applicato:** terzo livello di break dopo il `for tipo` in `_loop_invio_marce:1641` —
  propaga il break al while interno. Con il check già presente in `RaccoltaTask.run()` dopo
  `_loop_invio_marce`, il flag viene propagato su 3 livelli di loop annidati.
- **Validazione:** riavvio bot richiesto per attivare.

### 14-quater. Raccolta NameError MAX_TENTATIVI_CICLO (CHIUSA ✅ 22/04/2026)
- **Problema:** fix errato che assegnava `tentativi_ciclo = MAX_TENTATIVI_CICLO` dentro
  `_loop_invio_marce`. Entrambe le variabili sono locali a `RaccoltaTask.run()` (scope diverso)
  → `NameError` a runtime. FAU_09 e FAU_10 in stato `err` per tutti i tick raccolta.
- **Fix applicato:** rollback della riga errata in `_loop_invio_marce`. Check flag + break
  spostato in `RaccoltaTask.run()` dopo la chiamata `_loop_invio_marce` (scope corretto).

### 15-bis. Rifornimento distribuzione risorse sbilanciata (CHIUSA ✅ 22/04/2026)
- **Problema:** su 140.7M risorse inviate nel ciclo 20→21, distribuzione 65% legno /
  23% petrolio / 12% pomodoro / 0% acciaio. Pomodoro mandato solo da 3 istanze su 11.
- **Analisi:** `runtime_overrides.json` aveva `rifornimento.soglia_campo_m: 50` (50M)
  vs default `global_config.soglia_campo_m: 5.0` (5M). Deposito tipico pomodoro 27-33M
  → sempre sotto soglia 50M → round-robin saltava pomodoro sistematicamente.
- **Fix applicato:** `soglia_campo_m: 50 → 5` in `runtime_overrides.json` (dev+prod).
- **Distribuzione attesa post-fix:** pomodoro 40%, legno 40%, petrolio 20%.

### 16. OCR anomalo FAU_10 — valore "compila" scambiato per "reali" (MEDIA — NUOVA 21/04)
- Ciclo 20→21, FAU_10 spedizione 3: `Rifornimento: spedizione 3 — legno 999,000,000 reali | provviste=12,435,903`
- 999M è il valore di "compila" (tetto artificiale 999,000,000), non la quantità spedita.
- Singola occorrenza su 68 spedizioni — gonfia le metriche di 7x.
- Fix: aggiungere sanity check nel logger (`qta > provviste` → warning + readback).

### 17. Storico engine_status filtrato (MEDIA — NUOVA 21/04)
- `engine_status.storico` registra solo eventi `raccolta` e `arena`.
- Task `rifornimento`, `vip`, `alleanza`, `messaggi`, `zaino`, `arena_mercato`,
  `boost`, `store`, `radar` MAI presenti nello storico.
- Dashboard `/ui/partial/storico` mostra solo 2 tipi di eventi → trend incompleto.
- Fix: verificare dove `_append_storico` è chiamato, estendere a tutti i task terminali.

### 18. Dashboard mostra global_config raw, bot usa merged (CHIUSA ✅ 22/04/2026)
- **Problema:** route `/ui` passava `cfg = get_global_config()` (solo `global_config.json`)
  mentre il bot usa `merge_config(gcfg, overrides)` → divergenze verificate prod su
  `task_radar_census`, `task_rifornimento`, `rifornimento_mappa_abilitato`, `rifugio_x/y`.
- **Fix applicato (opzione A):** nuovo `get_merged_config()` in `dashboard/services/config_manager.py`.
  Route `/ui` ora passa i valori merged — dashboard e bot mostrano gli stessi valori
  effettivamente usati al tick successivo.

---

## Regole architetturali

### REGOLA DELAY UI (20/04/2026)
Dopo ogni tap che apre un popup o overlay, usare `time.sleep(≥ 2.0s)`
prima di qualsiasi `screenshot` o template matching.

**Derivato da**: fix rifornimento 20/04/2026 (`tasks/rifornimento.py`):
- `_centra_mappa`: tap castello `0.3s` → **`2.0s`** (allineato V5)
- `_apri_resource_supply`: `0.3s` → **`1.5s`** (minimo operativo)
- `_compila_e_invia`: retry OCR nome destinatario su stringa vuota con nuovo
  screenshot dopo `1.0s` di attesa

**Applicare a**:
- Tutti i `device.tap()` seguiti da `matcher.score()` / `matcher.find_one()` /
  `ctx.device.screenshot()` immediato
- Tutti i tap che aprono popup, maschere invio, pannelli overlay, popup di conferma
- Eccezione: pattern `tap + time.sleep(x) + _attendi_template(...)` dove il
  polling interno copre già la variabilità (allora `x ≥ 1.0s` basta,
  il polling fa il resto)

**Motivazione**: su Windows 11 con HDD lento e WiFi debole, i popup di
gioco impiegano 1.0-2.5s a renderizzare. Delay < 1.5s causa screenshot/OCR
su frame transienti con score borderline → falsi negativi e retry inutili.

---

## Fix applicati in sessione 18/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Filtro istanze abilitate | `main.py` | `_carica_istanze()` filtra `abilitata=False` prima del filtro nome — risolve avvio 12 istanze invece di 3 |
| BlacklistFuori globale | `tasks/raccolta.py` | File unico `data/blacklist_fuori_globale.json` condiviso tra istanze. Rimosso parametro `istanza` dal costruttore. Eliminati file legacy `blacklist_fuori_FAU_XX.json` |
| Sanity check OCR slot | `tasks/raccolta.py` | `attive > totale_noto` → skip conservativo. OCR anomalo ignorato |
| Flush frame cached | `tasks/raccolta.py` | `_verifica_tipo()`: doppio screenshot (flush + live) + sleep 0.5s. Fix score 0.05–0.23 su FAU_01/FAU_02 |
| Skip neutri per tipo | `tasks/raccolta.py` | `skip_neutri_per_tipo`: dopo 2 skip neutri consecutivi sullo stesso tipo → blocca tipo. Evita loop su stesso nodo in blacklist |
| Logica raccolta refactoring | `tasks/raccolta.py` | Nuova gestione risultati `_invia_squadra()`: tipo_bloccato NON incrementa fallimenti; loop esterno 3 tentativi; rilettura slot post-loop; uscita su slot pieni |
| reset_istanza() | `core/launcher.py` | Nuova funzione: force-stop + shutdown + polling spegnimento + adb disconnect. Chiamata all'inizio di ogni ciclo per garantire stato pulito |
| Stabilizzazione HOME | `core/launcher.py` | `attendi_home()`: dopo HOME rilevata, loop 30s (poll ogni 5s) che verifica 3 HOME consecutive prima di procedere. Evita avvio task con popup aperti |
| Verifica spenta pre-launch | `core/launcher.py` | `avvia_istanza()`: polling `is_android_started==False` prima del launch — evita avvio su istanza in stato intermedio |
| attendi_template() centralizzato | `shared/ui_helpers.py` | Nuova funzione polling con timeout. Sostituisce sleep fissi prima di verifiche template in tutti i task |
| attendi_scomparsa_template() | `shared/ui_helpers.py` | Polling attesa scomparsa template (popup caution zaino) |
| Polling apertura popup | `tasks/boost.py` | Sostituito sleep fisso con attendi_template (timeout 6s) per pin_manage |
| Polling apertura maschera VIP | `tasks/vip.py` | Sostituito wait_open_badge fisso con attendi_template |
| Polling apertura messaggi | `tasks/messaggi.py` | Sostituito wait_open fisso con attendi_template per PRE-OPEN |
| Polling tab messaggi | `tasks/messaggi.py` | Sostituito wait_tab fisso con attendi_template per tab Alliance/System |
| Polling apertura alleanza | `tasks/alleanza.py` | Sostituiti wait_open_alleanza e wait_open_dono con sleep minimo |
| Polling mercante store | `tasks/store.py` | Sostituito wait_tap fisso con attendi_template per merchant open |
| Polling lista arena | `tasks/arena.py` | Sostituiti sleep fissi navigazione con attendi_template |
| Polling continue arena | `tasks/arena.py` | Sostituiti sleep post-victory/failure con attendi_template |
| Polling arena mercato | `tasks/arena_mercato.py` | Sostituito sleep dopo carrello con attendi_template |
| Polling radar | `tasks/radar.py` | Ridotto sleep pre-notifiche da 2.5s a 0.5s |
| Polling rifornimento | `tasks/rifornimento.py` | Sostituiti sleep apertura popup con attendi_template |
| Polling caution zaino | `tasks/zaino.py` | Sostituito sleep caution con attendi_scomparsa_template |
| Fallback livelli raccolta | `tasks/raccolta.py` | Sequenza 7→6→5 (base=7) o 6→7→5 (base=6) prima di bloccare tipo |
| Ricentro mappa post-skip | `tasks/raccolta.py` | HOME+mappa dopo skip blacklist — fix tipo NON selezionato |
| skip_neutri_per_tipo | `tasks/raccolta.py` | Blocca tipo dopo 2 skip neutri consecutivi |
| MCP Monitor server | `monitor/mcp_server.py` | MCP server FastMCP per analisi log in tempo reale da Claude Code VSCode. Strumenti: ciclo_stato, istanza_anomalie, istanza_raccolta, istanza_launcher, log_tail, anomalie_live |
| Monitor analyzer | `monitor/analyzer.py` | Logica parsing JSONL, rilevamento anomalie, statistiche raccolta/launcher condivisa tra MCP server e futuri tool |
| BlacklistFuori path assoluto | `tasks/raccolta.py` | `BlacklistFuori.__init__()` risolve `data_dir` relativo contro project root (`Path(__file__).resolve().parents[1]`). Fix WinError 5 "Accesso negato: 'data'" quando CWD del processo ≠ `C:\doomsday-engine` (regressione blacklist globale) |
| CWD sempre project root | `main.py`, `run_task.py` | `os.chdir(ROOT)` subito dopo il calcolo di ROOT. Garantisce che il CWD del processo sia `C:\doomsday-engine` indipendentemente dalla directory da cui viene lanciato (cmd prompt, popup, shortcut). Fix sistemico per path relativi in tutto il codice |
| Fallback livelli con blacklist | `tasks/raccolta.py` | `_invia_squadra()`: il loop `sequenza_livelli` ora considera "nodo utile" solo se NON in `blacklist_fuori`. Prima il `break` scattava al primo nodo trovato anche se blacklistato, impedendo il fallback 6→7→5. Se tutti i livelli restituiscono blacklistati → skip neutro (gestito dal guard 2-strike). Rimossa funzione morta `_cerca_nodo_con_fallback` (mai chiamata) |
| Reset UI tra livelli fallback | `tasks/raccolta.py` | Tra un livello e il successivo nel loop `sequenza_livelli`: doppio BACK + vai_in_home + vai_in_mappa per stato UI pulito. Prima il solo `KEYCODE_BACK` lasciava la lente in stato intermedio → `_verifica_tipo` al livello successivo falliva sistematicamente (log "LENTE → Lv.7" senza mai "CERCA eseguita per Lv.7", 14s di retry prima di abort tipo_bloccato). Verificato su FAU_01 e FAU_02 ciclo 19:43-19:49 |

## Fix applicati in sessione 19/04/2026

Riscrittura completa `tasks/raccolta.py` e `tests/tasks/test_raccolta.py` per
consolidare la logica raccolta. Baseline test: 42 passed / 57. Post-riscrittura:
**57 passed / 57**.

| Fix | File | Dettaglio |
|-----|------|-----------|
| FIX A — sequenza _invia_squadra riscritta | `tasks/raccolta.py` | Flusso: CERCA + leggi_coord → blacklist_fuori (skip_neutro, prova lv successivo) → blacklist RAM (retry stesso lv, tipo_bloccato se ancora occupato) → reserve → tap nodo + gather → territorio (skip_neutro se FUORI) → livello nodo (tipo_bloccato se basso) → marcia → commit. Percorsi sparsi consolidati. |
| FIX B — `_reset_to_mappa()` centralizzato | `tasks/raccolta.py` | `vai_in_home() → leggi_contatore_slot() → vai_in_mappa()`. Sostituisce tutti i blocchi inline BACK+HOME+MAPPA. Ritorna attive_reali (-1 se OCR fallisce). |
| FIX C — verifica slot HOME post-marcia | `tasks/raccolta.py` | Dopo ogni ok=True in `_loop_invio_marce`: `_reset_to_mappa()` + aggiornamento `attive_correnti`. Uscita immediata se slot pieni. [RIALLINEA] logga discrepanze tra contatore in-memory e OCR. |
| FIX D — iteratore sulla sequenza | `tasks/raccolta.py` | `idx_seq` rimpiazzato da `for tipo in sequenza`. Sequenza ricalcolata ad ogni giro while; se ok=True → break for → ricalcola al prossimo while (gap-based allocation aggiornata con attive_correnti corrente). |
| FIX E — fallback livelli semplificato | `tasks/raccolta.py` | Rimosso Lv.5. `base=7 → [7,6]`, `base=6 → [6,7]`. Due soli livelli tentati per ogni invio. |
| FIX F — delay stabilizzazione aumentati | `tasks/raccolta.py` | `_cerca_nodo`: tap_lente 0.8→1.5, doppio tap_icona 1.2→1.8, MENO 0.15→0.2, PIU 0.2→0.25. `_verifica_tipo`: pre-flush 0.5→0.8, flush-live 0.2→0.5. `_tap_nodo_e_verifica_gather`: tap_nodo 1.0→1.5, retry 1.5→2.0. `_esegui_marcia`: RACCOGLI 0.5→0.8, SQUADRA 1.4→1.8, retry SQUADRA 1.8→2.2, MARCIA 0.8→1.2. |
| FIX G — `_GatherResult` dataclass | `tasks/raccolta.py` | `_tap_nodo_e_verifica_gather` ritorna `_GatherResult(ok, screen)` invece di tuple implicita. Rimosso isinstance(esito, tuple) workaround in `_invia_squadra`. |
| Test helper `_ctx_nav_ok` | `tests/tasks/test_raccolta.py` | Stubba `navigator.vai_in_mappa/vai_in_home` a True. Necessario perché `GameNavigator + FakeMatcher` senza template barra inferiore → vai_in_mappa=False → early return in `RaccoltaTask.run`. Sbloccati 9 test preesistenti. |
| Test ConGather aggiornati V6 | `tests/tasks/test_raccolta.py` | Chiave blacklist "tipo_campo" (legacy V5) → "100_200" (OCR V6 X_Y). Patchati `_leggi_coord_nodo`, `_reset_to_mappa`, `_leggi_attive_post_marcia`, `_leggi_livello_nodo` per isolare dalla catena OCR. |
| FIX H — Debug screenshot verifica tipo | `tasks/raccolta.py` | `_salva_debug_verifica()` salva frame BGR in `debug_task/raccolta/verifica_{istanza}_{tipo}_{ts}_score{N}.png` quando `_verifica_tipo` fallisce con score < 0.20. Permette analisi visiva dell'Issue #9 petrolio FAU_00 (score stabile 0.15 suggerisce UI alterata da overlay/popup, non rumore casuale). `*.png` già in .gitignore → nessun file in repo. |
| Fix boost polling USE | `tasks/boost.py` | Polling reale `find_one(pin_speed_use)` fino a timeout 5s + poll 0.4s dopo tap Gathering Speed, al posto di singolo shot post sleep 0.5s. Shot e match riutilizzati da STEP 6 (8h) e STEP 7 (1d). Verificato su FAU_00 ciclo 21:47 (pin_speed_use=-1.0 sistematico) — fix copre caso "animazione popup in corso" ma pattern overlay persistente (11/12 FAIL FAU_00) richiede investigazione separata (debug screenshot). |
| FIX I — _apri_lente_verificata | `tasks/raccolta.py` | Nuova funzione con pre-check "lente già aperta" + tap + post-check marker (pin_field visibile in ROI_LENTE) + BACK×2 recovery su fallimento, fino a max_retry=3. Integrata in `_cerca_nodo` sia in apertura primaria che in reset pannello. **Root cause identificata via debug screenshot**: il tap (38,325) su FAU_00 dopo una marcia finiva sulla mappa su una bestia NPC visibile → gioco apriva maschera beast roster/Level Up → tap successivi (tipo, livello, CERCA) su UI sbagliata → effetto a catena Issue #9. Il pre-check + BACK recovery chiude la maschera parassita e riprova l'apertura lente. |
| Fix boost tap coord Gathering Speed | `tasks/boost.py` | Tap su `(speed_cx, speed_cy)` invece di `(480, speed_cy)`. Il cx hardcoded a 480 cadeva in zona inerte tra icona e pulsante. Verificato runtime 12:12-12:14 FAU_00/FAU_01: `pin_speed_use=-1.0` sistematico, `pin_speed_8h=0.606` stabile = stessa lista boost (tap non aveva navigato alla sotto-maschera). Nuovo tap centra l'icona tappabile `pin_speed`. Log aggiornato con `cx` oltre a `cy`. **REVERT 19/04/2026 sessione successiva**: V5 (produzione bot-farm) conferma (480, speed_cy) funziona. Fix errato ripristinato a V5 esatto. |
| REVERT boost → V5 esatto | `tasks/boost.py` | Ripristinato tap `(480, speed_cy)` + `time.sleep(2.0)` fisso + singolo screenshot come V5 (`C:\Bot-farm\boost.py`). Rimossi i fix precedenti (polling 5s, tap su cx): non risolvevano il problema e introducevano complessità. V5 ha run stabile in produzione — il ripristino esatto è la baseline da cui partire per nuove ottimizzazioni. |
| Boost fix tap + polling + debug | `tasks/boost.py` | Tap su `(speed_cx, speed_cy)` (centro icona pin_speed), polling `pin_speed_use` timeout 4s via `_attendi_frame_use`, delay `wait_after_tap_boost=1.5s` post tap iniziale, screenshot debug pre/post tap in `debug_task/boost/`. Verificato via test live su FAU_00 (ore 18:12): boost 8h attivato con cy=260 (tap responsivo). Pattern osservato: se dopo swipe cy > 400 il tap è ignorato dal gioco (zona scroll-edge), sotto cy~260 tap risponde. Fix futuro potenziale: swipe aggiuntivo quando cy > 400. |
| test_boost_live.py | `test_boost_live.py` (nuovo) | Runner isolato standalone per BoostTask su FAU_00 reale. Bypassa `should_run()` (esegue `run()` direttamente), `navigator=None` (salta ensure_home), log console con timestamp, UTF-8 forzato su stdout. Utile per debug mirato del task boost senza dover lanciare l'intero `main.py`. Comando: `python test_boost_live.py`. |
| Fix test_boost.py _cfg_zero() | `tests/tasks/test_boost.py` | Rimossi parametri `wait_after_tap` e `wait_after_speed_tap` da `BoostConfig()` — non esistono più nel dataclass (parametri legacy). Sbloccati 20 test che fallivano con TypeError. Baseline 15/35 → 35/35 passed. |

## Fix e implementazioni sessione 23/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| Pannello risorse farm dati reali | `dashboard/app.py`, `stats_reader.py` | get_risorse_farm() da state/FAU_XX.json |
| Fix OCR Issue #16 | `stats_reader.py` | inviato da dettaglio_oggi invece di inviato_oggi |
| FauMorfeus aggiunto | `config/instances.json` | profilo raccolta_only, abilitata=true |
| Font +2px leggibilità | `dashboard/static/style.css` | gamma 7-11px → 9-13px |
| Fix stati CSS | `dashboard/static/style.css` | running/waiting/error/unknown |
| --reset-config | `main.py` | ripristina runtime_overrides da instances.json |
| task_setup.json | `config/task_setup.json`, `main.py` | _TASK_SETUP estratto da main.py |
| Badge PROD/DEV | `dashboard/app.py`, `base.html`, `style.css` | label ambiente in topbar |
| Bat separati dev/prod | `run_dashboard_prod.bat`, `run_dashboard_dev.bat`, `run_dev.bat` | porte 8765/8766 |
| Resume checkpoint | `main.py` | last_checkpoint.json + prompt interattivo |
| Storico farm giornaliero | `tasks/rifornimento.py` | data/storico_farm.json, retention 90gg |
| Prompt configurazione avvio | `main.py` | runtime vs reset + --use-runtime flag |
| _carica_istanze_ciclo() | `main.py` | merge dinamico instances.json + overrides ad ogni ciclo |
| Cleanup emulator orfani | `main.py` | `_cleanup_tutti_emulator()` startup + pre-ciclo (elimina MuMu orfani da kill unclean) |
| Config statica pulita | `config/instances.json` | FAU_09/FAU_10 truppe=0 (erano 60000/15000) |
| Allocazione raccolta | `config/global_config.json` | 35/35/20/10 (pomodoro/legno/acciaio/petrolio) |
| Fix `ts_invio` rifornimento | `tasks/rifornimento.py` | `ts_invio = time.time()` DOPO `_compila_e_invia` (era prima, sottostimava ETA di ~20s → attese sbagliate) |
| Filtro `raccolta_only` | `main.py:_thread_istanza` | Se `tipologia=="raccolta_only"` registra solo RaccoltaTask; FauMorfeus non tenta più boost/vip/arena/... |
| toggle_task async body parser | `dashboard/routers/api_config_overrides.py` | Legge JSON body o form data da HTMX con content-type detection (fix 500 error). Include Request dagli import fastapi |
| TipologiaIstanza raccolta_only | `dashboard/models.py` | Aggiunto enum value `raccolta_only` — prima pydantic rifiutava il valore di FauMorfeus causando 500 su tutti gli endpoint PATCH |
| Pill raccolta rimossa | `dashboard/app.py`, `templates/index.html` | raccolta è sempre-on → tolta dalla lista task flags e dot stato dal pannello allocazione |
| Ordine risorse fisso | `dashboard/app.py` | res-totali + res-oraria: pomodoro/legno/acciaio/petrolio coerente |
| Config 2×2 → 4×1 responsive | `dashboard/templates/index.html`, `static/style.css` | Nuovo `.cfg4` con col-box sistema+task-flags. 4 col desktop / 2×2 `<1400px` media query |
| Normalizzazione allocazione | `dashboard/services/config_manager.py` | `get_merged_config()` ora normalizza allocazione a frazioni 0-1 se max>1 (override era in percentuali) |
| storico_farm.json | `tasks/rifornimento.py` | `_aggiorna_storico_farm()` scrive `data/storico_farm.json` a fine `run()`, retention 90gg |
| Fix WinError 5 engine_status | `main.py:_scrivi_status_json` | Retry con backoff 0.1-0.5s su `os.replace` (Windows blocca rename se dashboard ha handle lettura aperto) |
| Font +2px | `dashboard/static/style.css` | Gamma font 7-11px → 11-15px (+2 due round, leggibilità) |
| Hide istanze zero | `dashboard/app.py:partial_res_totali` | Skip righe con `inviato_oggi` tutti 0 e `spedizioni_oggi=0` (es. FauMorfeus) |
| Issue #26 — Allocazione collegata al bot | `config/config_loader.py`, `tasks/raccolta.py` | `_from_raw` normalizza %→frazioni; `_loop_invio_marce` costruisce `ratio_cfg` da `ctx.config.ALLOCAZIONE_*` e lo passa a `_calcola_sequenza_allocation` (commit `424b440`) |
| None-safe build_instance_cfg | `config/config_loader.py`, `dashboard/models.py` | Helper `_ovr()` tratta null come miss → fall-through ai default; `RuntimeOverrides.save` con `exclude_none=True` previene riscrittura null (commit `4afb14e`) |
| Issue #37 — setModeRemote operativo | `dashboard/routers/api_config_overrides.py`, `dashboard/templates/index.html` | Nuovi endpoint PATCH `/api/config/rifornimento-mode/{mappa\|membri}` e `/api/config/zaino-mode/{bag\|svuota}` + JS `setModeRemote(taskName, sub)` fetch + sync UI + refresh task-flags-v2 (commit `c9ced2a`) |
| DonazioneTask V6 integrata | `tasks/donazione.py` (nuovo), `main.py`, `config/task_setup.json`, `config/runtime_overrides.json`, `templates/pin/pin_marked.png`, `pin_donate.png`, `pin_research.png` | Nuovo task V6 priority=105 tra Rifornimento e Raccolta. Refactor convenzioni V6 (core.task.Task, TaskContext, name()/should_run(), path `pin/pin_xxx.png`, `find_one(screen,...)`, `TaskResult(message=...)`, `task_abilitato()`, `vai_in_home()` no-arg). Back×3 dopo popup research/non_riconosciuto per chiudere catena Alliance→HOME. Test end-to-end FAU_00 validato: pin_marked → pin_donate 30 tap cap → back×3 → HOME → raccolta parte regolarmente. Flag `donazione: true` in runtime_overrides dev (prod NON aggiornato). |

| Area | File | Dettaglio |
|------|------|-----------|
| Raccolta No Squads — 3 livelli loop | `tasks/raccolta.py` | Fix completo per uscita pulita da No Squads attraverso i 3 livelli annidati: (1) break dal `for tipo` in `_loop_invio_marce:1565`, (2) break dal `while` interno di `_loop_invio_marce:1641`, (3) break dal `while tentativi_ciclo` in `RaccoltaTask.run:1857`. Bug precedente: break solo dal for → while interno rientrava → FAU_10 generava ~40 detection/tick. |
| Raccolta No Squads — fix scope MAX_TENTATIVI_CICLO | `tasks/raccolta.py:1564-1568` | Rollback del fix errato che usava `MAX_TENTATIVI_CICLO` in `_loop_invio_marce` (NameError — la variabile è locale a `RaccoltaTask.run`). Causava FAU_09/FAU_10 in stato err. Il flag `_raccolta_no_squads` resta True per essere letto dai chiamanti. |
| Raccolta No Squads — check universale | `tasks/raccolta.py:1095-1113` | Check `pin_no_squads` subito dopo verifica apertura maschera (non solo sul retry fallito). Copre caso "maschera aperta ma overlay No Squads visibile" — evita tap MARCIA inutile + rollback. |
| Rifornimento — soglia pomodoro corretta | `config/runtime_overrides.json` (dev+prod) | `soglia_campo_m: 50 → 5`. Con soglia 50M il pomodoro era sempre sotto soglia (deposito tipico 27-33M) → mai selezionato → distribuzione sbilanciata 65% legno / 23% petrolio / 12% pomodoro. Ora round-robin pulito 40/40/20. |
| Dashboard risorse farm | `dashboard/services/stats_reader.py` | Nuova API `get_risorse_farm()` → `RisorseFarm` dataclass con `inviato_per_risorsa`, `provviste_residue`, `spedizioni_oggi`, `quota_max_per_ciclo`, `istanze_detail`, `produzione_per_ora`. Filtro anti-OCR anomalo `_MAX_QTA_SPEDIZIONE=100M` (Issue #16). Override path via `DOOMSDAY_ROOT` env var. |
| Dashboard stats anti-OCR | `dashboard/services/stats_reader.py` | `_MAX_QTA_SPEDIZIONE=100M` filtra spedizioni anomale (es. FAU_10 legno=999M da Issue #16). Senza filtro il totale legno era gonfiato a 1.1B vs 117M reali. |
| Dashboard naming chiaro | `dashboard/services/stats_reader.py` | `quota_max_totale` → `quota_max_per_ciclo` — distingue quota per-ciclo da `spedizioni_oggi` (cumulativo giornaliero). |
| Dashboard fix Issue #18 | `dashboard/services/config_manager.py` | Nuovo `get_merged_config()` che applica `merge_config(global_config, runtime_overrides)`. Route `/ui` ora mostra i valori effettivamente usati dal bot (coerenti col tick successivo). |
| Dashboard layout two-column | `dashboard/templates/index.html` | Rewrite layout: `.page-layout` con main-col + side-col sticky (pannello risorse farm). Sezioni: istanze grid, task flags + globals, cfg 3-col (rifornimento/zaino/allocazione), istanze table, storico. |
| Dashboard API | `dashboard/routers/api_config_overrides.py` | 5 endpoint per sezione (rifornimento/zaino/raccolta/sistema/task) + PATCH singolo task e singola istanza. |
| Dashboard models | `dashboard/models.py` | Nuovi payload Pydantic: `SistemaOverride`, `ZainoOverride`, `AllocazioneOverride` + payload di sezione per le PUT. |
| Dashboard services | `dashboard/services/config_manager.py` | Aggiunto `save_instances_fields()` per update granulare delle istanze da UI. |
| Dashboard partial v2 | `dashboard/app.py` | Partial corretti: `ist-table` editabile 7 colonne, `task-flags-v2` compound (rifornimento mappa/membri, zaino bag/svuota), `inst-grid`, `storico` con filtri istanza/task, `res-totali` + `res-oraria` (placeholder). |
| Dashboard CSS unificato | `dashboard/static/style.css` + `dashboard/templates/base.html` | Unificata palette ambra Share Tech Mono, `page-layout` two-column. Eliminata divergenza `/ui` (standalone ambra) vs `/ui/config` (verde IBM). `base.html`: active home. |
| Layout istanze deprecato | `dashboard/app.py` + `dashboard/templates/index.html` | Rimosso campo `layout` dalla UI istanze (header + partial td + JS). Il campo resta Optional in `models.py` per retrocompat. file esistenti (bot ora usa template matching). |
| Sync prod | `C:\doomsday-engine-prod\dashboard\` | Rimossi manualmente `dashboard_server.py`, `dashboard.html`, `templates/overview.html` (sync_prod.bat copia ma non elimina). |

## Fix e implementazioni sessione 21/04/2026

| Area | File | Dettaglio |
|------|------|-----------|
| Cleanup legacy | `dashboard/` | Eliminati `dashboard_server.py` (stdlib), `dashboard.html` (V5), `templates/overview.html` (orfano post-index.html) |
| Main cleanup | `main.py` | Rimosso import `dashboard.dashboard_server.avvia`, sostituito con log info `uvicorn dashboard.app:app --port 8765` |
| Smoke test | `smoke_test.py` | Target `dashboard.dashboard_server.avvia` → `dashboard.app.app` |
| Template base | `dashboard/templates/base.html:17` | `overview` → `home`, rimosso marker CSS `active=='overview'` orfano |
| Dashboard unificata | `dashboard/templates/index.html` | Nuova single-page V6 (summary + grid + task flags + config form + istanze table + storico) con 6 partial HTMX |
| Dashboard partial | `dashboard/app.py:190-324` | 6 nuovi partial: status-inline, summary, inst-grid, task-flags-v2, ist-table, storico |
| Config truppe | `config/runtime_overrides.json` (dev+prod) | Tutte istanze FAU_01..FAU_10 → `truppe: 0` (FauMorfeus/FAU_00 già 0) |

## Fix e implementazioni sessione 20/04/2026

| Area | File | Dettaglio |
|------|------|-----------|
| Config layering | `config/config_loader.py` | `load_overrides()` + `merge_config()` — dict grezzi, failsafe totale |
| Config layering | `config/config_loader.py` | `build_instance_cfg` +2 righe: `tipologia` da override |
| Wire-up bot | `main.py` | `_OVERRIDES_PATH`, `_GLOBAL_CONFIG_PATH`, `GlobalConfig._from_raw(_merged_raw)` in pre/post-launcher |
| Config file | `config/runtime_overrides.json` | Nuovo file — 12 task flags + 12 istanze override |
| Dashboard | `dashboard/` (22 file) | Rewrite completo: FastAPI+Jinja2+HTMX, dark mode industrial |
| Cleanup | `.gitignore` | Rimosso `runtime.json` (file eliminato) |

## Prossima sessione — priorità

| Priorità | Task | Stato al 21/04/2026 |
|----------|------|---------------------|
| 1 | Issue #14 — Arena START CHALLENGE non visibile su 5 istanze (investigare UI/template) | 🆕 ALTA |
| 2 | Issue #15 — engine_status.json stale writer | 🆕 ALTA |
| 3 | Issue #18 — Dashboard `/ui` merged vs raw (Opzione A: passare merged) | 🆕 MEDIA |
| 4 | Issue #16 — OCR anomalia FAU_10 compila/reali | 🆕 MEDIA |
| 5 | Issue #17 — Storico filtrato (estendere a tutti i task) | 🆕 MEDIA |
| 6 | Issue #3 — Zaino fix scroll/screenshot | ⏳ |
| 7 | RT-18 — completare 3 sub-test scheduling pendenti | ⏳ backlog |

**Stato chiuso nella sessione 21/04/2026:**
- ✅ Cleanup legacy dashboard (3 file eliminati + refactor main.py + smoke_test)
- ✅ Issue #13 Boost `gathered` (validato in ciclo notte 20→21)
- ✅ Dashboard unificata `index.html` + 6 partial HTMX (`/ui/partial/*-v2`)
- ✅ Rifornimento validato prod su 11/11 istanze (68 spedizioni, ~140.7M risorse)

**Stato chiuso nella sessione 20/04/2026:**
- ✅ Issue #1 Rifornimento — validato prod 8 istanze con fix DELAY UI
- ✅ Dashboard V6 rewrite (commit `9773de3`, `7407e2b`, `2b33efc`)
- ✅ Chain override completa: `runtime_overrides.json` → `merge_config` →
  `GlobalConfig._from_raw(merged)` → `build_instance_cfg` → bot

---

## Sessione 19/04/2026 (pomeriggio) — ambiente prod + fix W11-slow

### Setup ambiente produzione separato
- Creato `C:\doomsday-engine-prod\` via robocopy con esclusioni (state/, logs/, data/, .git/, .claude/, debug_task/)
- Creato `runtime.json` prod — tutti task ON tranne rifornimento
- Creato `config/instances.json` prod — 11 istanze (FAU_00..FAU_10), FauMorfeus esclusa
- Creato `release_prod.bat` (release interattivo) e `sync_prod.bat` (sync non-interattivo, nuovo commit)
- Creato `run_prod.bat` con `PYTHONIOENCODING=utf-8`
- `core/mcp_server.py` parametrizzato: `_AUTO_ROOT` derivato da `__file__` + env override `DOOMSDAY_ROOT`/`DOOMSDAY_ISTANZE`

### Test runtime ciclo 1 (19:08:56 → 21:16:11, killed manual)

| Istanza | Durata | Esito | Note |
|---------|--------|-------|------|
| FAU_00 | 10m48s | ✅ | raccolta OK |
| FAU_01 | 8m32s | ✅ | raccolta OK |
| FAU_02 | 10m04s | ✅ | raccolta OK |
| FAU_03 | 7m53s | ❌ | ADB screenshot None dalle 17:44 (ARENA) → tutti task saltati |
| FAU_04 | 8m02s | ❌ | stesso pattern FAU_03 |
| FAU_05 | 17m59s | ✅ | raccolta OK, slow WiFi loading |
| FAU_06 | 8m30s | ❌ | gate HOME fallito → raccolta saltata |
| FAU_07 | 7m28s | ❌ | gate HOME fallito → raccolta saltata |
| FAU_08 | 15m38s | 🟡 | 3/4 squadre, 4° invio 3× retry "No Squads" non riconosciuto |
| FAU_09 | 12m11s | 🟡 | truppe=60000 ignorate (bug config_loader) |
| FAU_10 | (killed) | ❌ | bloccata su arena oltre 6 min, intervento manuale |

**Fallimenti**: 5/11 completi + 2 parziali. Tasso successo 27%. Necessità fix strutturali.

### Fix applicati (11 commit)

| Commit | Cat. | Fix | File |
|--------|------|-----|------|
| `9ba08a0` | Bug | RACCOLTA_TRUPPE letto via `ctx.config.get("truppe", ...)` (standard per-istanza) | `tasks/raccolta.py` |
| `624ba7a` | Resilience F1a | `vai_in_home` early abort su 3 screenshot None consecutivi (ADB unhealthy) | `core/navigator.py` |
| `1d1b4eb` | Resilience F1b | `adb kill-server`/`start-server` a inizio `avvia_istanza` (reset socket frame grabber) | `core/launcher.py` |
| `3c959cf` | Resilience F2 | Hard timeout globale arena 300s con log `run.errore` | `tasks/arena.py` |
| `701f7bd` | Bug F3 | Rilevamento `pin_no_squads` in `_esegui_marcia` → uscita immediata da `_loop_invio_marce` | `tasks/raccolta.py` |
| `9c1dfb4` | Tuning F4+F5+F7 | `delay_carica_iniz_s` 45→60, stabilizzazione HOME 30→60s, `wait_after_action` 1.5→2.0, `wait_after_overlay` 2.0→2.5 | `config/global_config.json`, `core/launcher.py`, `core/navigator.py` |
| `05d6952` | Perf B1 | Polling attivo post-launch: `t_min=15s` bloccanti + polling 2s fino a `delay_carica_iniz_s`, skip attesa residua su HOME/MAP | `core/launcher.py` |
| `bba45f0` | Perf F-A | `AdaptiveTiming` MVP: sliding window 10 samples, p90*1.5+10s, clamp [base/2, base]. Integrato su `boot_android_s` | `core/adaptive_timing.py` (nuovo), `core/launcher.py` |
| `5f5f4d9` | Tuning Fase 1 | 10 delay pre-match aumentati (raccolta, alleanza, zaino, messaggi) | 4 task files |
| `c3cc26f` | Tuning Fase 2 | `attendi_template` poll 0.5→0.7s + nuovo param `initial_delay` (default 0) | `shared/ui_helpers.py` |
| `a8ea422` | Reliability Fase 3 | `InstanceState.save()` atomica: tmp + `os.fsync` + `os.replace`. Evita corruzione su crash | `core/state.py` |

### Issues risolti

| # | Nome | Fix |
|---|------|-----|
| ADB screenshot None cascata | F1a + F1b |
| Arena hang indefinito | F2 |
| No Squads non rilevato | F3 |
| RACCOLTA_TRUPPE non letto | `9ba08a0` |
| State file corruttibile su kill | Fase 3 atomic save |
| `mcp_server.py` ROOT hardcoded | auto-detect + env override |

### Issues mitigati (non risolti)

| # | Nome | Stato |
|---|------|-------|
| #11 | Stabilizzazione HOME FAU_01/02 | Mitigato (F5 window 30→60s) |
| #12 | Stabilizzazione HOME timeout | Mitigato (stessa F5) |
| Performance boot istanze | Adaptive timing + polling attivo |

### Issues aperti nuovi

| # | Nome | Priorità |
|---|------|----------|
| `radar_tool/templates/` mancante | BASSA (workaround: radar_census saltato per cooldown) |
| Race buffer stdout ultima istanza | BASSA (cosmetico) |

### Test notturno 18/04/2026 — 3 cicli sequenziali FAU_00/01/02

- **FAU_00:** 5/5 squadre inviate in ciclo 2 (09:03). Cicli 1 e 3 correttamente skippati (slot pieni). OCR iniziale letto "7/5" al ciclo 1 — risolto da sanity check (d'ora in poi skip conservativo)
- **FAU_01:** 3 squadre inviate totali (1+1+1). Pattern "tipo NON selezionato" con score 0.19-0.23 ricorrente, 3 abort con CERCA fallita. Funziona solo al secondo tentativo dopo reset pannello
- **FAU_02:** 0 squadre inviate in 3 cicli. Tutti tentativi abortiti per VERIFICA tipo score 0.05-0.23. Ciclo 3: `vai_in_mappa fallito` → task FAIL
- **Conferma Issue #9:** il bug VERIFICA tipo score basso si presenta anche in modalità sequenziale (NON è parallelismo). Pattern identico tra FAU_01/FAU_02, assente su FAU_00
- **[RIALLINEA] funzionante:** FAU_01 1→3, FAU_02 3→2 post-rollback via OCR HOME
- **Blacklist globale funzionante:** crescita 1→3 nodi condivisi tra istanze

---

## MCP Monitor — Comandi di riferimento

Il MCP server `doomsday-monitor` è configurato in `.claude/mcp_servers.json`
e viene caricato automaticamente da Claude Code all'avvio di VSCode.

### Analisi ciclo completo
Ultime N righe del log JSONL di una istanza (o bot.log).

### Workflow monitoraggio durante esecuzione
1. Avvia motore in PS: `python main.py --tick-sleep 300`
2. In Claude Code chiedi: `anomalie_live` ogni 5 minuti
3. Se anomalia: `istanza_anomalie FAU_01` per dettaglio
4. Fine ciclo: `ciclo_stato` per summary completo
5. Problema raccolta: `istanza_raccolta FAU_01` per analisi

---

## Fix applicati in sessione 17/04/2026

| Fix | File | Dettaglio |
|-----|------|-----------|
| attendi_home() loop BACK | `core/launcher.py` | Loop BACK+polling invece di sequenza rigida — gestisce banner multipli |
| chiudi_istanza() post-tick | `main.py` | Chiusura MuMu dopo ogni tick, non solo a Ctrl+C |
| _TASK_SETUP priorità | `main.py` | Riallineamento completo a ROADMAP — erano completamente invertite |
| Regole anti-disallineamento | `.claude/CLAUDE.md` | Sezione vincolante: _TASK_SETUP ↔ ROADMAP sempre allineati |
| avvia_player() | `core/launcher.py` | Avvio automatico MuMuNxMain.exe — rileva processo esistente, polling 60s |
| Note W10/W11 | `.claude/CLAUDE.md` | W10: player non necessario; W11: player deve essere avviato |
| Lock globale screencap | `core/device.py` | _screencap_global_lock serializza screencap tra istanze diverse |
| Porte istanze | `config/instances.json` | Tutte le porte corrette con formula 16384 + indice×32 |
| task_abilitato 2 livelli | `config/config_loader.py` | rifornimento = task_rifornimento AND (mappa OR membri) |
| should_run rifornimento | `tasks/rifornimento.py` | Usa task_abilitato("rifornimento") come tutti gli altri task |
| Arena timeout | `tasks/arena.py` | _MAX_BATTAGLIA_S 15→52 (delay 8s + poll = 60s totali) |
| _istanza_chiusa guard | `main.py` | Evita doppia chiudi_istanza() su shutdown se già chiusa post-tick |
| Modalità sequenziale | `main.py` | Ciclo FAU_00→FAU_01→FAU_02→sleep 30min→ripeti. _thread_istanza esegue un solo tick per chiamata. main() gestisce il loop ciclo |
| report.py | NUOVO | Script autonomo analisi log notturni. Genera HTML con statistiche per N istanze: marce, task, errori, screenshot None, launcher |
| instances.json produzione | `config/instances.json` | Solo FAU_00/01/02 abilitate, tutte le altre abilitata=false |
| Lock screencap ripristinato | `core/device.py` | Rimosso lock globale, ripristinato lock per serial. Modalità sequenziale rende il lock globale non necessario |

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

### Scheduling task (`config/task_setup.json` ↔ `main.py::_TASK_SETUP`)

> Fonte di verità: `config/task_setup.json`. Aggiornato 02/05/2026 (WU90+WU91).
> I primi 3 task sono **sempre** Boost → Rifornimento → Raccolta (logica:
> incrementa produzione, verifica slot, occupa slot). Gli altri seguono.

| Pos | Classe | Priority | Interval | Schedule | Note |
|-----|--------|----------|----------|----------|------|
| 1 | BoostTask | 5 | — | periodic | always-run con BoostState guard (incrementa produzione) |
| 2 | RifornimentoTask | 10 | — | always | guard pre-condizioni (soglie risorse, slot disponibili) |
| 3 | RaccoltaTask | 15 | — | always | always-run se slot liberi (occupa slot squadre) |
| 4 | TruppeTask | 18 | 4h | periodic | addestra 4 caserme libere (skip se 4/4) |
| 5 | **DonazioneTask** | **20** | **8h** | **periodic** | **02/05 WU90: era always; pickup atteso 24-30 donate/run (cap 30, rigenero 1/20min)** |
| 6 | **MainMissionTask** | **22** | **24h** | **daily** | **02/05 WU91: era periodic 12h; guard `should_run` ora UTC < 20 = skip; recupero ricompense fine-giornata** |
| 7 | ZainoTask | 25 | 168h | periodic | |
| 8 | VipTask | 30 | 24h | daily | |
| 9 | AlleanzaTask | 35 | 4h | periodic | |
| 10 | MessaggiTask | 40 | 4h | periodic | |
| 11 | ArenaTask | 50 | 24h | daily | |
| 12 | ArenaMercatoTask | 60 | 24h | daily | |
| 13 | DistrictShowdownTask | 70 | — | always | guard finestre evento |
| 14 | StoreTask | 80 | 8h | periodic | |
| 15 | RadarTask | 90 | 12h | periodic | |
| 16 | RadarCensusTask | 100 | 12h | periodic | disabilitato default |
| 17 | RaccoltaChiusuraTask | 200 | — | always | chiusura tick (Issue #62) |

**Runtime swap RaccoltaFastTask** (WU57): se `tipologia == "raccolta_fast"`,
`main.py::_thread_istanza` sostituisce `RaccoltaTask` con `RaccoltaFastTask`
in fase di registrazione, preservando priority/interval/schedule.

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

---

## Struttura bot — file e responsabilità

Mappa completa del codice sorgente con ruolo di ciascun modulo. Serve come
guida per orientarsi nel repo e capire dove intervenire per ogni tipo di modifica.

### Root del progetto (`C:\doomsday-engine` dev / `C:\doomsday-engine-prod` prod)

#### File principali

| File | Tipo | Descrizione |
|------|:--:|-------------|
| `main.py` | core | Entry point bot — loop ciclico sequenziale 12 istanze. |
| `CLAUDE.md` | docs | Index del progetto, redirect a `.claude/CLAUDE.md` per istruzioni operative. |
| `ROADMAP.md` | docs | Fonte di verità issues + architettura + struttura. **Questo file.** |
| `engine_status.json` | runtime | Snapshot live stato bot (scritto da status_writer ogni N secondi). |
| `last_checkpoint.json` | runtime | Checkpoint `--resume` (istanza+ciclo). |
| `runtime.json` | runtime | Lock file processo bot attivo (PID). |
| `bot.log` | log | Log testuale globale (corrente). |
| `bot.log.bak` | log | Log backup (pre-rotazione, conservato 1 livello). |
| `bot_live.log` | log | Log dashboard avvio uvicorn. |

#### Launcher Windows (.bat)

| File | Descrizione |
|------|-------------|
| `run.bat` | Launcher dev base (legacy). |
| `run_prod.bat` | **Launcher principale produzione** — `cd C:\doomsday-engine-prod + DOOMSDAY_ROOT + main.py --tick-sleep 60 --no-dashboard --use-runtime --resume`. |
| `run_dashboard_prod.bat` | Launcher dashboard FastAPI/uvicorn prod (porta 8765). |
| `task.bat` | Helper esecuzione task singolo. |
| `reset.bat` | Reset state (utility manuale). |
| `fix_inplace_rifornimento.bat` | Fix one-shot legacy (storico). |
| `release_pytest_fix5_16042026.bat` | Release storico (storico). |

#### Cartelle codice/dati

| Cartella | Descrizione |
|----------|-------------|
| `core/` | Infrastruttura motore (orchestrator, task, telemetry, launcher, navigator, device, state, scheduler, logger, adaptive_timing). |
| `tasks/` | Implementazione 15 task (rifornimento, raccolta, donazione, district_showdown, arena, vip, zaino, alleanza, messaggi, boost, store, radar, ecc.). |
| `shared/` | Utility condivise (template_matcher, ocr_helpers, ui_helpers, rifornimento_base, morfeus_state, banner_catalog). |
| `dashboard/` | FastAPI web dashboard (app.py, models, routers/, services/, static/, templates/). |
| `tools/` | CLI utility — backfill_telemetry.py, build_rollup.py, capture_invio_mask.py. |
| `monitor/` | MCP server stdio per Claude Code (analyzer.py + mcp_server.py). |
| `radar_tool/` | Sottomodulo classificazione nodi mappa via ML (currently disabled). |
| `radar_archive/` | Archivio dataset radar (storico). |
| `config/` | Configurazione (config_loader, config, global_config.json, runtime_overrides.json, instances.json, task_setup.json). |
| `data/` | Dati persistenti (blacklist_fuori, storico_farm, morfeus_state, telemetry/). |
| `state/` | Stato per-istanza (FAU_XX.json + FAU_XX_timing.json). |
| `logs/` | Log JSONL per-istanza (FAU_XX.jsonl + .bak). |
| `templates/` | Template PNG per matching UI (130+ file in `pin/`). |
| `tests/` | Suite pytest (`unit/`, `tasks/`, `fixtures/`). |
| `temp_screen/` | Screenshot temporanei (output `tools/capture_invio_mask.py`). |
| `debug_task/` | Output debug task (storico, non versionato). |
| `.claude/` | Istruzioni operative Claude Code (CLAUDE.md, mcp_servers.json, settings.json). |

#### File legacy / orfani (candidati eliminazione — Issue #21)

| File | Stato |
|------|-------|
| `calibra_slot_ocr.py` | utility OCR slot calibration (storico) |
| `cd` | file vuoto (orfano) |
| `gitignore` | senza `.` davanti (errato — dovrebbe essere `.gitignore`) |
| `istruzioni di lancio.txt` | nota testo libero (storico) |
| `main.py.bak` | backup (storico) |
| `ocr_helpers_2e8ab2f.py` | hash commit antico (storico) |
| `pytest_output.txt` | output test (storico) |
| `python` | file vuoto (orfano) |
| `report.html`, `report.py` | report storico HTML/python |
| `reset_schedule.py` | utility one-shot (storico) |
| `rifornimento_mappa.py` | V5 legacy (mai usato in V6 — da eliminare) |
| `run_task.py` | runner task isolato V5-style |
| `smoke_test.py` | test pre-pytest |
| `tmp_clipboard.txt` | clipboard temp |
| `totale` | file vuoto |
| `test_*.py` (root) | test obsoleti (rimpiazzati da `tests/unit/test_*.py`) |

> Nota: la rimozione richiede sessione dedicata (Issue #21) per evitare break.

### Entry point

| File | Descrizione |
|------|-------------|
| `main.py` | Entry point del bot. Loop ciclico sequenziale su 12 istanze MuMu. Responsabilità: caricamento `task_setup.json`, gestione resume checkpoint, cleanup orfani MuMu, signal handling SIGINT/SIGTERM, status writer thread. Funzione chiave `_thread_istanza()` — un solo tick per chiamata con context rebuild post-HOME. Hot-check flag `abilitata` prima di ogni istanza (Issue #39). |
| `run.bat`, `run_dev.bat`, `run_prod.bat` | Launcher Windows per dev/prod. Path assoluti espliciti (no `%~dp0`). Prod: `cd C:\doomsday-engine-prod + DOOMSDAY_ROOT=... + main.py --tick-sleep 60 --no-dashboard --use-runtime --resume`. |
| `run_dashboard_dev.bat`, `run_dashboard_prod.bat` | Launcher dashboard FastAPI+uvicorn. Dev porta 8766, prod porta 8765. |
| `sync_prod.bat` | Rilascio dev→prod: sincronizza codice, `main.py`, `task_setup.json`, `templates/`, `dashboard/`, launcher prod. Blacklist: `instances.json`, `runtime_overrides.json`, `global_config.json`, `state/`, `logs/`. |
| `reset.bat`, `report.py`, `reset_schedule.py` | Utility CLI una-tantum per reset state/schedule. |

### `config/` — configurazione

| File | Descrizione |
|------|-------------|
| `config_loader.py` | Caricamento + merge configurazione. `load_global()`, `load_overrides()`, `merge_config()`, `build_instance_cfg()`. Dataclass `GlobalConfig` (task flags, soglie, coordinate). `_InstanceCfg.task_abilitato(nome)` — API che ogni task chiama in `should_run()`. Mappa task_name → bool flag. |
| `config.py` | Modulo import-friendly con tipi e enumerazioni condivise. |
| `global_config.json` | Config base (task flags default, soglie, rifornimento_comune, rifornimento_mappa, rifugio, zaino, raccolta/allocazione, sistema/mumu). Read-only dal bot, modificato solo via dashboard. |
| `runtime_overrides.json` | Overrides dinamici per-istanza e globali. Hot-reload a ogni tick. Struttura: `globali.{task, rifornimento, rifornimento_comune, zaino, raccolta, sistema, rifugio}` + `istanze.{FAU_XX.abilitata/truppe/tipologia/fascia_oraria/max_squadre/layout/livello}`. |
| `instances.json` | Anagrafica fisica istanze MuMu (nome, indice, porta ADB, truppe, layout, livello, profilo). Read-only dal bot. |
| `task_setup.json` | Scheduler: lista task con priority, interval_hours, schedule (always/periodic/daily). Priority ascending = esecuzione prima. Hot-reload per-istanza (letto a ogni `_thread_istanza`, no restart richiesto per cambi schedule/priority). |

### `core/` — infrastruttura motore

| File | Descrizione |
|------|-------------|
| `orchestrator.py` | Registra task, ordina per priority, gestisce il tick: per ogni task → `should_run()` check → `e_dovuto()` schedule check → gate HOME pre-task → `run()` → aggiornamento schedule. **WU38**: hook automatico TaskTelemetry per ogni run (start/finish/record), include cycle da ctx.extras + ADB cascade tagging. |
| `task.py` | Classi base V6: `Task` (ABC con `name()/should_run()/run()` astratti), `TaskContext` (device, navigator, matcher, config, state, log_msg), `TaskResult` (success, message, data). |
| `telemetry.py` | **WU38-48 (Issue #53/49)** — pipeline telemetria. `TaskTelemetry` dataclass + writer `record()` + reader `iter_events()/iter_events_range()` + rollup engine (`compute_rollup`, `save_rollup`, `cleanup_old_rollups`) + live writer (`compute_live_24h`, `live_writer_loop`) + backfill (`backfill_from_logs`) + anomaly detector (`detect_anomaly_patterns`). **WU46/48 cicli persistenti**: `record_cicle_start/end()`, `record_istanza_tick_start/end()`, `load_cicli()`, `backfill_cicli_from_botlog()`, `renumber_cicli_globally()`. Numerazione globale crescente + `run_id` per evitare duplicati cross-restart. Storage `data/telemetry/{events,rollup,cicli.json,live.json}`. Self-test integrato. |
| `launcher.py` | Avvio/chiusura istanze MuMu via `MuMuManager.exe` CLI. `avvia_player()` (MuMuNxMain.exe Win11), `avvia_istanza()` (launch + adb connect + `_avvia_gioco()` con am start + monkey + foreground check, Issue #46), `attendi_home()` (polling schermata + monkey recovery, Issue #46), `reset_istanza()`, `chiudi_istanza()`. |
| `device.py` | Astrazione ADB per singola istanza. `AdbDevice(host, port, name)`: screenshot (Screenshot con `.frame` ndarray), tap, back, swipe. `Screenshot.match_template()` usato da matcher. `@dataclass MatchResult(found, score, cx, cy)`. |
| `navigator.py` | Navigazione inter-schermata game. `schermata_corrente()` (Screen.HOME/MAP/UNKNOWN via template match), `vai_in_home()`, `vai_in_mappa()`, `tap_barra(ctx, voce)` (barra inferiore: campaign/alliance/hero/bag/beast). |
| `state.py` | Stato persistente per-istanza. `InstanceState(path)` save/load atomico tmp+fsync+os.replace. Sottocampi: rifornimento, daily_tasks, metrics, schedule, boost, vip, arena. **WU34**: `RifornimentoState` esteso con `inviato_lordo_oggi`, `tassa_oggi`, `tassa_pct_avg` (running average), `eta_rientro_ultima` (sync raccolta-rifornimento Issue #64). **WU47**: `chiudi_sessione_e_calcola()` propaga `produzione_oraria` calcolata a `metrics.aggiorna_risorse()` se `durata_sec≥300s` (Issue #47 — pannello produzione/ora ora popolato). |
| `scheduler.py` | Gestione interval/daily/always per-task con restart-safe restore da disco. |
| `logger.py` | Logger strutturato `ctx.log_msg(msg)`. Output duale: bot.log (testuale) + logs/FAU_XX.jsonl (JSONL machine-readable). Rotazione automatica a 5MB → `.jsonl.1`. |
| `adaptive_timing.py` | Timing per-istanza appreso dall'esperienza (es. `boot_android_s`). `get(key, fallback)` + `record(key, value)`. Salvato in `state/FAU_XX_timing.json`. |

### `tasks/` — implementazione task

| File | Descrizione | Priority | Schedule |
|------|-------------|:--:|:--:|
| `raccolta.py` | Invio squadre su nodi risorse. OCR slot squadre X/Y, blacklist nodi fuori-territorio, allocazione risorse, gestione fallimenti (tipo_bloccato/skip_neutro/marcia_fallita). Sempre attivo. | 110 | always |
| `rifornimento.py` | Invio risorse a FauMorfeus via mappa (tap castello) o membri (lista alleanza). Soglie per risorsa, quota giornaliera osservata (~21-69M per-istanza in base al livello). | 100 | always |
| `donazione.py` | Donazione tech alleanza marcata "Marked!". HOME→alliance→Technology→scan pin_marked→tap loop donate (max 30). Back x3 su research/non_riconosciuto/not_found. | 105 | always |
| `district_showdown.py` | Evento weekend Gold Dice. 5 fasi: (1) loop monitoring Auto Roll + interruzioni, (2) District Foray Collect All, (3) Influence Rewards claim chiavi, (4) Achievement Rewards Claim All, (5) Fund Raid select + loop attack con OCR counter. Gate temporale UTC: intero task attivo **Ven 00:00 → Lun 00:00 UTC** (3gg esatti); Fund Raid attivo solo **Dom 20:00 → Lun 00:00 UTC** (ultime 4h). Navigatore stato-aware `_torna_a_mappa_ds` con rientro automatico se uscito. | 107 | always |
| `zaino.py` | Modalità `bag` (template match per risorse + tap) o `svuota` (USE MAX sidebar). | 70 | periodic 168h |
| `vip.py` | Claim giornaliero VIP (cassaforte + free). | 10 | daily 24h |
| `alleanza.py` | Help alleanza (tap_barra + scroll + click). | 30 | periodic 4h |
| `messaggi.py` | Claim messaggi alleanza/sistema. | 20 | periodic 4h |
| `arena.py` | 5 sfide giornaliere. Skip popup primo accesso + categoria settimanale. | 50 | daily 24h |
| `arena_mercato.py` | Acquisti mercato arena (pack360). | 60 | daily 24h |
| `boost.py` | Usa speedup 8h/1d per gathered/construction/research. | 5 | periodic 0h |
| `store.py` | Acquisti VIP Store + Mercante Diretto + Free Refresh. | 40 | periodic 8h |
| `radar.py` | Tap badge radar rosso + chiusura pallini. | 80 | periodic 12h |
| `radar_census.py` | Scan mappa per classificazione nodi (currently disabled, templates mancanti). | 90 | periodic 12h |
| `conftest.py` | Fixture pytest condivise per test dei task. | — | — |

### `shared/` — utility condivise

| File | Descrizione |
|------|-------------|
| `template_matcher.py` | Wrapper cv2.matchTemplate + caching template + soglie default per-template. `find_one/find_all/exists/score`. Classe `FakeMatcher` per test. |
| `ocr_helpers.py` | Wrapper pytesseract. `ocr_risorse()` (OCR 4 valori risorse HOME), `ocr_slot()` (contatore squadre X/Y), `ocr_text()`, sanitize numeri ("5M"/"1.2B"). |
| `ui_helpers.py` | Helpers UI: pulse tap, swipe scroll, wait_for_template, back_x_volte, ecc. |
| `rifornimento_base.py` | Logica comune rifornimento (centratura mappa, resource_supply, compila_e_invia). **WU39**: nuova `OCR_DAILY_RECV_LIMIT (547,146,666,173)` + `leggi_daily_recv_limit()` (cap intake destinatario). |
| `morfeus_state.py` | **WU39 (NEW)** — storage globale destinatario rifornimento. Schema `{daily_recv_limit, ts, letto_da, tassa_pct}` in `data/morfeus_state.json` (atomic write). Last-write-wins: tutte le istanze inviano alla stessa Morfeus, vedono lo stesso valore. API `save()`, `load()`. Failsafe (eccezioni silenziose). |
| `banner_catalog.py` | Catalog banner riconosciuti dal navigator + dismiss action mirate (auto_collect_afk_banner, exit_game_dialog, banner_eventi_laterale, ecc.). Issue #54. |

### `dashboard/` — FastAPI web dashboard

| File | Descrizione |
|------|-------------|
| `app.py` | Entry point FastAPI + HTMX. Monta router API + servizi statici + template Jinja2. Endpoint `/ui` (home dashboard), `/ui/partial/*` (fragments HTMX: task-flags-v2, ist-table, storico, res-totali, status). Include `partial_task_flags_v2()` con ORDER + COMPOUND (rifornimento mappa/membri, zaino bag/svuota). |
| `models.py` | Modelli Pydantic. `TaskFlags`, `RuntimeOverrides`, `IstanzaOverride`, `RifornimentoOverride`, `ZainoOverride`, `RaccoltaOverride`, `SistemaOverride`. Validazione + serializzazione `exclude_unset=True`. |
| `routers/api_config_global.py` | GET/PUT `/api/config/globals` per task flags + sistema (merge incrementale `exclude_unset`, Issue #35). |
| `routers/api_config_overrides.py` | PUT `/api/config/rifornimento`, `/api/config/zaino`, `/api/config/raccolta`. PATCH `/api/config/overrides/task/{name}` (toggle), `/api/config/rifornimento-mode/{sub}`, `/api/config/zaino-mode/{sub}`. Hot-reload al prossimo tick. |
| `routers/api_log.py` | Tail log per-istanza (bot.log + FAU_XX.jsonl). |
| `routers/api_stats.py` | Stats aggregate: spedizioni oggi, produzione/ora, totali risorse, provviste. |
| `routers/api_status.py` | engine_status.json live: stato istanze, tick corrente, uptime. |
| `services/config_manager.py` | Layer di accesso config+overrides. `get_global_config()`, `get_overrides()`, `get_merged_config()` (UI vede valori reali bot, Issue #18), `save_overrides()`. Usa `DOOMSDAY_ROOT` env var per coerenza dev/prod (Issue #38). |
| `services/stats_reader.py` | Read-only stats da state/engine_status. `get_engine_status()`, `get_all_stats()`, `get_storico()`, `get_risorse_farm()` (aggregato farm). Filtro OCR anomalie >100M per spedizione (Issue #16/#27). **WU34/35**: `MorfeusState`, `RifornimentoIstanza` esteso con `provviste_residue_netta` + `tassa_pct_avg`. **WU39**: `_load_morfeus_state()` legge `data/morfeus_state.json`. **WU45**: fallback automatico su `data/storico_farm.json` quando `state.rifornimento` è vuoto (race post-restart `_controlla_reset` Issue #46). |
| `services/log_reader.py` | Tail efficiente log file con offset tracking. |
| `services/telemetry_reader.py` | **WU37+42+46+48 (Issue #53/49)** — reader API dual-source per dashboard. `get_task_kpi_24h()`, `get_health_24h()`, `get_ciclo_status()`, `get_storico_cicli(n)`, `get_trend_7gg()`. Source primaria: `data/telemetry/{live.json,cicli.json}` (precomputato). Fallback automatico al log scan WU37 (rolling 24h su `logs/FAU_*.jsonl` + `bot.log`). Cache TTL 30s. Pattern detector (WU44) integrato in health. **WU48**: `CicloStorico` con `aborted` flag per cicli interrotti da restart bot. |
| `templates/*.html` | Jinja2 template: `index.html` (dashboard principale), `config_global.html` (form parametri globali), `config_overrides.html` (form rifornimento/zaino). |
| `static/style.css`, `static/app.js` | CSS palette ambra + HTMX bootstrap. |

### `tools/` — utility CLI

| File | Descrizione |
|------|-------------|
| `build_rollup.py` | **WU40** — genera `data/telemetry/rollup/rollup_<date>.json` da events. Args: `--date {today,yesterday,YYYY-MM-DD}` `--range N` (ultimi N giorni) `--cleanup N` (retention sweep). |
| `backfill_telemetry.py` | **WU43** — backfill retroattivo TaskTelemetry da `logs/FAU_*.jsonl`. Idempotente (dedup su ts_start+task+instance). Args: `--days N` `--since ISO` `--until ISO` `--rebuild-rollup`. Inferisce anomalies per ADB UNHEALTHY + eccezioni generiche. |
| `capture_invio_mask.py` | Monitor screencap maschera invio rifornimento. Polling-based: tail logs JSONL, su `Rifornimento: RESOURCE SUPPLY trovato` (max-age 15s) attende 1.7s e cattura via ADB exec-out screencap. Output `temp_screen/maschera_<istanza>_<ts>.png`. Usato per calibrazione coordinate OCR (es. WU39 Daily Receiving Limit). |

### `monitor/` — MCP server per Claude Code

| File | Descrizione |
|------|-------------|
| `mcp_server.py` | MCP server stdio per analisi log live. Tool: `ciclo_stato`, `anomalie_live`, `istanza_anomalie`, `istanza_raccolta`, `istanza_launcher`, `log_tail`. |
| `analyzer.py` | Parser + pattern anomalie (ERROR/WARN) da bot.log e jsonl. |

### `radar_tool/` — sottomodulo radar census

Progetto separato per classificazione nodi mappa via ML. Usato da `radar_census.py` (attualmente disabilitato, templates mancanti). `detector.py`, `classifier.py`, `labeler.py`, `scan.py`, `train.py`, `template_builder.py`.

### `data/`, `state/`, `logs/`, `templates/`

| Cartella | Descrizione |
|----------|-------------|
| `data/blacklist_fuori_globale.json` | Lista nodi raccolta fuori-territorio (globale tra istanze). |
| `data/storico_farm.json` | Storico giornaliero produzione per istanza (90gg retention). |
| `data/morfeus_state.json` | **WU39** — stato globale destinatario rifornimento (Daily Receiving Limit FauMorfeus). Atomic write, last-write-wins. |
| `data/telemetry/events/events_<date>.jsonl` | **WU38** — eventi TaskTelemetry append-only (1 riga per esecuzione task). Retention 30gg. |
| `data/telemetry/rollup/rollup_<date>.json` | **WU40** — rollup giornaliero (totals/per_task/per_instance/anomalies/patterns_detected). Retention 365gg. |
| `data/telemetry/live.json` | **WU41** — sliding window 24h. Aggiornato dal LiveTelemetry thread ogni 60s. Source primaria della dashboard. |
| `data/telemetry/cicli.json` | **WU46/48** — cicli completi + per-istanza con durate. Numerazione globale crescente, `run_id` per discriminare restart. Retention ultimi 100. Aggiornato in tempo reale dal bot via hooks main.py. |
| `state/FAU_XX.json` | Stato persistente per-istanza (rifornimento, daily_tasks, schedule, metrics). Atomic save. |
| `state/FAU_XX_timing.json` | Timing appresi per-istanza (boot_android_s, etc.). |
| `logs/FAU_XX.jsonl` | Log strutturato per-istanza (1 JSON per riga). Ruotato `.bak` a ogni avvio. |
| `logs/bot.log` | Log testuale globale (MAIN + per-istanza). |
| `templates/pin/*.png` | Template PNG per matching UI (130+ file). |
| `engine_status.json` | Snapshot live stato bot (scritto ogni N secondi da status_writer). |
| `last_checkpoint.json` | Checkpoint per resume (scritto prima di ogni istanza). |

### `.claude/` — istruzioni Claude Code

| File | Descrizione |
|------|-------------|
| `CLAUDE.md` | Istruzioni operative complete (regole codice, architettura, issues tracking). Tracked in git. |
| `SESSION.md` | Handoff di sessione tra browser e VS Code. Local-only (gitignored). |
| `mcp_servers.json` | Configurazione MCP server (monitor). |
| `settings.json` | Settings Claude Code (permissions, etc.). Tracked. |
| `settings.local.json` | Settings locali (gitignored). |
