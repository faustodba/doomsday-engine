# Telegram Bot — Architettura (Doomsday Engine V6)

> Documento generato nella sessione 29/05/2026 contestualmente al refactoring WU-TgRefactor.
> Aggiornare quando si aggiungono comandi, moduli o si modifica il meccanismo di dispatch.

---

## Panoramica

Il Telegram bot è un **processo Python standalone** (`run_telegram_prod.bat`) indipendente dal bot di gioco e dalla dashboard. Comunica con il sistema tramite file su disco (no socket, no Redis). Il polling è **sincrono** per coerenza con l'architettura complessiva del progetto (tutto il sistema usa `time.sleep`, non asyncio).

```
run_telegram_prod.bat
  └─ py core/telegram_bot.py          ← processo standalone
       ├─ ThreadDaemon: TelegramBot   ← polling loop + dispatch
       └─ ThreadDaemon: TgStartupNotify
```

---

## Struttura moduli

Il bot è suddiviso in 5 file nella cartella `core/`:

| File | Righe | Responsabilità |
|------|-------|----------------|
| [`telegram_bot.py`](../core/telegram_bot.py) | ~587 | Entry point, polling loop, dict dispatch, lifecycle, notifiche proattive, alert bot |
| [`tg_utils.py`](../core/tg_utils.py) | ~407 | Helpers condivisi: path, config, patch runtime, data readers, formatters, check processo |
| [`tg_handlers_monitoring.py`](../core/tg_handlers_monitoring.py) | ~578 | Builders dati + handler comandi di sola lettura |
| [`tg_handlers_control.py`](../core/tg_handlers_control.py) | ~152 | Handler comandi di controllo sistema |
| [`tg_handlers_config.py`](../core/tg_handlers_config.py) | ~198 | Handler comandi di configurazione |

**Dipendenze tra moduli** (nessun ciclo):

```
tg_utils.py                 ← nessuna dipendenza interna
tg_handlers_monitoring.py   ← import da tg_utils
tg_handlers_control.py      ← import da tg_utils
tg_handlers_config.py       ← import da tg_utils
telegram_bot.py             ← import da tg_utils + tutti e 3 gli handler modules
```

---

## Lifecycle del processo

```
1. main block: setup logging + _acquire_lock() (PID file)
2. start() → lancia thread daemon "TelegramBot"
3. thread "TgStartupNotify" → sleep 8s → _notify_startup()
4. _svc_stop.wait() → blocca main thread fino a SIGINT/SIGTERM
5. stop(timeout=5s) + _release_lock()
```

Il processo è progettato per essere **riavviato dal bat** (`run_telegram_prod.bat` ha un `:loop` che rilancia su exit code 100). Il comando `/restart_telegram` esegue `os._exit(100)` dopo 5s.

---

## Polling loop

```python
while not stop.is_set():
    updates = get_updates(offset=_update_offset, timeout_s=20)  # long-polling
    if empty_too_fast:                   # risposta <5s → errore swallowed (es. 409)
        sleep(5); continue
    for upd in updates:
        if chat != authorized_chat: skip
        if not text.startswith("/"): skip
        reply = _handle_command(text, chat)
        send_message(chat, reply[:4000])
    # check bot silenzioso ogni 120s → alert su fail streak ≥3
```

**Security gate**: solo il `chat_id` configurato in `data/secrets.json` può inviare comandi. Messaggi da altri chat vengono loggati e scartati.

**Token e chat_id**: letti da `data/secrets.json` via `shared.telegram_client`. Il file è in `.gitignore`.

---

## Command dispatch

I comandi sono registrati in un **dict statico** `_DISPATCH` in `telegram_bot.py`:

```python
_DISPATCH: dict[str, Callable[[str], str]] = {
    "/help":             _cmd_help,
    "/status":           cmd_status,         # da tg_handlers_monitoring
    "/restart_bot":      cmd_restart_bot,    # da tg_handlers_control
    "/rif_risorsa":      cmd_rif_risorsa,    # da tg_handlers_config
    # ... 30 voci totali
}

def _handle_command(text, chat_id):
    handler = _DISPATCH.get(cmd)
    if handler:
        return handler(text)
    return "Comando non riconosciuto..."
```

