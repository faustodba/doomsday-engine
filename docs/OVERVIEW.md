# Doomsday Engine V6 — Overview architetturale

**Documento di riferimento** per comprendere cosa fa il progetto, come è
strutturato e quali funzionalità esegue ogni componente. Per dettagli
operativi (sessioni di lavoro, fix recenti, issue tracking) vedi
[ROADMAP.md](../ROADMAP.md).

---

## 1. Cosa fa

Doomsday Engine V6 è un **bot farm** Python che automatizza un gioco
mobile (genere strategy) eseguito su 12 istanze MuMuPlayer in parallelo
(processate sequenzialmente). Esegue ciclicamente un set di task per
ognuna delle istanze configurate:

- raccolta automatica risorse da nodi sulla mappa
- invio risorse al rifugio destinatario (FauMorfeus, master)
- attivazione boost di gathering speed
- combattimento arena giornaliera (5 sfide/die)
- raccolta ricompense alleanza, messaggi, missioni, VIP
- addestramento truppe nelle 4 caserme
- acquisti store / arena mercato
- partecipazione eventi (District Showdown weekend)

Tutta l'interazione col gioco avviene via **ADB** + **template matching
OpenCV** + **OCR Tesseract**. Nessuna API ufficiale. Il bot è
completamente headless e idempotente: ogni tick ripristina HOME e
verifica lo stato corrente prima di operare.

---

## 2. Architettura

```
┌─────────────────────────────────────────────────────────────┐
│                       main.py                               │
│  Orchestratore principale: scheduler tick + thread istanza  │
└──────────┬──────────────────────────────────────────────────┘
           │
   ┌───────┼───────────────────────────────┬──────────────┐
   │       │                               │              │
   ▼       ▼                               ▼              ▼
┌─────┐  ┌─────────────────┐  ┌──────────────────┐  ┌──────────┐
│core/│  │tasks/  (17 task) │  │ shared/         │  │ data/    │
│     │  │                 │  │ debug_buffer    │  │ telemetry│
│orch │  │ Boost           │  │ ocr_helpers     │  │ events/  │
│sched│  │ Rifornimento    │  │ template_match  │  │ rollup/  │
│nav  │  │ Raccolta        │  │ ui_helpers      │  │ live.json│
│dev  │  │ Arena           │  │ banner_catalog  │  │          │
│match│  │ ...             │  │ instance_meta   │  │ state/   │
└─────┘  └─────────────────┘  └──────────────────┘  └──────────┘
                                                          │
                                                          ▼
                                            ┌──────────────────────┐
                                            │  dashboard/  (FastAPI)│
                                            │  /ui  /telemetria     │
                                            │  /predictor  /storico │
                                            │  /config/global       │
                                            └──────────────────────┘
```

### 2.1 Componenti per livello

| Livello | Componente | Funzione |
|---------|------------|----------|
| Entry point | [`main.py`](../main.py) | Loop principale: per ogni tick, processa istanze sequenzialmente |
| Core | [`core/`](../core/) | Orchestrator, scheduler, navigator, device, launcher, telemetry |
| Task | [`tasks/`](../tasks/) | 17 implementazioni `Task` interfaccia uniforme `run(ctx)→TaskResult` |
| Shared | [`shared/`](../shared/) | Helper: OCR, template matcher, banner catalog, debug buffer |
| Config | [`config/`](../config/) | `instances.json`, `global_config.json`, `runtime_overrides.json`, `task_setup.json` |
| State | `state/` (runtime) | Stato per-istanza persistito (raccolta, rifornimento, schedule, metrics) |
| Telemetria | `data/telemetry/` | Events JSONL, rollup giornalieri, cicli storia, predictor decisions |
| Dashboard | [`dashboard/`](../dashboard/) | FastAPI + Jinja2 + HTMX, monitoring + config + analytics |
| Tool CLI | [`tools/`](../tools/) | Analisi standalone: telemetria, capacità nodi, predictor backtest |

---

## 3. Pipeline esecuzione bot

```
Boot bot (main.py)
  ├── Leggi config
  ├── Filter istanze abilitate (instances.json + runtime_overrides)
  ├── Cleanup processi orfani (Python+MuMu da kill non clean)
  └── Lancia _scheduler_tick() loop

Per ogni TICK (ogni `tick_sleep_min` minuti):
  Apri nuovo ciclo (numero globale crescente)
  Per ogni ISTANZA in ordine (adaptive scheduler se abilitato):
     Thread _thread_istanza(istanza):
       1. inizia_tick(metrics buffer in-memory)
       2. avvia_istanza(MuMu boot via MuMuManager)
       3. attendi_home (loop polling + dismiss banners + settings cleanup)
       4. ── core/troops_reader: snapshot Total Squads (1×/die UTC) ──
       5. Build TaskContext + Orchestrator
       6. Registra task da task_setup.json (filtrati per tipologia istanza)
       7. orc.tick() → esegue ogni task con priority + scheduling
          Per ogni task: should_run() guard → run() → save state
       8. chiudi_tick(persisti metriche + telemetry events + cicli.json)
       9. chiudi_istanza(MuMu shutdown clean)
  Chiudi ciclo (write cicli.json, durata, completato)
  Sleep tick_sleep_s
```

**Scheduling**: sequenziale — una istanza alla volta. Architettura
`max_parallel=1` corrente, parallelismo non implementato per evitare
interferenze ADB/MuMu.

**Resume-safe**: ogni avvio bot ricarica `state/<istanza>.schedule` e
ripristina i timestamp last_run dei task — cycle resilient ai restart.

---

## 4. Componenti core

### 4.1 `core/orchestrator.py`

Esegue task in ordine di **priorità** (numero più basso = prima). Per
ogni `orc.tick(ctx)`:

- itera entry registrate ordinate per `priority`
- per ognuna: `should_run(ctx)` → se True chiama `run(ctx)` con timing
- aggiorna `last_run` (solo se task ok/skip — WU79 evita falsi
  aggiornamenti su fail)
- timing per task in `entry.last_duration_s` → propagato a metrics

### 4.2 `core/scheduler.py` — `Scheduler`

Persistenza dei timestamp last_run per task. Salvato in
`state/<nome>.json::schedule`. Restore-safe: ripristina i timestamp
all'avvio bot. Ogni task registra il proprio schedule via `Wrapper`:

- `schedule_type="always"` → gira ogni tick (guard interno via `should_run`)
- `schedule_type="periodic", interval_hours=N` → gira ogni N ore
- `schedule_type="daily", interval_hours=24` → gira 1×/die

### 4.3 `core/navigator.py` — `GameNavigator`

Astrazione di alto livello sulla UI del gioco:

- `vai_in_home()` — porta l'istanza in HOME stabile (max 8 tentativi)
- `vai_in_mappa()` — switch HOME ↔ MAPPA
- `tap_barra(ctx, "campaign"|"alliance"|"bag"|...)` — match dinamico
  template `pin_<voce>.png` nella barra inferiore + tap su coord
  rilevate (resiste a layout barre con bottoni diversi)
- `schermata_corrente()` — classifica HOME/MAPPA/UNKNOWN via
  template matching su pin sentinel

### 4.4 `core/device.py` — `AdbDevice`

Wrapper ADB: screencap (in-memory via `exec-out` post-WU76),
input tap/swipe/key, foreground app detection. Builds via
`AdbDevice(host, port, name)`. Cascade health check: cascade detection
+ `ADBUnhealthyError` per abort tick (WU24).

### 4.5 `core/launcher.py`

- `avvia_istanza(ist)` — boot MuMu via MuMuManager + monkey foreground
  check + recovery (WU46+WU60)
- `attendi_home(ctx)` — splash detection + dismiss banners loop +
  stabilizzazione HOME (3 poll consecutivi 1s, WU71)
- `chiudi_istanza(ist, porta)` — shutdown clean + cleanup ADB

### 4.6 `core/state.py` — Persistent state

Stato per-istanza in `state/<nome>.json`. Sezioni principali:

- `schedule` — timestamps last_run per task
- `raccolta` — slot, marcia counters, blacklist nodi
- `rifornimento` — provviste, spedizioni_oggi, eta_rientro_ultima,
  cap_invio_iniziale_oggi (WU106), tassa_pct_avg
- `boost` — scadenza_iso del booster gather attivo
- `arena` — sfide_oggi, ts_inizio_sessione, tier corrente
- `metrics` — `*_per_ora` per risorsa (raccolta cumulativa)
- `daily_tasks` — flag boolean per task daily (vip, main_mission, ...)
- `diamanti` — snapshot diamanti

Atomic write tmp+fsync+os.replace. Salvato dopo ogni task tick.

### 4.7 `core/telemetry.py`

Pipeline events JSONL → rollup → KPI. Per ogni task `run()` esegue
emit di un event con: `ts_start, ts_end, duration_s, task, instance,
cycle, success, outcome, msg, output, anomalies, retry_count`.
Storage in `data/telemetry/events/events_YYYY-MM-DD.jsonl`.

Anomaly detector pattern-based legge gli eventi e flagga: cascade ADB
ricorrenti, task timeout, deficit istanza specifica. Pattern detection
usato in dashboard.

### 4.8 `core/istanza_metrics.py`

Buffer in-memory thread-safe per metriche per-istanza per-ciclo.
Schema record JSONL `data/istanza_metrics.jsonl`:

