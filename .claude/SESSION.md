# SESSION.md — Handoff Doomsday Engine V6

## Sessione 26/05/2026 (update 2) — Dynamic url_prefix: fix CSS locale dopo sub-path ngrok

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: IN ESECUZIONE con url_prefix dinamico ✓
- **Dashboard locale**: funziona su `http://localhost:8765/` senza prefisso ✓

### Problema

Dopo il fix sub-path (sessione 26/05), la dashboard locale (`localhost:8765`) aveva il CSS
rotto: `_URL_PREFIX = "/doomsday"` era statico, quindi i link diventavano
`/doomsday/static/style.css` anche in locale dove il prefisso non esiste.

### Fix: ContextVar + _DynamicPrefix

Il prefisso viene rilevato a runtime per ogni request tramite header `X-Forwarded-Proto`:
- Via ngrok/Caddy: `x-forwarded-proto: https` → prefisso `/doomsday`
- In locale: header assente → prefisso `""`

```python
_url_prefix_ctx: ContextVar[str] = ContextVar("url_prefix", default="")

class _DynamicPrefix:
    def __str__(self) -> str: return _url_prefix_ctx.get()
    def __html__(self) -> str: return _url_prefix_ctx.get()

templates.env.globals["url_prefix"] = _DynamicPrefix()

@app.middleware("http")
async def _url_prefix_middleware(request, call_next):
    proto = request.headers.get("x-forwarded-proto", "")
    token = _url_prefix_ctx.set(_URL_PREFIX if proto == "https" else "")
    try:
        return await call_next(request)
    finally:
        _url_prefix_ctx.reset(token)
```

Aggiornate anche 3 `RedirectResponse` per usare `_url_prefix_ctx.get()` invece di `_URL_PREFIX`.
Template invariati: `{{ url_prefix }}` funziona perché il global è ora l'oggetto dinamico.

**File modificati**: `dashboard/app.py`.
**Sync prod**: xcopy `dashboard/` → `C:\doomsday-engine-prod\dashboard\` → restart dashboard. ✓

---

## Sessione 26/05/2026 (update) — CSS fix: sync_prod.bat mancante

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: IN ESECUZIONE con `DASHBOARD_URL_PREFIX=/doomsday` ✓

### Fix applicato

CSS non si renderizzava via ngrok: il problema era che i fix (app.py + templates) erano stati fatti
in `C:\doomsday-engine` (dev) ma NON deployati in `C:\doomsday-engine-prod` (prod).

**Causa root:** `sync_prod.bat` non era stato eseguito dopo i fix della sessione precedente.
`C:\doomsday-engine-prod` non è un git repo — il codice va copiato esplicitamente.

**Fix:** xcopy manuale `dashboard/` + resto codice da dev a prod (equivalente a `sync_prod.bat`).
Dashboard riavviata con env var corretta. CSS link ora è `/doomsday/static/style.css`. ✓

**Regola:** dopo ogni modifica a `dashboard/` o altro codice Python, eseguire `sync_prod.bat`
prima di riavviare il processo prod.

---

## Sessione 26/05/2026 — Sub-path deployment via ngrok/Caddy

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: richiede restart uvicorn per attivare le modifiche sub-path (ora completato)

### Lavoro completato

**Sub-path deployment support** — la dashboard può ora essere esposta via ngrok sotto `/doomsday/`
senza che i path assoluti nei template rompano la navigazione e le chiamate API.

**Meccanismo:**
- `app.py`: aggiunto `DASHBOARD_URL_PREFIX` env var (default `""`); iniettato come Jinja2 global `url_prefix`
- Tutti i template Jinja2: path assoluti convertiti in `{{ url_prefix }}/path` per href, hx-get, hx-post, hx-patch, hx-delete
- JS in template: aggiunto `const URL_PREFIX = '{{ url_prefix }}';` in `base.html`; tutte le `fetch('/api/...')` e `htmx.ajax(...)` usano `URL_PREFIX + '/...'`
- `run_dashboard_prod.bat` (prod + dev): aggiunto `set DASHBOARD_URL_PREFIX=/doomsday`
- App redirects interni (`/`, `/ui/predictor`, `/ui/config`): aggiornati a usare `_URL_PREFIX`

**File modificati:**
- `dashboard/app.py` — DASHBOARD_URL_PREFIX + Jinja2 global + redirect
- `dashboard/templates/base.html` — static, nav, HTMX polling, JS URL_PREFIX, fetch
- `dashboard/templates/` — ab_test, index, advanced, config_global, instance, raccolta, telemetria, storico, predictor_istanze
- `dashboard/templates/partials/` — notifications_card, telegram_card, adaptive_scheduler_card, task_flags
- `run_dashboard_prod.bat` (C:\doomsday-engine-prod e C:\doomsday-engine)

**Non modificati (orfani/legacy):**
- `templates/predictor.html` — non servito da app.py (redirect a predictor_istanze)
- `templates/config_overrides.html.legacy` — non attivo

**Per attivare:** riavviare `run_dashboard_prod.bat` da `C:\doomsday-engine-prod`

**Accesso locale invariato:** senza `DASHBOARD_URL_PREFIX` (o con `=""`), tutto funziona come prima su `http://localhost:8765/`

### Pendenze ereditate

- **Restart dashboard prod** (commit `7927a71` — `shared/prod_unificata.py`)
- **AI Advisor concept** — lasciato in pending esplicito dall'utente

---

## Sessione 24/05/2026 (chiusura) — prod_unificata master fix + DS AP poll + docs reference

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: richiede restart uvicorn per caricare `shared/prod_unificata.py` (commit `7927a71` sessione precedente)
- **Telegram bot**: IN ESECUZIONE (PID 21536)

### Lavoro completato

**1. prod_unificata HTML renderer (daily report sez. 2)**
Completato renderer HTML sezione 2 "PRODUZIONE INTERNA RIFUGIO" in `core/daily_report.py`.
Blocco `prod_unificata` inserito dopo `n_sess_anomali` (~riga 1533), prima di `# 3. RISORSE INVIATE AL MASTER`.
Mostra: farm total `prod_unif_farm_h` M pom-eq/h + tabella per istanza.

**2. Fix master in prod_unificata**
- `dashboard/services/stats_reader.py::get_produzione_istanze`: se `is_m` → `_pu_empty()` (skip compute per master)
- `core/daily_report.py`: `farm_pom_eq` usa `totali_ord` solo istanze ordinarie; `master_row["prod_unif_h"] = 0.0`
- Root cause: `FauMorfeus.json::produzione_qty` include risorse ricevute via rifornimento. WU128 non funziona cross-mezzanotte UTC. Fix definitivo: escludi master dalla metrica.

**3. Fix DS AP poll — early exit transizione**
`tasks/district_showdown.py::_attendi_ap_chiuso()`: counter `streak_transizione`.
Dopo popup closes, `pin_dado` non matchato durante animazione → 45s sprecati.
Fix: dopo 3 poll "transizione, nessun pin" → return immediato. Reset su `has_ap.found`.

**4. JavaDoc HTML reference documentation**
Nuovo `docs/reference.html` (96KB, 1257 righe) dark theme, sidebar fissa 22 sezioni, 29 tabelle metodi.
Fix: "Rise of Kingdoms" → "Doomsday: Last Survivors".

### Commit questa sessione

| Hash | Descrizione |
|------|-------------|
| `86a1aeb` | feat(prod_unificata): Telegram /produzione + daily report HTML sezione 2 |
| `2ae8e56` | fix(prod_unificata): escludi master da prod_unif_h |
| `4162cd6` | fix(DS): AP poll — early exit dopo 3 poll consecutivi di transizione |
| `6f1e368` | docs: JavaDoc HTML reference documentation (96KB, 1257 righe) |
| `60db5ea` | docs: fix nome gioco Rise of Kingdoms -> Doomsday: Last Survivors |

### Pendenze

- **Restart dashboard prod** per caricare `shared/prod_unificata.py` (commit `7927a71`, sessione precedente)
- **AI Advisor concept** — lasciato in pending esplicito dall'utente

### Prossimo step

- Restart dashboard prod → verifica sezione 2 daily report + Telegram `/produzione`
- Monitor DS prossima finestra evento (Ven-Lun UTC): cercare `[DS] AP: transizione persistente` nel log

---

## Sessione 24/05/2026 (aggiornamento) — prod_unificata delta-based

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: richiede restart uvicorn per caricare `shared/prod_unificata.py` aggiornato
- **Commit**: `7927a71` — feat(prod_unificata): delta-based production metric from produzione_storico

### Lavoro completato

**Metrica prod_unificata reale** — usa `produzione_qty` da `produzione_storico` invece di `dettaglio_oggi`.

Formula: `prod_r = (deposit_N1 - deposit_N + inviato_N→N1) / 24h` — già calcolato dal bot in `chiudi_sessione_e_calcola`. Floor a 0 per delta negativi.

Valori smoke test: FAU_00=2.976, FAU_01=1.124, FAU_03=1.414, FAU_10=1.241 M pom-eq/h (fonte=storico).

**Prossimo step**: restart dashboard prod per caricare `prod_unificata.py` aggiornato.

---

## Sessione 24/05/2026 — Bug FT flag FAU_00 chiuso

### Stato corrente

- **Bot prod**: IN ESECUZIONE
- **Dashboard prod**: riavviata con fix `f0ac930` attivo in memoria
- **Bug FT flag FAU_00**: ✅ CHIUSO

### Bug FT — raccolta_fuori_territorio FAU_00

**Commit fix**: `f0ac930` — `dashboard/routers/api_config_overrides.py:691`: aggiunto `raccolta_fuori_territorio` nell'`allowed` set del PATCH `/api/config/overrides/istanze/{nome}`. Senza questa chiave il payload era silenziosamente droppato ad ogni save dalla card HOME.

**Stato finale verificato**:
- `runtime_overrides.json` prod FAU_00: `raccolta_fuori_territorio: true` ✓
- Dashboard HOME card ic-ft: `checked` ✓
- Log bot 24/05 UTC 05:17-05:19: 5/5 marce, 0 territory check ✓
- `RaccoltaFastTask` rispetta il flag via `RACCOLTA_FUORI_TERRITORIO_ABILITATA` in `tasks/raccolta_fast.py:388-389` ✓

### WU-RaccoltaStats — pagina analisi nodi raccolta ✅

**Commit**: `4a5ba8f` — nuova pagina `/ui/raccolta` con tabella Layout B (righe=istanze, colonne=tipo×livello).

**Sorgente**: `data/cap_nodi_dataset.jsonl` (scritto da `shared/cap_nodi_dataset.py` dopo ogni marcia raccolta — dati persistenti, non log).

**Funzionalità**:
- `get_raccolta_nodi_stats(days)` in `stats_reader.py`: aggrega fill rate (load_squadra/capacita) per tipo × livello × istanza
- Tipi: `campo→🍅pomodoro`, `segheria→🪵legno`, `acciaio`, `petrolio` / livelli L6+L7+tot
- Fill rate colorato: ≥95% verde (satura), 75-94% giallo (marginale), <75% rosso (underprovisioned)
- FauMorfeus esclusa, outlier fill>150% filtrati
- Riga TOTALE FARM in cima, istanze ordinate per fill% ASC (peggiori prima)
- Filtro periodo 7gg/30gg/tutti via query param `?days=N`
- Nav link "raccolta" tra "telemetria" e "predictor istanze"

**Test prod**: 1387 record 7gg, 11 istanze, fill tot 99.3%

### Prossimo step

- Riavviare dashboard prod per attivare `4a5ba8f` (uvicorn no --reload)
- Verificare durante prossima finestra DS (Ven-Lun UTC): log `[DS] banner chiuso (score=...) — tap apri (345,63)`

---

## Sessione 23/05/2026 — WU-RifCentratura validato + fix Telegram /rifornimento + DS banner aperto

### Stato corrente

- **Bot prod**: IN ESECUZIONE (FAU_04 ciclo corrente ~12:00 UTC)
- **WU-RifornimentoCentratura (da86da0)**: ✅ VALIDATO PROD — 4 "tap diretto castello cached" per istanza su FAU_00/01/02/03. Saving confermato ~6 min/ciclo
- **Telegram /rifornimento bug (e48d3a8)**: ✅ RISOLTO — bot riavviato (PID 21536)
- **DS banner fix (adf9008)**: ✅ IMPLEMENTATO — in attesa prossima finestra evento (Ven-Lun UTC)
- **WU162 double-thread**: ✅ CONFERMATO RISOLTO
- **Fix raccolta livello (e7421c5)**: ✅ VALIDATO
- **Telegram bot**: IN ESECUZIONE (PID 21536)

### Commit questa sessione

| Hash | Fix |
|------|-----|
| `da86da0` | perf(rifornimento): skip centratura mappa dopo la prima spedizione |
| `e48d3a8` | fix(telegram): /rifornimento — dettaglio_oggi è lista non dict |
| `adf9008` | fix(district_showdown): apri banner prima di cercare icona, chiudi su tutti i path uscita |

### WU-RifCentratura — validazione ✅

**Dati prod FAU_00/01/02/03** (ciclo 23/05 08:09-09:37 UTC):
- Ogni istanza: **4 "tap diretto castello cached"** per ciclo (sped 2-5 skip centratura, solo sped 1 fa centratura completa)
- Throughput invariato: 5/5 spedizioni per ogni istanza
- Nessun fallback "ri-centro" → tap diretto sempre funzionante
- Saving confermato: ~8s × 4 × 11 istanze ≈ **~6 min/ciclo**

### Fix Telegram /rifornimento

**Bug**: `_build_rifornimento()` in `core/telegram_bot.py:755-756` chiamava `det.values()` ma `dettaglio_oggi` è una **lista** `[{ts, risorsa, qta_inviata, ...}]`, non un dict.

**Fix**: `rif.get("dettaglio_oggi", [])` + iterazione diretta `for v in det` (senza `.values()`).

**Bot riavviato**: vecchio PID 15028 killato, nuovo PID 21536 attivo con codice corretto.

### Fix DS banner aperto per ricerca icona

**Regola**: il tab banner eventi laterale deve essere **sempre chiuso** (icone righe 2/3 si nascondono quando aperto). DS è l'**unica eccezione**: deve aprire il banner prima di cercare `pin_district_showdown`, poi chiuderlo su TUTTI i path di uscita.

**Implementazione** (`tasks/district_showdown.py::run()`):
1. Pre-`_apri_evento`: screenshot → se score `pin_banner_chiuso ≥ 0.85` → tap `(345,63)` + sleep 1.0s (apre banner)
2. `_chiudi_banner()` helper locale (chiama `comprimi_banner_home`)
3. `_chiudi_banner()` su 3 path di uscita: `_apri_evento` fallisce · `_attiva_auto_roll` fallisce · completamento normale

**Da validare**: prossima finestra DS (Ven 00:00 → Lun 00:00 UTC). Log atteso: `[DS] banner chiuso (score=...) — tap apri (345,63)`.

### Prossimo step

- Verificare durante prossima finestra DS: log `[DS] banner chiuso (score=...) — tap apri` nei FAU_*.jsonl
- Monitorare ri-centratura rifornimento (`ri-centro e riprovo`) — dai dati odierni mai attivata, comportamento atteso

### Chiusura sessione

