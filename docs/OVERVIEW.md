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
  Per ogni ISTANZA in ordine:
     Thread _thread_istanza(istanza):
       1. inizia_tick(metrics buffer in-memory)
       2. ── WU89-Step4: SKIP PREDICTOR HOOK (flag-driven) ──
          Se enabled: predict() → SkipDecision
          Se applied (LIVE+should_skip): early return, no avvio MuMu
       3. avvia_istanza(MuMu boot via MuMuManager)
       4. attendi_home (loop polling + dismiss banners + settings cleanup)
       5. ── core/troops_reader: snapshot Total Squads (1×/die UTC) ──
       6. Build TaskContext + Orchestrator
       7. Registra task da task_setup.json (filtrati per tipologia istanza)
       8. orc.tick() → esegue ogni task con priority + scheduling
          Per ogni task: should_run() guard → run() → save state
       9. chiudi_tick(persisti metriche + telemetry events + cicli.json)
       10. chiudi_istanza(MuMu shutdown clean)
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

### 4.10 `core/skip_predictor.py`

Decide se skippare il tick di una istanza (saving ~600s boot+task).
5 regole + guardrail anti-stallo + master exclusion:

1. `squadre_fuori` (score 0.90, refactor empirico) — slot saturi +
   T_min_rientro > gap_atteso
2. `trend_magro` (0.65) — avg_invii_3 < 0.5
3. `low_total_invii` (0.60, WU103) — avg(rac+rif)_3 < target × 0.5
4. `recovery` (0.75) — outcome degraded + gap < 5min
5. `low_prod` (0.55) — prod_h < 100K (con growth_phase block)

Modello empirico: `T_marcia = 2×eta + saturazione × T_L_max[livello, istanza]`.
`saturazione = load_squadra / cap_nominale_L_max` (post-WU116).
`T_L_max` da `config/predictor_t_l_max.json`.

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

[tasks/boost.py](../tasks/boost.py) — Attiva booster Gathering Speed.

**Flusso**: HOME → tap badge boost → swipe lista per trovare "Gathering
Speed" → tap card USE → seleziona durata (8h default) → tap conferma.

**Parametri**:
- `tipo_default="8h"` (alternative: 1h, 24h)
- Stato in `BoostState` (core/state.py): `scadenza_iso`,
  `ultimo_check_ts`. `should_run()` legge la scadenza — se
  `now > scadenza` → True

**Regole speciali**:
- WU115 debug per task abilitabile da dashboard
- Se boost già attivo → registra `scadenza` corrente, return success
- `wait_after_tap_speed: 2.0s` (DELAY UI vincolante)
- `_salva_debug_shot` disabilitato (WU59 cleanup 105MB)

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
mappa Radar Station.

**Flusso**:
1. Verifica badge rosso icona Radar (pixel check numpy)
2. Tap icona → attesa apertura mappa + notifiche
3. Loop raccolta:
   - screenshot
   - find pallini rossi (connected components BFS numpy)
   - tap su ognuno
4. 2 scan vuoti consecutivi → exit
5. Census icone (RadarCensusTask opzionale)

### 5.16 RadarCensusTask (priority 100, periodic 12h)

[tasks/radar_census.py](../tasks/radar_census.py) — Training data
collection per classifier RF (icone radar).

**Flusso**: dalla schermata radar aperta → screenshot → detector
icone (radar_tool) → crops → classify RF → cataloga in
`radar_archive/census/YYYYMMDD_HHMMSS_<istanza>/`.

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

Override runtime per dashboard. Modificato live, letto a ogni tick:

- `globali.task.<nome>: bool` — flag abilitazione task
- `globali.sistema.tick_sleep_min: int` — minuti tra cicli
- `globali.skip_predictor_enabled` / `shadow_only` — predictor flags
- `globali.debug_tasks.<nome>: bool` — debug screenshot per task (WU115)
- `istanze.<nome>.<campo>` — override per istanza

### 6.4 `config/task_setup.json`

Schema scheduler (priority + interval + schedule type) per ogni task.
Vincolante: `_TASK_SETUP` in `main.py` deve essere identico.

### 6.5 `config/predictor_t_l_max.json`