Ogni handler ha firma `(text: str) -> str`. Il parsing degli argomenti è responsabilità di ciascun handler.

**Aggiungere un nuovo comando** richiede:
1. Funzione `cmd_xxx(text: str) -> str` nel modulo appropriato
2. Una riga in `_DISPATCH`
3. Una riga nel testo `/help` in `_cmd_help()`

---

## Tutti i comandi (30 totali)

### Monitoraggio (sola lettura)

| Comando | Handler | File | Descrizione |
|---------|---------|------|-------------|
| `/help` | `_cmd_help` | `telegram_bot.py` | Lista comandi con meccanismo |
| `/status` | `cmd_status` | `tg_handlers_monitoring.py` | Stato completo: bot, dashboard, ciclo, DRL |
| `/istanze` | `cmd_istanze` | `tg_handlers_monitoring.py` | Lista istanze ON/OFF con istanza live |
| `/istanza FAU_03` | `cmd_istanza` | `tg_handlers_monitoring.py` | Card dettaglio singola istanza |
| `/produzione` | `cmd_produzione` | `tg_handlers_monitoring.py` | Produzione 24h per istanza (M pom-eq/h) |
| `/rifornimento` | `cmd_rifornimento` | `tg_handlers_monitoring.py` | DRL master + spedizioni + config |
| `/cicli` | `cmd_cicli` | `tg_handlers_monitoring.py` | Ultimi 5 cicli (in corso + 4 completati) |
| `/ciclo [N]` | `cmd_ciclo` | `tg_handlers_monitoring.py` | Dettaglio ciclo #N (ometti per ultimo) |

### Avvio sistema

| Comando | Handler | Meccanismo |
|---------|---------|------------|
| `/avvia_bot` | `cmd_avvia_bot` | Lancia `start.bat` in nuova console (se bot non in esecuzione) |
| `/avvia_dashboard` | `cmd_avvia_dashboard` | Lancia `run_dashboard_prod.bat` (se non attiva) |
| `/avvia_tutto` | `cmd_avvia_tutto` | Entrambi sopra se necessario |

### Bot management

| Comando | Handler | Meccanismo |
|---------|---------|------------|
| `/pausa` | `cmd_pausa` | Scrive `data/maintenance.flag` → bot pausa tra istanze |
| `/riprendi` | `cmd_riprendi` | Rimuove `data/maintenance.flag` |
| `/avvia_ora` | `cmd_avvia_ora` | Scrive `data/wake_now.flag` → salta sleep inter-ciclo |
| `/restart_bot` | `cmd_restart_bot` | Scrive `data/restart_requested.flag` → exit 100 a **fine ciclo** → `start.bat :loop` (riavvio programmato) |
| `/restart_telegram` | `cmd_restart_telegram` | `os._exit(100)` dopo 5s → `run_telegram_prod.bat :loop` (~15s downtime) |

### Configurazione istanze e task

| Comando | Handler | Meccanismo |
|---------|---------|------------|
| `/disabilita FAU_03` | `cmd_disabilita` | Scrive `runtime_overrides.json::istanze.FAU_03.abilitata=false` |
| `/abilita FAU_03` | `cmd_abilita` | Scrive `runtime_overrides.json::istanze.FAU_03.abilitata=true` |
| `/task` | `cmd_task` | Mostra stato ON/OFF di ogni task in runtime_overrides |
| `/disabilita_task arena` | `cmd_disabilita_task` | `runtime_overrides.json::globali.task.arena=false` |
| `/abilita_task arena` | `cmd_abilita_task` | `runtime_overrides.json::globali.task.arena=true` |

### Rifornimento

| Comando | Handler | Meccanismo |
|---------|---------|------------|
| `/rif_risorsa acciaio off` | `cmd_rif_risorsa` | `rifornimento_comune.acciaio_abilitato=false` in runtime_overrides |
| `/rif_modo mappa` | `cmd_rif_modo` | `rifornimento.mappa_abilitata/membri_abilitati` in runtime_overrides |
| `/rif_soglia acciaio 3.5` | `cmd_rif_soglia` | `rifornimento_comune.soglia_acciaio_m=3.5` in runtime_overrides |
| `/rif_provviste 80` | `cmd_rif_provviste` | `rifornimento.provviste_max=80` in runtime_overrides |
| `/rif_reset FAU_03` | `cmd_rif_reset` | Azzera `state/FAU_03.json::rifornimento.spedizioni_oggi+provviste_esaurite` |
| `/rif_reset` | `cmd_rif_reset` | Come sopra ma per tutte le istanze |

