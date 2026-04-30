# SESSION.md — Handoff Doomsday Engine V6

## Sessione 30/04/2026 mattina+pomeriggio — Arena fix completi + rebuild truppe (WU74-83)

### Stato finale sessione

**Bot prod fermato** (test giornata terminato 30/04 ~12:55 locale). Driver
DirectX validato 864/864 ADB ONLINE su 6 sfide test. Tutti fix arena
deployed: WU74-83 + Issue #88+89 + WU85 Glory.

### Aggiunte 30/04 mattina+pomeriggio

| WU | Cosa | Validazione |
|----|------|-------------|
| WU82 | Arena wait battaglia 60s → 15s (skip ON + DirectX = battaglie <10s) | Saving 225s/ciclo arena |
| WU83 | Rebuild truppe pre-1ª sfida del giorno (1×/die UTC) | FAU_06 4 celle +59% power, FAU_00 5 celle invariato (già max) |

### Flow WU83 dettagliato

Coord calibrate live (cross-istanza):
- 5 rimozioni: x=80, y=80/148/216/283/351
- 5 aperture cella: x=42, y=100/170/240/310/380
- READY auto-deploy: (723, 482)

N celle = `max_squadre` config. State `data/arena_deploy_state.json` UTC.

Trigger: `if run.sfide_eseguite == 0 and not _deploy_done_today(nome)` →
rebuild → mark today → re-check START CHALLENGE.

### Pre-condizioni prossima sessione

- Bot fermato, dashboard attiva
- Tutti fix WU74-83 + Issue #88+89 + WU77 deployed prod e syncati
- State arena reset, checkpoint da FAU_02 (last position)
- Driver DirectX su tutte 11 istanze (manuale utente)

### Next steps suggeriti

1. Restart bot in produzione (resume da checkpoint)
2. Validazione runtime arena complete su tutto ciclo
3. Issue #83 match dinamico Challenge button (effort ~30 righe)
4. Issue #81 Update Version popup gioco

---

## Sessione 30/04/2026 mattina — Arena fix completi (cascade + template + tap dinamico)

### Stato finale sessione

**Bot prod attivo** (PID 3112, finestra cmd visibile ~10:55) — ciclo 1
da FAU_02 (resume da checkpoint manuale). State arena resettato per
tutte 11 istanze (`schedule.arena = ''`). Monitor `bdyw1n7bw` su arena
+ raccolta slot.

### Driver MuMu DirectX (Issue #88)

**TUTTE le 11 istanze MuMu** richiedono switch driver Vulkan → DirectX
(manuale utente in MuMu Settings → Display). Senza, cascade ADB durante
animazione battaglia 3D.

**Validazione**: 864/864 polling ADB ONLINE su 6 sfide (FAU_00 + FAU_01
+ FAU_10) post-switch. Pre-switch: cascade endemica.

### Lavori completati questa sessione (30/04 mattina)

| WU | Fix | Status runtime |
|----|-----|---------------|
| WU77 | Template Failure NEW + ROI (155×46, score 0.998) | ✅ deployed |
| WU78-rev | Settings HIGH/MID/HIGH coord live FAU_00: G(809,123) F(717,209) O(229,330) | ✅ |
| WU79 | Issue #84 fix `last_run` solo on success/skipped | ✅ |
| WU80 | Tap dinamico Continue (loc match invece coord fisse) | ✅ validato |
| WU81 | Soglia victory/failure 0.80 → 0.90 (anti-falso 0.847) | ✅ validato |
| Issue #88 | Driver Vulkan→DirectX (manuale) | ✅ utente done |
| Issue #89 | Template Failure/Victory/Continue NEW | ✅ tutti estratti |
| Template Victory NEW | Estratto live FAU_00 30/04 (rank 81→53) | ✅ deployed |

### Test arena live (totali)

| Istanza | Sfide | V | F | ADB ONLINE |
|---------|-------|---|---|------------|
| FAU_10 | 3 (test) | — | — | 271/271 |
| FAU_00 | 2 | 1 | 1 | 432/432 |
| FAU_01 | 1 | — | 1 | 161/161 |
| **Totale** | **6** | **1** | **2** | **864/864** ✓ |

### Pre-condizioni prossima sessione

- Bot in esecuzione PID 3112 — lasciato girare ciclo 1 da FAU_02
- State arena resettato (`schedule.arena = ''` per tutte 11 istanze)
- WU74-81 + Issue #88+89 tutti attivi
- Driver DirectX su tutte istanze (manuale utente, da verificare 1×11)

### Issues aperte rimaste

| # | Priorità | Note |
|---|----------|------|
| 81 | ALTA | Update Version popup gioco (no fix automatico, richiede APK update) |
| 83 | ALTA | Arena `_TAP_ULTIMA_SFIDA` cieco (745,482) match dinamico TODO |
| 65 | BASSA | Wait > 60s rifornimento → anticipare task post-raccolta |
| 23 | BASSA | smoke_test GlobalConfig dict vs dataclass |
| 25 | BASSA | Tracciamento diamanti nello state |
| 19 | BASSA | Race buffer stdout ultima istanza fine ciclo |

### Next steps suggeriti

