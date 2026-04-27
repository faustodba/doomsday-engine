@echo off
REM ============================================================================
REM   DOOMSDAY ENGINE V6 — Launcher DASHBOARD PRODUZIONE
REM ============================================================================
REM
REM   Avvia il server dashboard FastAPI/uvicorn in produzione (porta 8765).
REM   La dashboard NON dipende dal bot — gira come servizio separato e legge
REM   gli stessi file del bot (config/, state/, data/, logs/).
REM
REM   URL accesso: http://localhost:8765/ui  (redirect da /)
REM
REM ----------------------------------------------------------------------------
REM   ENV E PATHS
REM ----------------------------------------------------------------------------
REM
REM   DOOMSDAY_ROOT=C:\doomsday-engine-prod
REM     Variabile letta da dashboard/services/{config_manager,stats_reader,
REM     telemetry_reader}.py per leggere config/state/logs/data dalla dir prod
REM     (Issue #38). Senza questa variabile, la dashboard userebbe la dir dello
REM     script (= la dir prod, OK per coerenza) ma con possibili discrepanze
REM     se il file viene chiamato da percorsi diversi.
REM
REM   PYTHONIOENCODING=utf-8
REM     Forza utf-8 su stdout/stderr Python. Necessario per emoji/caratteri
REM     speciali nei log (es. "▸", "✓", caratteri italiani con accenti).
REM
REM ----------------------------------------------------------------------------
REM   CLEANUP PORTA
REM ----------------------------------------------------------------------------
REM
REM   Prima del lancio, chiudiamo eventuali processi che tengono occupata la
REM   porta 8765 (lancio precedente di dashboard non chiuso pulito, conflitto
REM   con bot launcher integrato, ecc.). Senza cleanup uvicorn fallisce con
REM   "Address already in use".
REM
REM ----------------------------------------------------------------------------
REM   MODALITA' DI AVVIO
REM ----------------------------------------------------------------------------
REM
REM   Default: produzione headless su 0.0.0.0:8765 (accessibile da rete locale).
REM   Decommenta UNA SOLA delle righe "py -3.14 -m uvicorn ..." sotto.
REM
REM ============================================================================

cd /d C:\doomsday-engine-prod
set PYTHONIOENCODING=utf-8
set DOOMSDAY_ROOT=C:\doomsday-engine-prod


REM --- CLEANUP PORTA 8765 ---------------------------------------------------
REM Kill processi che tengono occupata la porta dashboard.
echo [DASHBOARD] Pulizia porta 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do (
    echo [DASHBOARD] Kill PID %%a
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 >nul


echo [DASHBOARD] Avvio dashboard FastAPI/uvicorn su http://0.0.0.0:8765 ...


REM --- MODALITA' 1: PRODUZIONE STANDARD (default) --------------------------
REM Bind 0.0.0.0 (accessibile da LAN). Reload disabilitato.
py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765


REM --- MODALITA' 2: SOLO LOCALHOST -----------------------------------------
REM Sicurezza: bind 127.0.0.1 (accessibile solo dalla stessa macchina).
REM py -3.14 -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8765


REM --- MODALITA' 3: DEV CON HOT-RELOAD -------------------------------------
REM Riavvia automaticamente al cambio file Python (utile per sviluppo).
REM ATTENZIONE: non usare in produzione (consuma piu' RAM, restart spurious).
REM py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765 --reload


REM --- MODALITA' 4: PORTA ALTERNATIVA --------------------------------------
REM Se 8765 e' permanentemente occupata da altro servizio.
REM Ricorda: il bot e altre integrazioni cercano dashboard su 8765 di default.
REM py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8766


REM --- MODALITA' 5: VERBOSE LOGGING ----------------------------------------
REM Log uvicorn dettagliato (debug) per troubleshooting.
REM py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765 --log-level debug


REM --- MODALITA' 6: WORKERS MULTIPLI ---------------------------------------
REM Multi-process per gestire piu' connessioni simultanee. Sconsigliato:
REM la dashboard ha cache TTL in-memory che non e' shared tra worker.
REM py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765 --workers 2


REM --- MODALITA' 7: SOLO API (no UI/HTMX) ----------------------------------
REM Stesso server ma utile come reminder che gli endpoint API REST sono
REM accessibili a /api/* indipendentemente dalla UI Jinja2.
REM Apri /docs per Swagger UI auto-generato.
REM py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765


REM ============================================================================
if not "%NOPAUSE%"=="1" pause