### Notifiche

| Comando | Handler | Meccanismo |
|---------|---------|------------|
| `/stop_messaggi` | `cmd_stop_messaggi` | `runtime_overrides.json::globali.notifications.telegram.enabled=false` |
| `/start_messaggi` | `cmd_start_messaggi` | `runtime_overrides.json::globali.notifications.telegram.enabled=true` |

---

## Notifiche proattive

Le notifiche **proattive** sono chiamate esterne da `main.py` e `core/orchestrator.py`. Rispettano il flag `enabled` in `runtime_overrides.json`.

| Funzione | Trigger | Guard config |
|----------|---------|-------------|
| `notify_cycle_complete(n, istanze, marce, sped, durata)` | Fine ciclo, chiamata da `main.py` | `notify_cycle_every_n` (default ogni 5 cicli) |
| `notify_cascade_adb(instance, details)` | `ADBUnhealthyError` in `orchestrator.py` | `notify_cascade` (default True) |
| `notify_drl_saturo(residuo_m)` | DRL master = 0, da `core/alerts.py` | `notify_drl` (default True) |
| `notify_daily_report(text)` | Daily report `core/daily_report.py` | `notify_daily_report` (default True) |
| `notify_raccolta_bassa(ciclo_n)` | ≥3 istanze con slot liberi + 0 marce, da `main.py` | `enabled` (deduplicato per ciclo) |

Le notifiche di sistema (`_send_system_alert`) ignorano il flag `enabled` e vengono sempre inviate se il token è configurato:
- Boot del servizio Telegram (`_notify_startup`)
- Bot fermato inaspettatamente (rilevato dal check silenzioso nel polling loop)

---

## Singleton e anti-409

Il bot previene il doppio avvio (che causerebbe errore Telegram 409 "Conflict: terminated by other getUpdates request") con due meccanismi:

1. **PID file** `data/telegram_bot.pid`: al boot verifica se il vecchio PID è ancora vivo (via PowerShell `Get-Process`). Se vivo → exit 1. Se stale → sovrascrive.

2. **Timer anti-rapid-retry** nel polling loop: se `get_updates` torna in <5s con lista vuota (segnale di errore swallowed, tipicamente un 409) → sleep 5s prima di riprovare. Evita il flood API da loop tight.

---

## Check bot silenzioso

Il polling loop controlla ogni 120s se il bot di gioco è ancora in esecuzione. Se non trovato per 3 check consecutivi (~6 min) → invia `_send_system_alert` (sempre, ignora `enabled`). Cooldown 15 min tra alert per evitare spam.

`_check_bot_running()` usa 3 metodi in cascata:
1. `data/bot.pid` → `Get-Process -Id {pid}` (veloce, affidabile)
2. `Get-CimInstance Win32_Process` filtrando `*main.py*` non-uvicorn (fallback)
3. `engine_status.json` freschezza < 30 min (fallback finale, senza dipendenze PS)

---

## Flusso config (scrittura)

Tutti i comandi di configurazione scrivono su **`runtime_overrides.json`** (DYNAMIC, hot-reload). Il bot di gioco rilegge il file ad ogni tick.

Pattern usato da tutti i comandi di config:
```python
def _patch_runtime(patch_fn) -> bool:
    ov = json.loads(ov_path.read_text())   # legge
    patch_fn(ov)                            # modifica in-memory
    tmp = ov_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ov, indent=2))
    os.replace(tmp, ov_path)               # atomic write
    return True
```

Nessun comando scrive su `global_config.json` (STATIC) né su `instances.json` — quelli sono modificabili solo da `/ui/config/global` nella dashboard.

---

## Avvio sistema (bat)

I bat vengono avviati tramite `subprocess.Popen` con `CREATE_NEW_CONSOLE`:
```python
subprocess.Popen(
    ["cmd", "/c", str(bat_path)],
    creationflags=subprocess.CREATE_NEW_CONSOLE,
    cwd=str(bat_path.parent),
)
```