1. Validare arena runtime sui prossimi cicli (WU74-81 + DirectX)
2. Quando capita Glory tier-up reale → validare Issue #85 fix template
3. Fix #83 match dinamico Challenge button (effort ~30 righe)

---

## Sessione 29/04/2026 sera — Pulizia cache + truppe storico + dashboard + Glory + OCR slot WU64-71

### Stato finale sessione

**Bot prod attivo** (PID 3060, lanciato in finestra cmd visibile ~21:23) —
ciclo 6 in corso da FAU_00. Monitor `blfp65lyu` persistente su slot/arena.

### Lavori completati questa sessione

| WU | Cosa | Stato runtime |
|----|------|---------------|
| **WU64** | Pulizia cache 1×/die in fase settings (Avatar→Settings→Help→Clear cache→polling CLOSE→CLOSE). State `data/cache_state.json` | ✅ Validato FAU_10 c4 + FAU_00 c5 (CLOSE 6s, ~22s pulizia) |
| **WU65** | Lettura Total Squads 1×/die (`core/troops_reader.py`). Storage `data/storico_truppe.json` 365gg | ✅ Validato FAU_10=112,848, FAU_00=2,665,764 |
| **WU66** | Dashboard truppe — Layout A (riga card 🪖+Δ7gg+sparkline) + Layout B (sezione storico 8gg tabella ordinata Δ% desc) | ✅ Endpoint `/ui/partial/truppe-storico` testato HTTP 200 |
| **#85** | Glory ROI fix `(380,410,570,458)→(345,405,615,465)` 270×60 — root cause: template 225×35 > ROI 190×48 → cv2.matchTemplate impossibile | ✅ Sync prod, attivo dal restart |
| **WU67** | Raccolta livello — reset+conta sostituito con delta diretto. Saving 1.5-2s/raccolta | ✅ Sync prod, attivo dal restart |
| **WU68** | Sanity OCR slot post-marcia: `attive_map < attive_pre` → fallback HOME singolo | ✅ Sync prod, attivo dal restart |
| **WU69** | Pattern slot pieni: 2× maschera_not_opened consecutivi → break loop con `_raccolta_slot_pieni=True`. Saving 60-90s/ciclo patologico | ✅ Sync prod, attivo dal restart |
| **WU70** | **OCR slot SX-only ensemble (proposta utente)**: legge SOLO cifra SX in ROI 10×24 isolata con 3 PSM (10/8/7), sanity pre-vote `0≤v≤totale_noto`, majority vote, totale=config | ✅ **VALIDATO RUNTIME FAU_00 c6**: pre-fix=skip 0 inviate, post-fix=1 inviata pulita |
| **WU71** | Stabilizzazione HOME polling 3s→1s. Saving ~110s/ciclo | ✅ Sync prod, **attivo al prossimo restart spontaneo** |

### Sequenza decisioni utente chiave

1. **Pulizia cache 1×/die** — esplorazione manuale guidata utente su FAU_10
   per trovare coord. Coord finale Help (570,235), Clear cache (666,375).
2. **Lettura truppe** — solo "Total Squads", non Squad Might né Travel Queue.
3. **Layout dashboard A+B** approvato.
4. **Restart bot multipli**: PID 16188 → 19652 → 19976 → 3060 (per WU70,
   partito da FAU_00 perché istanza target con bug 5→7).
5. **Bug "5→7" diagnosticato**: pattern OCR confonde SX nel contesto X/Y.
   Fix utente-proposto: tagliare DX e "/" dalla ROI → WU70.
6. **Polling stab HOME 3s→1s** richiesto utente → WU71.

### Pre-condizioni prossima sessione

- Bot in esecuzione PID 3060 — lasciato girare. Monitor notturno persistente.
- WU71 attivo solo dopo restart spontaneo.
- `config/runtime_overrides.json` invariato (`raccolta_ocr_debug=false`)
- `data/cache_state.json`: FAU_00, FAU_10 marked oggi
- `data/storico_truppe.json`: 2 entry (FAU_00 + FAU_10). 9 istanze rimanenti
  popoleranno al loro primo settings di domani.
- Δ7gg disponibile dal **2026-05-06** (7gg dal primo log).

### Issues aperte rimanenti

- **#83**: Arena `_TAP_ULTIMA_SFIDA` cieco (Watch vs Challenge) — ALTA
- **#84**: Orchestrator `entry.last_run` aggiornato anche su fail — ALTA
- **#81**: Update Version popup gioco — ALTA
- **#65**: Wait > 60s rifornimento → anticipare task post-raccolta — BASSA
- **#23**: smoke_test GlobalConfig dict vs dataclass — BASSA

### Next steps suggeriti

1. **Restart spontaneo bot** per attivare WU71 (saving 110s/ciclo HOME stab)
2. **Aspettare 7gg** per primi dati Δ7gg significativi nel pannello dashboard
   storico truppe
3. **Indagare #83/#84 arena** appena prossimo evento Glory si manifesta

---

## Sessione 29/04/2026 pomeriggio (continua 3) — Nuovo task TRUPPE

### Nuovo task `tasks/truppe.py` — addestramento automatico 4 caserme

**Scenario**: client gioco mostra in colonna sx HOME un'icona scudo+2 fucili
con counter `X/4` dove X = caserme correntemente in addestramento (0..4).
Tap sull'icona porta automaticamente alla prossima caserma libera.

