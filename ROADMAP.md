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
| RadarCensusTask | 90 | 12h | periodic | disabilitato default |
| RifornimentoTask | 100 | — | always | always-run con guard pre-condizioni (soglie risorse, slot) |
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
| `telemetry.py` | **WU38-44 (Issue #53)** — pipeline telemetria. `TaskTelemetry` dataclass + writer `record()` + reader `iter_events()/iter_events_range()` + rollup engine (`compute_rollup`, `save_rollup`, `cleanup_old_rollups`) + live writer (`compute_live_24h`, `live_writer_loop`) + backfill (`backfill_from_logs`) + anomaly detector (`detect_anomaly_patterns`). Storage `data/telemetry/{events,rollup,live.json}`. Self-test integrato. |
| `launcher.py` | Avvio/chiusura istanze MuMu via `MuMuManager.exe` CLI. `avvia_player()` (MuMuNxMain.exe Win11), `avvia_istanza()` (launch + adb connect + `_avvia_gioco()` con am start + monkey + foreground check, Issue #46), `attendi_home()` (polling schermata + monkey recovery, Issue #46), `reset_istanza()`, `chiudi_istanza()`. |
| `device.py` | Astrazione ADB per singola istanza. `AdbDevice(host, port, name)`: screenshot (Screenshot con `.frame` ndarray), tap, back, swipe. `Screenshot.match_template()` usato da matcher. `@dataclass MatchResult(found, score, cx, cy)`. |
| `navigator.py` | Navigazione inter-schermata game. `schermata_corrente()` (Screen.HOME/MAP/UNKNOWN via template match), `vai_in_home()`, `vai_in_mappa()`, `tap_barra(ctx, voce)` (barra inferiore: campaign/alliance/hero/bag/beast). |
| `state.py` | Stato persistente per-istanza. `InstanceState(path)` save/load atomico tmp+fsync+os.replace. Sottocampi: rifornimento, daily_tasks, metrics, schedule, boost, vip, arena. **WU34**: `RifornimentoState` esteso con `inviato_lordo_oggi`, `tassa_oggi`, `tassa_pct_avg` (running average), `eta_rientro_ultima` (sync raccolta-rifornimento Issue #64). |
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
| `services/stats_reader.py` | Read-only stats da state/engine_status. `get_engine_status()`, `get_all_stats()`, `get_storico()`, `get_risorse_farm()` (aggregato farm). Filtro OCR anomalie >100M per spedizione (Issue #16/#27). **WU34/35**: `MorfeusState`, `RifornimentoIstanza` esteso con `provviste_residue_netta` + `tassa_pct_avg`. **WU39**: `_load_morfeus_state()` legge `data/morfeus_state.json`. |
| `services/log_reader.py` | Tail efficiente log file con offset tracking. |
| `services/telemetry_reader.py` | **WU37+42 (Issue #53)** — reader API dual-source per dashboard. `get_task_kpi_24h()`, `get_health_24h()`, `get_ciclo_status()`, `get_trend_7gg()`. Source primaria: `data/telemetry/live.json` (precomputato). Fallback automatico al log scan WU37 (rolling 24h su `logs/FAU_*.jsonl` + `bot.log`). Cache TTL 30s. Pattern detector (WU44) integrato in health. |
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
