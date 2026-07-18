# Revisione tecnica Doomsday Engine V6 — bot + dashboard (luglio 2026)

> **STATO: IN CORSO — revisione autonoma Claude ⇄ Gemini (avviata 17/07/2026 sera).**
> Deliverable a incrementi: documento tecnico (findings motivati+verificati) +
> planning a fasi. **Solo analisi: nessuna modifica al codice senza approvazione
> utente.** Ogni finding verificato sul codice reale + dati live (standard v1.1).

## 0. Metodo e governance

- **Scope**: tutti e 4 gli assi (scelta utente 17/07): (1) Correttezza &
  robustezza, (2) Architettura & manutenibilità, (3) Performance & efficienza,
  (4) Dashboard + Affidabilità/Test. Consegna a **incrementi** (un asse/tema alla
  volta), non un mega-documento unico.
- **Divisione ruoli** (a verbale, vedi `master-tasks-refactor-design.md` §8):
  Gemini = ricognizione ampia + mining log/telemetria + prime bozze; Claude =
  verifica critica + qualificazione severità + sintesi architetturale.
- **Regole finding**: ogni voce ha `[ID] titolo · asse · severità · evidenza
  (file:riga / log / dato live) · riproducibilità · proposta`. Niente
  affermazioni non verificate. I dubbi → "DECISIONE APERTA per l'utente".
- **Escalation immediata**: bug che perde dati / regressione attiva / rischio
  sicurezza → segnalati subito all'utente, non a fine revisione.
- **Baseline**: si riconcilia con `docs/analisi_2026-06-07.md` (27 findings, piano
  5 fasi) — marcare risolto / stale / ancora-valido prima di aggiungere nuovo.
- **No script ADB esterni su istanze live** (lezione WU185): solo log + MCP monitor.

## 1. Fase A — Inventario & baseline (in corso)

### 1a. Snapshot live iniziale (17/07 ~20:50 UTC)
- Bot in esecuzione, **0 anomalie** negli ultimi 10 min (MCP `anomalie_live`).
- Contesto noto da oggi (già in `docs/issues/`): master 10/10 task OK, canary
  reset-leggero chiuso 67/67, ciclo "starved" per i riavvii odierni (si
  auto-ripara). Questi NON sono findings nuovi, sono stato noto.

### 1b. Riconciliazione con analisi 07/06 (Gemini mining + Claude verifica)

Mining di Gemini sui 14 punti critici del 07/06, con verifica Claude in corso
(colonna "Verif. Claude": ✅ verificato / — da verificare nel prossimo incremento).

| ID | Finding | Gemini | Evidenza | Verif. Claude |
|----|---------|--------|----------|---------------|
| C1 | Heartbeat alert non scatta | RISOLTO | `core/alerts.py:353-378` | — |
| **C2** | **Dashboard senza auth su 0.0.0.0** | **APERTO** | `run_dashboard_prod.bat:66` + nessun middleware auth in `app.py` | ✅ **CONFERMATO (security)** |
| C3 | tick_end esito sempre 'ok' | RISOLTO | `main.py:1570-1575` (WU46) | — |
| **C4** | **`_esegui_marcia` success su screen None** | **APERTO** | `tasks/raccolta.py:~1735` | ✅ **CONFERMATO** |
| **C5** | **`_save_ov` droppa chiavi (Pydantic)** | **APERTO** | `api_config_overrides.py:64` + `RuntimeOverrides` senza `extra` | ✅ **CONFERMATO (sistemico)** |
| C6 | max_squadre/livello static ignorati | APERTO | `config_loader.py:1265-1266` | — |
| C7 | BlacklistFuori scrittura non atomica | RISOLTO | `raccolta.py:501-521` (WU231, oggi) | — |
| C8 | Store non_trovato → fail() non skip | APERTO | `tasks/store.py:792-794` | — |
| C9 | rifornimento no post-verifica VAI | APERTO | `rifornimento.py:793-807` | — |
| C10 | Fallback OCR 999M rifornimento | RISOLTO | `rifornimento.py:756-780` (WU213) | — |
| C11 | DistrictShowdown rigira ogni tick | APERTO | `district_showdown.py:184-185` | — |
| C12 | vai_in_home fail/skip incoerente | APERTO | `alleanza.py:73`/`messaggi.py:125`/`boost.py:183` | — |
| C13 | Window DS duplicata nel predictor | APERTO | `cycle_duration_predictor.py:773-800` | — |
| C14 | auto_learn_banner toggle morto | RISOLTO | `launcher.py:891-897` (WU189) | — |