**Coord FISSE calibrate su FAU_05** (esplorazione manuale guidata utente):
- `(30, 247)` — icona pannello caserme HOME
- `(564, 382)` — cerchio "Train" del menu mappa post-tap pannello
- `(794, 471)` — pulsante TRAIN giallo (Squad Training screen)
- `(687, 508)` — checkbox Fast Training
- box pixel `(676,497)→(699,518)` — sample stato checkbox
- soglia `R-mean > 110 → ON`
- zona OCR counter: `(12, 264, 30, 282)`

**OCR cascade**: `otsu` primario funziona per X ∈ {1,2,3,4}, `binary`
fallback per X==0 (otsu lo perde). Validato su tutti i 5 stati 0/4..4/4
in test reale.

**Test reale FAU_05** (29/04 14:55-15:10): 4 cicli consecutivi 0/4 → 4/4
tutti OK con stesse coord. 4 tipi caserme: Infantry (Ruffian) / Rider
(Iron Cavalry) / Ranged (Ranger) / Engine (Rover). Checkbox sempre OFF.

**Vincolo**: Fast Training SEMPRE disabilitato (premium-free).

**Flow MVP**:
1. `vai_in_home()`
2. Leggi counter X (OCR cascade)
3. Se X==4 → skip
4. Loop (4-X) cicli: pannello → cerchio Train → check pixel checkbox
   → tap correttivo se ON → TRAIN. Delay 5s/step.
5. Re-leggi counter (best effort)
6. `tap_barra("city")` ritorno HOME

**Integrazione**:
- `tasks/truppe.py` — NUOVO
- `config/task_setup.json` — `TruppeTask` **priority 18, periodic 4h**
  (subito dopo `RaccoltaTask=15`, prima di `DonazioneTask=20`. I primi 3
  sono sempre Boost→Rifornimento→Raccolta, gli altri seguono)
- `main.py::_import_tasks` — aggiunto
- `dashboard/models.py::TaskFlags` — `truppe: bool = True`
- `dashboard/routers/api_config_overrides.py` — `valid_tasks` esteso
- `dashboard/app.py::partial_task_flags_v2::ORDER` — `truppe` in pill UI
  (Row 3 accanto ad `arena`); `district_showdown` orfano in ultima riga

**4 template estratti** in `templates/pin/` (NON usati dal MVP, per
robustezza futura):
- `pin_truppe_pannello.png` (55×36)
- `pin_truppe_train_btn.png` (100×29)
- `pin_truppe_check_off.png` (23×21)
- `pin_truppe_check_on.png` (23×21)

### WU63 — Audit debug PNG + cleanup (29/04 15:30-15:45)

**Audit** dei 6 punti che scrivono PNG durante runtime bot prod:
1. `shared/ocr_dataset.py` (WU55 dataset) — toggle `raccolta_ocr_debug` era
   `true` in prod runtime_overrides nonostante memoria/SESSION dicessero
   "spegnerlo". 1530 PNG / 445 MB accumulati. **Spento ora** → `false`.
2. `core/launcher.py::_save_discovery_snapshot` — discovery banner UNKNOWN.
   ✅ MANTENUTO (utente: "boot_unknown lasciamolo"). Cap 4/ciclo, ~9 MB.
3. `shared/ocr_helpers.py:414` — slot OCR fail (2 file fissi sovrascritti).
   Trascurabile.
4. `tasks/raccolta.py::_salva_debug_verifica` — solo su anomalia score.
   Mai scattato finora.
5. `tasks/raccolta.py::_salva_debug_lv_panel` — cap interno MAX_DEBUG_FILES.
   Mai scattato finora.