- Monitor `b04p6kjqh` chiuso (ciclo pulito FAU_00→FAU_06, nessuna anomalia)
- Bot prod: in esecuzione (FAU_07+ in corso)
- Telegram bot: in esecuzione (PID 21536)
- Tutti i commit pushati su `origin/main` (ultimo: `621f208`)
- Documentazione aggiornata: SESSION.md + ROADMAP.md + CLAUDE.md

---

## Sessione 22/05/2026 (aggiornamento 2) — validazione fix + Telegram 409 risolto

### Stato corrente (al termine della sessione)

- **WU162 double-thread**: ✅ CONFERMATO RISOLTO — nessun log doppio dopo reboot PC
- **Fix raccolta livello (e7421c5)**: ✅ VALIDATO — 0 NON selezionato, 0 tipo_bloccato su FAU_01/02/03/05
- **Telegram bot 409**: ✅ RISOLTO — processo concorrente sparito; aggiunto sleep 5s su risposta vuota rapida (commit `0d09018`)
- **Telegram bot**: NON in esecuzione — richiede avvio manuale `run_telegram_prod.bat`

### Commit sessione 22/05

| Hash | Fix |
|------|-----|
| `e7421c5` | fix(raccolta): delay reset 0.3→0.8s + rilettura livello + verifica pre-CERCA |
| `1cd2337` | fix(telegram): rimuovi /rifornimento duplicato da /help |
| `0d09018` | fix(telegram): sleep 5s su risposta vuota rapida (409) nel polling loop |

---

## Sessione 22/05/2026 — WU162 startup double-thread fix (PID file + CIM)

### Problema risolto

**Double-thread bug** (FAU_08, FAU_10 avviate due volte): il vecchio processo bot non veniva killato al riavvio, lasciando i suoi thread daemon (in `attendi_home` fase 4) vivi mentre il nuovo bot avviava nuovi thread per le stesse istanze. Entrambi i processi scrivevano su `bot.log` con lo stesso prefisso istanza.

Root cause `_cleanup_orfani_processi_startup`:
1. Usava `Get-WmiObject` (deprecato/silent-fail in PS7+) → `returncode != 0` → `return []` silenzioso
2. Filtrava solo `python.exe` ma il bat usa `py -3.14 main.py` → possibile residuo `py.exe`
3. Nessun meccanismo di fallback indipendente da WMI

### Fix WU162 (commit `7e34484`)

**`main.py` + `run_prod.bat`** (dev e prod aggiornati):
- **Meccanismo 0 (PID file)**: al boot legge `data/bot.pid` e killa quel PID con `taskkill /F /PID` — affidabile indipendentemente da WMI e nomi processo. Alla fine scrive PID corrente su file.
- **Get-WmiObject → Get-CimInstance**: fix per PS7+ compatibility
- **Diagnostic logging**: returncode + stderr del CIM query esposti nel log (non più silenti)
- **py.exe aggiunto**: terza query per `py.exe` con `*main.py*` nel cmdline
- `run_prod.bat`: stesso approccio dual-level (bot.pid + CIM dual-name) PRIMA del lancio python

### Log atteso al prossimo avvio

```
[CLEANUP-ORFANI] PID-file: killed old bot PID=XXXXX
cleanup orfani: cmd killed=0  | python killed=N [...] | current_pid=YYYYY parent=ZZZZZ
```

oppure, se old bot era già uscito normalmente:
```
[CLEANUP-ORFANI] PID-file: old bot PID=XXXXX non trovato (già uscito)
```

### Stato post-sessione

- Commit `7e34484` su `main`, push OK
- Dev e prod entrambi aggiornati (main.py + run_prod.bat)
- **Restart bot necessario** per attivare — al prossimo `run_prod.bat` il bot.pid sarà scritto

### Prossimo step

- Al prossimo restart bot: verificare log `[CLEANUP-ORFANI]` — deve mostrare il kill del vecchio PID
- Verificare assenza di log doppi per stessa istanza (es. due "in attesa... (Xs)" con elapsed alternanti)
- Se il bug si ripete → guardare `r.stderr` nel log CIM query (nuova diagnostica) per capire se filtro ancora fallisce

---

## Sessione 19/05/2026 (aggiornamento) — WU-Telegram /istanze enhanced

### Fix completati (aggiornamento 2)

**`/istanze` enhanced** (commit `8aca94b`):
- Header: `ciclo #N | 🎯 Adaptive LIVE/👁 SHADOW/📋 Sequenza fissa | 🟢/🔴 bot attivo`
- Ordine istanze per timestamp ultima esecuzione (sequenza ciclo ascendente)
- Istanza LIVE: `▶ LIVE` con task corrente in corso
- Già eseguita questo ciclo: icona outcome + "(X fa)" in corsivo
- In attesa: `⏳ attesa`
- Bot spento: per ogni istanza mostra ultimo outcome + "X fa"
- Aggiornati `_read_all_last_metrics()` e `_parse_dt()` helper
- Testato su prod con FAU_08 live: output corretto con 3 completed + live + 8 waiting

### Stato post-sessione

- Commit `8aca94b` su `main`, push OK
- Prod: `core/telegram_bot.py` aggiornato manualmente
- Telegram service: restart necessario per caricare nuovo codice

---

## Sessione 19/05/2026 (continua) — WU-Telegram standalone + fix operativi

### Fix completati (aggiornamento)

**WU-Telegram-Standalone** (commit `4cb6178`): fix operatività senza VSCode
- `core/telegram_bot.py::_launch_bat`: fix critico — Popen su `.bat` senza shell=True fallisce.
  Ora usa `["cmd", "/c", "start", f'"{label}"', str(bat_path)]` — cmd gestisce l'associazione .bat→cmd.exe
  e apre la nuova finestra console correttamente anche quando Python non è in un terminale.
- `run_telegram_prod.bat`: `python` → `C:\Python314\python.exe` (full path per Task Scheduler, non dipende dal PATH utente)
- `sync_prod.bat`: aggiunto `run_telegram_prod.bat` nella lista file da sincronizzare

**WU-Telegram** (commit `cf45d4d` + `02abfd3` + `475986c`): sistema Telegram completo (3 processi indipendenti)
- `shared/telegram_client.py`: client stdlib urllib, token+chat_id in `data/secrets.json`
- `core/telegram_bot.py`: daemon polling + comandi + notifiche + avvio sistema
- `run_telegram_prod.bat`: auto-restart loop (crash recovery 10s)
- `setup_telegram_autostart.bat`: registra Task Scheduler (onlogon, delay 1min)
- Comandi: /help /status /istanze /rifornimento /stop /avvia /stop_messaggi /start_messaggi /avvia_bot /avvia_dashboard /avvia_tutto
- Boot notification: uptime<300s → "⚡ Riavvio PC", else "▶ bot avviato" + stato bot/dashboard + azioni rapide

**Setup richiesto dall'utente (una tantum)**:
1. Creare bot su @BotFather → /newbot → copiare token
2. Dashboard → Config globale → sezione "💬 telegram bot" → incollare token → salva
3. Inviare /start al bot → ottenere chat_id → incollare in dashboard → salva
4. Abilitare toggle "abilitato" per notifiche proattive
5. Fare "📤 invia messaggio test" per verifica
6. `setup_telegram_autostart.bat` come amministratore → Task Scheduler registrato

**Architettura 3 processi indipendenti**:
- Telegram: Task Scheduler → `run_telegram_prod.bat` (sempre, anche senza VSCode)
- Dashboard: `run_dashboard_prod.bat` (manuale o `/avvia_dashboard`)
- Bot: `run_prod.bat` (manuale o `/avvia_bot`)

### Setup completato ✅

- Token: `@fau_doomsday_bot` (DoomsDayBot) salvato in `data/secrets.json` prod
- Chat ID: `964056909` (@Faustodoom) salvato in `data/secrets.json` prod
- Messaggio di test inviato e ricevuto OK
- Autostart: `TelegramDoomBot.lnk` nella cartella Startup utente (no admin necessario)
- `StartDoomBot.bat.lnk` eliminato (obsoleto)

### Prossimo step

- **Avviare bot Telegram** (doppio click su `run_telegram_prod.bat` o riavvio PC)
- **Abilitare notifiche proattive** da dashboard → Config globale → toggle "abilitato"
- **Verificare /status** via Telegram una volta avviato il processo

---

## Sessione 19/05/2026 — WU163 zombie MuMu + WU164 raccolta_fast delay + timeout_adb_s

### Stato corrente

- **Bot prod**: gira. Tutte le fix di questa sessione richiedono restart bot per attivarsi.
- **Dashboard prod**: modificata (timestamp su log) → restart uvicorn necessario.
- **Contesto dual-bot**: su questo PC gira un altro bot (non correlato a V6) → CPU/RAM condivisa → MuMu più lento → delay UI calibrati su PC singolo possono non bastare.

### Fix completati questa sessione

**WU163** (`main.py`, commit `d522a51`): zombie MuMu su timeout avvio Android
- Root cause: `avvia_istanza()` timed-out (60s) ma `chiudi_istanza()` non veniva chiamata → MuMu restava aperto → accumulo zombie → 5 istanze contemporanee
- Fix: aggiunto `chiudi_istanza()` nel ramo `avvia_istanza()` failed

**WU164** (`tasks/raccolta_fast.py`, commit `e4a4ecb`): FAST_DELAY_SQUADRA 1.2→2.0s
- Root cause: maschera score=0.388 NON aperta (no retry) su FAU_00 → recovery 30s × 4 fail → 1/5 marce in 354s
- `tap_squadra` apre pannello truppe (overlay) → violava DELAY UI vincolante (min 2.0s)
- La raccolta standard con 1.8s ottiene score=1.000 stesso device
- Fix: 2.0s (DELAY UI vincolante)

**timeout_adb_s** (`config_loader.py`, `global_config.json`, `runtime_overrides.json`): 120→300s
- AdaptiveTiming con base=120s portava il timeout a 60s (lower_cap=fallback/2)
- Ora base=300s → lower_cap=150s
- Aggiunto propagazione `sistema.timeout_adb_s` → `mumu.timeout_adb_s` in config_loader
- Campo UI aggiunto in index.html e config_global.html

**Dashboard timestamps** (`dashboard/app.py`): print con UTC timestamp su log predictor

### Analisi ciclo 151 (lento: 4h3min totale, FAU_00 = 26min)

- FAU_00 usa `raccolta_fast`: ogni marcia falliva maschera 1-shot → recovery 30s → solo 1/5 marce
- Root cause: FAST_DELAY_SQUADRA=1.2s insufficiente su PC a carico condiviso
- Risolto da WU164
- Ciclo totale lungo anche per boot lenti causa dual-bot (PC condiviso)

### Monitoraggio dual-bot

Segnali da osservare nei prossimi cicli:
- Score 0.35-0.50 su template panel dopo tap → delay specifico da alzare
- Recovery frequente in raccolta_fast o altri task → fail sulla fase panel
- Boot HOME >4min → MuMu sotto pressione, valutare riduzione istanze

### Prossimo step

- **Restart bot** → attiva WU163 (zombie), WU164 (raccolta_fast delay), timeout_adb_s=300s
- **Restart dashboard** → attiva timestamp log
- **Verificare ciclo successivo FAU_00**: raccolta_fast deve inviare >3/5 marce senza recovery
- **Osservare** altri task per score anomali simili (0.35-0.50) da dual-bot load

---

## Sessione 18/05/2026 — WU161 rifornimento falso positivo pin

### Stato corrente

- **Bot prod**: gira (ciclo corrente, FAU_05 appena avviato dopo FAU_08). WU161 in prod, attivo al prossimo restart.
- **Fix in prod (richiedono restart)**:
  - WU159 `tasks/rifornimento.py`: `AVATAR_MAPPA_SOGLIA` 0.75→0.55 (base ancora necessaria per retry ROI)
  - WU160 `tasks/raccolta.py`: fallback livello 6→7 ripristinato — **CONFERMATO FUNZIONANTE** (FAU_08 ciclo 0: L6→L7 fallback triggered, 4/4 marce OK)
  - **WU161 `tasks/rifornimento.py`**: soglia ROI primaria 0.55→0.70 — **DA VERIFICARE** al prossimo ciclo dopo restart
- **Stato repository**: push fatto, `main` allineato a `origin/main` (commit `8a22bbd`).

### Root cause WU159 ancora broken → WU161

- WU159 aveva abbassato `AVATAR_MAPPA_SOGLIA` 0.75→0.55 per coprire istanze con score basso
- **Ma** la stessa soglia era usata per la ROI primaria (200×200 centrata su mappa)
- FAU_08 ciclo 0 (UTC 11:01): score=0.558 in ROI primaria → `r.found=True` → retry ROI mai eseguito
- Tap a (402,260) che è un elemento sbagliato → RESOURCE SUPPLY score=0.377 → 0 spedizioni
- Il castello reale è a ~(487,199), stesso per tutte le istanze (stessa destinazione master)

### WU161 — fix

- `tasks/rifornimento.py:406-416`: `_SOGLIA_PRI = 0.70` per ROI primaria
- Retry ROI (300×300) usa ancora `soglia=0.55` da `AVATAR_MAPPA_SOGLIA`
- Score=0.558 < 0.70 → fail primaria → trigger retry → trova castello reale
- FAU_00 con score=1.000 → primaria passa immediatamente → invariato

### WU160 confermato

- FAU_08 ciclo 0 log UTC 11:09: "tentativo CERCA campo Lv.7" → "nodo trovato a Lv.7" → 4/4 marce
- Monitor bjvcyhisc mostra FAU_05 con sped=0, provv=-1 → stessa causa WU161 (stesso ciclo corrente, vecchio codice)

### Prossimo step

- **Restart bot** → attiva WU161
- **Verificare dopo restart**: rifornimento FAU_05/08 (e tutte le istanze) → sped > 0
- **Log da controllare** (FAU_08.jsonl cycle 1): `"pin destinatario [ROI primaria] score=... soglia=0.70 found=False"` → `"[ROI retry] score=... found=True"` → RESOURCE SUPPLY trovato → spedizioni OK
- Monitor bjvcyhisc/be57azxh9 armati, si attivano su eventi rifornimento/raccolta

---

## Sessione 14/05/2026 — Verifica allocazione + revert WU151 FIX A radar

### Stato corrente

- **Bot prod**: gira. Nessun restart necessario per le modifiche di questa sessione (solo revert `radar_actions.py`, già sincronizzato in prod).
- **Dashboard prod**: nessuna modifica. Nessun restart necessario.
- **Stato repository**: pulito post-commit `1aa637a` (revert WU151 FIX A). Branch `main` allineato a `origin/main`.

### Lavoro completato

**Verifica sistema allocazione raccolta** (analisi, nessun fix necessario):
- Traccia completa flusso: dashboard → disco → `merge_config` → `GlobalConfig._from_raw` → bot
- Raccolta usa percentuali su disco (0-100), rifornimento usa frazioni (0-1). Design inconsistency documentata, non bug.
- Bot auto-rileva formato raccolta via `_al_div = 100 if max(values) > 1 else 1`
- Fragilità teorica (display 0% se overrides mancanti) non impatta prod attuale
- Algoritmo allocazione spiegato: weighted-deficit su composizione attuale castello vs target

