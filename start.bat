@echo off
REM ============================================================================
REM   DOOMSDAY ENGINE V6 — start.bat
REM   Avvio unificato: sostituisce run_prod.bat + riavvia_bot.bat
REM
REM   Sequenza sempre eseguita:
REM     1. Kill bot orfani (PID file + CIM)
REM     2. Shutdown tutte le istanze MuMu (0-11)
REM     3. Reset ADB server (rompe connessioni zombie)
REM     4. Avvio bot con --resume (usa last_checkpoint.json se esiste)
REM     5. Loop automatico su exit code 100 (restart schedulato)
REM
REM   Stato di gioco NON modificato:
REM     - last_checkpoint.json preservato → --resume riprende dall'interruzione
REM     - scheduler_planned_order.json preservato → ordine adattivo intatto
REM   Per azzerare tutto usa reset_emergenza.bat.
REM
REM   Usato da:
REM     - Avvio manuale (doppio clic o terminale)
REM     - Telegram /avvia_bot, /avvia_tutto
REM     - Loop restart automatico su exit 100
REM ============================================================================

cd /d C:\doomsday-engine-prod
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set DOOMSDAY_ROOT=C:\doomsday-engine-prod
set ADB=C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe
set MUMU_MGR=C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe

echo.
echo ===== DOOMSDAY ENGINE — Avvio %DATE% %TIME% =====
echo.

REM --- 1. Kill bot orfani (PID file) ------------------------------------------
echo [1/3] Kill bot orfani...
if exist "data\bot.pid" (
    powershell -NoProfile -Command "try { $p=[int](Get-Content 'data\bot.pid'); Stop-Process -Id $p -Force -EA SilentlyContinue; Write-Host ('  kill PID='+$p+' (bot.pid)') } catch {}"
    del "data\bot.pid" >nul 2>nul
)
powershell -NoProfile -Command "@('python.exe','py.exe') | ForEach-Object { $n=$_; try { Get-CimInstance Win32_Process -Filter ('Name='''+$n+'''') | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -notlike '*-m uvicorn*' -and $_.CommandLine -notlike '*claude-bridge*' } | ForEach-Object { Write-Host ('  kill PID='+$_.ProcessId+' ('+$n+')'); Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue } } catch {} }"
timeout /t 3 /nobreak >nul

REM --- 2. Shutdown tutte le istanze MuMu (0-11) --------------------------------
echo [2/3] Shutdown istanze MuMu...
for /L %%i in (0,1,11) do (
    "%MUMU_MGR%" control -v %%i shutdown >nul 2>nul
)
echo   Istanze MuMu spente
timeout /t 2 /nobreak >nul

REM --- 3. Reset ADB server ------------------------------------------------------
echo [3/3] Reset ADB server...
"%ADB%" kill-server >nul 2>nul
echo   ADB server resettato

REM   Stato di gioco preservato integralmente:
REM   - last_checkpoint.json: --resume riprende dall'ultima istanza interrotta
REM   - scheduler_planned_order.json: ordine adattivo del ciclo corrente
REM   Per azzerare lo stato usa reset_emergenza.bat

echo.
echo Avvio bot...
echo.

REM --- Loop: riavvio automatico su exit code 100 --------------------------------
:run_loop
py -3.14 main.py --no-dashboard --use-runtime --resume
if %ERRORLEVEL%==100 (
    echo [start] Restart richiesto dal bot ^(exit 100^), ripartenza fra 5s...
    timeout /t 5 /nobreak >nul
    goto :run_loop
)
echo [start] Bot uscito con exit code %ERRORLEVEL% — stop.

if not "%NOPAUSE%"=="1" pause