- ts, instance, cycle_id, outcome
- boot_home_s, tick_total_s
- raccolta: invii[] (tipo, livello, cap_nodo, **load_squadra**, eta_marcia_s, ts_invio), attive_pre/post, totali
- rifornimento: invii[] (risorsa, qta_netta, eta_residua_s)
- task_durations_s: dict {task: secondi}

Hook in `main.py::_thread_istanza` (inizia/chiudi tick) +
`tasks/raccolta.py` (aggiungi_invio_raccolta) + `tasks/rifornimento.py`
(aggiungi_invio_rifornimento). Foundation del Skip Predictor.

### 4.9 `core/cycle_duration_predictor.py`

Stimatore durata ciclo bot (schedule-aware). Per ogni istanza, calcola:

```
T_istanza = boot_home_median + Σ task_due_median
T_ciclo   = Σ T_istanza + tick_sleep_s
```

`predict_cycle_from_config(strict_schedule=True)` filtra task per
istanza in base a `state.schedule[task]` + `interval_hours` + edge
cases (es. main_mission gate UTC≥20). Rolling stats da ultimi 20
record per istanza. Cache TTL 30min.

### 4.10 `core/skip_predictor.py` ⚠ DEPRECATO

**Rimosso 08/05/2026** — regola architetturale "no skip istanza": nessun
sistema di predizione può saltare un'istanza nel ciclo. Modulo lasciato
in repo per git history; le funzioni helper (`_calc_t_marcia_min`,
`load_metrics_history`) restano usate da `core/adaptive_scheduler.py`.

Modello empirico T_marcia ancora vivo:
`T_marcia = (2×eta + saturazione × T_L_max[livello, istanza]) × coef`.
`saturazione = load_squadra / cap_nominale_L_max` (post-WU116).
`T_L_max` da `config/predictor_t_l_max.json` (statico).
`coef` da `core/t_marcia_calibration.py` (closed-loop, vedi 4.13).

Skip totale di un'istanza VIETATO. L'unico riordino consentito è
quello dell'**Adaptive Scheduler** (4.12). Vedi memoria
`feedback_no_skip_istanza.md`.

### 4.11 `core/cycle_predictor_recorder.py`

Snapshot della predizione ogni 15 min + accuracy fine-ciclo.
Storage:
- `data/predictions/cycle_snapshots.jsonl` — 1 record per snapshot
  (ts, cycle_numero, elapsed_min, predicted_min, input_context con
  istanze + task + per-istanza T_s)
- `data/predictions/cycle_accuracy.jsonl` — 1 record per ciclo
  completato con error_pct per ogni snapshot

Background task in dashboard `lifespan` esegue `record_snapshot()` +
`evaluate_cycles()` ogni 15 min.

### 4.12 `core/adaptive_scheduler.py` (08/05)

Riordino dinamico delle istanze nel ciclo bot per massimizzare la
produttività dell'arrivo del bot ad ogni istanza. **Mai skip totale**:
tutte le istanze vengono processate ogni ciclo; cambia solo l'**ordine**.

Componenti:
- `should_activate_scheduler()` — 4 precondizioni in OR:
  1. master DRL residuo ≤ 50M (saturo, riordino utile)
  2. rifornimento OFF
  3. ≥50% istanze sature
  4. spedizioni oggi > 100
- `compute_slot_liberi_atteso(ist, t_offset)` — score per istanza:
  blend deterministico (modello T_marcia) + empirico (lookup_slot_liberi
  storico). `α` adaptive in funzione di n_samples (proposta A 08/05).
- `ordina_istanze_adaptive(istanze, log_fn)` — greedy con sort key
  `(score desc, p_saturo asc, anzianita desc)`. Master FauMorfeus sempre
  in fondo. Trace step-by-step in `bot.log` come `[ADAPT-TRACE]`.
- `compute_ab_test_metrics()` + `record_ab_test()` — confronto virtuale
  ordine adaptive vs naive (proposta E). Persiste `delta_slot` in
  `data/predictions/scheduler_ab.jsonl`.
- `_stima_durata_istanza_min()` — chiama `predict_cycle_from_config(
  strict_schedule=True)` × `get_calibration_factor()` (proposta D).

Stati:
- `enabled=False` → no-op
- `enabled+shadow_only=True` → calcola+logga, **no apply**
- `enabled+shadow_only=False` → applica riordino + persistence

Persistence: `data/scheduler_planned_order.json` con TTL 4h, supporta
resume post-restart bot.

### 4.13 `core/empirical_slot_predictor.py` (08/05, proposta A)

Lookup empirico `E[slot_liberi | gap_min, istanza]` da
`data/istanza_metrics.jsonl` (coppie consecutive di record per istanza).
Bucket gap: `<60, 60-90, 90-120, >120` min. Stessa logica del pannello
dashboard "slot liberi rientrati vs elapsed", estratta in modulo
riusabile. Cache TTL 60s.

API:
- `lookup_slot_liberi(ist, gap_min) → {n_samples, mean, median, p25,
  p75, max_squadre, bucket_label}`
- `lookup_p_saturo_globale(ist) → fract sample con slot_liberi=0`
  (proposta C, tie-breaker greedy)
- `get_lookup_summary()` — info dashboard

### 4.14 `core/cycle_predictor_calibration.py` (08/05, proposta D)

Calibrazione closed-loop **globale** del cycle predictor. Legge ultimi
N=10 cicli da `cycle_accuracy.jsonl`, calcola bias mediano
`(actual - predicted) / predicted` → factor moltiplicativo applicato
in `_stima_durata_istanza_min()`.

Persiste in `data/predictions/cycle_calibration.json`. Cache TTL 30min.
Auto-rebuild se stale.

Guardrail: factor clamped `[0.5, 2.0]`, min 5 cicli, bias < 5% → 1.0.
Validazione prod: bias +19% → factor 1.19 (cycle predictor sottostima
sistematicamente).

### 4.15 `core/t_marcia_calibration.py` (08/05, proposta B)

Calibrazione closed-loop **per (istanza, livello)** del modello T_marcia.
Per ogni record con `adaptive_scheduler_meta.slot_liberi_attesi`
(predizione al ciclo N), confronta col record successivo della stessa
istanza con `raccolta.attive_pre + totali` (osservazione N+1). Aggrega
bias_slot mediano per (ist, lv) → coefficiente moltiplicativo applicato
in `_calc_t_marcia_min()`.

Persiste in `data/predictor_t_l_calibration.json`. Cache TTL 30min.
Guardrail: min 5 sample per (ist, lv), bias < 0.5 slot → 1.0,
coef clamped `[0.7, 1.5]`. Si auto-attiva dopo accumulo dati post adaptive.

### 4.16 `core/alerts.py` (WU137 fase 2)

Alert real-time email per eventi anomali bot, rate-limited per event_type
con state persistente `data/alerts_state.json`. 5 event_type configurati:

| event_type | trigger | severity | cooldown |
|---|---|---|---|
| `cascade_adb` | ≥3 cascade in 1h per istanza | error | 1h |
| `heartbeat_cicli` | 0 cicli in 1h | critical | 30min |
| `master_saturo_long` | DRL=0 da >1h (escl. stato stale post-mezzanotte UTC, WU144) | warn | 2h |
| `maintenance_long` | maintenance.flag >2h | warn | 4h |
| `bot_unexpected_restart` | restart senza exit pulito | critical | 15min |

API:
- `trigger_alert(event_type, severity, title, body, instance, cooldown_s)`
- `check_master_saturo()` / `check_heartbeat_cicli()` /
  `check_maintenance_long()` — chiamati post-ciclo da `main.py`
- `report_cascade_adb(istanza)` — hook in
  `core/orchestrator.py` su `ADBUnhealthyError`

Master toggle `globali.notifications.alerts_enabled` (default False) +
lista `alerts_disabled` per silenziare singoli event_type.

**WU144 (10/05) DRL stale fix**: il check `master_saturo_long` ora skippa
se `morfeus_state.ts.date() != today UTC` (il gioco resetta DRL a 00:00
UTC, evita falsi alert finché il bot non rilegge OCR). Auto-reset duale
in `shared/morfeus_state.py::load` ritorna in memoria
`daily_recv_limit_max` come cap stimato — beneficia tutti i consumer
(adaptive scheduler `_master_drl_residuo_m`, dashboard, daily_report).

### 4.17 `core/daily_report.py` (WU137 fase 1 + revisione 10/05 + WU196)

Daily report email costruito ogni mattina (default 07:35 UTC) tramite
`maybe_send_daily_report()` chiamato post-ciclo dal main loop.
Architettura: 12 funzioni `_section_*` indipendenti aggregano da
diverse sources, due render text/html separate dalla logica dati.

**12 sezioni del report** (ordine fisso, rev 10/05 + WU196):

