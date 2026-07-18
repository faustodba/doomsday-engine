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
MEDIO-ALTA (sistemico)** · evidenza: `dashboard/routers/api_config_overrides.py:64`
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
**severità MEDIA** · evidenza: `tasks/raccolta.py` `_esegui_marcia`: dopo tap
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
**severità MEDIA** · `tasks/rifornimento.py:793-807`: dopo `tap(coord_vai)` +
`sleep(2.5)` ritorna `True` senza accertare che la maschera si sia chiusa/l'invio
sia partito. Se il tap fallisce (lag UI), il bot registra come inviata una
quantità mai partita → **contabilità corrotta** + delay viaggio sprecato nel
predictor. (C9, evidenza Gemini; pattern gemello di R-03). **Proposta**:
post-verifica (maschera chiusa / conferma invio) prima di ritornare success.

**[R-05] Policy incoerente su fallimento gate HOME** · **severità MEDIA
(consistenza)** · Claude VERIFICATO: stessa condizione `vai_in_home()==False` →
`alleanza.py:73` ritorna **skip** (posticipa 4h), `messaggi.py:125` e
`boost.py:183` ritornano **fail** (retry immediato). Su un'istanza bloccata,
comportamenti divergenti → messaggi/boost affaticano l'emulatore con retry.
Inoltre **ridondante** col gate HOME dell'orchestrator (`orchestrator.py:242`).
**Proposta**: policy unica (preferibile delegare al gate orchestrator + rimuovere
i check duplicati nei task, o uniformare a skip). (C12)

### Asse 2 — Architettura & manutenibilità
- **[seed, già noto]** Config-tangle risoluzione task list (3 meccanismi
  sovrapposti) — già in refactor, vedi `master-tasks-refactor-design.md`.
- Vedi R-02 (field-wipe Pydantic, sistemico) sopra.

**[R-06] Logica window DistrictShowdown duplicata** · **severità MEDIA (debito)**
· `core/cycle_duration_predictor.py:773-800` duplica la logica date/ore weekend di
`tasks/district_showdown.py:191-215`. Rischio disallineamento: cambiando gli orari
del task senza aggiornare la copia nel predictor → stime ciclo errate. (C13,
evidenza Gemini). **Proposta**: unificare in una funzione condivisa (stesso
principio di `risolvi_task_istanza` del refactor task).

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
**severità BASSA-MEDIA (efficienza)** · `tasks/store.py:792-794`: `STORE_NON_TROVATO`
→ `fail()`. Lo scheduler non salva `last_run` sui fail → ritenta ogni ciclo
(~20-30s scan griglia sprecati/ciclo). Latente oggi (edifici posizionati bene),
ma spreca tempo se un edificio si sposta. (C8). **Proposta**: `skip()` quando
la causa è "non trovato" (condizione ambientale, non errore tecnico).

**[R-08] DistrictShowdown senza persistenza dadi → rinaviga ogni tick** ·
**severità BASSA-MEDIA (efficienza)** · `tasks/district_showdown.py:184-185`
`e_dovuto → True` sempre in-window, nessuno stato "dadi esauriti" su disco. Con
dadi a zero, apre comunque il menu evento ogni ciclo per 3 giorni (~1-2 min
navigazione sprecata/tick). (C11). **Proposta**: state persistito (come
BoostState/VipState) che marca "dadi esauriti oggi" → skip.

### Asse 4 — Dashboard + Affidabilità/Test
- Vedi R-01 (auth, LAN → basso) e R-02 (field-wipe) sopra.

**[R-09] `max_squadre`/`livello` static ignorati (fallback hardcoded)** ·
**severità MEDIA** · `config/config_loader.py:1265-1266`: `_ovr("max_squadre", 4)`
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
