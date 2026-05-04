@echo off
REM ============================================================================
REM   DOOMSDAY ENGINE V6 — Launcher PRODUZIONE
REM ============================================================================
REM
REM   Avvia il bot in modalita' produzione (porta 8765 dashboard separata).
REM   Il bot processa SEQUENZIALMENTE le 12 istanze MuMu definite in
REM   config/instances.json (FAU_00..FAU_10 + FauMorfeus).
REM
REM   La dashboard NON viene avviata da qui (--no-dashboard). Per la dashboard
REM   usare run_dashboard_prod.bat in una console separata.
REM
REM ----------------------------------------------------------------------------
REM   ARGOMENTI MAIN.PY DISPONIBILI
REM ----------------------------------------------------------------------------
REM
REM   --tick-sleep N        Secondi di pausa tra un ciclo completo di istanze
REM                         e il successivo. Default 300, prod usa 60.
REM
REM   --no-dashboard        Non avvia la dashboard FastAPI integrata. Da usare
REM                         sempre in prod (la dashboard gira separata).
REM
REM   --use-runtime         SKIP prompt configurazione iniziale. Usa il file
REM                         config/runtime_overrides.json cosi' com'e'.
REM                         Senza questo flag, il bot chiede a console se
REM                         vuoi mantenere/resettare la configurazione.
REM
REM   --resume              SKIP prompt resume. Riprende automaticamente
REM                         dall'ultima istanza interrotta (last_checkpoint.json).
REM                         Senza questo flag, il bot chiede da quale istanza
REM                         riprendere (o ricominciare da zero).
REM
REM   --reset-config        Ripristina runtime_overrides.json (sezione istanze)
REM                         dai valori base di instances.json. Mantiene
REM                         invariati i globali (task flags, soglie, ecc.).
REM                         Da usare quando vuoi azzerare overrides per-istanza.
REM
REM   --istanze FAU_00,FAU_01,FAU_02
REM                         Filtra le istanze da processare. Tutte le altre
REM                         vengono saltate. Utile per test o per ridurre
REM                         carico RAM (12 istanze MuMu = ~10-12 GB).
REM
REM   --dry-run             Modalita' test: niente ADB reale, usa FakeDevice.
REM                         Per validare configurazione senza avviare emulator.
REM
REM   --status-interval N   Intervallo (sec) scrittura engine_status.json.
REM                         Default 5. Aumentare se i save sembrano frequenti.
REM
REM ----------------------------------------------------------------------------
REM   MODALITA' DI AVVIO PRECONFIGURATE
REM ----------------------------------------------------------------------------
REM
REM   Decommenta UNA SOLA delle righe "py -3.14 main.py ..." sotto.
REM   Quella attiva (default) e' la modalita' PRODUZIONE AUTO.
REM
REM ============================================================================

cd /d C:\doomsday-engine-prod
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set DOOMSDAY_ROOT=C:\doomsday-engine-prod


REM --- PRE-KILL: bot main.py orfani da lanci precedenti ---------------------
REM   Killa python.exe con "main.py" nel command line. Eseguito PRIMA del
REM   lancio nuovo bot per evitare sovrapposizioni su engine_status.json,
REM   state/, logs/. Il nuovo python.exe non e' ancora stato spawnato quindi
REM   l'inclusione di tutti i match e' safe (no PID corrente da escludere).
REM   Esclude esplicitamente "-m uvicorn" per non killare la dashboard.
REM   Doppia rete: main.py contiene anche _cleanup_orfani_processi_startup
REM   che killa cmd.exe + python.exe orfani al primo tick (preserva PID corrente).
echo [run_prod] Pre-kill bot main.py orfani...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -notlike '*-m uvicorn*' } | ForEach-Object { Write-Host ('  kill PID=' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul


REM --- MODALITA' 1: PRODUZIONE AUTO (default) -------------------------------
REM Nessun prompt. Riprende ultimo checkpoint. Usa runtime config corrente.
REM Tipico per cron/avvio automatico.
REM tick-sleep: NON specificato → letto da config (sistema.tick_sleep_min × 60).
REM Override esplicito per test/debug: aggiungi --tick-sleep N (in secondi).
py -3.14 main.py --no-dashboard --use-runtime --resume


REM --- MODALITA' 2: PRODUZIONE INTERATTIVA ---------------------------------
REM Prompt config + resume. Usare quando vuoi controllo manuale al boot.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard


REM --- MODALITA' 3: SOLO PROMPT CONFIG (auto-resume) -----------------------
REM Chiede config ma riprende automatico dal checkpoint.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --resume


REM --- MODALITA' 4: SOLO PROMPT RESUME (auto-config) -----------------------
REM Mantiene runtime config; chiede da quale istanza riprendere.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime


REM --- MODALITA' 5: RESET RUNTIME OVERRIDES + AVVIO ------------------------
REM Azzera overrides per-istanza poi parte. Globali (task flags) preservati.
REM Utile dopo modifiche manuali al file che hanno rotto qualcosa.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime --resume --reset-config


REM --- MODALITA' 6: RIDOTTA RAM (4 istanze) ---------------------------------
REM Per macchine con poca RAM o quando dev tools aperti (VSCode, Claude).
REM 4 istanze MuMu = ~4 GB invece di ~12 GB.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime --resume --istanze FAU_00,FAU_01,FAU_02,FAU_03


REM --- MODALITA' 7: SOLO 1 ISTANZA TEST -------------------------------------
REM Per debug/calibrazione singola istanza.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime --resume --istanze FAU_00


REM --- MODALITA' 8: DRY-RUN (no ADB) ----------------------------------------
REM Nessun emulator avviato. Per validare config + import + scheduler.
REM py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime --resume --dry-run


REM --- MODALITA' 9: TICK PIU' LENTO (sleep 5 minuti tra cicli) -------------
REM Riduce frequenza tick (utile in modalita' "manutenzione" o low-priority).
REM py -3.14 main.py --tick-sleep 300 --no-dashboard --use-runtime --resume


REM ============================================================================
REM   PAUSE finale: lascia la finestra aperta dopo l'uscita del bot.
REM   Per chiusura immediata (es. cron) impostare NOPAUSE=1 prima del lancio.
REM ============================================================================
if not "%NOPAUSE%"=="1" pause