| # | Sezione | Source | Contenuto chiave |
|---|---|---|---|
| 1 | CICLI | `cicli.json` + events | cicli completati/in_corso, durata media+range, uptime%, produttività (marce/spedizioni/sfide) |
| 2 | PRODUZIONE INTERNA RIFUGIO | `state/<ist>.json::produzione_storico[]` | produzione effettiva castello aggregata per istanza nel giorno, throughput/h |
| 3 | RISORSE INVIATE AL MASTER | `storico_farm.json` | netto post-tassa per risorsa, totale + tassa scartata |
| 4 | TREND vs media 7gg | `storico_farm.json` | confronto inviato vs media settimana precedente, ▲▼= per risorsa |
| 5 | RIFORNIMENTO | events_jsonl + storico_farm | dettaglio per istanza: invii/netto/v_invio/tassa/residuo, range tassa, saturazione |
| 6 | TRUPPE | `storico_truppe.json` | totale master separata, Δ giorno + Δ 7gg per istanza |
| 7 | PERFORMANCE TASK | events_jsonl | per task: n, avg, p95, max, outliers IQR % |
| 8 | BOOT HOME → READY | `istanza_metrics.jsonl::boot_home_s` | per istanza: avg/min/max boot fino a tick pronto (include settings+troops post-HOME, WU127) |
| 9 | COPERTURA SQUADRE | `cap_nodi_dataset.jsonl` | load_squadra/cap_nodo per istanza, summary 100%, dettaglio underprov |
| 10 | EVENTI RILEVANTI | cicli + mail_queue + logs + restart_state | esiti tick, alert email, rifornimento skip master, HOME stab timeout, bot restart |
| 11 | ANOMALIE TASK | events_jsonl | aggregato per task con fail_rate%, lista istanze, causa principale (top msg) |
| 12 | DEPOSITO ATTUALE (WU196) | `state/<ist>.json::produzione_corrente.risorse_iniziali` | ultima lettura nota risorse in deposito per istanza + timestamp — snapshot LIVE (non storico del giorno, a differenza delle altre 11 sezioni) |

**Nota sezione 12**: a differenza delle altre sezioni (tutte filtrate per
`date` = ieri UTC), la sezione 12 legge lo stato corrente
(`produzione_corrente`, la sessione ancora aperta) — riflette quindi il
deposito "ad ora" (ultimo ciclo completato per istanza al momento della
generazione del report), non un valore storico associato al giorno del
report. Fonte già esistente: l'OCR robusto a consenso di
`main.py::_leggi_risorse()` (gira ad ogni avvio istanza, indipendente da
`ZainoTask`), già persistito in `risorse_iniziali` della sessione aperta —
nessuna nuova lettura OCR introdotta, solo esposizione nel report di un
dato già raccolto.

**Regole applicate** (rev 10/05):
- **No duplicazione dati** tra sezioni: stress test eseguito su tutte le 11
- **`_fmt_dur_s`** segue regola memoria `feedback_format_durata`: durate
  ≥60s mai con secondi (`1h38m`, `5m`, `46s`)
- **Throughput su `denom_s`** coerente tra sezioni 1/2/3 (24h o
  elapsed if oggi)
- **Master FauMorfeus** sempre separato da ordinarie nei totali (sez 6)
- **Tabelle**: tutte le 12 istanze mostrate, no top-N truncato
- **Marker visivi**: ✓ ok · ⚠ critico · · marginale · ▲▼= delta

**Schedulazione**: `maybe_send_daily_report()` legge
`globali.notifications.daily_report_hour_utc` (default 07:35) + verifica
`last_sent_date` in `data/daily_report_state.json` per idempotenza
giornaliera. Se ora UTC ≥ schedule AND `last_sent_date < today` → builds
report, enqueue email, aggiorna state.

---

## 5. Task system

I task sono classi che implementano `core.task.Task`. Ognuna:

- `name() → str` (snake_case)
- `should_run(ctx) → bool` (gate decisionale)
- `run(ctx) → TaskResult(success, message, data)` (esecuzione)
- Eventuale `interval_hours()`, `schedule_type()` (override default)

Registrati da `main.py` via `config/task_setup.json` con
`{class, priority, interval_hours, schedule}`.

**17 task attivi in produzione**, ordinati per priority crescente
(0 = prima):

### 5.1 BoostTask (priority 5, periodic 0h)

[tasks/boost.py](../tasks/boost.py) — Attiva i booster del popup Manage
Shelter → sezione "Economic Boost": **Gathering Speed** (tutte le risorse)
+, dal 20/07/2026, i 4 booster di **produzione risorsa singola**
(Food/Wood/Steel/Oil Production = pomodoro/legno/acciaio/petrolio).

**Flusso Gathering Speed** (invariato): HOME → tap badge boost → swipe lista
fino a "Gathering Speed" → espansione INLINE nella stessa lista (score
`pin_speed_8h`/`pin_speed_1d` allineati per riga a `pin_speed_use`) → tap
USE → conferma. Preferenza 8h, fallback 1d.

**Flusso produzione risorsa** (nuovo, calibrato dal vivo 20/07/2026): swipe
lista fino a "<Risorsa> Production" → se già attivo (barra verde
`"<Risorsa> Production +25%"`) → skip, nessun tap → altrimenti tap riga →
apre una **SOTTO-PAGINA dedicata** (diverso da Gathering: non inline) con
2 righe fisse "8h Boost"/"24h Boost", ciascuna col proprio pulsante USE
(zone-based, non allineamento riga) → tap back sotto-pagina per tornare
alla lista (la sotto-pagina non torna da sola). Un solo popup aperto per
tick, gestisce fino a 5 slot (produzioni PRIMA, gathering per ultimo — il
suo `back()` su ATTIVATO chiude l'intero popup in un colpo solo, per design
collaudato; le produzioni tornano sempre alla lista tramite il proprio tap
back dedicato).

**Parametri**:
- Stato: `BoostState` (core/state.py) per Gathering, `ProduzioneBoostState`
  (4 slot `BoostState` indipendenti, uno per risorsa) per la produzione —
  stessa classe riusata, zero duplicazione di scheduling. `should_run()`
  del task è vero se Gathering O almeno una produzione è dovuta.
- `BoostConfig.produzioni`: tupla di 4 `ProduzioneBoostConfig`
  (risorsa/template riga/template attivo), coordinate sotto-pagina fisse
  (`tap_subpage_use_8h`, `tap_subpage_use_24h`, `tap_subpage_back`) e zone
  di ricerca per disambiguare 8h vs 24h (`pin_speed_use.png` riusato,
  identico su entrambe le righe).

**Regole speciali**:
- WU115 debug per task abilitabile da dashboard
- Se boost già attivo → registra `scadenza` corrente, return success
- `wait_after_tap_speed`/`wait_after_subpage_open`: 2.0s (DELAY UI
  vincolante)
- `_salva_debug_shot` disabilitato (WU59 cleanup 105MB)
- `TaskResult.data` porta un riepilogo per slot (`{"gathering": "...",
  "pomodoro": "...", ...}`) — schema multi-slot, sostituisce il vecchio
  `durata`/`outcome` single-slot

### 5.2 RifornimentoTask (priority 10, always 0h)

[tasks/rifornimento.py](../tasks/rifornimento.py) — Invia risorse al
rifugio destinatario (master). Modalità mappa o membri.

**Flusso modalità mappa**: HOME → MAPPA → centra rifugio
(`coord_x, coord_y` da config) → tap castello → Resource Supply →
seleziona risorsa (ciclica round-robin) → compila qty → tap MARCIA →
loop fino a saturazione slot o quote esaurite.

**Modalità membri**: tap_barra("alliance") → Members → tap player
target → Send → loop spedizioni.

**Parametri** (`rifornimento_comune` + `rifornimento`):
- `dooms_account` — nome destinatario (default FauMorfeus)
- `max_spedizioni_ciclo` — default 2 (WU105 tuning)
- `soglia_<risorsa>_m` — soglia minima invio (in M unità)
- `<risorsa>_abilitato` — flag boolean
- `mappa_abilitata` / `membri_abilitati` — modalità (XOR)
- `rifugio.coord_x/y` — coordinate destinatario su mappa

**Regole speciali**:
- WU105: branch `slot=0` usa `continue` invece di `break` per
  ricontrollare slot dopo wait
- WU106: alla prima spedizione del giorno cattura
  `cap_invio_iniziale_oggi` + `qta_max_invio_lordo`