**Bilancio grezzo**: 5 risolti (C1,C3,C7,C10,C14), 9 ancora aperti. I risolti con
attribuzione WU chiara (C7=oggi, C10=WU213, C14=WU189) sono attendibili; gli altri
verrà spot-check nel prossimo incremento.

### 1b-bis. Findings verificati da Claude (primo incremento)

**[R-01] Dashboard esposta su LAN senza autenticazione** · asse 4 (dashboard) ·
**severità ALTA (security)** · evidenza: `run_dashboard_prod.bat:66`
(`--host 0.0.0.0 --port 8765`) + `dashboard/app.py` privo di middleware auth
(nessun `add_middleware`/`HTTPBasic`/`Depends` di auth). · La dashboard espone
controlli sensibili (restart bot, modifica config, maintenance, override
istanze). Chiunque sulla stessa rete può usarli. · **Proposta**: (a) auth minima
(HTTP Basic o token in header via middleware), oppure (b) bind su `127.0.0.1` +
tunnel/reverse-proxy autenticato se serve accesso remoto. · **CALIBRATO con
l'utente (18/07)**: macchina su **LAN di casa fidata**, nessuna esposizione
esterna → **severità effettiva BASSA**, non urgente. Decisione utente:
**documentare nel planning** con la proposta di fix, implementazione a sua
discrezione (nessun intervento ora, coerente con "solo analisi").

**[R-02] Bug-class field-wipe Pydantic (root cause)** · asse 2+4 · **severità
MEDIO-ALTA (sistemico)** · **✅ RISOLTO 18/07**. Catena verificata: `model_validate`
(default `extra='ignore'`) scarta i campi ignoti in lettura + `save_overrides`
sovrascrive col `model_dump()` → campi non dichiarati cancellati dal file. Fix:
`model_config = ConfigDict(extra='allow')` su `IstanzaOverride`/`GlobaliOverride`/
`RuntimeOverrides` → i campi ignoti sopravvivono al round-trip (verificato Pydantic
2.13.4). Validato sul config prod REALE: 0 campi persi; campo ignoto arbitrario
preservato. I campi espliciti restano validati. Non tocca il bot (config_loader
legge JSON grezzo). Chiude anche la porta a R-09. Test +5 (`test_field_wipe_r02`),
test_master_task_whitelist 11/11. **Trade-off accettato**: un typo ora persiste
(visibile) invece di sparire (bug silenzioso). · evidenza: `dashboard/routers/api_config_overrides.py:64`
`save_overrides(ov.model_dump())` + `RuntimeOverrides`/`IstanzaOverride` senza
`model_config extra` → ogni campo di `runtime_overrides.json` NON dichiarato nel
modello viene **droppato** al primo save dashboard. · Già colpito 2 volte oggi
(`raccolta_reset_leggero_abilitato`, `master_task_whitelist`), tappato campo-per-
campo — ma la causa radice resta: ogni campo runtime futuro è a rischio silenzioso.
· **Proposta**: fix strutturale — merge raw JSON + setattr field-by-field (pattern
già in memoria `feedback_dashboard_save_merge`), oppure `model_config =
ConfigDict(extra='allow')` + preservazione dei campi extra nel dump. Da valutare
(extra='allow' ha implicazioni di validazione). · Chiude una classe di bug, non
un singolo caso.