**Revert WU151 FIX A** (`tasks/radar_actions.py`, commit `1aa637a`):
- Rimosso pre-check popup via pixel test (90,465) — causava falsi positivi su mappa luminosa
- FIX B (stagnant detector) gestisce il caso popup residuo con overhead ~30s
- Dev = prod (sync già avvenuto prima del commit)
- `popup_pre_resolved` sempre False nel dict telemetria (campo mantenuto per compat)

### Prossimo step

- **Domani**: verificare log radar — cercare `[SAFETY] iter stagnante` per confermare FIX B funziona correttamente su popup residui
- **Pending da sessioni precedenti**: restart bot prod ancora pendente per WU155 (timeout 300s) + WU157 (gate centralizzati `shared/task_scheduling.py`) — nessun restart fatto oggi
- **WU158 integrazione**: anagrafe avatar ancora da integrare nel bot (POC validato 12/05, script standalone in `c:/tmp/`)

---

## Sessione 12/05/2026 — WU155 + WU156 + WU157 (timeout boot + predictor sync arena + gate centralizzati)

### Stato corrente

- **Bot prod**: gira con il codice del commit precedente al WU155/156/157. Modifiche WU155 (timeout 300s + dashboard sistema), WU156 (predictor edge case arena UTC<10, poi superseded), WU157 (gate centralizzati `shared/task_scheduling.py`) **non ancora attive** in runtime → richiedono **restart bot prod** (`run_prod.bat`).
- **Dashboard prod**: file WU155 sincronizzati, ma processo uvicorn gira con Pydantic schema vecchio (no `timeout_carica_s`) → **restart dashboard pendente** per attivare l'input. Refresh browser sufficiente per le predizioni post-WU156/157 (la funzione `_is_task_due` è ricaricata at-call).
- **Stato repository**: pulito post-commit `c774049` (WU157). Branch `main` allineato a `origin/main`.

### Lavoro completato

**WU155 — Timeout boot HOME 180→300s + esposto in dashboard sezione sistema** (commit `22560d6`)
- Default `MumuConfig.timeout_carica_s` 180→300
- Nuovo path canonico dashboard `sistema.timeout_carica_s` (priorità `sistema.*` > `mumu.*` legacy > 300)
- `_merge_globali` propaga DYNAMIC → `merged.mumu.timeout_carica_s` finale
- `SistemaOverride` Pydantic: campo `timeout_carica_s: int = Field(default=300, ge=30, le=900)`
- UI HOME (`index.html`) + CONFIG (`config_global.html`): riga "timeout boot HOME (s)" range 30-900
- `global_config.json` prod+dev aggiornato (backup `.bak.20260511_wu155_timeout`)

**WU156 — Predictor: arena gate UTC<10 in `_is_task_due`** (commit `c740683`, **superseded da WU157**)
- Sintomo: predictor sovrastimava T_ciclo notturno 3-5min includendo arena (gate UTC<10 WU145 non sincronizzato)
- Fix temporaneo: edge case hardcoded `if task_name == "arena" and now_utc.hour < 10: return False` in `_is_task_due` branch daily
- Logica simmetrica a `main_mission` (WU91 UTC≥20)
- **Edge case rimosso da WU157** (sostituito da introspection registry)

**WU157 — Sistema centralizzato regole scheduling live ↔ predictor** (commit `c774049`)
- Pattern pre-WU157: ogni gate orario richiedeva 2 modifiche (live + predictor) con rischio drift (caso reale WU145→WU156: 2 giorni di drift)
- Nuovo modulo `shared/task_scheduling.py` (NEW):
  - `time_gate_arena(now=None) -> bool` (WU145, UTC>=10)
  - `time_gate_main_mission(now=None) -> bool` (WU91, UTC>=20)
  - `TIME_GATES: dict[str, Callable]` registry
  - `can_run_by_time_gate(task_name, now=None)` helper failsafe
- `tasks/arena.py` + `tasks/main_mission.py`: import + uso gate centralizzati
- `core/cycle_duration_predictor.py::_is_task_due`: chiamata `can_run_by_time_gate` early-return all'inizio + rimossi 2 edge case hardcoded WU91+WU145+WU156
- Smoke test: 11/11 gate function + 6/6 integrazione `_is_task_due` verdi
- Aggiungere nuovo gate in futuro: 1 sola modifica in `shared/task_scheduling.py` (definisci + registra) — predictor automaticamente coerente

### File modificati

WU155:
- `core/launcher.py` (default 300s)
- `core/config_loader.py` (path canonico + merge)
- `dashboard/models.py` (SistemaOverride field)
- `dashboard/templates/index.html` + `config_global.html` (input UI)
- `config/global_config.json` (prod+dev) + backup

WU156 (superseded):
- `core/cycle_duration_predictor.py` (edge case hardcoded, poi rimosso da WU157)

WU157:
- `shared/task_scheduling.py` (NEW)
- `tasks/arena.py` (import + uso)
- `tasks/main_mission.py` (import + uso)
- `core/cycle_duration_predictor.py` (import + introspection + rimozione edge case)

### Documentazione

- `.claude/CLAUDE.md` riga WU157 + WU156 marcata "superseded"
- `ROADMAP.md` sezione narrativa 12/05 pomeriggio
- Memory locale: `feedback_centralized_scheduling.md` + MEMORY.md updated
- Vault Obsidian: `03-WU/WU-157-Centralized-Scheduling-Rules.md` (NEW), `WU-156` marcato superseded, `_Index-WU.md` legenda stato `superseded`, `02-Memorie/Feedback/Centralized-Scheduling.md` (NEW), `Cycle-Predictor-Sync.md` cross-link aggiunto, `01-Doc-Operativa/ROADMAP-Sessioni.md` riga 12/05 pomeriggio

### Prossimo step

- Restart bot prod (`run_prod.bat`) per attivare WU155 + WU157 (no hot-reload moduli Python `shared`/`tasks`/`core`)
- Restart dashboard uvicorn per attivare WU155 Pydantic schema (`timeout_carica_s` input)
- Refresh browser per vedere predizioni post-WU157
- Monitorare prima sessione arena post-restart (10:00-24:00 UTC) per confermare gate centralizzato funzionante

### Pending da sessioni precedenti

- Restart bot per WU151 (radar popup pre-detect) + WU154 (rifornimento stop DRL=0): già pendente da 11/05 — coperto dal restart per WU155/157
- Restart dashboard per WU152 (adaptive scheduler dual-write) + WU153 (collapsable panels): coperto dal restart per WU155

---

## Sessione 11/05/2026 — WU147 + WU148 + WU149 (pin rifugio + scheduler flag fix + AB test page)

### Stato corrente
- **Bot prod**: gira (ciclo 2 da 10:50 locale post-restart utente). Codice WU147 attivo (pin rifornimento). Codice WU148 NON ancora attivo (planned_order in memoria del ciclo precedente, fix attivo al prossimo restart spontaneo).
- **Dashboard prod**: file WU149 sincronizzati ma processo uvicorn gira con codice vecchio → restart dashboard pendente per attivare `/ui/ab-test`.
- **Adaptive Scheduler**: precondizioni OFF (`flag_disabled` da WU148 fix). master_drl_residuo=174.5M, no precondizione attiva.
- **Test rifornimento WU147 validato live** su FAU_00 alle 08:46 UTC: pin score=1.000, RESOURCE SUPPLY OK, spedizione pomodoro netto 3.499M in 35.9s.

### Lavoro completato

**WU147 — Rifornimento pin centratura mappa**
- Nuovo template `templates/pin/pin_rifugio.png` (27×28, dev+prod md5 identici)
- `tasks/rifornimento.py::_DEFAULTS`: `AVATAR_MAPPA_TEMPLATE` separato + ROI 2-step primaria 200×200 / retry 300×300 + tap su `(r.cx, r.cy)` centro pin (no più offset_y hardcoded)
- Script test `c:/tmp/test_rifornimento_pin_rifugio.py` standalone su FAU_00, validato end-to-end

**WU148 — Bug fix adaptive_scheduler flag**
- `_flags_status()` ora legge DYNAMIC > STATIC (pattern uguale a `_rifornimento_abilitato`)
- `load_planned_order()` invalida cross-mezzanotte UTC
- `scheduler_planned_order.json` rinominato in `.bak.20260511_WU148`

**WU149 — Dashboard AB test page**
- 4 endpoint in `dashboard/app.py` (riga 304+) + nuovo template `ab_test.html` + voce nav in `base.html`
- 3 pannelli HTMX (riepilogo / trend SVG / tabella ultimi 15) sul file `data/predictions/scheduler_ab.jsonl` (31 record)
- 4 correzioni vs codice ricevuto (`_data_path`, `_env_css`, async→sync, import json)

### File modificati
- `templates/pin/pin_rifugio.png` (NEW)
- `tasks/rifornimento.py` (WU147)
- `core/adaptive_scheduler.py` (WU148)
- `dashboard/templates/ab_test.html` (NEW WU149)
- `dashboard/templates/base.html` (WU149 nav)
- `dashboard/app.py` (WU149 4 endpoint)
- `.claude/CLAUDE.md` (3 righe WU147/148/149) dev+prod
- `ROADMAP.md` (sessione 11/05) dev+prod

### Commits
- `2c52289` "feat: WU144-WU148 alert/arena/daily-report/pin-rifugio/scheduler-flag" (push origin/main)
- `2bb12b3` "Add AB test adaptive scheduler page WU149" (push pendente)

### Pendenze
- **Restart dashboard prod** per attivare `/ui/ab-test` (utente)
- **Restart bot prod** per attivare codice WU148 in memoria (opzionale: il fix scatta da solo al prossimo restart spontaneo)
- **Push commit `2bb12b3` + doc updates** su origin/main

### Prossimo step
Utente conferma "modifiche importanti" in arrivo dopo questo aggiornamento documentazione. Branch dev allineato, pronto per nuove modifiche.

---

## Sessione 11/05/2026 — Nuovo pin centratura mappa rifornimento (WU147)

### Stato corrente
- **Bot prod**: in esecuzione con codice **precedente** alla modifica WU147. Restart bot pendente (utente lo farà manualmente quando ricevuto OK).
- **FAU_00**: usata come banco di prova live. Lasciata in mappa post-spedizione test 08:46 UTC. Sicura per il prossimo restart.
- **Dashboard prod**: invariata.

### Lavoro completato

**WU147 — Rifornimento, nuovo pin `pin_rifugio.png` + ROI dinamica + tap su centro pin matchato**

Punto di partenza: utente fornisce nuovo template `c:/radar_tool/templates/pin_rifugio.png` (27×28, avatar con cappello blu su sfondo dorato) da usare per centratura mappa rifornimento al posto di `pin/avatar.png`. Richiesta: ROI calcolata partendo dal centro mappa (quadrato 50→100→200→300 a step), tap dinamico sul centro avatar (no offset hardcoded).

**Cosa è stato fatto**:
1. Copia template in `templates/pin/pin_rifugio.png` dev + prod (md5 verificati identici).
2. Nuova key config `AVATAR_MAPPA_TEMPLATE` separata da `AVATAR_TEMPLATE` (membri lasciano `pin/avatar.png`).
3. ROI strategia 2-step:
   - **Primaria 200×200** `(380, 170, 580, 370)` — centrata su centro mappa (480, 270)
   - **Retry 300×300** `(330, 120, 630, 420)` se primo match < soglia 0.75
4. Refactor `_centra_mappa` con 2 tentativi sequenziali + log per ROI usata.
5. Tap castello rivoluzionato: `(r.cx, r.cy)` = centro esatto del template matchato (no più offset_y).
6. Test live `c:/tmp/test_rifornimento_pin_rifugio.py` — partenza HOME → dismiss banner → mappa → centra (700,533) → tap pin → RESOURCE SUPPLY → invio pomodoro.

**Diagnosi che ha portato al fix** (3 iterazioni):
- Iter 1: ROI 50×50 al centro mappa → match score=0.452 < 0.75. La ROI conteneva SOLO il banner nome "LND_FauMorfeus / 25", non il pin avatar.
- Iter 2: ROI 100×100 → score=0.560, sempre < 0.75. Ancora insufficiente.
- Iter 3 (diagnostico): `cv2.matchTemplate` globale (no ROI) ha dato **score=1.000 a (487, 199)** — cioè il pin sta **71 px SOPRA il centro mappa**, non al centro.
- Soluzione: ROI 200×200 centrata su centro mappa contiene il pin con margine; tap su (r.cx, r.cy)=(487, 199) cliccando direttamente sull'avatar apre il popup castello (RESOURCE SUPPLY score 0.387→0.999).

**Validazione finale** (FAU_00 11/05 08:46 UTC):
- match pin: score=1.000 ROI primaria (no retry) ✅
- tap: (487, 199) ✅
- RESOURCE SUPPLY: 0.999 ✅
- provviste OCR: 65,000,000 ✅
- Daily Recv Limit: 200,000,000 ✅
- ETA viaggio: 28s ✅
- spedizione pomodoro: lordo **3.977M** / netto **3.499M** (tassa ~12%) ✅
- durata totale: 35.9s

**Bug collaterale scoperto** (NON modificato — è feature di sicurezza prod): `_compila_e_invia(nome_rifugio="placeholder")` triggera DEST MISMATCH OCR del nome destinatario → BACK silenzioso + return failure. Nello script test usato `nome_rifugio=""` per skip check. In produzione il check è importante per safety: il bot passa il nome reale del membro alleanza atteso.

### File modificati
- `templates/pin/pin_rifugio.png` (NEW, dev + prod, 2018 bytes, md5 `83cf75287c0448fd631be09fa0130ada`)
- `tasks/rifornimento.py` (dev + prod):
  - `_DEFAULTS` esteso con `AVATAR_MAPPA_TEMPLATE`, `AVATAR_MAPPA_ROI` (200×200), `AVATAR_MAPPA_ROI_RETRY` (300×300)
  - `_centra_mappa` refactor: 2 tentativi ROI + tap su `(r.cx, r.cy)` centro pin
  - `AVATAR_MAPPA_OFFSET_Y` marcato legacy nel commento
- `.claude/CLAUDE.md` (dev + prod): riga WU147 in tabella issues
- `c:/tmp/test_rifornimento_pin_rifugio.py` (NEW): script test live standalone

### Pendenze
- **Restart bot prod** (utente, manuale via `run_prod.bat`) per attivare WU147 sulle 11 istanze prod.
- **Monitor primo ciclo post-restart**: cercare nei log `Rifornimento: pin destinatario [ROI primaria] score=X.XXX found=True`. Se `[ROI retry]` invocata >10% dei tick → allargare primaria a 250×250.
- ROADMAP.md non aggiornata in questa sessione (file >256 KB, append richiede grep di sezione precisa) — CLAUDE.md fa fede per tracking issues.

### Prossimo step
Utente riavvia bot. Al primo ciclo monitorare log su tutte le 11 istanze ordinarie + master FauMorfeus. WU146 (daily report) e WU147 (pin rifugio) si attivano insieme al restart.

---

## Sessione 10/05/2026 — Daily report revisione completa sezioni 1-11 (WU146)

### Stato corrente
- **Bot prod**: in esecuzione, ciclo #47+ in corso (uptime ~24h+ dal 09/05 09:18 UTC).
- **Adaptive Scheduler**: dorme (DRL master 100M+ residuo, precondizione `≤50M` falsa).
- **Daily report**: 11 sezioni rivisitate con audit ridondanze. Sync prod ✓.
- **Restart bot pendente** per applicare fix WU144/WU145 (moduli `core/alerts.py` e `tasks/arena.py` già caricati in memoria).