`CREATE_NEW_CONSOLE` invece di `shell=True` evita il double-escaping delle virgolette che causava misparsing degli argomenti su Windows.

| Bat | Path |
|-----|------|
| `_BAT_BOT` | `{_root()}/start.bat` |
| `_BAT_DASHBOARD` | `{_root()}/run_dashboard_prod.bat` |

`_root()` rispetta la variabile d'ambiente `DOOMSDAY_ROOT` → funziona sia in dev che in prod.

---

## Configurazione runtime

Schema in `runtime_overrides.json::globali.notifications.telegram`:

```json
{
  "enabled":              false,
  "notify_cycle_every_n": 5,
  "notify_cascade":       true,
  "notify_drl":           true,
  "notify_daily_report":  true
}
```

Tutti i valori sono hot-reload: letti da `_tg_config()` ad ogni notifica proattiva. Non richiedono restart del servizio.

---

## File su disco usati

| File | Accesso | Scopo |
|------|---------|-------|
| `data/secrets.json` | lettura | Token Telegram + chat_id |
| `config/runtime_overrides.json` | lettura + scrittura atomica | Config bot (comandi config) |
| `config/instances.json` | lettura | Lista istanze configurate |
| `engine_status.json` | lettura | Check bot running (fallback 3) |
| `data/bot.pid` | lettura | Check bot running (primario) |
| `data/telegram_bot.pid` | lettura + scrittura | Singleton guard |
| `data/telemetry/cicli.json` | lettura | `/cicli`, `/ciclo`, `/status` |
| `data/istanza_metrics.jsonl` | lettura | `/istanze`, `/istanza`, `notify_raccolta_bassa` |
| `data/morfeus_state.json` | lettura | DRL master per `/rifornimento`, `/status` |
| `data/storico_truppe.json` | lettura | Truppe per `/istanza` |
| `state/*.json` | lettura + scrittura | `/istanza`, `/rif_reset` |
| `data/maintenance.flag` | scrittura (touch/unlink) | `/pausa`, `/riprendi` |
| `data/wake_now.flag` | scrittura (touch) | `/avvia_ora` |
| `data/restart_requested.flag` | scrittura | `/restart_bot` |
| `logs/telegram_service.log` | scrittura | Log del servizio |

---

## Differenze vs trading bot

| Aspetto | Doomsday (questo) | Trading bot |
|---------|-------------------|-------------|
| Framework | stdlib urllib puro | python-telegram-bot 20.x |
| Concorrenza | Thread daemon sincrono | asyncio + await |
| Config state | File JSON su disco | Redis |
| Split moduli | 4 handler modules | 4 handler modules (analogo) |
| Test | Nessun test dedicato | 39 test mockati |
| AI integration | Nessuna | Claude Code bridge HTTP/CLI |
| Callback inline | Non presenti | Bottoni conferma azioni pericolose |

La scelta di stdlib urllib è intenzionale: il resto del sistema è tutto sincrono (`time.sleep`, ADB sincrono, no asyncio). Introdurre asyncio solo per il Telegram bot creerebbe un confine sincrono/asincrono difficile da gestire correttamente.

---

## Come aggiungere un nuovo comando

```python
# 1. Scegli il modulo giusto:
#    - Sola lettura (dashboard) → tg_handlers_monitoring.py
#    - Controllo sistema → tg_handlers_control.py
#    - Config runtime_overrides → tg_handlers_config.py

# 2. Scrivi il handler in quel modulo:
def cmd_mio_comando(text: str) -> str:
    parts = text.split()
    if len(parts) < 2:
        return "⚠ Uso: /mio_comando <arg>"
    # ... logica ...
    return "✅ Fatto."

# 3. In telegram_bot.py, aggiungi al dict _DISPATCH:
"/mio_comando": cmd_mio_comando,  # import già fatto in cima al file

# 4. In _cmd_help(), aggiungi la riga nella sezione appropriata:
"/mio_comando <arg>  — descrizione\n"
```

Tre modifiche, tutte evidenti, nessuna nascosta dentro 350 righe di if/elif.