**[R-03] `_esegui_marcia` — successo spurio su screenshot fallito** · asse 1 ·
**severità MEDIA** · **✅ RISOLTO 18/07**. 2 percorsi di `return True` spurio:
(a) `screen_post is None` → blocco saltato → True incondizionato; (b) maschera
aperta + retry con `screen_post2 is None` → True pur avendo visto la maschera
aperta. Fix: `True` SOLO su conferma positiva maschera chiusa; screenshot None →
retry (0.8s), se ancora None → esito prudente **FALLITO** (il caller fa
rollback+reset, più sicuro di una marcia fantasma). Coerente con la logica
esistente ("maschera confermata aperta = FALLITO"). Verificato per lettura +
`test_raccolta` 81/81 invariato. **Follow-up test**: coprire il path None
richiede estrarre un helper `_verifica_marcia` (refactor a sé) — tracciato,
non fatto (evita scope creep su un fix piccolo). · evidenza: `tasks/raccolta.py` `_esegui_marcia`: dopo tap
MARCIA, se `screen_post is None` (screenshot fallito) il blocco di verifica
maschera è saltato e la funzione ritorna `True` (marcia "OK") senza conferma. ·
Impatto: falso positivo marcia → contabilità slot sfasata (il bot crede che una
squadra sia partita quando potrebbe non esserlo). Raro (richiede screenshot None
nell'istante), ma silenzioso. · **Proposta**: su `screen_post is None`, o retry
screenshot, o ritornare esito prudente (non `True` incondizionato) coerente con
gli altri rami di fallimento.

### 1c. Mappa subsystem + hotspot (DA FARE — assegnato a Gemini, mining)
Inventario dei subsystem (tasks/, core/, shared/, dashboard/) con dimensione,
n. funzioni, ultima modifica, e primo scan di **hotspot di rischio** (pattern:
`except: pass` silenziosi, `TODO/FIXME`, duplicazioni logiche, `sleep` fissi,
handle non chiusi, test falliti). Grezzo da verificare poi.

## 2. Findings per asse (popolati a incrementi)

### Asse 1 — Correttezza & robustezza
Vedi R-03 (marcia success spurio) sopra. Fase B (Gemini evidenza + Claude verifica):

**[R-04] `_compila_e_invia` rifornimento — successo su tap VAI non verificato** ·
**severità MEDIA** · **✅ RISOLTO 18/07**. Diverso da R-03: nessuna verifica
post-invio esisteva (solo pre-check VAI abilitato). Confermato dall'utente che
dopo un invio riuscito **il pannello si chiude e VAI sparisce** → verifica
sicura possibile. Fix: dopo tap VAI, screenshot (retry su None) + `_vai_abilitato`:
se VAI ANCORA presente (o screenshot non disponibile) → invio NON partito →
**non conteggiato** (return False + BACK), altrimenti registra produzione e
True. Evita spedizioni fantasma nella contabilità/coda_volo/predictor.
Valutato e SCARTATO un fix cieco (avrebbe rischiato falsi-negativi → doppio
invio); implementato solo dopo conferma UI dell'utente. Verificato per lettura;
test_rifornimento 43 pass invariati (9 fail pre-esistenti STALE, firma 5→7
tuple — test-debt R-10, non miei). · `tasks/rifornimento.py:793-807`: dopo `tap(coord_vai)` +
`sleep(2.5)` ritorna `True` senza accertare che la maschera si sia chiusa/l'invio
sia partito. Se il tap fallisce (lag UI), il bot registra come inviata una
quantità mai partita → **contabilità corrotta** + delay viaggio sprecato nel
predictor. (C9, evidenza Gemini; pattern gemello di R-03). **Proposta**:
post-verifica (maschera chiusa / conferma invio) prima di ritornare success.

**[R-05] Policy incoerente su fallimento gate HOME** · **severità MEDIA
(consistenza)** · **✅ RISOLTO 18/07 (Opzione A — uniformato a fail)**. Claude
VERIFICATO: stessa condizione `vai_in_home()==False` → `alleanza.py:73` ritornava
**skip** (posticipa 4h), `messaggi.py:125` e `boost.py:183` ritornano **fail**
(retry immediato). Il rischio concreto dello skip: `skip()` aggiorna `last_run`
(WU79) → alleanza rinviata di 4h su un fallimento HOME meramente tecnico/
transitorio → possibile **perdita di claim** in quella finestra. **Fix**: `alleanza.py`
riga 73 `skip()` → `fail("Navigator non ha raggiunto HOME", step="assicura_home")`
→ `last_run` invariato → ritenta al tick successivo, coerente con messaggi/boost e
col gate orchestrator (`orchestrator.py`). Scelta A (uniformare a fail) invece di
delegare-e-rimuovere: minima, chirurgica, reversibile; il de-duplica col gate
orchestrator resta come debito architetturale (non bloccante). **Nessuna
regressione**: `test_alleanza` 15/9 identico con/senza fix (git-stash diff; i 15
fail sono stale pre-esistenti, debito R-10). Commit `8df5a48`, sync prod OK.
**Effettivo al restart BOT.** (C12)

### Asse 2 — Architettura & manutenibilità
- **[seed, già noto]** Config-tangle risoluzione task list (3 meccanismi
  sovrapposti) — già in refactor, vedi `master-tasks-refactor-design.md`.
- Vedi R-02 (field-wipe Pydantic, sistemico) sopra.

**[R-06] Logica window DistrictShowdown duplicata** · **severità MEDIA (debito)**
· **✅ RISOLTO 18/07**. `core/cycle_duration_predictor.py::_district_showdown_will_skip`
duplicava la logica date/ore weekend di `tasks/district_showdown.py::_is_in_event_window`
come **if-ladder hardcodato** che ignorava `ds_end_hour` (assumeva "lunedì sempre
fuori"). Drift latente: cambiando gli orari nella config, il task li onorava ma il
predictor no → stime ciclo errate (stessa classe di WU145→WU156). (C13, evidenza
Gemini). **Fix**: unica funzione `shared.task_scheduling.is_in_ds_event_window`
(modulo già condiviso WU157, dipendenze leggere). Il task la chiama passando la sua
config (source of truth, onora override); il predictor la chiama **negata** (skip =
fuori finestra). Estrazione fedele (stessa logica/ordine di check, zero cambio
semantico a default); il bug latente `ds_end_hour>0` è ora gestito uniformemente.
**Test +8** (`test_ds_event_window_r06`): equivalenza su 168 slot/settimana vs
vecchia logica sia del task sia del predictor. Suite DS/predictor 28/28. Commit
sync prod OK. Effettivo al restart BOT. (C13)

### Asse 3 — Performance & efficienza
**Misurazioni live (Gemini, log reali)**:
- **Boot Android**: 17 boot, 26-43s, media **30s**, 0 timeout → in QUESTO ambiente
  il boot NON è un collo di bottiglia (il vecchio timeout 300s WU201 non si
  manifesta ora). Declassato.
- **Timeout arena 10s**: **0 occorrenze nei log correnti** — perché l'arena era
  già esaurita per oggi. Il ~78% timeout osservato da Claude era DURANTE le run
  arena reali (diurne). → **PENDING**: valutare con gli screenshot debug arena
  (già armati) alla prossima run arena reale (post gate UTC≥10). Non concludere
  finché non c'è la cattura.
- **Rifornimento delay-measure**: 0 campioni finora (nessun invio recente loggato
  col debug). Da raccogliere.

**[R-07] Store `fail()` invece di `skip()` su non-trovato → rilancio ogni ciclo** ·
**severità BASSA-MEDIA (efficienza)** · **✅ RISOLTO 18/07**. `tasks/store.py`:
`STORE_NON_TROVATO` (grid-scan sotto soglia riga 368 / re-match fallito riga 410)
→ era `fail()`. Lo scheduler non salva `last_run` sui fail → ritenta ogni ciclo
(~20-30s scan griglia sprecati/ciclo), concreto sulle istanze con edificio spostato
(~22% fail su FAU_00/04/07/09, memoria `project_store_edificio_da_spostare`). **Fix**:
spostato `STORE_NON_TROVATO` nel dict `skip_esiti` (accanto a LABEL/CARRELLO/MERCHANT
_NON_TROVATO/NON_APERTO già a skip) → `skip()` posticipa all'intervallo, no hammer.
Principio: *fallimento tecnico transitorio → fail; condizione ambientale persistente
→ skip*. **Corroborazione forte**: il design voluto era già skip — `test_store_non_trovato_skip`
lo asseriva ma il codice era driftato a `fail`; il fix riallinea codice↔test
(test_store **5→3 fail, 34→36 pass**, +2 verdi 0 rotti; i 3 residui = `TestFreeRefresh`,
area diversa pre-esistente). Commit `f0e4e0d`, sync prod OK. Effettivo al restart BOT.
(C8)

**[R-08] DistrictShowdown senza persistenza dadi → rinaviga ogni tick** ·
**severità BASSA-MEDIA (efficienza)** · `tasks/district_showdown.py:184-185`
`e_dovuto → True` sempre in-window, nessuno stato "dadi esauriti" su disco. Con
dadi a zero, apre comunque il menu evento ogni ciclo per 3 giorni (~1-2 min
navigazione sprecata/tick). (C11). **Proposta**: state persistito (come
BoostState/VipState) che marca "dadi esauriti oggi" → skip.

### Asse 4 — Dashboard + Affidabilità/Test
- Vedi R-01 (auth, LAN → basso) e R-02 (field-wipe) sopra.

**[R-09] `max_squadre`/`livello` static ignorati (fallback hardcoded)** ·
**severità MEDIA** · **✅ RISOLTO 18/07** (fix codice + allineamento static +
test). Scoperta chiave in validazione: lo static `instances.json` era DRIFTATO
(FAU_01-10 max_squadre=4 vs dynamic=5). Fix: (1) `_ovr(k, ist.get(k, cost))` —
fallback dynamic>static>costante (pattern WU220), costante max_squadre 4→5; (2)
allineato instances.json (FAU_01-10 →5). Livello già allineato (7 FAU_00/
FauMorfeus, 6 altri — imposti dall'alleanza, ora protetti dal wipe). Commit
`fix(config): R-09`. Test +4 (`test_config_static_fallback`), config 39/39. · `config/config_loader.py:1265-1266`: `_ovr("max_squadre", 4)`
/ `_ovr("livello", gcfg.livello_nodo)` leggono solo il dynamic; se la chiave manca
in `runtime_overrides.json` (post field-wipe R-02, o reset) ripiegano su 4/globale
ignorando `instances.json` (FAU_00/FauMorfeus = 5 squadre) → master retrocede a 4
squadre, ciclo più lento. **Interagisce con R-02** (il field-wipe può innescarlo).
(C6). **Proposta**: fallback `_ovr` su static `instances.json` prima del default
(fix bug-class C6 già previsto nell'analisi 07/06).

**[R-10] Debito test** · **severità MEDIA (qualità)** · **✅ RISOLTO (fase 1
collection) 18/07**. Diagnosi verificata: la collection crashava (INTERNALERROR)
per 17 script standalone `test_*.py` a ROOT (uno con `sys.exit` all'import) +
collisioni di basename dentro `tests/` (due `test_orchestrator.py`) + 3 test con
import stale (simboli rimossi: `PEZZATURE`, `KeyCall`+`TapCall`/`SwipeCall`/
`MuMuDevice`, `ZONE_RISORSE_DEFAULT`). **Fix applicato** (test infra, non tocca
il runtime): nuovo `pytest.ini` con `testpaths=tests` (esclude gli stray root,
nessuna cancellazione) + `--import-mode=importlib` (risolve basename uguali) +
`--ignore` di `test_device.py` (obsoleto, testa API rimossa — TODO riscrittura);
rimossi 2 import stale salvabili (`ZONE_RISORSE_DEFAULT` inutilizzato in
test_ocr_helpers; `PEZZATURE` + classe obsoleta `TestPezzature` in test_zaino,
struttura sostituita da `_PIN_CATALOGO`). **Risultato: collection PULITA — 1009
test raccolti, 0 errori** (prima: crash totale). La suite ora gira = rete di
sicurezza sbloccata per i refactor. **Follow-up (aperti, non bloccanti)**: (a)
riscrivere `test_device.py` sull'API attuale di FakeDevice; (b) decidere se
rimuovere/relocare i 17 script standalone a root (tracciati in git, ora
inerti alla suite). Pass/fail baseline della suite: da misurare (run completa).

## 2-bis. Sistema di monitoraggio anti-regressione (18/07)

Attivato su richiesta utente per verificare che i fix implementati **non
introducano regressioni o peggioramenti**. Due componenti, sola lettura, nessuna
azione sul bot:

**1. Tool KPI** — `tools/verifica_fix_revisione.py` (py -3.14).
- Fonti: telemetry events JSONL (KPI strutturati per task) + log per-istanza
  JSONL (segnali fix + ERROR/eccezioni). Windows-safe (path `C:\...`).
- Metriche di regressione: `fail_rate_pct` per task, `throughput_per_run`
  (marce raccolta / spedizioni rifornimento / rivendiche alleanza), ERROR/ora,
  eccezioni. Soglie: fail_rate +10pp, throughput −25%, ERROR +5/h, eccezioni >0.
- Segnali fix (informativi, prova che il path del fix si esercita, **non**
  regressioni): R-03 `esito prudente FALLITO`, R-04 `invio NON confermato`,
  R-05 `Navigator non ha raggiunto HOME` (su alleanza).
- Modi: `--baseline` (snapshot pre-restart) / `--check` (confronto + verdetto,
  exit 1 se regressione). **Baseline pre-restart catturata**:
  `C:\doomsday-engine-prod\data\verifica_fix_baseline.json`.

**2. Monitor live** — poll 10 min che riusa la logica del tool e stampa SOLO
transizioni azionabili: `REGRESSIONE:` (nuova), `RIENTRO:`, `ATTIVAZIONE R-0x:`
(primo esercizio di un fix), `ERRORE-MONITOR:`. Silenzio = salute.

**Dipendenza restart (vincolante)**: i fix diventano attivi solo dopo il
riavvio di **BOT** (R-03/R-04/R-05/R-09) e **DASHBOARD** (R-02). Prima del
restart il monitor è correttamente muto e il `--check` confronta baseline↔se
stessa (nessuna regressione). Il valore diagnostico parte **dopo** il restart:
finestra 24h che sfuma da old-code a new-code, throughput e fail_rate non devono
peggiorare oltre soglia.

### Asse 2 — Architettura & manutenibilità
- **[seed, già noto]** Config-tangle risoluzione task list (3 meccanismi
  sovrapposti) — già in refactor, vedi `master-tasks-refactor-design.md`. Non
  ri-analizzare, referenziare.

### Asse 3 — Performance & efficienza
- **[seed, da verificare]** Timeout arena (~78% sfide a timeout 10s) — osservato
  oggi, ipotesi template stale (issue `arena-combat.md`). Candidato asse 3+1.
- **[seed, da verificare]** Delay UI fissi (`sleep(2.0)` ecc.) — misura in corso
  (rifornimento delay-measure). Referenziare.

### Asse 4 — Dashboard + Affidabilità/Test
- **[seed, sistemico]** Bug-class field-wipe Pydantic (`IstanzaOverride`) —
  colpito 2 volte oggi (raccolta_reset_leggero + master_task_whitelist mancanti
  dal modello). Verificare se altri campi runtime_overrides sono a rischio.
- **[seed]** ~51 test falliti pre-esistenti (`ImportError: KeyCall`, marker
  asyncio, firme disallineate) — inventariare e classificare.

## 3. Planning prioritizzato (a fine analisi)
_(matrice impatto × sforzo × rischio — da compilare)_

## 4. Log revisione (autonomo)
- **17/07 ~23:xx — Claude**: doc creato, Fase A avviata (snapshot live). Kickoff
  a Gemini con divisione compiti: Gemini → 1b riconciliazione 07/06 + 1c mining
  hotspot; Claude → verifica e qualificazione. Cadenza 20-30 min, incrementi.