### Lavoro completato

**WU146 — Revisione daily report sezioni 1-11** (10/05 mattina/pomeriggio)
- Audit ridondanze tra tutte le sezioni → consolidato "anomalie ticks" da sez 1 → sez 10.
- **Nuova sezione 2 PRODUZIONE INTERNA RIFUGIO**: produzione effettiva castello per istanza, sommata da `state/<ist>.json::produzione_storico[]` con campo `produzione_qty`. Distinta da "risorse inviate al master" (sez 3 = `storico_farm.json` netto).
- Numerazione shifted: era 1-10, ora 1-11.
- **Regola formattazione `_fmt_dur_s`**: durate ≥60s mai con secondi. Memoria `feedback_format_durata.md`.
- **Drivers tassa rifornimento chiariti**: dipende dal **livello rifugio mittente** (FAU_00 12% top-level), NON dalla distanza. Memoria `reference_tassa_rifornimento.md`.
- 11 sezioni revisionate:
  1. CICLI — uptime% + produttività (marce/sped/sfide)
  2. PRODUZIONE INTERNA RIFUGIO (NEW)
  3. RISORSE INVIATE AL MASTER — netto + throughput + tassa scartata
  4. TREND vs media 7gg — ▲▼= per risorsa + totale aggregato
  5. RIFORNIMENTO — range tassa + saturazione + tutte le 11 istanze
  6. TRUPPE — master separata + Δ giorno coerente + Δ 7gg
  7. PERFORMANCE TASK — tutti i 15 task + p95 + outliers%
  8. BOOT HOME → READY — label chiarito (WU127)
  9. COPERTURA SQUADRE — solo <100% + summary 100% + n_attacchi
  10. EVENTI RILEVANTI — alert email + restart + HOME timeout (consolidato da sez 1)
  11. ANOMALIE TASK — aggregato per task + fail_rate% + causa principale

### File modificati
- `core/daily_report.py` (~1200 righe) — 11 sezioni revisionate + nuova sez 2 + render text/HTML
- `.claude/CLAUDE.md` — riga WU146 aggiunta tabella issues
- `docs/OVERVIEW.md` — sezione 4.16 alerts aggiornata WU144 + nuova 4.17 daily_report con tabella 11 sezioni
- 3 memorie nuove:
  - `feedback_format_durata.md` (regola fmt durata)
  - `reference_tassa_rifornimento.md` (tassa = livello rifugio, drivers n_invii)
  - `project_daily_report_revisione.md` (WU146 sintesi)
- MEMORY.md indice aggiornato (30 memorie totali)

