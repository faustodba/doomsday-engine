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
tunnel/reverse-proxy autenticato se serve accesso remoto. · **ESCALATO
all'utente** (dipende dall'esposizione di rete reale — vedi domanda).

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
_(in attesa Fase A)_

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