Baseline empirica T_L_max (minuti gather) per livello +
multiplier per istanza. Validato FAU_00 best gatherers L7=125min /
L6=114min, multiplier istanze farm 1.3-1.5x.

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
| `data/predictor_decisions.jsonl` | decisioni skip predictor live | append at skip hook |
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

## 8. Predictor (cycle + skip)

Vedi sezione 4.9, 4.10, 4.11 + dashboard `/ui/predictor`.

**Cycle Duration Predictor**: stima T_ciclo dato un setup
(istanze + task + interval/last_run). Output: T_ciclo_min,
breakdown per istanza, schedule_debug DUE/SKIP.

**Skip Predictor**: decide se skippare il tick di una istanza.
Modalità shadow (log+telemetria, no apply) o LIVE (skip applicato).

**Workflow attivazione**:
1. Restart bot — flag default off → bot identico
2. Attivare shadow da dashboard (home → sistema → predictor)
3. Osservare 6-12 cicli — analisi `predictor_decisions.jsonl`
4. Se OK precision/recall → attivare LIVE (saving stimato 480-600s/skip)

**Accuracy tracking**: snapshot ogni 15min auto-correlato con cycle
in corso. A fine ciclo: error% per ogni snapshot vs actual_min.
Pannello `/ui/predictor` mostra storia.

### 8.1 Allineamento bot ↔ predictor (sweep 05/05/2026)

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
| `/ui` | **Home**: card produzione istanze, configurazione 4-card (sistema · rifornimento · zaino · allocazione), tabella istanze, sidebar farm (trend7gg + risorse + ora-tbl) |
| `/ui/telemetria` | 8 tel-card: telemetria task, storico cicli, health 24h, ciclo corrente, tempi medi 7gg, trend 7gg, storico truppe, debug screenshot, copertura squadre |
| `/ui/predictor` | Cycle predictor + drilldown what-if + accuracy snapshots + skip predictor live |
| `/ui/storico` | Tabella storico eventi filtrabile per istanza + task |
| `/ui/config/global` | Configurazione baseline (global_config.json) — tutte le sezioni |
| `/ui/instance/<nome>` | Dettaglio singola istanza |
| `/docs` | OpenAPI auto-doc |

### 9.2 Endpoint chiave

| Endpoint | Metodo | Funzione |
|----------|--------|----------|
| `/api/config/globals` | PUT | Save sistema + task + skip_predictor flags |
| `/api/config/rifornimento` | PUT | Save rifornimento config |
| `/api/config/istanze` | PUT | Save istanze (instances.json + runtime_overrides) |
| `/api/maintenance/{start\|stop}` | POST | Toggle modalità manutenzione bot |
| `/api/debug-tasks/<task>/{enable\|disable}` | PATCH | Toggle debug screenshot per task |
| `/ui/partial/<panel>` | GET | HTMX partial per pannelli auto-refresh |

### 9.3 Pattern UI

- **HTMX** per refresh asincrono pannelli (no full reload)
- **Hot-reload config**: cambio runtime_overrides → attivo al prossimo tick
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
| `tools/predictor_backtest.py` | Backtest empirico Skip Predictor su dati storici |
| `tools/predictor_shadow.py` | Replay storico decisioni predictor (Step 3) |
| `tools/report_copertura_ciclo.py` | Report istanza×ciclo SATURA/NON SATURA per invio |

Tutti supportano `--prod` per leggere da `C:/doomsday-engine-prod/`.

---

## 11. Operations

### 11.1 Avvio bot

```
run_prod.bat            # produzione (12 istanze, --use-runtime --resume)
run_dev.bat             # dev locale, no MuMu boot
```

`run_prod.bat` esegue pre-kill PowerShell per processi orfani
(WU104), poi lancia `python main.py --no-dashboard --use-runtime
--resume`.

### 11.2 Avvio dashboard

```
run_dashboard_prod.bat  # uvicorn su :8765, env DOOMSDAY_ROOT=prod
```

### 11.3 Modalità manutenzione

Toggle da dashboard (banner top sempre visibile) o via
`/api/maintenance/{start|stop}`. Bot in pausa fino a `auto_resume_ts`.
File flag: `data/maintenance.flag`.

### 11.4 Restart sicuro

Bot **mai restart silente**. L'utente lancia manualmente
`run_prod.bat`. Aspetta sempre la chiusura naturale dell'istanza
corrente (Thread completato/chiudi_istanza) per evitare state
corrotto.

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