### Pendenze
- **Restart bot prod** (utente, manuale via `run_prod.bat`) per applicare WU144 (`core/alerts.py` + `shared/morfeus_state.py`) e WU145 (`tasks/arena.py`). NON serve restart per WU146 (daily_report importato fresh ogni invio).
- **Verifica daily report** prossimo invio (07:35 UTC dell'11/05) sui dati reali.
- **Nota OCR FAU_09 storico_truppe**: prima lettura 29/04 a 15K → +1637%/7gg artefatto, da gestire futuramente con outlier detection (es. cap delta_7gg% se prima lettura <30% di oggi).

### Prossimo step
Restart bot prod via `run_prod.bat` per attivare:
- gate arena UTC<10 (sez 10/05 cicli notturni meno gonfi)
- fix alert DRL stale (no falsi alert master_saturo post-mezzanotte UTC)

Monitor log al primo restart per:
- `[ARENA] gate orario UTC<10 → posticipata` nei cicli 00:00→10:00 UTC
- `[ALERTS] master_saturo: DRL=0 STALE` se condizione si verifica

---

## Sessione 09→10/05/2026 — Switch raccolta_fast→full + fix alert DRL stale + gate arena UTC<10

### Stato corrente
- **Bot prod**: in esecuzione (uptime 20h al 10/05 05:16 UTC), ciclo #46 in corso. Codice PRECEDENTE ai fix WU144/WU145 — restart pendente (utente).
- **Dashboard prod**: invariata in questa sessione.
- **Adaptive Scheduler**: LIVE attivo nei cicli notturni 09/05 sera. Disattivo da c46 (mattina 10/05) perché DRL master ha 102M residui (precondizione `≤50M` falsa).
- **FauMorfeus**: temporaneamente disabilitata da utente alle 19:32 UTC del 09/05 per test → poi riabilitata in c43.

### Lavoro completato (in ordine cronologico)

**1. WU143 — Switch tipologia raccolta_fast → full per FAU_01..FAU_10** (analisi + fix utente, 09/05 sera)
- Diagnosi: efficacia raccolta_fast 86%→43% per **deadlock blacklist fuori globale** (lente deterministica + 1-shot non avanza al prossimo nodo). Sintomo: `RaccoltaFast [campo]: nodo 726_538 in blacklist fuori — skip` ripetuto fino a 0/N inviate.
- **Bug correlato scoperto**: modifica statica isolata era inefficace (`main.py:128` priorizza DYNAMIC su STATIC) → memorizzato in `feedback_modifiche_sempre_dinamiche.md` (regola: ogni modifica config va su DYNAMIC).
- Switch DYNAMIC `runtime_overrides.json::istanze.<nome>.tipologia: raccolta_fast → full` per FAU_01..FAU_10. FAU_00 e FauMorfeus invariate.
- Pulizia blacklist fuori globale (18 → 0 entries, ricostituita a 3 nodi reali post-cicli notturni).
- **Risultato post-switch**: marce/run 0.63 → **1.75** (+178%); FAU_01 da 0/12 → 13 marce in 7 run.

**2. Verifica adaptive scheduler con FauMorfeus disabilitata** (09/05 sera)
- Confermato: bot RISPETTA il flag `abilitata=False` correttamente. Adaptive scheduler considera solo istanze abilitate (`_carica_istanze_ciclo` filtra a riga 130-131); hot-check mid-ciclo intercetta disabilitazione tardiva (`main.py:1339-1345`); `is_master_instance` hardcoded riordina solo istanze in lista, non aggiunge.
- Coerente con regola "no skip istanza" del 08/05 (vieta skip automatici, non intent espliciti utente).

**3. WU144 — Fix alert master_saturo + DRL stale auto-reset** (10/05 mattina)
- Bug: alert `master_saturo_long` continua a spedire mail post-mezzanotte UTC anche se gioco ha già resettato DRL.
- Root cause: `morfeus_state.json::ts` è timestamp ultima lettura OCR. Se master disabilitato/ultimo nel ciclo, `daily_recv_limit=0, ts=ieri` resta sul disco e contamina tutti i consumer.
- Fix in 2 livelli:
  - `core/alerts.py::check_master_saturo` skip se `ts.date() != today` UTC.
  - `shared/morfeus_state.py::load` auto-reset stale: ritorna in memoria `daily_recv_limit = daily_recv_limit_max` (cap stimato 200M dal max monotone) se ts di giorno UTC diverso. File su disco invariato (la prossima `save()` da OCR riallinea). Marker `_stale_reset_applied=True` per diagnostica.
- Beneficio collaterale: tutti i consumer (`adaptive_scheduler._master_drl_residuo_m`, dashboard pannello DRL, daily_report) ora vedono valore non-stale.
- Test 3/3 verdi.

**4. WU145 — Gate orario UTC<10 per ArenaTask** (10/05 mattina)
- Analisi pattern cicli notturni lunghi: top 5 (217/188/181/160/153 min) tutti tra 23:35 e 02:45 UTC. Causa: a 00:00 UTC reset simultaneo DRL master (rifornimento +50min) + arena (+30min cumulati) → primo ciclo post-reset gonfio +75-85min vs regime diurno.
- Fix: gate orario in `tasks/arena.py::ArenaTask.should_run` — `if datetime.now(timezone.utc).hour < 10: return False`. Pattern preso da MainMissionTask WU91.
- Effetto: -25-33 min sul ciclo critico, +25-33 min su un ciclo diurno. NON tocca `last_run` né `segna_esaurite`.
- Trade-off: bot fermo 14h consecutive nella finestra 10→24 UTC perde la giornata di arena (rischio basso).

**5. Aggiornamento documentazione e memoria**
- CLAUDE.md tabella issues: aggiunte righe WU143, WU144, WU145.
- Memorie nuove: `project_raccolta_full_swap_09_05.md`, `project_alert_drl_stale_fix.md`, `project_arena_gate_utc10.md`, `feedback_modifiche_sempre_dinamiche.md` (regola DYNAMIC).
- MEMORY.md indice aggiornato con 4 nuove righe.

### File modificati questa sessione
- `tasks/arena.py` — gate UTC<10 in should_run + docstring
- `core/alerts.py` — check_master_saturo skip se ts stale
- `shared/morfeus_state.py` — load auto-reset stale
- `config/runtime_overrides.json` (DYNAMIC, prod) — tipologia FAU_01..10 → full
- `config/instances.json` (STATIC, prod) — tipologia allineata (precauzione, ma DYNAMIC è la fonte)
- `data/blacklist_fuori_globale.json` (prod) — svuotata, ricostituita a 3 entries
- `.claude/CLAUDE.md` — 3 righe WU143/144/145
- Memorie utente — 3 nuovi file + index MEMORY.md aggiornato

### Backup creati (prod)
- `config/instances.json.bak.20260509_pre_full_swap`
- `config/runtime_overrides.json.bak.20260509_pre_full_swap`
- `data/blacklist_fuori_globale.json.bak.20260509_1923`

### Pendenze
- **Restart bot** (utente, manuale) per applicare fix WU144 (`core/alerts.py` + `shared/morfeus_state.py`) e WU145 (`tasks/arena.py`). Moduli già caricati in memoria.
- **Verifica notte 10→11/05**: prossimo ciclo critico ~00:15 UTC senza arena (gate UTC<10) — durata attesa ~165-185 min vs 217 di stanotte.
- **Verifica primo ciclo post-10:00 UTC** (~10:30): arena scatta per tutte e 11 le istanze, durata attesa ~120 min (vs ~95 attuali).

### Prossimo step
Restart bot prod tramite `run_prod.bat`. Monitor sui log al primo ciclo post-restart per:
1. Conferma `[ARENA] gate orario UTC<10 → posticipata, no skip esecuzione` nei cicli 00:00→10:00 UTC.
2. Conferma `[ALERTS] master_saturo: DRL=0 STALE (...) — skip` se la condizione si verifica.
3. Verifica adaptive scheduler riaccende quando DRL scende sotto soglia 50M (dopo qualche ora di rifornimento attivo).

---

## Sessione 08/05/2026 sera — Skip Predictor RIMOSSO + Adaptive Scheduler UI + WU137 fase 2 + bug fix livello

### Stato corrente
- **Bot prod**: in esecuzione con codice PRECEDENTE alle modifiche di stasera. Restart bot pendente (utente lo farà manualmente). Le modifiche attivano i fix al primo ciclo post-restart.
- **Dashboard prod**: restartata (PID 16424) con tutte le modifiche UI applicate.
- **Adaptive Scheduler**: attivato dall'utente (modalità da verificare al prossimo ciclo via monitor `tail -F bot.log | grep ADAPT`).
- **Monitor attivo**: tail su `bot.log` filtrando `[ADAPT...]` — ID `bz7hzl3bc` background.

### Lavoro completato (in ordine cronologico)

**1. Refactor sezione config rifornimento** (richiesta utente)
- Aggiunta sotto-sezione "allocazione % invio" in `/ui/config/global` card rifornimento (parità con home).
- Salvataggio static via `PATCH /api/config/global` (frazioni 0-1).

**2. Promote runtime → static** (richiesta utente)
- Endpoint `POST /api/config/promote` + funzione `_build_static_from_runtime` (deep merge per preservare campi solo-static come `qta_*`, `mumu`).
- Bottone "⬆ runtime → static" nel banner UI accanto a "↺ reset runtime".

**3. tick_sleep uniformato a minuti** (richiesta utente)
- File static `global_config.json::sistema.tick_sleep` (60s) → `tick_sleep_min` (1 min).
- Loader `_DEFAULTS` + `_from_raw` + `to_dict` + `_merge_globali` aggiornati.
- UI label "(min)" coerente con home.
- Cleanup chiave legacy in `_save_global_raw` + `_build_static_from_runtime`.

**4. Skip Predictor (WU89) RIMOSSO** (richiesta utente: "no skip istanza")
- Hook live in `main.py::_thread_istanza` rimosso (~80 righe).
- `_predictor_states` + `_append_predictor_decision` rimossi.
- Flag `skip_predictor_enabled` + `_shadow_only` rimossi da `GlobalConfig` + `GlobaliOverride` + `PayloadGlobals` + `_merge_globali`.
- UI `/ui/predictor` sezioni "config predictor (WU89)" + "skip predictor — squadre fuori" rimosse.
- `core/skip_predictor.py` marcato DEPRECATO (lasciato in repo per git history).
- Memoria `feedback_no_skip_istanza.md` (regola architetturale vincolante).
- Memoria `project_skip_predictor.md` aggiornata "RIMOSSO 08/05".
- Memoria `feedback_skip_predictor_logic.md` marcata OBSOLETA.

**5. Pagina `/ui/predictor-istanze`** (richiesta utente)
- Nuovo template `predictor_istanze.html` assorbe vecchio `predictor.html` (cycle predictor + distribuzione empirica) + adaptive scheduler (config + simulazione preview) — separa config statica da strumenti operativi.
- Vecchia route `/ui/predictor` → redirect 302.
- Nav link "predictor istanze".
- Sezione adaptive scheduler RIMOSSA da `/ui/config/global` (spostata).

**6. Adaptive Scheduler — pannello simulazione + soglia M assoluti + condizione invertita + layout compatto + trace**
- Endpoint `GET /api/adaptive-scheduler/preview` ritorna ordine LIVE greedy + ordine PERSISTED.
- Partial `adaptive_scheduler_preview.html` con tabella score/t_avvio/residui per istanza.
- Soglia DRL: % → M assoluti (default 50). Schema `adaptive_scheduler_thresholds.drl_residuo_m`.
- `_master_drl_residuo_m()` ritorna M direct (no più calcolo % vs limite).
- Condizione INVERTITA: scheduler attivo se `residuo ≤ soglia` (master saturo, riordino utile), no più `≥`.
- `shared/morfeus_state.save` traccia `daily_recv_limit_max` monotone con reset giornaliero UTC.
- Card UI compattata 2×2 grid invece di tabella verticale.
- Stato a "pill" coerente con design (`as-pill off/shadow/live/wait`).
- Trace step-by-step del greedy: log `[ADAPT-TRACE]` con candidati top-4 + scelto + offset cumulativo (richiede restart bot per attivarsi).
- Log precondizioni LIVE prima del greedy.

**7. Fix livello rispettato strict** (richiesta utente: "imposto L6 ma cerca L7")
- `tasks/raccolta.py::_invia_squadra` sequenza_livelli: `base=6 → [6, 7]` (fallback up errato) → `base=6 → [6]` strict.
- Solo `base=7 → [7, 6]` (L7 max → fallback a L6 ammesso).
- Bonus: `tasks/raccolta_fast.py:280` telemetria usa `cfg.livello` per-istanza invece di `LIVELLO_NODO` globale.

**8. Lettura runtime-only campi per-istanza** (regola utente: "livello letto a runtime, non statico")
- `config/config_loader.py::_InstanceCfg`: `truppe`, `max_squadre`, `livello`, `profilo`, `fascia_oraria` ora leggono SOLO da runtime (override) + fallback default globale. Niente più `ist.get(...)` static.
- Eccezione: `abilitata` resta dual-source (pre-filtro `_carica_istanze_ciclo`).
- Memoria `architecture_config_static_dynamic.md` aggiornata con sezione "Lettura runtime — bot legge SOLO dynamic".

**9. WU137 fase 2 — alert real-time email**
- Modulo nuovo `core/alerts.py` (~370 righe): `trigger_alert` rate-limited con state persistente `data/alerts_state.json`.
- 3 check periodici (chiamati da `main.py` post-ciclo): `check_master_saturo` / `check_heartbeat_cicli` / `check_maintenance_long`.
- 2 hook event-driven: `report_cascade_adb` (in `core/orchestrator.py` su `ADBUnhealthyError`, 2 punti) + `report_bot_unexpected_restart` (predisposto, hook al boot non collegato).
- Schema config esteso: `notifications.alerts_enabled` (default False) + `alerts_disabled` (lista event_type silenziati).
- UI in `notifications_card.html`: riga "alert real-time" toggle + 5 checkbox event_type.
- Endpoint `PATCH /api/notifications` accetta nuovi campi.
- Memoria `project_email_notifier.md` aggiornata fase 2.

### File modificati (totale)

**Codice (21 file)**:
- `main.py` (skip removal + alerts hook + adaptive log_fn + tick_sleep risolution)
- `config/config_loader.py` (tick_sleep min + alerts schema + skip removal + lettura runtime-only + promote_runtime_to_static + _build_static_from_runtime + deep merge)
- `config/global_config.json` (tick_sleep_min, drl_residuo_m, alerts_*, skip_predictor_* rimosso)
- `core/adaptive_scheduler.py` (DRL M, condizione ≤, trace step-by-step)
- `core/orchestrator.py` (hook report_cascade_adb)
- `core/skip_predictor.py` (header DEPRECATO)
- `core/alerts.py` (NEW, ~370)
- `shared/morfeus_state.py` (max monotone)
- `tasks/raccolta.py` (sequenza_livelli strict)
- `tasks/raccolta_fast.py` (telemetria cfg.livello per istanza)
- `dashboard/app.py` (route predictor-istanze + redirect + partial preview + cleanup)
- `dashboard/models.py` (skip_predictor rimosso)
- `dashboard/routers/api_config_global.py` (cleanup tick_sleep legacy)
- `dashboard/routers/api_config_overrides.py` (skip_predictor setter rimosso + endpoint promote)
- `dashboard/routers/api_adaptive_scheduler.py` (preview endpoint + threshold_drl_residuo_m)
- `dashboard/routers/api_notifications.py` (alerts_enabled/_disabled)
- `dashboard/templates/base.html` (nav predictor istanze)
- `dashboard/templates/config_global.html` (allocazione invio + bottone promote + tick_sleep min + adaptive sezione rimossa)
- `dashboard/templates/predictor.html` (skip sezioni rimosse)
- `dashboard/templates/predictor_istanze.html` (NEW)
- `dashboard/templates/partials/adaptive_scheduler_card.html` (compatta 2x2 + pill + condizione ≤)
- `dashboard/templates/partials/adaptive_scheduler_preview.html` (NEW)
- `dashboard/templates/partials/notifications_card.html` (riga alert)

### Pending utente

1. **Restart bot prod** — applica TUTTE le modifiche di stasera (livello strict, lettura runtime-only, skip removal, alerts hook, adaptive trace, 5 proposte adaptive scheduler).
2. Verifica al prossimo ciclo post-restart:
   - Bot cerca solo L6 sulle istanze con `livello=6` (no più tap CERCA a L7).
   - Log `[ADAPT-TRACE] step1 t=0.0m | FAU_05:sla=4/5(...,emp=3/n8α0.7) ...` step-by-step + blend empirico.
   - Log `[ADAPT-AB] adapt_tot=X naive_tot=Y delta=+Z` per A/B test.
   - Alerts attivi se utente ha checked `alerts_enabled=true`.
3. Adaptive scheduler già attivato dall'utente in prod — modalità LIVE confermata, sta riordinando + persistence in `scheduler_planned_order.json`.

### Sistema predittivo COMPLETO (sessione sera 08/05 post-recap)

5 proposte implementate per migliorare l'adaptive scheduler:

| commit | proposta | scope |
|---|---|---|
| `df810ad` | A blend empirico | `compute_slot_liberi_atteso` blend `α·det + (1-α)·median_emp` con α adaptive su n_samples |
| `4489b21` | D cycle calibration | factor globale closed-loop bias actual/predicted (prod: +19% sottostima → factor 1.19) |
| `cacc64c` | E A/B test | confronta adaptive vs naive ad ogni greedy → `scheduler_ab.jsonl` (prod: +4 slot, +36%) |
| `ba8428c` | C P_saturo tie-breaker | sort key `(score desc, p_saturo asc, anzianita desc)` |
| `167fb9b` | B T_marcia calibration | coef per (istanza, livello) closed-loop (auto-attivo dopo 5+ samples) |

Nuovi moduli:
- `core/empirical_slot_predictor.py` — lookup empirico + P_saturo
- `core/cycle_predictor_calibration.py` — factor globale + auto-rebuild
- `core/t_marcia_calibration.py` — coef per (ist, lv) + auto-rebuild

Risultato T_ciclo evolutivo prod (12 istanze):
- OLD (tutti task storici): 212.8 min
- NEW schedule-aware: 68.8 min (sottostima)
- NEW + cycle_calib (D): **84.6 min** (vicino al reale 89-112 min)

### Allocazione raccolta — comportamento

L'utente potrebbe lamentarsi "non vedo produzione di acciaio". Comportamento by design:
`raccolta.allocazione.acciaio=10%` ma TUTTE le istanze hanno acciaio in eccesso nel
deposito castello (es. FAU_09 48%, FAU_05 33%) → algoritmo `_calcola_sequenza_allocation`
mette acciaio in coda perché `gap = target - perc_attuale < 0`. Soluzione: utente alza
target dalla card "allocazione raccolta" (`/ui` home cfg4) oppure modifica logica per
garantire min 1 invio/tipo.

### Documentazione aggiornata

- `docs/OVERVIEW.md` — sezione 4 (4.10 skip_predictor DEPRECATO + 4.12-16 nuovi moduli),
  sezione 6.3 (runtime keys aggiornate + regola WU140), sezione 6.6 (nuovi files
  calibrazione), sezione 7 (telemetria scheduler_ab + alerts), sezione 8 (predictor
  ricostruita con architettura), sezione 9 (pagine dashboard aggiornate +
  /ui/predictor-istanze + endpoint promote/reset), sezione 10 (CLI nuovi moduli)
- Memorie aggiornate: `project_adaptive_scheduler.md` (5 proposte), `MEMORY.md` index

### Memorie aggiornate / nuove
- NEW `feedback_no_skip_istanza.md` — regola architetturale "no skip istanza"
- UPDATE `project_skip_predictor.md` — RIMOSSO 08/05
- UPDATE `feedback_skip_predictor_logic.md` — OBSOLETA
- UPDATE `architecture_config_static_dynamic.md` — sezione "Lettura runtime — bot legge SOLO dynamic"
- UPDATE `project_email_notifier.md` — fase 2 IMPLEMENTATA
- UPDATE `MEMORY.md` index

### Backlog (non urgente)
- Issue #65 — wait>60s rifornimento → anticipare task post-raccolta nel tempo morto
- Issue #51 — DistrictShowdown gate readiness popup (BASSA)
- Modalità raccolta_fast estesa — analisi costi/benefici post 1-2 cicli post-restart (debug screenshot ON)
- Hook `report_bot_unexpected_restart` al boot main.py (predisposto, non collegato)

---

## Sessione 04/05/2026 sera — Predictor completo (cycle + skip + recorder + dashboard) + OVERVIEW.md

### Stato corrente
- Bot prod **in esecuzione** (PID variabile, restart utente alle ~13:00)
- Skip Predictor attivo in modalità **shadow** (`enabled=True, shadow_only=True`)
- Cycle predictor **già usato** dal skip predictor come gap_atteso dinamico
- Background recorder dashboard **richiede restart dashboard** per partire

### Lavoro completato in sessione

**1. WU116 OCR Load squadra** (~mattino) — già documentato sessione precedente

**2. WU117 Arena tap prima sfida** (~mezzogiorno) — già documentato

**3. WU118-121 dashboard refactor** (~pomeriggio) — già documentato

**4. WU89-Step4 Skip Predictor live hook** (~tardo pomeriggio)
- Hook in `main.py::_thread_istanza` flag-driven shadow/live
- Telemetria `data/predictor_decisions.jsonl`
- Pannello live decisioni in dashboard

**5. WU-CycleDur Cycle Duration Predictor** (~sera)
- `core/cycle_duration_predictor.py` (rolling stats + schedule-aware)
- Tool CLI `tools/predict_cycle.py`
- Config baseline `config/predictor_t_l_max.json` (multiplier per istanza)
- Refactor `_rule_squadre_fuori` con modello empirico T_marcia
- Pannello dashboard "predict cycle" → poi spostato su `/ui/predictor`

**6. WU-CycleAccuracy Recorder + drilldown what-if** (~sera)
- `core/cycle_predictor_recorder.py` (snapshot 15min + accuracy fine-ciclo)
- Background task in dashboard `lifespan`
- Schema `input_context` per reproducibilità
- Pagina dedicata `/ui/predictor` con 3 sezioni
- Nav link "predictor" in topbar
- Pannelli predictor rimossi da `/ui/telemetria`

**7. `docs/OVERVIEW.md` (NEW ~700 righe)**
- Documento completo architettura + funzionalità
- Sezioni: cosa fa, architettura, pipeline, core, 17 task dettagliati,
  configurazione, telemetria, predictor, dashboard, tool CLI, operations
- Dettaglio per ogni task: schedule, flusso, parametri, regole speciali
- Riferimento all-in-one per onboarding

**8. Fix collaterali**
- WU121 master FauMorfeus hardcoded (eliminata UI checkbox + override config)
- Riordino risorse pomodoro/legno/acciaio/petrolio in tutta dashboard
- Fix tick_sleep unit mismatch (campo MIN coerente)
- Trend 7gg spostato sidebar farm
- Storico eventi pagina dedicata `/ui/storico`
- Tabella istanze rendering visivo risolto post-restart
- ROI OCR Total Squads estesa (740,55,950,95) per cifre 6+ (FAU_09 fix)

### File principali toccati (sessione completa)
- `main.py` (predictor hook + recorder background)
- `core/skip_predictor.py` (refactor _rule_squadre_fuori empirico)
- `core/cycle_duration_predictor.py` (NEW)
- `core/cycle_predictor_recorder.py` (NEW)
- `core/troops_reader.py` (ROI fix)
- `core/istanza_metrics.py` (load_squadra + rifornimento.invii)
- `tasks/raccolta.py` (load_squadra hook)
- `tasks/arena.py` (TAP_PRIMA_SFIDA)
- `tasks/raccolta_chiusura.py`, `rifornimento.py`, `district_showdown.py`, ... (WU115 debug buffer migrazione)
- `dashboard/app.py` (cycle endpoints + predictor recorder loop + ★)
- `dashboard/services/stats_reader.py` (copertura cicli + predictor decisions)
- `dashboard/templates/{index,telemetria,storico,predictor,base}.html`
- `dashboard/static/style.css` (.cov-* + .res-block .tel-table)
- `shared/debug_buffer.py` + `shared/instance_meta.py` + 17 task migrati
- `shared/ocr_helpers.py` (leggi_load_squadra + cap_nodo)
- `shared/cap_nodi_dataset.py`
- `tools/{predict_cycle,predictor_backtest,report_copertura_ciclo,analisi_cap_nodi}.py`
- `config/predictor_t_l_max.json` (NEW)
- `docs/OVERVIEW.md` (NEW)

### File NEW di rilievo
| File | Scopo |
|------|-------|
| `docs/OVERVIEW.md` | Documento completo architettura + funzionalità |
| `core/cycle_duration_predictor.py` | Stimatore T_ciclo schedule-aware |
| `core/cycle_predictor_recorder.py` | Snapshot 15min + accuracy fine-ciclo |
| `core/skip_predictor.py` (refactor) | Modello empirico squadre_fuori |
| `tools/predict_cycle.py` | CLI standalone cycle predictor |
| `tools/predictor_backtest.py` | Backtest empirico skip predictor |
| `tools/report_copertura_ciclo.py` | Report istanza×ciclo SATURA/NON SATURA |
| `dashboard/templates/predictor.html` | Pagina dedicata predictor |
| `config/predictor_t_l_max.json` | Baseline T_L_max + multiplier istanze |

### Stato post-sessione
- **Bot**: in shadow mode, accumulando decisioni `predictor_decisions.jsonl`
- **Dashboard**: serving paginas WU118-121, MA non ha ancora il
  background recorder loop attivo (serve restart per `lifespan` re-run)
- **Predictor accuracy**: 0 cicli valutati (snapshot inizia post-restart dashboard)

### Pending utente
1. **Restart dashboard** per attivare:
   - Background task recorder (snapshot ogni 15min)
   - Pagina `/ui/predictor` rendering corretto
2. Osservazione 24-72h per accumulare:
   - 50+ decisioni shadow predictor → backtest valutabile
   - 6-12 cicli con snapshot completi → accuracy real
3. Calibrazione T_L_max empirica (post-accumulo dati)
4. Decisione SHADOW → LIVE quando precision/recall sono OK

### Prossimi passi (non urgenti)
- WU89-Step5 pannello dashboard precision/recall (blocco "in sviluppo" già visibile in `/ui/predictor`)
- Fix bug guardrail `cicli_dall_ultimo_retry=0` (init a COOLDOWN)
- Calibrazione T_L_max[istanza, livello] empirica da samples reali
- Storico cicli con snapshot link clickable per drilldown

---

## Sessione 04/05/2026 pomeriggio — WU118-121 dashboard refactor + bug fix

### Stato corrente
- Bot prod **fermo** (solo dashboard uvicorn attiva, PID 5792)
- Modifiche dashboard pronte, **restart dashboard richiesto** per attivare nuove pagine /ui/telemetria + /ui/storico + ★ FauMorfeus
- Bot non restartato dal mattino → ancora con codice nuovo WU115/116/117 attivo nel restart precedente

### WU118 — Refactor dashboard telemetria/storico pagine separate
**Effetto**: home alleggerita (rimossi 8 tel-card + storico eventi). Topbar: home | telemetria | storico | config | api.

**Componenti**:
- 2 nuovi template: `telemetria.html` (8 tel-card + nuovo "🛡 copertura squadre"), `storico.html` (filtri+tabella)
- 2 nuove routes app.py: `/ui/telemetria`, `/ui/storico`
- Nav link in base.html
- Pannello "🛡 copertura squadre — ultimi 5 cicli" full-width in telemetria con `get_copertura_ultimi_cicli()` + `partial_copertura_cicli` endpoint + `partials/copertura_cicli.html` + CSS classi `.cov-*`
- Trend 7gg spostato in sidebar farm di home (top), CSS override `.res-block .tel-table` con table-layout:fixed
- `core/istanza_metrics.py::aggiungi_invio_raccolta` esteso con `load_squadra` param
- Tool CLI `tools/report_copertura_ciclo.py` per analisi per istanza×ciclo

### WU119 — Ordine risorse uniformato 🍅→🪵→⚙→🛢
3 file: index.html (5 punti), config_global.html (3 punti), stats_reader.py (2 punti). Valida 7/7 endpoint via emoji position check.

### WU120 — Bug tick_sleep unit mismatch
Display secondi vs save minuti → utente inserisce 30 (intendendo sec) → salvato come 30 min → ricarico 1800s. Fix: campo unificato in MINUTI con label/min/max coerenti. Bonus: prod runtime_overrides aveva `tick_sleep_min=300` (5h!) artefatto dello stesso bug — utente dovrà correggere.

### WU121 — Master FauMorfeus ripristino + ★ marker uniforme
Flag `master=True` perso in prod (artefatto save dashboard) → ripristinato in `instances.json` + `runtime_overrides.json` prod (dev era OK). Cache invalidate. Aggiunto ★ marker in `partial_ist_table` (era l'unico pannello che lo mancava). 4/4 pannelli ora coerenti.

### File modificati totali sessione (10 file dashboard + config)
- `dashboard/templates/index.html` (refactor + ordine + tick_sleep)
- `dashboard/templates/config_global.html` (ordine)
- `dashboard/templates/base.html` (nav)
- `dashboard/templates/telemetria.html` (NEW)
- `dashboard/templates/storico.html` (NEW)
- `dashboard/templates/partials/copertura_cicli.html` (NEW)
- `dashboard/static/style.css` (`.cov-*` + `.res-block .tel-table`)
- `dashboard/app.py` (routes + endpoint + ★)
- `dashboard/services/stats_reader.py` (get_copertura + ordine)
- `core/istanza_metrics.py` (param load_squadra)
- `tasks/raccolta.py` (passa load_squadra)
- `tools/report_copertura_ciclo.py` (NEW)
- `config/instances.json` + `config/runtime_overrides.json` (prod) — master flag

### Pending note (vedi recap completo per dettaglio)
1. **Restart dashboard** richiesto (per attivare nuove pagine + ★ + ordine)
2. **Restart bot** (per accumulare load_squadra in nuovi cicli + tick_sleep_min config corretto)
3. Tabella istanze `/ui/config/global` rendering visivo da indagare DevTools
4. Skip Predictor Step 4-5 (hook live + dashboard precision/recall)

---

## Sessione 04/05/2026 mattina+mezzogiorno — WU116 (Load squadra) + WU117 (Arena prima sfida)

### Stato corrente
- Bot prod **fermo** (solo dashboard uvicorn attiva, PID 5792)
- Modifiche pronte in dev+prod, **restart richiesto** dall'utente per attivarle
- Test arena_mercato standalone su FAU_01 OK (37.8s, 6 pack 360 acquistati): WU113 fix DELAY UI confermato funzionante in produzione

### WU116 — OCR Load squadra + KPI copertura squadre
**Obiettivo**: identificare istanze con squadra underprovisioned → nodi non chiusi → spreco efficienza farm.

**Validazione OCR 8/8 su FAU_01**:
| # | Scenario | OCR result |
|---|----------|------------|
| 1 | L7 Field squadra ampia | 1,320,012 ✓ |
| 2 | L6 Field squadra ampia | 1,200,007 ✓ |
| 3 | L6 Field truppe ridotte | 708,822 ✓ (caso underprovisioning!) |
| 4 | Acciaio L6 squadra ampia | 600,018 ✓ |
| 5 | Petrolio 5 cifre | 90,153 ✓ |
| 6,7,8 | Popup nodo (no maschera) | -1 ✓ no falsi positivi |

**File modificati**:
- `shared/ocr_helpers.py`: `_ZONA_LOAD_SQUADRA=(610,420,780,455)` + `leggi_load_squadra(img)` cascade `raw → binv150` + regex `_LOAD_RE`
- `shared/cap_nodi_dataset.py`: param `load_squadra: int = -1` opzionale in `registra_cap_sample`
- `tasks/raccolta.py`: hook in `_esegui_marcia` post-ETA + registrazione differita
- `tools/analisi_cap_nodi.py`: Sezione 4 "Copertura squadra" con verdetti

**Insight gameplay confermato**: con `RACCOLTA_TRUPPE=0` (auto), `load_squadra = min(squadra_max, cap_nodo)`. Se load < cap_nodo → squadra non basta → nodo non chiuso → no rigenera al max.

### WU117 — Arena tap prima riga (anti lista incompleta)
**Bug**: `_TAP_ULTIMA_SFIDA=(745,482)` falliva quando la lista sfide arena ha meno di 5 righe (account low-level / opponenti scarsi).

**Fix**: rinominata `_TAP_PRIMA_SFIDA=(745,250)` — la prima riga è sempre presente se lista non vuota. File: `tasks/arena.py:67` + call site :403.

**Test rinviato a 05/05** prod (FAU_01 sfide odierne consumate).

### File toccati totali sessione (11)
- `shared/ocr_helpers.py`, `shared/cap_nodi_dataset.py`
- `tasks/raccolta.py`, `tasks/arena.py`
- `tools/analisi_cap_nodi.py`
- `.claude/CLAUDE.md`, `.claude/SESSION.md`, `ROADMAP.md`
- 3 file aggiunti al fault tolerant flow (no funzionali)

### Sync prod
Eseguito manualmente via PowerShell xcopy (sync_prod.bat ha LF endings problematici in shell non interattiva). 5 file critici copiati in C:\doomsday-engine-prod\.

### Pending
- Utente fa restart bot (run_prod.bat) per attivare codice nuovo
- 24-48h dopo: verificare `data/cap_nodi_dataset.jsonl` accumula record con `load_squadra` valorizzato + eseguire `python tools/analisi_cap_nodi.py --prod` per primo report copertura squadre
- 05/05 mattina: verificare arena con prima riga (WU117) su prod

### Memorie potenzialmente da aggiornare
- `reference_capacita_nodi.md` → potrebbe estendersi con nota su `load_squadra` e KPI copertura

---

## Sessione 04/05/2026 mattina presto — WU115 espansione debug a 17 task

### Stato corrente
- **Tutti 17 task** del bot ora hanno DebugBuffer integrato con anomalia logic specifica
- **Restart richiesto** dall'utente per attivare codice nuovo (modifiche su 14 task aggiuntivi + dashboard)
- Pre-kill già nel `run_prod.bat` (WU104) → safe rilancio

### Migrazione completata (Step F espansione WU115)
Pattern uniforme per ognuno: `DebugBuffer.for_task(...)` factory + 2-5 snap + flush condizionale.

| # | Task | Snap | Anomalia (force=...) |
|---|------|:-:|---|
| 1 | vip | 4+exc | `cass_ok=False AND free_ok=False` |
| 2 | messaggi | 4+exc | `not alliance_ok AND not system_ok` |
| 3 | boost | 4+exc | `outcome ∈ {POPUP_NON_APERTO, SPEED_NON_TROVATO, ERRORE}` |
| 4 | alleanza | 5+exc | `rivendiche=0` |
| 5 | donazione | 3+exc | `donate_count=0` |
| 6 | radar | 3+exc | `pallini_tappati=0 AND no errore` |
| 7 | radar_census | 2 | `matches vuoto` |
| 8 | truppe | 3+exc | `ok < iterazioni` |
| 9 | zaino | 2+exc | `bool(da_caricare) AND totale_caricato=0` |
| 10 | main_mission | 3+exc | tutti i claim=0 |
| 11 | raccolta + raccolta_chiusura (sub-classe) | 2 | `bool(libere) AND inviate_totali=0` |
| 12 | rifornimento | 2 | `max_sped>0 AND spedizioni=0` |
| 14 | district_showdown | 4 | `esito ∈ {timeout, errore}` |

**Lista finale `_KNOWN_TASKS`** (api_debug.py + app.py): 17 task = 3 originali (arena/arena_mercato/store) + 14 nuovi.

### Verifiche
- `python -c "import" su tutti 17 task → OK
- Sync prod (xcopy core/, tasks/, shared/, dashboard/, ecc.) — eseguito manualmente perché sync_prod.bat ha line endings Unix che CMD non parsing in shell non interattiva
- Verifica file critici in prod: 6/6 presenti (debug_buffer, api_debug, district_showdown, rifornimento, raccolta, main_mission)
- Grep su prod: nuovi snap label confermati nel district_showdown.py

### Stato post-restart atteso
- Pannello "🐛 debug screenshot per task" mostra 17 toggle invece dei 3 originali
- Utente abilita debug per qualsiasi task → al prossimo run su qualsiasi istanza screenshot su `data/{task}_debug/`
- Senza anomalia → nessun file su disco (flush condizionale)
- Cleanup automatico file >7gg via `cleanup_old()` (chiamare da launcher.py se non già fatto)

### File modificati in questa sessione
- 11 task migrati progressivamente (vip→district_showdown) in sessioni precedenti, district_showdown finalizzato qui
- `dashboard/routers/api_debug.py`: `_KNOWN_TASKS` esteso a 17
- `dashboard/app.py::partial_debug_tasks`: `known_tasks` esteso a 17
- ROADMAP.md: aggiunta sezione "Step F — Espansione 14 task" sotto WU115
- CLAUDE.md: aggiunta riga WU115 nella tabella issues

### Pending
- Restart bot (utente)
- Validazione runtime: abilitare debug per 1 task non-arena (es. raccolta) e verificare creazione `data/raccolta_debug/` solo su anomalia

---

## Sessione 03/05/2026 notte — Master istanza generalizzato + Fix raccolta + Predictor 5-invii + run_prod pre-kill

### Stato corrente
- Bot prod attualmente **in esecuzione** (PID 19340) sul vecchio codice
- Modifiche pronte in dev+prod, **restart richiesto** dall'utente per attivarle
- Restart pre-kill già nel `run_prod.bat` (WU104) → safe rilancio multiplo

### Modifiche applicate (5 WU + 1 fix immediato)

**Bug A — raccolta skippata da 18:23 UTC**
- Diagnosi: `runtime_overrides.json::globali.task` non aveva `raccolta` (cancellata da Pydantic save)
- Fix immediato (A): aggiunta chiave `"raccolta": true` direttamente nel runtime_overrides prod
- Root cause (WU102): `TaskFlags.raccolta: bool = True` aggiunto al modello Pydantic — ora preservato in ogni save

**WU101 — Master istanza config-driven generalizzato**
- Nuovo modulo `shared/instance_meta.py` (cache 30s, helper config-driven)
- Flag `master: bool` per istanza in `instances.json` + `runtime_overrides.json`
- 9 punti di esclusione lato server (predictor, stats_reader, telemetry, rollup live.json)
- UI: colonna "M" toggle in /ui/config/global, ★ accanto ai nomi master, riga master separata sfondo dorato in storico truppe
- Migrazione: FauMorfeus.master=true (dev+prod, instances+overrides)
- Cache invalidate automatico in PUT /api/config/istanze

**WU102 — Fix B raccolta TaskFlags** (vedi Bug A sopra)

**WU103 — Predictor 5-invii target**
- Hook `aggiungi_invio_rifornimento` in `core/istanza_metrics.py` + chiamato in `tasks/rifornimento.py` (mappa+membri)
- Schema record esteso con `rifornimento.invii[]` accanto a `raccolta.invii[]`
- Nuova regola predictor `_rule_low_total_invii`: TARGET=5, soglia avg=2.5 ultimi 3 cicli
- Guard: regola disattiva se nessun ciclo nella finestra ha rifornimento (no doppione di trend_magro)
- Tool `predictor_shadow.py` esteso con sezione "Valutazione rifornimento" (avg_inv on/off + delta)

**WU104 — run_prod.bat pre-kill**
- Pre-kill `python.exe main.py` via `Get-CimInstance + Stop-Process -Force` PRIMA del lancio
- Esclude `-m uvicorn` per non toccare dashboard
- Timeout 2s grace per release file handle
- Doppia rete con `_cleanup_orfani_processi_startup` al boot del bot (preserva PID corrente)

**WU105 — Rifornimento bug "1 spedizione invece di 5"**
- Sintomo: FAU_09 18:27 con `slot liberi=1` invia 1, attende 86s rientro, esce con stop
- Root cause: branch `if slot==0` faceva `break` SEMPRE dopo wait, senza ricontrollare slot
- Fix: `continue` invece di `break` (rilegge slot OCR al prossimo giro)
- Coda vuota + slot=0 resta `break` (squadre fuori per altri task)
- Saving atteso: ~3-4 spedizioni in più/ciclo × 11 ist × 12 cicli/die = ~30-50 spedizioni extra/die

**Tuning max_spedizioni_ciclo: 5 → 2** (post-WU105, sera tarda)
- Analisi: produzione netta farm ~207M/die vs cap rifugio FauMorfeus 200M lordi (~154M netti)
- Calcolo per-istanza filtrato (16 sessioni pulite, no consumo, no outlier OCR):
  - 5 istanze ≥20M/die (FAU_00/01/02/04/08) → ~2 sped/ciclo target
  - 6 istanze <20M/die (FAU_03/05/06/07/09/10) → ~1 sped/ciclo target
  - Totale ottimale: 5×2 + 6×1 = 16 sped/ciclo × 12 cicli ≈ 192 sped/die ≈ saturazione 100% cap
- Strategia A (globale=2) scelta: l'auto-stop "risorse sotto soglia → stop" + cap rifugio gestisce le istanze meno produttive che faranno naturalmente 1 sped
- Saturation attesa: 85-90% del cap (margine per cicli persi)
- Slot occupati: 2/4 durante rifornimento, 2/4 liberi per raccolta in parallelo
- Modifica hot-reload, attiva al prossimo tick di ciascuna istanza

**Step 2 (futuro)**: implementare `max_spedizioni_ciclo` per-istanza in `IstanzaOverride` per fine-tuning quote individuali (effort ~30 righe + 1 colonna UI)

**WU110 — BannerLearner cleanup (deprecato, default disable)**
- Diagnosi: 0 eventi [LEARNER] in 7gg log, learned_banners.json mai creato
- Root cause: fallback X cerchio dorato dismisses banner PRIMA del learner → counts non vuoto → learner skip
- Fix opzione B: default False ovunque + docstring DEPRECATO + pannello UI rimosso
- 4 file config aggiornati, 2 moduli marcati deprecati, 1 pannello UI rimosso
- Smoke test 4/4 verdi
- Riattivazione futura: refactor learn-after-fallback (~50 righe)

**WU109 — Telemetry pattern detector escluso raccolta_chiusura**
- Sintomo: 15 outlier raccolta_chiusura severity high (max 225s) ma legittimi (work-mode)
- Distribuzione bimodale: skip-mode 3.4s vs work-mode 60-225s (1-4 invii)
- Fix cosmetico: EXCLUDED_TASKS_TIMEOUT = {"raccolta_chiusura"} skip in detector

**WU108 — DistrictShowdown ignora flag dashboard (201 fail/201 exec)**
- Sintomo: utente disabilita DS in dashboard ma task gira comunque, 0% success
- Root cause: should_run faceva return _is_in_event_window() ignorando task_abilitato (auto-WU17 27/04)
- Fix: check `task_abilitato("district_showdown")` come VETO esplicito prima della window
- Logica: flag OFF → skip, flag ON + fuori window → skip, flag ON + in window → run
- Smoke test 2/2 verdi
- Hot-reload al prossimo tick — saving 5.6s × 201 ≈ 19 min/die

**WU107 — Tick_sleep dashboard ignorato (gap reale 60s vs configurato 5min)**
- Sintomo: dashboard tick=5 ma cicli ogni 60s da `data/telemetry/cicli.json`
- Doppio bug: config_loader senza conversione min→sec + main.py ignora merged config
- Fix: (a) `tick_sleep_min × 60 → tick_sleep` esplicito in config_loader; (b) main.py argparse default -1 + lettura config; (c) run_prod.bat senza `--tick-sleep 60` esplicito
- Priorità: CLI esplicito > config > default 300s
- Validazione: merge_config su prod ritorna 300s con `tick_sleep_min=5`
- Effetto al prossimo restart bot

**WU106 — Cap istanza rifornimento (cattura giornaliera prima sped)**
- Estensione `RifornimentoState`: `cap_invio_iniziale_oggi` (NETTO) + `qta_max_invio_lordo` (LORDO)
- Hook task: alla prima sped del giorno UTC salva e logga `[WU106] cap=X M netti | qta_max=Y M lordo`
- Reset automatico al cambio data, idempotente intra-giornata
- Persistenza in state file via to_dict/from_dict (compat legacy default -1)
- Permette stima quote dinamiche per istanza nel predictor + dashboard
- **Modello aggiornato**:
  - Cap RICEZIONE master = 200M netti/die (Daily Receiving Limit FauMorfeus)
  - Cap INVIO per istanza = ~21-26M netti/die (variabile, dipende da livello edificio)
  - Cap totale potenziale = 11 × 22M = 242M netti/die
  - Bottleneck = ricezione master (200M < 242M)
  - Saturation farm con produzione 207M/die: 207/200 = **103%** (margine 3%, non 34% — correzione errore mio precedente)
  - Tassa 23% applicata SUL MITTENTE, non sul cap di ricezione

### Stato post-restart atteso

**Bot**:
- Lancia `run_prod.bat` → pre-kill PID 19340 → `_cleanup_orfani` al boot per cmd.exe orfani → ciclo 1 con tutte le istanze a raccolta + rifornimento
- Nuovi record in `data/istanza_metrics.jsonl` includono `rifornimento.invii[]`
- Predictor `low_total_invii` inizia ad attivarsi dopo 3 cicli con dati rifornimento

**Dashboard**:
- Lancia `run_dashboard_prod.bat` → ricarica modelli Pydantic con `TaskFlags.raccolta`, `IstanzaOverride.master`, `InstanceStats.master`
- Da quel momento ogni save preserva `raccolta` automaticamente (Bug A non torna)
- Pannelli mostrano FauMorfeus solo nella sezione master dedicata (riga sfondo dorato sotto totale truppe)

### Pending — Step futuri predictor (non in questo restart)
- Step 4: hook orchestrator main.py per attivare skip in modalità live (no shadow)
- Step 5: pannello dashboard predictor con precision/recall + toggle ON/OFF
- Analisi rifornimento sempre-attivo vs on-demand: serve attendere 6-12 cicli post-restart per dati validi nel tool predictor_shadow

### Memorie aggiornate
- `reference_faumorfeus_master.md` → generalizzato a flag config-driven
- `project_skip_predictor.md` → Step 3 + 5-invii rule + master exclusion

---

## Sessione 03/05/2026 sera — Cambio config istanze + WU89 Step 3 Skip Predictor

### Cambio config istanze (utente, da dashboard)

**Levels istanze aggiornati** in `runtime_overrides.json`:
- **FAU_00..FAU_05 + FauMorfeus**: livello 7 (prima solo FAU_00 era a lvl 7)
- **FAU_06..FAU_10**: livello 6 (invariate)

**FauMorfeus ABILITATA** (era `abilitata: false`). Tipologia `raccolta_only`,
max_squadre 5, lvl 7. Implicazione: 12 istanze attive nel ciclo bot (era 11).

**tick_sleep_min=5** confermato attivo (validato +9pp efficacy raccolta).

### WU89 Step 3 — Skip Predictor IMPLEMENTATO

#### Componenti
- `core/skip_predictor.py` — modulo standalone pure function, no side-effect
- `tools/predictor_shadow.py` — CLI replay/validazione storica
- Flag `skip_predictor_enabled` (False) + `skip_predictor_shadow_only` (True)
- Regole: squadre_fuori, trend_magro, recovery, low_prod (con growth_phase
  protection per truppe < 100K)
- Guardrail: max 3 skip consec, re-eval ogni 6 cicli, cooldown post-retry

#### Validazione shadow
416 record / 3 giorni → 33 skip suggeriti (7.9%), 44 guardrail-blocked,
saving stimato ~116 min applicato live.

#### NOT implementato (pending)
- Step 4: hook orchestrator (consumer del predictor)
- Step 5: dashboard pannello shadow/live

Step 3 è standalone — bot non lo usa, è solo disponibile come modulo +
CLI per validazione. Decidere step 4-5 dopo accumulo dati shadow validation.

## TODO aperti (da rivedere)

- **OCR `load_squadra` (carico per squadra) — calibrazione ROI maschera invio**
  (segnalato 02/05 sera). Il valore della capacità di trasporto della squadra
  appare nella maschera invio raccolta, vicino al pulsante MARCIA. Serve uno
  screenshot manuale della maschera per identificare la ROI esatta. Polling
  automatico via ADB tentato → 0 catture in 4 minuti (eventi maschera troppo
  brevi + istanze MuMu non sempre online). User farà screenshot manuale nei
  prossimi giorni e lo salverà in `c:/tmp/maschera_inv/`. Poi:
    1. Identificare ROI numero "carico" (zona ~y=480-520, x=600-780 stimata)
    2. `shared/ocr_helpers.py::leggi_load_squadra(img)` — pattern simile a
       `leggi_capacita_nodo()` (cascade PSM6 raw→binv th150)
    3. Hook in `tasks/raccolta.py::_compila_e_invia()` post-OCR ETA
    4. Estendere schema `cap_nodi_dataset.jsonl` con campo `load_squadra`
    5. `tools/analisi_cap_nodi.py` nuova sezione "saturazione invio" =
       `load_squadra / cap_nodo_attuale`
  Effort ~50 righe + calibrazione ROI. Beneficio: skip predictor preciso
  (no più stima `truppe × 1.5` per carico squadra).

- ~~Tabella istanze in `/ui/config/global` — rendering visivo da aggiustare~~
  ✅ RISOLTA 04/05 — utente conferma rendering corretto post-restart dashboard.
  Probabilmente fixata implicitamente da WU118-121 (refactor template + ordering
  + sync css). Nessuna modifica mirata necessaria.

## Sessione 02/05/2026 mattina+pomeriggio — WU90-100

### WU100 — Fix lettura RAW global_config (02/05 sera)

**Bug post-WU99**: utente segnala "allocazione dati non caricato" + "rifornimento
non selezionato di default mappa".

**Root cause**: `get_global_config()` (in `dashboard/services/config_manager.py`)
passa per `GlobalConfig._from_raw → to_dict()` che fa 2 trasformazioni rotture:
1. Schema legacy: `rifornimento_mappa.abilitato` (non legge `rifornimento.mappa_abilitata`)
2. Allocazione divisa per 100 (35.0 → 0.35) → template fa `0.35\|round\|int = 0`
3. Dataclass non include nuovi campi (rifugio, rifornimento unificato,
   auto_learn_banner, raccolta_ocr_debug, soglia_allocazione) → vengono persi

**Fix**: `app.py::ui_config_global` ora legge `global_config.json` raw via
`json.load()`, no round-trip via dataclass. Pattern coerente con
`_save_global_raw` introdotto in WU99 per il PATCH.

**Validazione post-fix**:
- alloc pomodoro=35, petrolio=20 ✅ (era 0/0)
- mode-mappa class="mode-btn active" ✅ (era inactive)
- rifugio X=680, Y=531 ✅ (era 687, 532 default legacy)
- auto-learn checkbox checked ✅

### WU99 — Config layout 4-card identico overview (02/05 fine pomeriggio)

**Richiesta utente** (con screenshot): "le configurazioni nel menù config
devo avere lo stesso layout di home".

**Modifiche**:
- `config_global.html` riscritto con layout `cfg4` clonato da overview:
  4 col-box affiancate (Sistema/Rifornimento/Zaino/Allocazione) con
  stile compatto identico (col-head con titolo + on/off dot, col-body
  con p-row/rr/mode-row/alloc-bar, col-foot con bottone arancione).
- Card Sistema include task baseline (16 checkbox 2-col) + flag globali.
- ID prefissati `gc-` per isolamento.
- JS dedicato `gcSalva*` chiama nuovo endpoint `PATCH /api/config/global`.
- Tabella istanze + Mumu read-only sotto la sezione config.

**Nuovo endpoint** `PATCH /api/config/global` (`api_config_global.py`):
merge incrementale top-level + scrittura dict raw (no round-trip via
GlobalConfig dataclass, che perdeva campi nuovi). `_save_global_raw()`
con tmp+replace atomico.

**Bug intermedio risolto**: il PUT esistente passava per `_from_raw → to_dict()`
del dataclass GlobalConfig, che NON include i campi nuovi (rifugio,
rifornimento unificato, auto_learn_banner, raccolta_ocr_debug,
soglia_allocazione). Risultato: PUT/PATCH cancellava quei campi. Fix:
PATCH endpoint dedicato che scrive raw.

**Sync prod ✅**, file allineati.

### WU98 — /ui/config eliminato (correzione utente)

**Osservazione utente post-WU97**: anche dopo aver rimosso le 2 sezioni
duplicate, la pagina /ui/config era ancora "una duplicazione della overview"
+ duplicava /ui/config/global per le altre sezioni. Decisione: eliminarla.

**Modifiche**:
- `GET /ui/config` → 302 redirect a `/ui/config/global`
- `base.html` menu: rimossa voce "config" separata, "config" punta a global
- `config_overrides.html` rinominato `.legacy` (backup)
- Aggiunta sezione "🤖 istanze (default statici)" in `config_global.html`
  con tabella editabile + JS `__saveIstanze()` → PUT /api/config/istanze
- Endpoint `/ui/config/global` ora passa `instances` + `overrides` al template

**Pagina finale /ui/config/global** (6 sezioni, 60KB):
Sistema·Flag globali · Task baseline · Rifornimento · Zaino·Allocazione ·
**Istanze (default statici)** · Mumu read-only.

Sync prod ✅.

### WU97 — Config rimozione duplicate con overview (02/05 fine pomeriggio)

**Osservazione utente**: "la sezione config mi sembra una duplicazione della
overview". Verifica conferma 2 sezioni replicate (task flags + istanze
abilitazione rapida).

**Modifiche in `config_overrides.html`**:
- Rimossa sezione task flags (già pill `task-flags-v2` in overview)
- Rimossa sezione istanze abilitazione rapida (già tabella `ist-table` in overview)
- Footnote bottom: rimando alla overview per quei controlli

**Risultato**: pagina /ui/config 38KB → 19KB (-50%). Sezioni residue tutte
config-specific (non duplicate altrove): Sistema · Flag globali · Rifornimento
· Zaino · Allocazione raccolta.

### WU96 — Dashboard config + global config layout uniforme (02/05 fine pomeriggio)

**Obiettivo utente**: "uniforma i layout delle due sezioni come la sezione
principale, differenza tra config e global config".

**Modifiche**: `config_overrides.html` + `config_global.html` riscritti con
pattern `tel-grid` + `tel-card` + `tel-head` + `sec-label` come `index.html`.
Banner top esplicativo in entrambe pagine.

**Modernizzazione config_global.html**: rimosso pattern legacy (id-based + JS
save manuale) → HTMX nested via listener globale di WU95. Hidden input per
mumu paths e rifornimento_comune.qta_* (preservazione campi non-editabili
nel save).

**Differenza pagine** (chiarita in banner):
- `/ui/config` → `runtime_overrides.json` · HOT-RELOAD al prossimo tick
- `/ui/config/global` → `global_config.json` · richiede RIAVVIO bot ·
  baseline reset (cancellando runtime_overrides il bot riparte da qui)

**Verifica**: GET 200 OK su entrambe, identici count tel-card/tel-grid/etc.
Sync prod ✅.

### WU95 — Dashboard config_overrides.html riallineato (02/05 fine pomeriggio)

**Obiettivo utente**: "aggiorna le sezioni della dashboard config con le
modifiche fatte". Il template `config_overrides.html` esponeva solo task +
sub-form rifornimento parziale + istanze; molte sezioni dello statico non
erano gestibili da UI.

**Sezioni aggiunte al template**: Sistema (max_parallel, tick_sleep_min),
Rifornimento completo (modalità+rifugio+comune+4 risorse), Zaino, Allocazione
raccolta (4 percentuali), Flag globali (auto_learn_banner toggle + raccolta_ocr_debug toggle).

**Fix infrastruttura JS**: aggiunto listener globale `htmx:configRequest` in
`base.html` che parsa `name="sezione[campo]"` → nested JSON + coerce
true/false/numeric strings + serializza JSON+Content-Type per form `hx-ext="json-enc"`
(l'estensione non era shipped — ricostruita inline). Beneficio: tutti i form
dashboard nested ora funzionano (compreso il vecchio rifornimento che era
parziale).

**File modificati (sync prod ✅)**: `dashboard/templates/config_overrides.html`,
`dashboard/templates/base.html`.

---

## Sessione 02/05/2026 mattina+pomeriggio — WU90-94 (scheduling + banner learner + baseline reset)

### Stato finale sessione

**Bot prod fermo** in attesa di restart utente. Modifiche WU90 + WU91 + WU92
+ WU93 + WU94 deployate in dev e syncate in prod. Documentazione aggiornata.

### WU94 — global_config.json baseline reset

**Obiettivo utente**: "tutti i task implementati e tutte le configurazioni
devono essere presenti nei statici in modo da poter effettuare un reset di
configurazione".

**Modifiche** in `config/global_config.json` (sync dev+prod, backup `.bak.20260502_pre_reset`):
- `sistema`: tick_sleep 300→60 (1 min), max_parallel 2→1
- `task`: 16 chiavi tutte → false (raccolta, rifornimento, zaino, vip,
  alleanza, messaggi, arena, arena_mercato, boost, store, radar,
  radar_census, donazione, main_mission, district_showdown, truppe).
  Mancavano `donazione`, `main_mission`, `truppe` nel vecchio file.
- `rifornimento_comune.acciaio_abilitato`: false → true
- `rifornimento`: nuovo schema dashboard `mappa_abilitata` +
  `membri_abilitati` + `provviste_max`. Rimosse `rifornimento_mappa` +
  `rifornimento_membri` (legacy).
- `raccolta.allocazione`: frazioni 0-1 → percentuali 0-100 (35/35/20/10).
- `raccolta.soglia_allocazione`: aggiunto (3).
- `rifugio`: nuova sezione (680, 531).
- `raccolta_ocr_debug`: false (root level).
- `auto_learn_banner`: true (root level, WU93).

**Verifica reset**: simulato runtime_overrides vuoto → bot legge 16 task false,
sistema (1, 60s), auto_learn_banner true. Reset completo funzionante.

### WU93 — BannerLearner (auto-apprendimento, no-AI)

**Obiettivo utente**: "implementare sistema di riconoscimento automatico
banner che auto-apprende e riconosce X destra in alto, aggiorna catalogo
indipendente da AI".

**Architettura confermata** (6 punti decisi insieme):
1. Threshold streak UNKNOWN >= 4 cicli (~14s) prima di attivare learner
2. Persistenza JSON dinamico (`data/learned_banners.json`)
3. Validazione (a)+(b): visual_diff_score >= 0.10 AND classify HOME/MAP >= 0.70
4. Cap LRU 25 entry + dedup similarity 0.85
5. Dashboard panel "🧠 banner appresi (auto)"
6. Auto-revoca dopo 3 fail streak consecutivi

**File aggiunti/modificati**:
- `shared/banner_learner.py` (NEW 240 righe) — detection heuristic OpenCV
  multi-color (rosso/oro/magenta) + edge density + shape filter
- `shared/learned_banners.py` (NEW 280 righe) — storage JSON + dedup +
  LRU + record_outcome + bridge load_learned_as_specs
- `shared/ui_helpers.py` — param `enable_learner` in `dismiss_banners_loop`,
  step LEARNER prima del break, tracking `_last_dismissed_learned`
- `core/launcher.py` — `_enable_learner = unknown_streak >= 4 and
  ctx.config.auto_learn_banner` (toggle globale runtime)
- `dashboard/app.py` — 4 endpoint: `/ui/partial/learned-banners`,
  `/learned-template/{name}/{kind}`, `POST /api/learned-banners/{name}/{action}`,
  `POST /api/banner-learner/{enable|disable}` (toggle globale)
- `dashboard/templates/index.html` — sezione "🧠 banner appresi (auto)"
  dopo "📊 storico truppe"
- `dashboard/models.py::GlobaliOverride` — campo `auto_learn_banner: bool = True`
- `config/config_loader.py::GlobalConfig` — campo `auto_learn_banner: bool = True`
  + propagazione root-level + costruzione da raw
- `runtime_overrides.json` (prod) — `globali.auto_learn_banner: true`

**Validazione heuristic**:
- Test detection X su Equipment Report (`FAU_02_*streak4.png`):
  ground truth (825, 54) → detected (824, 53), score 0.649
- Falsi positivi su HOME pulita: 0
- Iterazioni di tuning: 3 (sat threshold 80→100→multi-color masks)

**Sync prod**: ✅ 6 file copiati + verifica diff identici.

**Effetto runtime atteso**:
- Primo encounter dialog ignoto: ~5s extra (3 tap × 1.5s wait validazione)
  ma sblocca invece di 57s freeze
- Encounter successivi: riconoscimento istantaneo via catalog dinamico
- Auto-cleanup: dedup + LRU + auto-disable patologici

### Pre-condizioni prossima sessione

- Bot prod **fermo**, da riavviare manualmente
- 6 file deployati prod (WU90 + WU91 + WU92 + WU93)
- `data/learned_banners.json` ancora vuoto (verrà popolato runtime)
- Dashboard pannello "🧠 banner appresi" attivo (vuoto inizialmente)

### Validazione runtime post-restart (cumulativa)

| WU | Pattern atteso log |
|---|---|
| WU90 Donazione | `[DONAZIONE] completato — donate=N` con N ∈ [24-30] |
| WU91 MainMission | `should_run=False → saltato` fino 20 UTC, poi 1×/die |
| WU92 EquipReport | `[BANNER-LOOP] equipment_report chiuso (score=0.XX) tap_template@(cx,cy)` |
| WU93 Learner | `[LEARNER] detect_x_candidates: N candidate` + `[LEARNER] NEW banner registrato: learned_xxx` |

### WU92 — Banner Equipment Report popup IAP

Durante monitor della sessione: pattern UNKNOWN persistente ~57s su FAU_02
09:04 e FAU_03 09:10 UTC. Banner-loop "nessun banner riconosciuto" su 4
tentativi consecutivi. Fallback `_unmatched_tap_x` (WU66 cerchio dorato)
sblocca con 2 tap a (870,97) ma cieco.

**Cattura**: `_save_discovery_snapshot` esistente in `core/launcher.py` ha
generato `debug_task/boot_unknown/FAU_02_*streak3_20260502_094837.png`
(HOME + banner General Notice chat alleanza, falso UNKNOWN per occlusione
sentinella) e `*streak4_20260502_094902.png` (popup **Equipment Report**).

**Diagnosi visiva**: popup IAP gioco — titolo "Equipment Report" arancione
su carta beige + countdown "1d 16:10:59" + 6 icone equipment + CTA "€19,99
/ instantly receive 1750x". Chiusura via piccolo **cartellino bordeaux**
a forma di diamante con X bianca/oro in alto-destra del popup (zona
~800-855 × 25-80) + graffetta metallica adiacente. NON è la stessa X cerchio
dorato di `pin_btn_x_close` (forma diversa, sfondo rosso, dimensione minore).

**Modifiche**:
- `shared/banner_catalog.py` — entry `equipment_report` priority 2
- `templates/pin/pin_equipment_report_title.png` (34×340) — titolo NEW
- `templates/pin/pin_btn_x_tag_diamond.png` (51×55) — X chiusura NEW

**Sync prod**: ✅ tutti e 3 i file copiati manualmente.

**Effetto atteso**: chiusura al primo iter del banner-loop invece di 57s
freeze. Saving ~55s × N occorrenze al giorno (era ricorrente su FAU_02/03
al boot).

**Validazione runtime**: al prossimo popup, log dovrà mostrare
`[BANNER-LOOP] equipment_report chiuso (score=0.XX) tap_template@(cx,cy)`.

### Analisi notte 01→02/05 (12h, 7 cicli completati)

| Ciclo | Durata | Esiti | avg_tick | Note |
|---|---|---|---|---|
| c78-c79 | 78m / 72m | 11/11 ok | 420 / 388s | normale |
| c80-c81 | 101m / 115m | 11/11 ok | 544 / 621s | c81 contiene episodio FAU_07 |
| c82-c83 | 85m / 77m | 11/11 ok | 457 / 412s | recupero |
| c84 | in corso | 3/11 | — | |

**Anomalia singola (auto-recoverata)**: FAU_07 02:58→03:06 UTC stuck in
`screen=UNKNOWN` per ~8min (32 fail vai_in_home). WU79 gate HOME ha protetto:
tutti i task post-raccolta SALTATO senza burnare last_run, riprovati e completati
al ciclo successivo c82 04:31. Costo singolo: tick c81 1064s (vs avg 568s).

**Cascade ADB**: 0 in tutta la notte. DirectX driver continua a tenere.

**Foundation skip predictor (WU89)**: 88 record in `data/istanza_metrics.jsonl`,
70 utili (con `attive_pre`). Insight chiave dall'analisi:
- Predittore primario: `tick_total_s ~ n_invii` (correlazione lineare forte,
  ~70-90s/invio). 0 invii = tick 331s, 4 invii = tick 620s.
- ETA residua a fine ciclo è ~0s nel 28/34 casi → marce rientrano sempre prima
  del prossimo tick. **Skip "aspetta che rientrino" non serve**.
- La leva di saving non è skip ciclo intero (perderebbe 76% degli invii) ma
  **skip selettivo task post-raccolta**.
- Dataset ancora corto (70) per ML/clustering — soglia decente 200+ cicli.

### WU90 — DonazioneTask periodic 8h

**Pre-fix**: `schedule="always"` `interval=0` → 7 run/notte/istanza, ~58 min/notte
tempo bot.

**Calcolo finestra ottima**: cap pool gioco = 30, rigenero 1 donate/20min.
- 25 donate × 20 min = 500 min = 8h 20min
- Saturazione (30) = 600 min = 10h
- Scelta: `interval_hours=8.0` → pickup atteso 24-30/run

**Saving**: ~47 min/giorno tempo bot, throughput donate identico (bound dal
rate gioco, non dalla frequenza task).

**File modificato**: `config/task_setup.json:6`.

### WU91 — MainMissionTask daily 24h + guard 20:00 UTC

**Pre-fix**: `periodic 12h` → 2 run/die in qualsiasi ora.

**Modifiche**:
1. `config/task_setup.json:7` — `daily 24h` (era periodic 12h)
2. `tasks/main_mission.py:38-40` — `from datetime import datetime, timezone`
3. `tasks/main_mission.py:222-231` — `should_run` con guard:
   ```python
   if datetime.now(timezone.utc).hour < 20:
       return False
   ```

**Effetto combinato**: `daily` (max 1×/die, reset 01:00 UTC) + guard 20:00 UTC =
finestra utile 20:00→01:00 UTC (5h, 2-3 tick). Se bot fermo nella finestra →
salta giorno (accettato dall'utente).

**Razionale**: ricompense mission accumulano nel giorno, raccolta a fine-giornata
massimizza chest milestone (AP elevato).

### Sync prod manuale

`sync_prod.bat` ha avuto glitch encoding via shell PowerShell — sync diretto
dei 2 file modificati:
- `cp config/task_setup.json → C:/doomsday-engine-prod/config/`
- `cp tasks/main_mission.py → C:/doomsday-engine-prod/tasks/`

Verificato post-sync: entrambi i file in prod riflettono le modifiche dev.

### Documentazione aggiornata

- `ROADMAP.md` — sezione "Sessione 02/05 mattina" con WU90+WU91 + tabella
  `_TASK_SETUP` riallineata (aggiunto MainMissionTask che era stato dimenticato
  in WU88, posizione 6 priority 22)
- `.claude/CLAUDE.md` — righe WU90, WU91 aggiunte nella tabella issues
- `.claude/SESSION.md` — questa sezione

### Pre-condizioni prossima sessione

- Bot prod **fermo**, da riavviare manualmente da utente
- 2 file deployati prod: `config/task_setup.json` + `tasks/main_mission.py`
- Donazione ora `periodic 8h`, MainMission `daily 24h` + guard 20:00 UTC
- Rifornimento globalmente OFF (scelta utente, invariato)

### Validazione post-restart

1. **Donazione**: osservare `donate_count` nei log:
   - 24-30 consistente → tuning OK
   - Spesso 30 + log "cap max_donate_tap raggiunto" → scendere a 7h
   - Sotto 22 spesso → salire a 9h
2. **MainMission**: prima esecuzione tra 20:00 e 01:00 UTC. Pre-20:00 UTC
   nei log appare gate negato (no log esplicito ma should_run returna False
   silenziosamente — l'orchestrator logga "saltato")

### Issues aperte rimaste

| # | Priorità | Descrizione |
|---|----------|-------------|
| 81 | ALTA | Update Version popup gioco — detect + gestione |
| 83 | ALTA | Arena `_TAP_ULTIMA_SFIDA` cieco — match dinamico Challenge |
| 14 | ALTA | Arena START CHALLENGE non visibile multi-istanza (correlato #83?) |
| 15 | ALTA | `engine_status.json` stale writer |
| 46 | ALTA | state.rifornimento azzerato post-restart bot — root cause |
| 65 | BASSA | Wait>60s rifornimento → anticipare task post-raccolta |
| 23 | BASSA | smoke_test GlobalConfig dict vs dataclass |
| 25 | BASSA | Tracciamento diamanti nello state |
| Skip predictor step 3-5 | — | Aspettare 200+ cicli (~3-4 giorni) |

---

## Sessione 30/04/2026 sera — Cap nodi dataset (WU84) + monitor produzione

### Stato finale sessione

**Bot prod attivo** (PID 12220, restart 19:18 UTC) con tutti fix WU74-84 +
Issue #88+89 deployed. Resume da FAU_07. Driver DirectX confermato
(0 cascade ADB su ~5h monitor 13:01-18:29 prima dello stop manuale per WU84).

### Lavoro principale: WU84 Cap nodi dataset

**Motivazione**: pattern saturazione molto diversi tra istanze (FAU_06 87.5%
slot pieni vs FAU_09 14.3%). Servono dati oggettivi per discriminare causa
(livello target, marcia lunga, capacità nominale, raccolta parziale altri).

**Censimento manuale 30/04 18:50-19:08** su FAU_07 con utente che apriva i
popup gather, io facevo `adb exec-out screencap`:

| Tipo (icona client) | L6 | L7 |
|---------------------|---:|---:|
| Pomodoro (Field) | 1,200,000 | 1,320,000 |
| Legno (Sawmill) | 1,200,000 | 1,320,000 |
| Acciaio (Steel Mill) | 600,000 | 660,000 |
| Petrolio (Oil Refinery) | 240,000 | 264,000 |

**Pattern: L7 = L6 × 1.10** (esatto). Pomodoro = Legno = base 100%,
Acciaio = 50%, Petrolio = 20% di base.

**Note errore**: prima ROI tentata `(430,285,570,320)` SBAGLIATA — funzionava
solo sul primissimo screenshot dove popup era spostato (probabilmente overlay
mini-popup search). Dopo censimento ripartito da zero, ROI corretta è
**`(270,280,420,320)` 150×40 px**. Validato 9/9 OCR test.

### File modificati/creati (4)

| File | Cambio |
|------|--------|
| `shared/ocr_helpers.py` | NEW `leggi_capacita_nodo(img)` cascade PSM6 raw RGB → binv th150. ROI `(270,280,420,320)`. Helper `_parse_int_with_commas()`. ROI fissa perché popup gather sempre al centro mappa post SEARCH+tap nodo |
| `shared/cap_nodi_dataset.py` | NEW modulo. `registra_cap_sample(instance, tipo, livello, capacita)` → JSONL `data/cap_nodi_dataset.jsonl`. Lock thread-safe, silent on I/O error. Schema `{ts, instance, tipo, livello, capacita}` |
| `tasks/raccolta.py` | Hook subito dopo `_leggi_livello_nodo` ([raccolta.py:1719](tasks/raccolta.py#L1719)). Try/except esterno: nessun crash se OCR/dataset fallisce. Logga anche nodi sotto livello_min |
| `tools/analisi_cap_nodi.py` | NEW CLI tool. Sezioni: capacità per (tipo,liv) max/media/min vs nominale, campioni per istanza con %OCR_ok + residuo medio, residuo% per (istanza,tipo). Flag `--prod` `--days N` |

**Anche**: `sync_prod.bat` esteso con `xcopy tools/*.py` (mancava la directory `tools/` nel sync, l'ho aggiunta).

### Sync + restart prod

Sync completato 19:14 UTC. Restart bot 19:18 con `--use-runtime --resume` →
PID 12220 attivo, riprende da FAU_07.

### Pre-condizioni prossima sessione

- Bot prod attivo PID 12220, dashboard separata PID 21256
- 4 file WU84 deployed dev + prod, allineati
- Memoria `reference_capacita_nodi.md` salvata
- Dataset inizia ad accumulare campioni dal prossimo nodo aperto (raccolta running)

### Next steps suggeriti

1. Lasciar girare bot 24h → analizzare con `python tools/analisi_cap_nodi.py --prod`
2. Confronto residuo medio per istanza → identificare istanze con competizione alta (residuo basso ricorrente)
3. Aggiungere telemetry `capacita` + `livello` nell'output `raccolta` (visibile in dashboard)
4. (Futuro) Lettura load_squadra dalla maschera MARCIA → calcolo saturazione invio

---

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