- WU34 schema NETTO/LORDO/TASSA con `tassa_pct_avg` ~23%
- Stato `eta_rientro_ultima` per coordinarsi con raccolta (Issue #64)

### 5.3 RaccoltaTask (priority 15, always 0h)

[tasks/raccolta.py](../tasks/raccolta.py) — Invio squadre raccoglitrici
ai nodi risorsa sulla mappa.

**Flusso**: HOME → MAPPA → leggi slot OCR (X/Y) → loop:
1. CERCA tipo (lente icona campo/segheria/acciaio/petrolio) + livello
2. Tap su nodo trovato → popup Gather → leggi cap_nodo via OCR
3. RACCOGLI → SQUADRA → leggi ETA marcia + **load_squadra**
   (WU116 — popup invio)
4. Set truppe (auto=0) → MARCIA
5. Verifica slot post-marcia (sanity check WU68)
6. Aggiorna blacklist nodi (territorio/fuori, cooldown)
7. Loop fino a slot_pieni o tipi tutti bloccati

**Parametri** (`raccolta`):
- `RACCOLTA_SEQUENZA = ["campo","segheria","petrolio","acciaio"]` —
  ordine round-robin
- `RACCOLTA_OBIETTIVO=4` — slot target
- `RACCOLTA_LIVELLO=6/7` — livello nodi target
- `RACCOLTA_MAX_FALLIMENTI=3` — tentativi/ciclo prima di abort
- `RACCOLTA_TRUPPE=0` — auto (game determina min truppe)
- `livello_min` — soglia minima (sotto: skip neutro, blacklist temp)
- `allocazione` — frazioni 0-1 per ratio target raccolta
- `raccolta_fuori_territorio` — flag per istanza (WU50)

**Regole speciali**:
- WU24 3-level break su No Squads (FAU_09/10 da 40 detect→1)
- Blacklist Fuori Territorio GLOBALE (`data/blacklist_fuori_globale.json`)
- WU67 reset livello: delta diretto invece di 7×meno + N×piu (saving 25-35min/die)
- WU70 OCR slot SX-only ensemble PSM 10/8/7 + sanity pre-vote
- WU84 hook `cap_nodi_dataset.jsonl` per analytics capacità
- WU116 hook `_calc_t_marcia` per skip predictor empirico

### 5.4 TruppeTask (priority 18, periodic 4h)

[tasks/truppe.py](../tasks/truppe.py) — Addestramento automatico delle
4 caserme (Infantry, Rider, Ranged, Engine).

**Flusso**: HOME → leggi counter X/4 (icona pannello caserme, OCR) →
se X<4 loop (4-X) volte:
1. tap (30, 247) → naviga prossima caserma libera
2. tap (564, 382) → cerchio Train
3. verifica checkbox Fast Training (R-mean>110=ON, soglia 110, **sempre OFF**)
4. tap (794, 471) → TRAIN giallo

**Parametri**: tutti hardcoded (coord, soglie). Fast Training sempre
disabled vincolante.

**Regole speciali**:
- OCR counter cascade otsu→binary su zona (12,264,30,282) per
  coprire X=0
- Validato FAU_05 4 cicli 0/4→4/4 OK (WU62)

### 5.5 DonazioneTask (priority 20, periodic 8h)

[tasks/donazione.py](../tasks/donazione.py) — Dona risorse alla
tecnologia alleanza marcata.

**Flusso**: HOME → tap_barra("alliance") → Technology → cerca pin_marked
(tecnologia "Marked!") → tap → check pin_donate (giallo) → loop tap
donate fino a 30 volte → BACK×3.

**Parametri**:
- `max_donate=30` — cap pool gioco
- `delay_per_tap_ms` — randomizzato

**Regole speciali**:
- WU90 schedule periodic 8h (era always, throughput bound 3 donate/h)
- WU42 ramo pin_marked assente: back×3 invece di back×1 per
  chiusura corretta Technology

### 5.6 MainMissionTask (priority 22, daily 24h)

[tasks/main_mission.py](../tasks/main_mission.py) — Recupera ricompense
Main Mission + Daily Mission + chest milestone.

**Flusso**: HOME → tap (33, 398) apri pannello → tab Main → loop CLAIM
Main → tab Daily → loop CLAIM Daily → OCR Current AP DOPO daily → per
ogni chest milestone (20/40/60/80/100) con AP≥soglia: tap chest +
chiusura popup.

**Parametri**:
- ROI claim main `(790,265,880,305)` tap fisso (832, 284) auto-scroll
- ROI claim daily `(810,210,895,460)` tap dinamico su match
- ROI OCR AP `(180,130,240,175)` upscale 3× th>200 PSM7
- Chest coord: 20=(397,160), 40=(517,160), 60=(633,160), 80=(751,160), 100=(873,160)

**Regole speciali**:
- WU88 detection 2-tab vs 3-tab via OCR "Chapter" (10,75,110,135)
- WU91 daily 24h + gate UTC≥20 (massimizza chest milestone con AP elevato)

### 5.6-bis DailyMissionAutoTask (priority 23, always — task custom MASTER, 20/07)

[tasks/daily_mission_auto.py](../tasks/daily_mission_auto.py) — Task esclusivo
del master (FauMorfeus, via `master_task_whitelist`). Il master ha il pulsante
**"Auto Complete"** che esegue automaticamente TUTTE le daily mission (le
istanze normali ne fanno solo alcune), portando l'AP al massimo → tutti e 5 i
chest/pacchi (20/40/60/80/100) raggiunti. Once/day, reset mezzanotte UTC.

**Struttura a DUE FASI differite** via `DailyMissionState` (core/state.py):
- **Fase TRIGGER** (tick N): HOME → pannello (33,398) → tab Daily → tap Auto
  Complete (843,225). Parte un timer "Auto ends in ~1-3 min" (nessun popup,
  conferma via comparsa `pin_auto_ends`). → `segna_trigger()` (+ timestamp).
- **Fase CLAIM** (tick successivo, ≥`wait_claim_min` dal trigger): loop CLAIM
  (`pin_btn_claim_mission`, con scroll — il primo CLAIM ritira in batch tutte
  le missioni) + ritiro chest: tappa TUTTI e 5 i chest incondizionatamente
  (con auto-complete sono sempre raggiunti; NO OCR AP — quello di MainMission
  ha cap 100 e scarterebbe l'AP=170 del master). Ogni chest → popup
  "Congratulations! You got" → chiude con tap zona vuota. → `segna_claim()`.

**Note**: un tick esegue UNA fase (guidata dallo stato); il claim differito
evita di coordinare trigger+claim nello stesso tick. Se il pulsante Auto
Complete è assente (istanza senza la funzione) → `segna_non_disponibile()`.
Calibrato + validato live su FauMorfeus (auto-complete → missioni → claim
batch → 5/5 chest, badge a 0).

### 5.6-ter RadarMasterTask (priority 24, periodic 12h — task custom MASTER, 20/07)

[tasks/radar_master.py](../tasks/radar_master.py) — Task esclusivo del master
(FauMorfeus, via `master_task_whitelist`). Il master ha un **Radar Station
Pass** (acquisto mensile) che abilita il pulsante **"Complete All"** nella
Radar Station: un click completa in batch tutte le missioni radar attive,
consumando stamina (50/missione, cap 1500). Indipendente da
[tasks/radar.py](../tasks/radar.py) (pallini+card, istanze ordinarie) —
nessuna condivisione di stato o codice, ma stessa cadenza di schedulazione
(`interval_hours=12.0`, 2 volte/giorno, richiesta esplicita utente per
allinearsi al ciclo di generazione missioni radar).

**Idempotente, nessuno `state` dedicato**: il cooldown "Refresh in HH:MM:SS"
è visibile a schermo dal gioco stesso — se già esaurito il task esce subito
(`pin_radar_completed`, ~5s), anche se richiamato prima delle 12h (safety
net, non il gate primario).

**Flusso `run()`**: HOME → tap icona Radar Station → loop (max
`max_complete_all_iter=15`): tap Complete All → se compare "You've completed
all the current events!" → fine; se si apre la maschera STAMINA → satura con
Emergency Recovery (+50) finché il **riempimento verde della barra** (pixel-
check su `stamina_bar_roi`, non template — il badge "XN >" cambia numero ad
ogni tap e non è discriminante via match, verificato live) raggiunge
`soglia_stamina_piena=0.97` → chiudi maschera → ritenta; altrimenti (missione
completata silenziosamente) → ritenta. **Guardia di sicurezza**: se per
`max_stato_inatteso=2` iterazioni consecutive non viene riconosciuto né
completamento né maschera stamina né `pin_radar_title` (ancora sulla Radar
Station) → abort pulito (mitiga il rischio di un tap caduto su schermata
inattesa, es. "Mass Deploy" osservato in calibrazione). **Chiusura sempre**
via `ctx.navigator.vai_in_home()` (mai back/tap grezzo — un back non
verificato da vista mappa ha aperto "Exit game?" in calibrazione).

**Non gestito** (rimandato): rilevare "Complete All" disabilitato su istanze
senza il Pass — la guardia di sicurezza intercetta il caso in modo
conservativo (abort senza azione utile), fallback al flusso standard non
ancora implementato.

### 5.7 ZainoTask (priority 25, periodic 168h = 7 giorni)

[tasks/zaino.py](../tasks/zaino.py) — Scarica risorse dal Bag al
deposito globale, fino a soglia.

**Modalità**:
- `bag` (default): scan TM griglia → inventario completo →
  greedy ottimale → USE per coprire gap
- `svuota`: USE MAX su ogni pezzatura senza soglia

**Flusso bag**:
1. OCR deposito (`ocr_risorse(screen)` barra superiore)
2. Calcola gap = target - attuale per ogni risorsa abilitata
3. Apri BAG → RESOURCE
4. FASE 1: scan griglia via TM `pin_<risorsa>_<pezzatura>.png`
5. FASE 2: greedy `_calcola_piano(gap, inventario)` minimizza spreco
6. FASE 3: per ogni voce piano: tap pin + input qty + USE
7. OCR deposito post → delta reale

**Parametri** (`zaino`):
- `modalita = "bag"|"svuota"`
- `usa_<risorsa>` boolean
- `soglia_<risorsa>_m` (default pomodoro=20, legno=20, acciaio=10, petrolio=5)

**Regole speciali**:
- Popup "Caution" gestito autonomo (riconosciuto + disabilitato sessione)
- Issue #3 confermata CHIUSA 04/05 (validazione end-to-end FAU_10
  +4.8M reale)

### 5.8 VipTask (priority 30, daily 24h)

[tasks/vip.py](../tasks/vip.py) — Ritiro ricompense VIP giornaliere
(cassaforte + claim free).

**Flusso macchina a stati** (max 3 tentativi):
1. HOME pulita
2. Tap badge VIP (85,52) → check pin_vip_01_store
3. CASSAFORTE: pin_vip_02_chiusa → claim → dismiss popup → polling
   ritorno store → POST check pin_vip_03_aperta
4. CLAIM FREE: pin_vip_04_chiuso → claim free → dismiss popup → polling
   → POST check pin_vip_05_aperto

**Output**: `cass_ok=bool, free_ok=bool`.

### 5.9 AlleanzaTask (priority 35, periodic 4h)

[tasks/alleanza.py](../tasks/alleanza.py) — Raccolta ricompense Alleanza
(Dono + Negozio + Attività).

**Flusso**: HOME → tap_barra("alliance") (WU111 dinamico) → Dono →
loop Rivendica via TM `pin_claim.png` (max 30 tap) → tab Negozio /
Attività se disponibili → BACK→HOME.

**Parametri**: `max_rivendica=30` (auto-WU13 con molti claim).

### 5.10 MessaggiTask (priority 40, periodic 4h)

[tasks/messaggi.py](../tasks/messaggi.py) — Raccolta ricompense
sezione Messaggi (tab Alliance + System).

**Flusso**: tap icona messaggi (928, 430) → tab Alliance → tap Read
All → ricompense → tab System → idem → close.

### 5.11 ArenaTask (priority 50, daily 24h)

[tasks/arena.py](../tasks/arena.py) — Combatte 5 sfide Arena of Glory.

**Flusso**: HOME → tap Campaign → Arena of Doom → handle popup glory →
lista sfide visibile → loop 5 sfide:
1. Tap PRIMA sfida (745, 250) (WU117 era ULTIMA)
2. START CHALLENGE
3. Wait battaglia (~10s post-WU82, era 60s)
4. Tap CONTINUE dinamico (WU80 match `pin_arena_05_continue`)
5. Skip animation toggle (always ON, _assicura_skip ad ogni sfida WU74)

**Pre-1ª sfida del giorno**: rebuild truppe (WU83) — rimuove tutte le
N celle e ricarica via tap+READY (auto-deploy migliore composizione).

**Regole speciali**:
- Driver MuMu DirectX richiesto (Vulkan crasha ADB su animazione, WU88)
- Templates Failure/Victory/Continue refresh post UI client redesign (WU77/89)
- Threshold 0.90 anti-falso-positivo Victory su Failure (WU81)

### 5.12 ArenaMercatoTask (priority 60, daily 24h)

[tasks/arena_mercato.py](../tasks/arena_mercato.py) — Acquisto pack
360 + pack 15 con monete arena.

**Flusso**: HOME → Campaign → Arena of Doom → check pin_arena_01_lista
→ tap Carrello (905, 68) → Arena Store →
- FASE 1 pack 360: loop tap acquisto finché btn360_open attivo
- FASE 2 pack 15: idem fino esaurimento monete
→ BACK→HOME.

**Regole speciali**:
- WU113 sleep 2.0s post-tap_carrello (DELAY UI vincolante)
- Confronto open vs close score per stato bottone (no soglia assoluta)
- Validato FAU_01 04/05: 6 pack 360 + 0 pack 15 (monete spese in 360)

### 5.13 DistrictShowdownTask (priority 70, always 0h)

[tasks/district_showdown.py](../tasks/district_showdown.py) — Evento
mensile 3 giorni: lancia tutti i dadi Gold via Auto Roll.

**Window evento**: VEN 00:00 → LUN 00:00 UTC. Fund Raid sub-event
DOM 22:00 → LUN 00:00.

**Flusso**: HOME → cerca pin_district_showdown barra eventi top →
tap icona → tap Auto (39, 151) → popup Auto Roll: verifica 3 toggle
ON → tap Start → loop monitoring 15s:
- Gang Leader → Request Help + assistance progress
- Access Prohibited → polling 5s × 90s safety
- Item Source → dadi esauriti, EXIT
- Auto-roll active → continua

Post-dadi: District Foray + Influence Rewards + Achievement Rewards +
Fund Raid (se window).

**Regole speciali**:
- WU108 flag dashboard come VETO (non più auto-bypass in window)
- Issue #51 (gate readiness popup fasi 3/4/5) APERTA — proposta
  `_wait_template_ready` su sentinel

### 5.14 StoreTask (priority 80, periodic 8h)

[tasks/store.py](../tasks/store.py) — Acquisto Mysterious Merchant
Store quando appare in mappa.

**Flusso**: HOME → collassa banner eventi → scan griglia spirale 25
passi → trova edificio Store → tap + verifica label/mercante diretto
→ tap carrello → loop acquisti pin gialli (legno/pomodoro/acciaio)
per pagina → swipe pagine 2,3 → Free Refresh (1×/run) → ripete →
BACK + ripristina banner.

**Regole speciali**:
- WU23 multi-candidate sorted desc + cascade retry (swipe non-idempotente)
- WU71 early-exit scan a primo match≥0.80 (saving 30-40s)
- WU85 debug buffer per analisi pattern bimodale temporale

### 5.15 RadarTask (priority 90, periodic 12h)

[tasks/radar.py](../tasks/radar.py) — Raccolta pallini rossi sulla
mappa Radar Station + dispatch azioni per categoria icona.

**Flusso** (post-WU150):
1. Verifica badge rosso icona Radar (pixel check numpy)
2. Tap icona → attesa apertura mappa + notifiche (10s)
3. `process_radar_actions(ctx, log_fn)` — loop integrato (max 10 iter):
   - `_loop_pallini`: screenshot → find pallini rossi (BFS numpy) → tap ognuno
   - wait 10s (animazioni gioco)
   - `RadarCensusTask` → legge `census.json` → filtra `actionable`
   - dispatch per categoria → `handle_card` (GO + RESCUE + RADAR_ICON)
   - exit se 0 pallini + 0 actionable
   - FIX B safety break: 2 iter consecutive con stesso n_pallini e 0 processed → abort + recovery popup (revert WU151 FIX A — 14/05)

**Handler attivi**: solo `card` (Protect Survivors/Assist Ally). Placeholder
presenti per skull/pedone/soldati/avatar/paracadute/camion/fiamma/bottiglia/numero/auto.

### 5.16 RadarCensusTask (priority 100, periodic 12h)

[tasks/radar_census.py](../tasks/radar_census.py) — Classificazione
icone sulla mappa radar via template matching + RF classifier.

**Flusso**: dalla schermata radar aperta → screenshot → detector
icone (radar_tool, 47 template) → crops → classify RF + heuristic
fallback → cataloga in `radar_archive/census/YYYYMMDD_HHMMSS_<istanza>/`
con `census.json` (cx, cy, categoria, ready).

**Uso in produzione**: chiamato da `process_radar_actions()` come step
3 del loop integrato. Il census standalone (`RADAR_CENSUS_ABILITATO`) è
mantenuto per compat ma sconsigliato (post-WU150).

### 5.17 RaccoltaChiusuraTask (priority 200, always 0h)

Sotto-classe di RaccoltaTask con priority alta (eseguita per ultima
nel ciclo). Riprende invii eventuali rimasti dopo gli altri task
(es. squadre tornate da rifornimento liberano slot).

### Variante: RaccoltaFastTask (WU57)

[tasks/raccolta_fast.py](../tasks/raccolta_fast.py) — Variante 1-shot
senza retry intermedi. Skip OCR livello pannello/nodo. Recovery 1
shot via BACK + vai_in_mappa.

Attivazione: tipologia istanza = `raccolta_fast` (alternativa a
`raccolta_only` o `full`). Runtime swap RaccoltaTask→RaccoltaFastTask
in `main.py` preservando priority/interval/schedule.

### 5.18 GraficaHqTask (priority 1, always 0h)

[tasks/grafica_hq.py](../tasks/grafica_hq.py) — Imposta Graphics Quality
HIGH + Frame Rate MID + Optimize Mode HIGH (WU78-rev, driver
Vulkan→DirectX). WU195 (07/07): estratto da `imposta_settings_lightweight`
(ex `core/settings_helper.py`), che girava incondizionatamente ad ogni
avvio istanza, in task orchestrator indipendente abilitabile/disabilitabile
da dashboard separatamente dalla pulizia cache.

**Flusso**: HOME → tap Avatar → tap icona Settings → tap System Settings
→ tap Graphics Quality HIGH → tap Frame Rate MID → tap Optimize Mode HIGH
→ BACK×3 → HOME. Sequenza autosufficiente in
`shared_helper`/`core/settings_helper.py::esegui_grafica_hq()`.

**Regole speciali**:
- Skip esplicito se `tipologia == "raccolta_only"` (FauMorfeus)
- `should_run()` → `ctx.config.task_abilitato("grafica_hq")`
- Priority 1 (gira per prima, replicando il comportamento storico
  "ad ogni avvio istanza, prima di ogni altro task")

### 5.19 PuliziaCacheTask (priority 2, always 0h)

[tasks/pulizia_cache.py](../tasks/pulizia_cache.py) — Pulizia cache
giornaliera (Help → Clear cache → CLOSE), gestita 1×/die per istanza via
`data/cache_state.json`. WU195 (07/07): estratto da
`imposta_settings_lightweight` in task indipendente, separato da
GraficaHqTask.

**Flusso**: HOME → tap Avatar → tap icona Settings (si ferma al pannello
Settings, non entra in System Settings) → `_pulisci_cache()` (invariata:
Help → Clear cache → poll CLOSE → tap) → BACK×2 → HOME. Se cache già
pulita oggi per l'istanza → uscita immediata, nessuna navigazione.

**Regole speciali**:
- Skip esplicito se `tipologia == "raccolta_only"` (FauMorfeus)
- `should_run()` → `ctx.config.task_abilitato("pulizia_cache")`
- Gate giornaliero invariato (`_cache_pulita_oggi`/`_marca_cache_pulita`
  su `data/cache_state.json`), indipendente dal flag abilitazione task
- Priority 2 (subito dopo GraficaHqTask)

### 5.20 Task del master — whitelist config-driven (WU-MasterTasks, 17/07)

> **WU234 (`FauMorfeusSetupTask`) ANNULLATO** e rimosso. Il bundle giornaliero
> fisso (grafica_hq+pulizia_cache+boost+vip) è stato sostituito da un
> meccanismo generico e **selezionabile** — vedi sotto.

Il master (FauMorfeus, `tipologia="raccolta_only"`) normalmente esegue solo
`RaccoltaTask`/`RaccoltaChiusuraTask` (`main.py::_thread_istanza` filtra la
registrazione degli altri task per quel profilo). Con WU-MasterTasks il master
può eseguire un **sottoinsieme configurabile** degli altri task, ciascuno con
la sua **schedulazione normale** (identica alle istanze ordinarie).

**Meccanismo**:
- Campo per-istanza `master_task_whitelist` (lista di nomi task snake_case) in
  `runtime_overrides.json::istanze.<master>` (dynamic, modificabile a caldo).
- `main.py`: per un'istanza `raccolta_only`, oltre a raccolta registra i task
  la cui classe mappa (`_TASK_CLASS_TO_NAME`) a un nome nella whitelist, con
  `priority/interval/schedule` invariati da `task_setup.json`.
  `forza_solo_raccolta` (doppio giro FAU_00) → whitelist ignorata (solo raccolta).
- `config/config_loader.py::_InstanceCfg`: espone `MASTER_TASK_WHITELIST`
  (attributo) + `master_task_whitelisted(nome)` (metodo).
- `tasks/grafica_hq.py` / `tasks/pulizia_cache.py`: lo skip interno
  `tipologia == "raccolta_only"` è ora **whitelist-aware** — il master li
  salta SOLO se non selezionati (prima erano sempre saltati per il master).
  Gli altri task (vip/alleanza/messaggi/donazione/district_showdown) non
  hanno skip interni: bastava il filtro `main.py`.

**UI**: sezione "task del master" in `/ui/config/global` (checkbox per task,
salva via `PATCH /api/config/overrides/istanze/{nome}` con
`master_task_whitelist`). Task selezionabili: tutti gli schedulabili tranne
raccolta/raccolta_chiusura (sempre attivi per il master).

**Pydantic** (`dashboard/models.py::IstanzaOverride`): `master_task_whitelist`
+ `raccolta_reset_leggero_abilitato` aggiunti al modello — senza, un save
dashboard li strippava silenziosamente (bug-class field-wipe WU199/WU102).

**Config attuale FauMorfeus (prod)**: `["grafica_hq","pulizia_cache","vip",
"alleanza","messaggi","donazione","district_showdown"]`.

---

## 6. Configurazione

### 6.1 `config/instances.json`

Lista anagrafica fissa istanze MuMu (default statici):

```json
[
  {"nome": "FAU_00", "porta": 16384, "abilitata": true,
   "tipologia": "full", "max_squadre": 5, "livello": 7, ...},
  ...
  {"nome": "FauMorfeus", "porta": 16736, ..., "master": true,
   "tipologia": "raccolta_only"}
]
```

### 6.2 `config/global_config.json` (baseline)

Schema "reset configurazione" neutra (WU94). Tutti i task default
False (l'utente abilita via dashboard). Sezioni: `task`, `sistema`,
`rifornimento`, `zaino`, `raccolta`, `rifugio`, ...

### 6.3 `config/runtime_overrides.json` (hot-reload)

Override runtime per dashboard. Modificato live dalla HOME `/ui`,
letto ad ogni tick:

- `globali.task.<nome>: bool` — flag abilitazione task
- `globali.sistema.tick_sleep_min: int` — minuti tra cicli
- `globali.adaptive_scheduler_enabled` / `shadow_only` /
  `adaptive_scheduler_thresholds` — adaptive scheduler 08/05
- `globali.notifications.{enabled, alerts_enabled, alerts_disabled,
  daily_report_enabled, daily_report_hour_utc, from_addr, recipients,
  smtp.{host,port}}` — email notifier
- `globali.debug_tasks.<nome>: bool` — debug screenshot per task (WU115)
- `globali.rifornimento_comune.{acciaio_abilitato, allocazione, ...}` —
  config rifornimento
- `istanze.<nome>.<campo>` — override per istanza (livello, max_squadre,
  truppe, tipologia, fascia_oraria, raccolta_fuori_territorio,
  truppe_override.caserme.{infantry,rider,ranged,engine})

**Regola architetturale (WU140)**: dashboard HOME modifica SOLO dynamic;
dashboard CONFIG modifica SOLO static. I 2 piani sono indipendenti.
Bootstrap copia static→dynamic al primo avvio. Reset esplicito ricrea
dynamic da static. Promote runtime → static disponibile via bottone UI.

### 6.4 `config/task_setup.json`

Schema scheduler (priority + interval + schedule type) per ogni task.
Vincolante: `_TASK_SETUP` in `main.py` deve essere identico.

### 6.5 `config/predictor_t_l_max.json`

Baseline empirica T_L_max (minuti gather) per livello +
multiplier per istanza. Validato FAU_00 best gatherers L7=125min /
L6=114min, multiplier istanze farm 1.3-1.5x.

### 6.6 Files calibrazione closed-loop (08/05)

Auto-generati dalle pipeline calibrazione, no manutenzione manuale:

- `data/predictions/cycle_calibration.json` — factor moltiplicativo
  globale del cycle predictor (proposta D, ~30min TTL)
- `data/predictor_t_l_calibration.json` — coefficienti T_marcia per
  (istanza, livello) (proposta B, ~30min TTL)
- `data/alerts_state.json` — state rate-limit alert real-time
  (last_sent_iso + count per event_type)
- `data/scheduler_planned_order.json` — ordine pianificato adaptive
  ciclo in volo (TTL 4h, supporta resume post-restart)

---

## 7. Telemetria & analytics

### 7.1 Storage

| File | Schema | Refresh |
|------|--------|---------|
| `data/telemetry/events/events_YYYY-MM-DD.jsonl` | event per task `{ts_start, ts_end, duration_s, task, instance, success, output, anomalies}` | append at task end |
| `data/telemetry/cicli.json` | cicli storici globali con run_id + numero crescente | append at cycle end + auto-close stale |
| `data/telemetry/rollup/rollup_YYYY-MM-DD.json` | aggregati giornalieri | rebuilt nightly |
| `data/telemetry/live.json` | snapshot stato corrente bot | every 5s |
| `data/istanza_metrics.jsonl` | per-istanza per-ciclo (raccolta+rifornimento dettaglio invii) | flush at chiudi_tick |
| `data/cap_nodi_dataset.jsonl` | per-invio raccolta `{tipo, livello, capacita, load_squadra}` | append in raccolta hook |
| `data/predictions/cycle_snapshots.jsonl` | snapshot predictor ogni 15min | dashboard background task |
| `data/predictions/cycle_accuracy.jsonl` | accuracy fine-ciclo (errore% per snapshot) | dashboard background task |
| `data/predictions/scheduler_ab.jsonl` | A/B test virtuale adaptive vs naive (proposta E) — **feature RIMOSSA WU210 14/07, no più scritto** | dormiente |
| `data/predictor_decisions.jsonl` | decisioni skip predictor live (legacy, no più scritto post-RIMOZIONE WU89 08/05) | dormiente |
| `data/mail_queue.jsonl` | queue email notifier (WU137) | append at enqueue, mutate at dispatch |
| `data/alerts_state.json` | state rate-limit alert real-time (WU137 fase 2) | mutate at trigger_alert |
| `data/storico_truppe.json` | snapshot daily Total Squads per istanza | 1×/die UTC settings_helper |
| `data/storico_farm.json` | spedizioni rifornimento daily (retention 90gg) | append at rifornimento end |

### 7.2 KPI dashboard

- **Telemetria task** (24h): outcomes per task (ok/skip/fail), durate medie
- **Storico cicli**: ultimi 15 cicli con durata, n istanze, outcome
- **Health 24h**: pattern detection (cascade ADB, timeout, deficit)
- **Tempi medi 7gg**: filtro outlier IQR Tukey k=1.5
- **Trend 7gg**: spedizioni e produzione per giorno (sparkline ASCII)
- **Storico truppe 8gg**: crescita per istanza
- **Copertura squadre 5 cicli**: load_squadra/cap_nodo per istanza×tipo
- **Predict cycle**: durata atteso prossimo ciclo schedule-aware
- **Predictor decisions**: live stream skip predictor

---

## 8. Predictor (cycle + adaptive scheduler)

Pagina dashboard: `/ui/predictor-istanze` (assorbe vecchio `/ui/predictor`).

### 8.1 Architettura del sistema predittivo (08/05)

```
┌─ Fonti dati ──────────────────────────────────────────────────┐
│  data/istanza_metrics.jsonl (raccolta.invii, attive_pre/post,  │
│                              adaptive_scheduler_meta)          │
│  data/predictions/cycle_accuracy.jsonl                         │
│  data/morfeus_state.json (DRL master)                          │
└──────┬──────────────────┬──────────────────────┬──────────────┘
       ▼                  ▼                      ▼
┌──────────────────┐ ┌─────────────────┐ ┌────────────────────┐
│ EMPIRICAL slot   │ │ CYCLE predictor │ │ T_MARCIA calib     │
│ lookup (4.13)    │ │ calib (4.14)    │ │ (4.15)             │
│ — median/p25/p75 │ │ — factor global │ │ — coef per         │
│ — P_saturo       │ │   (~1.19 prod)  │ │   (ist, livello)   │
└────────┬─────────┘ └────────┬────────┘ └─────────┬──────────┘
         ▼                    ▼                    ▼
   compute_slot_liberi_atteso (det+emp blend, prop. A)
   _stima_durata_istanza_min  (× cycle_factor, prop. D)
   _calc_t_marcia_min         (× t_marcia_coef, prop. B)
                          ▼
   ordina_istanze_adaptive (greedy + sort: score desc → P_saturo asc
                            → anzianita desc, prop. C)
                          ▼
   compute_ab_test_metrics (confronto vs naive, prop. E)
                          ▼
   data/scheduler_planned_order.json + bot.log [ADAPT-TRACE]
```

### 8.2 Componenti

**Cycle Duration Predictor** (4.9): stima T_ciclo dato un setup
(istanze + task DUE da `state.schedule + interval`). Output: T_ciclo_min,
breakdown per istanza, schedule_debug DUE/SKIP. Usa rolling stats
ultimi 20 record.

**Adaptive Scheduler** (4.12): riordina le istanze nel ciclo per
massimizzare slot liberi al passaggio. **Mai skip totale** (regola
"no skip istanza" 08/05).

**Empirical slot lookup** (4.13): `E[slot_liberi | gap, istanza]` da
storico. Usato come blend nel deterministico.

**Cycle predictor calibration** (4.14): factor moltiplicativo globale
da bias closed-loop `actual/predicted`. Auto-rebuild ogni 30min.

**T_marcia calibration** (4.15): coefficiente per (istanza, livello)
da bias predicted vs real per `slot_liberi_atteso`. Si attiva dopo 5+
sample per (ist, lv).

**A/B test virtuale** (`compute_ab_test_metrics`): registra ad ogni
greedy adaptive_tot vs naive_tot in `data/predictions/scheduler_ab.jsonl`.
Misura oggettiva del valore aggiunto dello scheduler (es. delta +4 slot
in setup tipico = +36% produttività predetta).

**Skip Predictor** (4.10): ⚠ DEPRECATO. Le sue funzioni helper restano
usate (`_calc_t_marcia_min`, `load_metrics_history`).

### 8.3 Workflow attivazione adaptive scheduler

1. Restart bot — flag default off → bot identico (sequenziale alfabetico).
2. Attivare flag da dashboard `/ui/predictor-istanze` card 🎯:
   - `enabled=True, shadow_only=True` → calcola+logga `[ADAPT-TRACE]` ma NO apply
   - `enabled=True, shadow_only=False` → applica riordino + persistence
3. Osservare:
   - `[ADAPT-TRACE]` in `bot.log` per trace step-by-step del greedy
   - Pagina `/ui/predictor-istanze` 🧮 simulazione live
   - `[ADAPT-AB]` log per delta_slot adaptive vs naive
4. Calibrazioni si auto-attivano dopo accumulo dati (~10 cicli per D,
   ~5 sample per (ist,lv) per B).

### 8.4 Accuracy tracking

Snapshot ogni 15min auto-correlato con cycle in corso. A fine ciclo:
error% per ogni snapshot vs actual_min. Pannello
`/ui/predictor-istanze` ⏱ mostra storia.

### 8.5 Allineamento bot ↔ predictor (sweep 05/05/2026)

Il bot e il predictor devono concordare su 4 livelli per ogni task:

1. **Flag dashboard** — letto da `runtime_overrides.json::globali.task.<nome>`. Filtrato a monte in `task_globali` per il predictor; controllato in `should_run` dal bot.
2. **Schedule + reset** — `always` / `periodic Nh` / `daily 24h` da `config/task_setup.json`. Reset daily allineato a **00:00 UTC** (post-`951df2a`).
3. **Guard di stato persistente** — letto da `state/{ist}.json` o `data/morfeus_state.json` quando applicabile. Modellato dal predictor in `_task_will_be_noop`.
4. **Offset cumulativo** — `now_for_inst = t0 + Σ T_j_predicted` per gate temporali delle istanze in coda nel ciclo (post-`133ba86`).

**Tabella sinottica** (17 task, esito sweep 05/05):

| # | Task | Schedule | Guard state | Allineato | Note |
|---|------|----------|-------------|-----------|------|
| 1 | boost | always | BoostState (scadenza) | ✅ | offset cumulativo applicato; predictor esclude se boost attivo a `now+tick+5min` |
| 2 | rifornimento | always | DRL master + provviste istanza | ✅ | freshness check 00:00 UTC (post-`0fb1c77`) |
| 3 | raccolta | always | — | ✅ | sempre eseguita; mediana cattura bimodalità skip/work |
| 4 | truppe | periodic 4h | counter X/4 (runtime) | ✅ | guard runtime non modellato (impatto trascurabile) |
| 5 | donazione | periodic 8h | — | ✅ | post-`b7f9634` snapshot timing |
| 6 | main_mission | daily 24h | — | ✅ | gate hour ≥ 20 UTC + reset 00:00 UTC |
| 7 | zaino | periodic 168h | — | ✅ | thundering herd settimanale, no fix |
| 8 | vip | daily 24h | VipState (cass+free) | ✅ | post-`680b475` daily branch |
| 9 | alleanza | periodic 4h | — | ✅ | task semplice |
| 10 | messaggi | periodic 4h | — | ✅ | post-WU124 fix `_Esito.OK→COMPLETATO` |
| 11 | arena | daily 24h | ArenaState (esaurite) | ✅ | post-`680b475` daily branch + ArenaState |
| 12 | arena_mercato | daily 24h | — | ✅ | post-`680b475` daily branch |
| 13 | district_showdown | always (window) | window UTC weekday/hour | ✅ | Ven 00:00 → Lun 00:00 UTC (post-`c710f34`) |
| 14 | store | periodic 8h | — | ✅ | task probabilistico (mercante itinerante) |
| 15 | radar | periodic 12h | — | ✅ | task semplice |
| 16 | radar_census | periodic 12h | — | ✅ | task analytics, flag OFF in prod |
| 17 | raccolta_chiusura | always | — | ✅ | sub-classe Raccolta, override percentile p75 (bimodalità) |

**Pattern di allineamento per schedule type**:

- **always** (interval_h=0): `task_globali` filter a monte + opzionale `_task_will_be_noop(name, istanza, tick_sleep_s, now)` per task con stato persistente. Coperti: `boost`, `rifornimento`, `district_showdown`.
- **periodic Nh**: predictor `elapsed_h >= N` confrontato con `last_run` da `state[ist].schedule.<nome>`. Allineato a `_e_dovuto_periodic` dell'orchestrator.
- **daily 24h** (post-`680b475`): predictor `last_dt < reset_oggi` con `reset_oggi = now_for_inst.replace(hour=0,...)`. Allineato a `_e_dovuto_daily` + `_reset_daily_corrente` dell'orchestrator (post-`951df2a` reset 00:00 UTC).

**Commit chiave sweep 05/05**:

| Commit | Fix |
|--------|-----|
| `133ba86` | Offset cumulativo applicato ai guard di stato (boost / DS) |
| `0fb1c77` | Rifornimento freshness check (DRL + provviste) a cavallo 00:00 UTC |
| `b7f9634` | Snapshot recorder "new_cycle" anche post-gap (was: `last_cycle_snap is not None`) |
| `951df2a` | Orchestrator reset daily 01:00 → 00:00 UTC + 3 test files |
| `c710f34` | District Showdown lunedì sempre fuori window (allineato config bot) |
| `680b475` | `_is_task_due` daily branch (allineato `_e_dovuto_daily`) |
| `fa45c7c` `841eac4` `5853b95` `87aa119` `96e849b` | Docstring/docs fix (main_mission/arena_mercato/store/radar/radar_census) |

**Convenzioni vincolanti**:

- Reset daily uniforme **00:00 UTC** in tutto il sistema: orchestrator (`_reset_daily_corrente`), stati persistenti (`_today_utc()`), reset gioco (missioni daily, DRL master, cassaforte VIP).
- Offset cumulativo `now_for_inst` propagato ai guard temporali (`_boost_will_skip`, `_district_showdown_will_skip`, `_rifornimento_will_skip`, `_is_task_due` daily branch).
- Esclusione FauMorfeus (master) hardcoded via `shared/instance_meta.is_master_instance` (frozenset).
- Window evento DS: caratteristica del gioco (3 giorni esatti Ven 00:00 → Lun 00:00 UTC), invariata.

**Guard di stato non modellati** (BoostState a parte): VipState, ArenaState, MainMissionState. Sono **ridondanti** post-WU79 perché `last_run` viene aggiornato anche su skip → schedule daily basta. Fix non necessario ma valutabile in futuro per maggiore precisione drilldown.

---

## 9. Dashboard FastAPI

Avvio: `run_dashboard_prod.bat` → uvicorn su `:8765`.

### 9.1 Pagine

| URL | Descrizione |
|-----|-------------|
| `/ui` | **Home**: card produzione istanze (con controlli inline post-WU142), configurazione 4-card (sistema · rifornimento · zaino · allocazione raccolta), sidebar farm (trend7gg + risorse + ora-tbl) |
| `/ui/advanced` | Bulk istanze + addestramento truppe (default globale + override per istanza) |
| `/ui/telemetria` | Tel-card: telemetria task, storico cicli, health 24h, trend 7gg, storico truppe, debug screenshot (pannello storico eventi rimosso in WU142) |
| `/ui/predictor-istanze` | Adaptive scheduler config + 🧮 simulazione greedy + cycle predictor + distribuzione empirica slot |
| `/ui/predictor` | redirect 302 → `/ui/predictor-istanze` (legacy) |
| `/ui/config/global` | Configurazione baseline (global_config.json) + bottone "↺ reset runtime" + "⬆ runtime → static" (promote) |
| `/ui/instance/<nome>` | Dettaglio singola istanza |
| `/docs` | OpenAPI auto-doc |

### 9.2 Endpoint chiave

| Endpoint | Metodo | Funzione |
|----------|--------|----------|
| `/api/config/globals` | PUT | Save sistema + task (HOME → dynamic) |
| `/api/config/rifornimento` | PUT | Save rifornimento config (HOME → dynamic) |
| `/api/config/zaino` | PUT | Save zaino config (HOME → dynamic) |
| `/api/config/allocazione` | PUT | Save allocazione raccolta (HOME → dynamic) |
| `/api/config/istanze` | PUT | Save istanze (CONFIG → static `instances.json`) |
| `/api/config/global` | PATCH | Save baseline `global_config.json` (CONFIG → static) |
| `/api/config/reset` | POST | Reset runtime_overrides ← static |
| `/api/config/promote` | POST | Promuove runtime → static (inverso del reset) |
| `/api/notifications` | PATCH | Email notifier config + alert flags |
| `/api/adaptive-scheduler` | PATCH | Adaptive scheduler flags + soglie precondizioni |
| `/api/adaptive-scheduler/preview` | GET | Greedy live preview + ordine persisted |
| `/api/maintenance/{start\|stop}` | POST | Toggle modalità manutenzione bot |
| `/api/debug-tasks/<task>/{enable\|disable}` | PATCH | Toggle debug screenshot per task |
| `/api/restart-bot` | POST/DELETE | Richiedi/cancella restart bot post-cycle (§11.4) |
| `/ui/partial/<panel>` | GET | HTMX partial per pannelli auto-refresh |

### 9.3 Pattern UI

- **HTMX** per refresh asincrono pannelli (no full reload)
- **Hot-reload config**: cambio runtime_overrides → attivo al prossimo tick
- **Static vs Dynamic** (regola WU140): config CONFIG → static (non hot,
  serve restart/reset per applicare); HOME → dynamic (hot)
- **Master istanza** ★ marker accanto al nome (FauMorfeus, hardcoded WU121)
- **Dashboard parla solo PROD** (DOOMSDAY_ROOT env var)

---

## 10. Tool CLI

Eseguibili standalone (no dipendenza dashboard):

| Tool | Funzione |
|------|----------|
| `tools/analisi_istanza_metrics.py` | Boot HOME, tick total, task durata, raccolta, ETA marcia |
| `tools/analisi_cap_nodi.py` | Capacità nominale + saturazione + copertura squadra |
| `tools/predict_cycle.py` | Stima T_ciclo + breakdown istanza (CLI cycle predictor) |
| `tools/predictor_backtest.py` | Backtest empirico Skip Predictor (offline, post-WU89 RIMOSSO) |
| `tools/predictor_shadow.py` | Replay storico decisioni predictor (offline) |
| `tools/report_copertura_ciclo.py` | Report istanza×ciclo SATURA/NON SATURA per invio |
| `python -m core.adaptive_scheduler --check` | Test precondizioni + score per istanza |
| `python -m core.cycle_predictor_calibration compute` | Forza ricalcolo factor globale |
| `python -m core.t_marcia_calibration compute` | Forza ricalcolo coefficienti per (ist, lv) |
| `python -m core.empirical_slot_predictor --summary` | Stato lookup table empirico |
| `python -m core.alerts trigger --type test --sev info ...` | Test trigger alert manuale |
| `python -m core.notifier {enqueue\|dispatch\|stats}` | Test queue email |

Tutti supportano `--prod` per leggere da `C:/doomsday-engine-prod/`.

---

## 11. Operations

### 11.1 Avvio bot

```
run_prod.bat            # produzione (12 istanze, --use-runtime --resume)
run_dev.bat             # dev locale, no MuMu boot
```

`run_prod.bat` esegue:

1. Pre-kill PowerShell per processi orfani (WU104)
2. Lancio `python main.py --no-dashboard --use-runtime --resume`
3. **Loop wrapper `:run_loop`** (06/05): se il bot esce con
   `ERRORLEVEL=100` → timeout 5s + relaunch automatico. Per altri
   exit code (0 normale / 1 errore) → no restart automatico.

L'exit code 100 è riservato al `restart_scheduler` (vedi §11.4).

### 11.2 Avvio dashboard

```
run_dashboard_prod.bat  # uvicorn su :8765, env DOOMSDAY_ROOT=prod
```

### 11.3 Modalità manutenzione

Toggle da dashboard (banner top sempre visibile) o via
`/api/maintenance/{start|stop}`. Bot in pausa fino a `auto_resume_ts`.
File flag: `data/maintenance.flag`.

### 11.4 Restart sicuro + scheduler automatico (06/05)

**Regola invariante**: bot **mai restart mid-tick**. State coerente
solo a fine ciclo (post `chiudi_tick` di FauMorfeus, ultima istanza).

**Architettura "bot decide, .bat riavvia"**:

```
+----------------------+      exit_code      +-----------------+
|  main.py             | -----  100  ------> | run_prod.bat    |
|  loop cicli          |                     | :run_loop label |
|  + should_restart()  | <-- relaunch ----- | timeout 5s      |
+----------------------+                     +-----------------+
```

[`core/restart_scheduler.py`](../core/restart_scheduler.py) — pure
logic con 4 trigger valutati in OR a fine ciclo:

| # | Trigger | Config | Use case |
|---|---------|--------|----------|
| 1 | File flag | `data/restart_requested.flag` | Bottone dashboard "🔄 restart fine ciclo" |
| 2 | Schedule cron-like | `globali.restart_schedule_hh_mm: "03:00"` | Restart notturno automatico |
| 3 | Cicli max | `globali.restart_after_cicli: 200` | Anti memory-leak / refresh ADB |
| 4 | (cleanup) | `init_boot()` al startup | Cancella flag pendenti, azzera contatore |

**Flusso end-to-end**:

1. **Init startup** (`main.py` post args): `init_boot()` cancella
   `data/restart_requested.flag` se presente + reset contatore
   `cicli_da_boot=0` in `data/restart_state.json`.
2. **Post-cycle hook** (`main.py` dopo `record_cicle_end`):
   `mark_cycle_completed(ciclo)` incrementa contatore +
   `should_restart_now()` valuta trigger.
3. **Match trigger**: `sys.exit(EXIT_CODE_RESTART=100)` con log esplicativo.
4. **Bat loop**: `if %ERRORLEVEL%==100 → timeout 5s + goto :run_loop`.
5. **Nuovo bot**: `init_boot()` cancella flag + reset state →
   `is_restart_requested()=False` al prossimo check.

**Endpoint API**:

| Endpoint | Metodo | Funzione |
|----------|--------|----------|
| `/api/restart-bot/status` | GET | Stato richiesta + state contatore |
| `/api/restart-bot` | POST | Crea flag `data/restart_requested.flag` |
| `/api/restart-bot` | DELETE | Cancella flag pendente |

**Dashboard UI**: bottone `🔄 restart fine ciclo` nel banner topbar
(accanto a `🔧 manutenzione`). Quando flag attivo → banner blu
"RESTART BOT PENDENTE — attesa fine ciclo" con bottone annulla.

**Sicurezza intrinseca**:
- Restart MAI mid-tick (check post-`chiudi_tick` ultima istanza)
- State coerente: tutti i task hanno chiuso, salvato su disco
- Timer 5s tra exit e relaunch evita race con dashboard reader
- Flag cancellato al boot del nuovo bot per evitare loop infinito

### 11.5 Debug screenshot per task

WU115 hot-reload: toggle pill in `/ui/telemetria` →
`data/<task>_debug/<istanza>_<ts>_<idx>_<label>.png` automatico
solo on anomalia. Cleanup 7gg automatico via `cleanup_old()`.

---

## 12. Riferimenti

- [`ROADMAP.md`](../ROADMAP.md) — issue tracker + sessioni di lavoro
- [`CLAUDE.md`](../CLAUDE.md) — vincoli operativi del progetto
- [`.claude/CLAUDE.md`](../.claude/CLAUDE.md) — regole architetturali
- [`.claude/SESSION.md`](../.claude/SESSION.md) — handoff sessioni
  (locale, non versionato)
- [`radar_tool/METODOLOGIA.md`](../radar_tool/METODOLOGIA.md) — sotto-modulo
  classificatore radar