6. `tasks/boost.py::_salva_debug_shot` — chiamate commentate (Issue #59).

**Cleanup file accumulati in PROD**:
- `data/ocr_dataset/` 2040 file 445 MB → cancellati
- `debug_task/screenshots/` 1 file 2 MB → cancellato
- `debug_task/vai_in_home_unknown/` 3 file 2 MB → cancellati (deprecato #63)
- `debug_task/boot_unknown/` 11 file 9 MB → **MANTENUTO**

**Totale**: **~448 MB liberati**. Hot-reload toggle al prossimo tick.

### Tabella `_TASK_SETUP` in ROADMAP riallineata (29/04)

Era obsoleta da molti riordini. Ora aggiornata a `config/task_setup.json`
attuale con TruppeTask priority 18 + tutti i 16 task in ordine reale.

### Stato 29/04 ore 15:45
- **FAU_05**: counter caserme 4/4 (test concluso)
- **Bot prod**: in pausa, modalità raccolta-only (invariato)
- **tasks/truppe.py**: in dev e prod ✅
- **`raccolta_ocr_debug=false`** in prod runtime_overrides ✅
- **~448 MB** liberati su disco prod ✅
- **ROADMAP `_TASK_SETUP` table**: aggiornata e allineata a task_setup.json ✅

### Prossimo step
1. Sync prod: `tasks/truppe.py` + 4 PIN + `config/task_setup.json` + `main.py` +
   `dashboard/models.py` + `dashboard/routers/api_config_overrides.py`.
2. Restart bot prod per attivare TruppeTask al prossimo ciclo (priority 8 →
   parte subito dopo BoostTask, prima di RifornimentoTask).
3. Validazione runtime: aspettare counter X<4 in qualche istanza per vedere
   il task in azione (l'utente può forzare con instant training/cancel).

---

## Sessione 29/04/2026 pomeriggio (continua 2) — Test FAU_03 reinstallato

### Test FAU_03 (29/04 ore 13:16-13:19, 3.2 min totali)

Script: `c:\tmp\test_fau03_settings_arena.py` (clone test_fau02 con porta 16480
+ NAME=FAU_03 + helper `_dismiss_glory_if_present()` per fix #85).

**Sequenza testata**:
- PRE-FASE 1: dismiss Glory popup (stato corrente, opzionale)
- FASE 1: settings lightweight (Graphics/Frame/Optimize LOW)
- FASE 2: Campaign → Arena of Doom → Glory check (opzionale) → 5 sfide

**Risultati**:

| Fase | Esito | Note |
|------|-------|------|
| PRE Glory dismiss | ⚠️ NON esercitato | `found=False score=0.000` — popup non visibile all'avvio (visto alle 13:08 nello screenshot, sparito alle 13:16:08 prima del lancio test) |
| FASE 1 Settings | ✅ 22.5s | Optimize template score 0.998 (già attivo) |
| Glory post-Arena of Doom | ⚠️ NON esercitato | `found=False score=0.000` |
| FASE 2 Arena | ✅ 159.6s — 5/5 sfide @ 31.9s/sfida | Identico a FAU_02 (156.2s @ 31.2s) |

**Issue #85 template Glory: NON validato in questa sessione** — in nessuno
dei 2 hook il popup era presente. Il PNG nuovo (8KB del 12:36) e la ROI
espansa `(380,410,570,458)` sono in posizione ma non esercitati. Validazione
rimandata al prossimo cambio tier in produzione (oppure forzando visivamente
il popup e ripetendo match isolato).

**FAU_03 confermato stabile post-reinstallazione**: no cascade ADB, no freeze,
arena 5/5 = pattern identico FAU_02. Pulizia/reinstallazione effettiva.

### WU61 — Integrazione `imposta_settings_lightweight()` in `core/launcher.py`

**Hook**: `attendi_home()` riga ~976, dopo `nav.vai_in_home()` con `ok=True`
e prima del return. Try/except con lazy import (`from core.settings_helper
import imposta_settings_lightweight`). MiniCtx `_SettingsCtx` con `device`
+ `matcher` + `navigator`. Errori non bloccanti — solo log warn.

**Effetto**: ad ogni avvio istanza, dopo HOME confermata, applica i 3 settings
lightweight (~22s/istanza). Idempotente per Optimize (template check).

**Costo aggregato**: 12 istanze × 22s × 2 cicli/h ≈ 9 min/h aggiuntivi.

### Sync prod 29/04 ore 13:22

`sync_prod.bat` eseguito. File critici in prod (verifica `ls`):
- `core/launcher.py` (47670 bytes, contiene WU60 hook)
- `core/settings_helper.py` (7808 bytes)
- `tasks/arena.py` (27769 bytes, fix #85 coord/ROI)
- `templates/pin/pin_arena_07_glory.png` (8006 bytes — nuovo PNG)
- `templates/pin/pin_settings_optimize_low_active.png` (2301 bytes)

ROADMAP.md propagato a prod via sync (è incluso in xcopy).

### Stato 29/04 ore 13:23
- **FAU_02**: reinstallato + test arena 5/5 OK (12:40)
- **FAU_03**: reinstallato + test settings + arena 5/5 OK (13:19)
- **Bot prod**: in pausa, modalità raccolta-only — **DA RIAVVIARE** per attivare
  hook settings lightweight in `attendi_home`
- **arena.py / pin_arena_07_glory.png**: ✅ sync prod
- **launcher.py / settings_helper.py / pin_settings_optimize_low_active.png**: ✅ sync prod

### Prossimo step
1. **Restart bot prod** (decisione utente — bot in raccolta-only, decisione
   timing libera). Hook settings si attiverà al primo avvio istanza dopo restart.
2. Validazione end-to-end fix #85 (popup Glory) al prossimo cambio tier in prod.
3. Test FAU_04+ se utente prosegue reinstallazione istanze.
4. Re-abilitare arena su prod e re-validare 11 istanze (post-restart).

---

## Sessione 29/04/2026 pomeriggio (continua) — Test arena FAU_02 + fix template Glory

### Test arena standalone FAU_02 reinstallato (29/04 12:40)

Script: `c:\tmp\test_fau02_arena_only.py` (estratto FASE 2 di
`test_fau02_settings_arena.py`, partendo da FAU_02 in HOME).

**Risultato**: 5/5 sfide completate in 156.2s (31.2s/sfida), nessun freeze.
Su FAU_02 pre-pulizia (29/04 mattina) freezava a sfida 2.

**Limite del test**: tap a coord fisse senza match dinamico — pattern
fragile, race condition #83 non riprodotta solo per timing favorevole +
istanza pulita. **Da non promuovere a prod senza pin check**.

### Fix template Glory popup tier-up (Issue #85)

Utente segnala che la schermata "Congratulations / Glory Silver" non era
nel test e va comunque gestita in prod. Verifica codice prod:

- **Logica già presente** in `tasks/arena.py` (3 hook):
  - `_gestisci_popup_glory()` post-tap Arena of Doom
  - GUARD-GLORY pre-sfida nel loop `_esegui_sfida`
  - POST-CONTINUE post-vittoria (cambio tier mid-session)
- **Bug**: `pin_arena_07_glory.png` cattura il banner header
  "Arena of Glory" (arancione, in alto), NON il pulsante Continue
  giallo del popup tier-up. → check fallisce silenziosamente.

**Modifiche `tasks/arena.py`**:
- Coord `_TAP_GLORY_CONTINUE`: `(471, 432)` → `(473, 432)` (utente).
- ROI `"glory"`: `(379, 418, 564, 447)` (185×29) → `(380, 410, 570, 458)`
  (190×48) — accomoda template ~177×40 px.
- Docstring header file + `_gestisci_popup_glory()` chiariti.

**Pendente**: utente deve sostituire `templates/pin/pin_arena_07_glory.png`
con il pin Continue giallo allegato. Una volta fatto: sync prod + restart.

### Stato 29/04 ore 12:50
- **FAU_02**: reinstallato, test arena 5/5 OK con script standalone.
- **FAU_03**: utente in fase di reinstallazione.
- **Bot prod**: in pausa, modalità raccolta-only (invariato).
- **arena.py**: aggiornato in dev, **non ancora sync prod** (attendiamo nuovo PNG).

### Prossimo step
1. Utente salva pin Continue come `templates/pin/pin_arena_07_glory.png` (sovrascrivere).
2. Sync prod: copiare `tasks/arena.py` + `templates/pin/pin_arena_07_glory.png` in `C:\doomsday-engine-prod\`.
3. Test FAU_03 reinstallato (settings lightweight + arena 5 sfide) → idem FAU_02.
4. Se OK: re-validare istanze residue + considerare riabilitare arena su prod.

---

## Sessione 29/04/2026 pomeriggio — Settings lightweight + pulizia istanze

### Obiettivo
Reinstallare/pulire le istanze MuMu per stabilizzarle (cascata ADB persistente
su FAU_02/03/04 durante test arena diretto). Dotare il bot di una funzione
riusabile per impostare 3 settings "lightweight" del client gioco ad ogni
avvio istanza, così che il flow del bot sia stabile anche su istanze
precedentemente problematiche.

### WU60 — `core/settings_helper.py` (nuovo modulo)
Funzione `imposta_settings_lightweight(ctx, log_fn)` che applica:
- **Graphics Quality LOW** (slider, idempotente)
- **Frame Rate LOW** (radio button, idempotente)
- **Optimize Mode LOW** (toggle stateful, NON idempotente)

**Coordinate calibrate via getevent ADB su FAU_01 (960×540 display)**:
| Step | Coord | Note |
|------|------|------|
| Avatar (alto-sx HOME) | (48, 37) | apertura menu profilo |
| Icona Settings (basso-sx) | (135, 478) | |
| Voce System Settings | (399, 141) | |
| Graphics Quality LOW | (695, 129) | slider posizione LOW |
| Frame Rate LOW | (623, 215) | radio LOW |
| Optimize Mode toggle | (153, 337) | check stateful |

**Gestione toggle stateful Optimize Mode**:
- Pre-tap: screenshot + match template `pin_settings_optimize_low_active.png`
  (90×40 px, ROI 108-198 × 317-357, soglia 0.70).
- Se attivo → skip tap (un secondo tap disattiverebbe).
- Se non attivo / matcher non disponibile / errore → tap (pessimistico).

**Ritorno HOME via 3 BACK** (uscita pulita dalle 3 schermate annidate).

### Delay calibrati per PC lento (utente conferma instabilità match checkbox)
Calibrazione iniziale (~17s) troppo aggressiva; raddoppiati per stabilità:

| Costante | Prima | Ora | Uso |
|----------|------|-----|-----|
| `_DELAY_NAV` | 1.5s | **3.0s** | tra cambi schermata |
| `_DELAY_TOGGLE` | 0.8s | **2.0s** | tra tap nella stessa schermata |
| `_DELAY_PRE_CHECK` | 0.5s | **1.5s** | prima screenshot Optimize |
| `_DELAY_BACK` | 1.0s | **2.0s** | tra BACK consecutivi |

Tempo totale ora ~22s/istanza (era ~17s) — accettabile rispetto al rischio
di template matching su schermata non renderizzata.

### Test eseguiti (pre-pulizia istanze)
- **FAU_01 (manuale)**: registrazione tap via `getevent /dev/input/event4`
  → calibrate tutte le 6 coordinate sopra.
- **FAU_02 (script)**: settings sequence + arena 5 sfide bot-style
  - Settings: ✅ score template Optimize 1.000 (già attivo)
  - Arena: ❌ freeze a sfida 2 nonostante settings applicati
  - **Conclusione**: settings da soli NON sufficienti su FAU_02 — qualcosa
    di altro (corruption emulator?) → utente avvia pulizia/reinstallazione.

### Stato bot 29/04 ore 14:xx
- **Bot prod**: in pausa, utente sta facendo pulizia generale + reinstallazione
  istanze MuMu (FAU_02/03/04 instabili).
- **Modalità task** (utente toggle dashboard 19:45 28/04):
  - ON: `raccolta` (always) + `radar_census`
  - OFF: tutti gli altri
- **Settings lightweight**: implementato, NON ancora integrato in `launcher.py`.
  Integrazione rimandata a quando le istanze saranno reinstallate e validate.

### Prossimo step (post-reinstallazione)
1. Validare nuove istanze: avvio singolo + ADB stabile.
2. Test settings lightweight su 1 istanza re-installata (FAU_02).
3. Se OK: integrare `imposta_settings_lightweight()` in `launcher.py`
   (chiamare in `attendi_home` post-stabilizzazione).
4. Test arena 5 sfide su istanza pulita + settings.
5. Se OK: re-abilitare task arena su prod e ri-validare 11 istanze.

---

## Sessione 29/04/2026 mattina — Fix dashboard stale daily

### Eventi notturni
- **22:56 (28/04)**: utente attiva modalità manutenzione da dashboard (motivo
  "aggiornamento") → bot in pausa.
- **22:56 → 05:46 (29/04)**: bot in pausa per **6h 49min** (24540s logged).
- **05:46:28**: bot killato + rilanciato manualmente (PID 18544 → poi 5916 →
  PID 18544 ripartito su run_prod.bat).
- **0 spedizioni rifornimento** durante la notte.

### WU58 — Fix dashboard "stale daily state" (commit pendente)

**Problema**: `state/FAU_*.json::rifornimento` mantiene `data_riferimento`,
`inviato_oggi`, `inviato_lordo_oggi`, `tassa_oggi`, `dettaglio_oggi`,
`provviste_residue` aggiornati solo quando il task rifornimento gira.
Se task OFF da >24h o pausa manutenzione lunga, dashboard mostra dati di
ieri come se fossero di oggi.

**Fix applicati** in `dashboard/services/stats_reader.py`:

1. **`get_state_per_istanza()`** (riga ~450): se `data_riferimento != today_utc`
   azzera in-memory `spedizioni_oggi`, `inviato_oggi`, `inviato_lordo_oggi`,
   `tassa_oggi`, `dettaglio_oggi`, `provviste_residue=-1`, `provviste_esaurite=False`.
2. **`get_risorse_farm()`** (riga ~590): stessa logica per il pannello aggregato.
3. **`_load_morfeus_state()`** (riga ~251): se `ts[:10] != today_utc` ritorna
   `daily_recv_limit=-1` → dashboard mostra "capienza morfeus —".

**File NON toccati**: il bot scriverà nuovi valori al primo tick rifornimento
di oggi, dopo aver invocato `_controlla_reset()` interno.

### WU59 — Pannello "📚 storico cicli" colonna DATA

**Problema**: dopo pausa lunga (es. 28→29/04) i cicli precedenti e attuali
sono indistinguibili in dashboard (mostrava solo `start_hhmm → end_hhmm`).

**Fix** in `dashboard/services/telemetry_reader.py`:
- `CicloStorico.start_date: str` (formato `DD/MM` UTC)
- `get_storico_cicli()` estrae da `start_ts[8:10]/start_ts[5:7]`

E in `dashboard/app.py::partial_telemetria_storico_cicli`:
- Tabella con colonna "data" tra "ciclo" e "finestra"

### Stato bot 29/04 ore 09:36
- **Bot**: PID 18544 (UTC 05:46:28) — attivo modalità raccolta-only
- **Dashboard**: PID 25552 (29/04 09:36:09) — restartata 3 volte stamattina per testing fix
- **Cicli completati 29/04**: ciclo 1 in corso da 05:46, attualmente FAU_03

## Sessione 28/04/2026 sera — Arena root cause + Modalità raccolta-only

### Obiettivo sessione (sera)
Indagine fallimento arena post-attivazione (12 istanze tutte falliscono o
freezano). Root cause identificato. Bot stabilizzato in modalità minima
(solo raccolta) in attesa di fix.

### Stato attuale
- **Bot prod**: PID 5964 riavviato 18:17:34 (kill+restart manuale dopo
  conferma utente, FAU_10 fine ciclo era safe-point). Comando immutato:
  `main.py --tick-sleep 60 --no-dashboard --use-runtime --resume`.
- **Modalità task** (utente toggle dashboard 19:45):
  - **ON**: `raccolta` (always) + `radar_census`
  - **OFF**: alleanza, arena, arena_mercato, boost, district_showdown,
    donazione, messaggi, radar, rifornimento, store, vip, zaino
- **Reset arena state** eseguito 19:15 — backup
  `state/_arena_reset_20260428T191510/` (11 file FAU_00..FAU_10).
  Nota: ora i task sono off da dashboard quindi arena non scatta comunque.
- **Dataset WU55**: 156 sample, **71 pair complete** (target ≥30 superato).
  Pipeline OCR validata 98.6% MAP valid, 100% HOME. Cross-validation
  multi-preprocessing recovery 8/8 da pattern 4↔7. KEEP refactor confermato.

### Issue critiche identificate (SERA 28/04)

#### #83 Arena freeze multi-causa — race condition rendering lista

**Ipotesi iniziale "Watch button"**: smentita. Utente ha confermato che
la lista 5 sfide ha SEMPRE 5 button "Challenge" cliccabili (anche stesso
avversario può essere sfidato fino a 5 volte). Non esistono pulsanti
"Watch/replay/Done" come pensavo.

**Causa root effettiva (verificata 28/04 sera con test ADB diretto su
FAU_01/02/03/04):**

1. **Race condition rendering lista post-vittoria**: dopo `tap CONTINUE`,
   la lista si rigenera con nuovi avversari basati sul nuovo score.
   Header `pin_arena_01_lista` matcha 0.993 ma le righe sono in
   animazione. Tap immediato (745, 482) cade in stato transitorio →
   schermata bianca → MuMu freeze → ADB cascade abort.

2. **Coord (745, 482) timing-sensitive**: sulla lista appena navigata
   con `time.sleep(3.0)` post Arena of Doom, su FAU_03/FAU_04 il tap
   non apre il popup (lista invariata) — 3s insufficienti per rendering
   completo. Su FAU_01/FAU_02 invece funziona.

3. **Skip animation determinante**: con skip OFF la battaglia dura
   30-60s e i timeout interni del bot (`_DELAY_BATTAGLIA_S=8 +
   _MAX_BATTAGLIA_S=52`) NON bastano. Continue tap su battaglia in
   corso → tap su elementi non gestiti → cascade.

**Conferma sperimentale (4 istanze):**
- FAU_01 isolato: tap (745,482) → ✅ apre popup
- FAU_02 sequenziale 5s delay: sfida 1✅ + sfida 2✅ poi esaurimento sfide
- FAU_02 sequenziale 3s delay: sfida 1✅ + sfida 2 ❌ (race cond.)
- FAU_03/04 sequenziale 3s delay: sfida 1 ❌ tap fallito (timing post-Arena)
- FAU_04 con sfida 1 OK + sleep 10s post-CONTINUE: sfida 2 ❌ schermata bianca

**Fix candidati combinati (da implementare in arena.py):**
1. `_attendi_lista_stabile()` — 2 match consecutivi a 1.5s pre-tap
   (sostituisce `time.sleep(3.0)` riga 359)
2. Sleep post-CONTINUE da 0.5s → 5-8s (riga 409)
3. Match dinamico button Challenge in ROI lista (cattura template
   `pin_btn_challenge_lista.png` da screenshot raccolti)
4. Verifica `_assicura_skip()` AD OGNI sfida (non solo 1° volta)

#### #84 Bug orchestrator: `entry.last_run` aggiornato anche su fail
`core/orchestrator.py:316` setta `last_run=time.time()` SEMPRE dopo
`task.run()` indipendentemente da `result.success`. Conseguenza: arena
fallita 13/13 stamattina → `last_run` aggiornato → `e_dovuto_daily=False`
→ arena non riprovata fino al reset 01:00 UTC giorno dopo.

**Fix:** `if result.success or result.skipped: entry.last_run = time.time()`.
Effort 2 righe + restart.

### Telemetry arena 28/04 mattina (pre-reset)
13 esecuzioni, 0 success:
- 10/13 timeout 300s (3-4 sfide su 5 prima del cap)
- 3/13 ADB cascade (FAU_02/06/09 mattina) → abort emergenziale

### Issues chiuse oggi (12 commit `7984478` → `27fd5d2`)

| WU | Titolo | Commit |
|----|--------|--------|
| 49 | Pannello tempi medi task con filtro outlier IQR | `7984478` |
| 50 | Raccolta fuori territorio per istanza (toggle dashboard) | `4012b70` |
| 51 | Modalità manutenzione bot — file flag + dashboard toggle | `2f1b9ea` |
| 52 | Istanze disabilitate read-only + sync flag fuori_territorio | `72f7b0e` |
| 53 | Detect popup MAINTENANCE gioco — skip istanza | `c9f543f` |
| 54 | Popup MAINTENANCE — auto-pause + OCR countdown | `fcdad78`, `55d62c7` |
| 55 | Data collection OCR slot HOME vs MAPPA | `2c470ab` |
| 56 | Pannello produzione/ora storico 12h con sparkline | `39fdfcf`, `0490b18`, `a767201` |
| 57 | RaccoltaFastTask — variante fast via tipologia istanza | `55d2e61` |
| 55-bis | Shadow OCR MAP post-marcia in `_reset_to_mappa` | `d451b8f` |
| — | UI rename tipologie completo/solo raccolta + header FT | `27fd5d2` |

### File chiave modificati
- `tasks/raccolta.py` — 3 hook WU55 (riga 1147, 2058, 2180) + WU55-bis hook in `_reset_to_mappa` (riga 1212+)
- `tasks/raccolta_fast.py` — NUOVO file (440 righe)
- `shared/ocr_dataset.py` — modulo data collection (NUOVO)
- `shared/morfeus_state.py` — storage globale OCR daily limit
- `core/maintenance.py` — file flag + auto-resume
- `core/launcher.py` — 3 hook detect MAINTENANCE in `attendi_home`
- `dashboard/app.py` — endpoint `/api/maintenance/*`, `/api/raccolta-ocr-debug/*`, `partial_ist_table` colonna FT, partial_res_oraria layout 2-righe sparkline 12h
- `dashboard/services/stats_reader.py` — `get_produzione_storico_24h(hours=12)`, `_load_storico_farm_today` fallback
- `dashboard/models.py` — enum `TipologiaIstanza.raccolta_fast`, `IstanzaOverride.raccolta_fuori_territorio`, `GlobaliOverride.raccolta_ocr_debug`
- `config/config_loader.py` — propagazione root-level globali (`raccolta_ocr_debug`)
- `main.py` — `_import_tasks` aggiunto `RaccoltaFastTask`, runtime swap RaccoltaTask→RaccoltaFastTask se tipologia=`raccolta_fast`
- `dashboard/templates/index.html` — header `FT` (era `⛯`)
- `templates/pin/pin_game_maintenance_refresh.png`, `pin_game_maintenance_discord.png` — NUOVI template (174×35)

### Prossimo step (priorità)

1. **Fix #83 arena `_TAP_ULTIMA_SFIDA` dinamico** — ricostruire flow di
   selezione sfida: `matcher.find_one(pin_btn_challenge_lista, zone=ROI_lista)`,
   tappare la coordinata del primo match invece di pixel fisso (745,482).
   Richiede screenshot UI corrente lista 5 sfide per estrarre template.
2. **Fix #84 orchestrator last_run** — 2 righe in `core/orchestrator.py:316`,
   aggiungere guard `if result.success or result.skipped`. Restart bot.
3. **Re-test arena** dopo fix #83+#84 — riabilitare arena da dashboard,
   reset state arena (procedura WU58: copia da backup
   `state/_arena_reset_20260428T191510/` o azzeramento) → nuovo ciclo.
4. **Re-test arena_mercato** post-fix template `pin_btn15_open` (issue #79
   dei todo, ricalibrare con screenshot UI corrente Arena Store).
5. **Disabilitare debug WU55 OCR** — pipeline stabile (98.6%), no più
   serve raccolta dataset. Toggle off `globali.raccolta_ocr_debug`.
6. **Continuare modalità raccolta-only** finché non si applicano fix
   strutturali (#83 + #84). Bot stabile in produzione.

### Issues residue aperte (priorità)

| # | Priorità | Descrizione |
|---|----------|-------------|
| **83** | **ALTA** | **Arena `_TAP_ULTIMA_SFIDA` cieco — freeze su righe "Watch"** (root cause 28/04 sera) |
| **84** | **ALTA** | **Orchestrator `entry.last_run` aggiornato anche su fail/abort** |
| 81 | ALTA | Update Version popup gioco — detect + gestione |
| 14 | ALTA | Arena START CHALLENGE non visibile multi-istanza (correlato a #83?) |
| 15 | ALTA | `engine_status.json` stale writer |
| 16 | MEDIA | OCR FAU_10 anomalia legno 999M |
| 17 | MEDIA | Storico `engine_status` filtrato |
| 25 | BASSA | Tracciamento diamanti nello state |
| 46 | ALTA | state.rifornimento azzerato post-restart bot — issue root da indagare |
| 49 (vecchio) | BASSA | Ottimizzazioni startup istanza (-90s/ciclo) |
| 51 (vecchio) | ALTA | DS gate readiness popup fase 3/4/5 |
| 52a | MEDIA | WU14 produzione_corrente null in state files |
| 52b | MEDIA | Stab HOME 88% timeout |
| 52d | BASSA | FAU_07 deficit netto + acciaio overflow |
| 54 | — | Banner catalog discovery (3/N banner attivi) |
| 55 | ✅ | Data collection OCR — VALIDATA 98.6% (71 pair) — disabilitare debug |
| 65 | BASSA | Wait>60s rifornimento → anticipare task post-raccolta |
| 72 | DA OSSERVARE | Fase 4 #69 false negative su gioco in background |
| — | BASSA | Template `pin_btn15_open` arena_mercato stale (open=0.43-0.47 sotto soglia 0.65) |
| — | BASSA | Arena timeout F2 300s troppo stretto (post-fix #83 da rivalutare) |

### Doc aggiornata oggi (28/04)

**Mattina/pomeriggio:**
- `ROADMAP.md` — sezione "Sessione 28/04/2026" con WU49-57 + WU55-bis
- `.claude/CLAUDE.md` — tabella issues estesa (WU49-57, WU55-bis)

**Sera:**
- `ROADMAP.md` — Issue #83 e #84 aggiunte sotto "Issues aperti"
- `.claude/CLAUDE.md` — righe 83, 84 + nota modalità raccolta-only
- `.claude/SESSION.md` — questo documento (sezione SERA aggiunta)

### Restart policy (memorizzata)
- Default: mai riavvio mid-tick (memoria `feedback_restart_policy.md`)
- Eccezione: solo richiesta esplicita utente
- Oggi 28/04 mattina: kill mid-tick FAU_10 esplicitamente richiesto per applicare WU55-bis
- Oggi 28/04 sera: kill+restart 18:17 esplicito utente, FAU_10 fine ciclo come safe-point

### Backup operazioni (28/04)
- `state/_arena_reset_20260428T191510/` — 11 state files FAU_00..FAU_10 pre-azzeramento arena
