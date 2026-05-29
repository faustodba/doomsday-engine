@echo off
REM ============================================================
REM  RIAVVIA BOT — Doomsday Engine V6
REM
REM  Usato da: Telegram /avvia_bot, /avvia_tutto
REM  NON usare per avvio manuale → usa run_prod.bat
REM
REM  Differenza da run_prod.bat:
REM   - Killa SEMPRE il vecchio bot E resetta ADB prima di partire
REM   - Questo rompe connessioni zombie dei thread orfani
REM   - Cancella checkpoint e planned_order (no resume)
REM   - Mantiene il loop di restart automatico (exit code 100)
REM ============================================================

cd /d C:\doomsday-engine-prod
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set DOOMSDAY_ROOT=C:\doomsday-engine-prod
set ADB=C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe

echo [riavvia_bot] Avvio sequenza restart pulito...

REM --- 1. Kill bot (PID file + CIM) ------------------------------------
echo [riavvia_bot] Kill bot orfani...
if exist "data\bot.pid" (
    powershell -NoProfile -Command "try { $p=[int](Get-Content 'data\bot.pid'); Stop-Process -Id $p -Force -EA SilentlyContinue; Write-Host ('  kill PID='+$p) } catch {}"
    del "data\bot.pid" >nul 2>nul
)
powershell -NoProfile -Command "@('python.exe','py.exe') | ForEach-Object { $n=$_; try { Get-CimInstance Win32_Process -Filter ('Name='''+$n+'''') | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -notlike '*-m uvicorn*' -and $_.CommandLine -notlike '*claude-bridge*' } | ForEach-Object { Write-Host ('  kill PID='+$_.ProcessId+' ('+$n+')'); Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue } } catch {} }"
timeout /t 3 /nobreak >nul

REM --- 2. Reset ADB server (rompe connessioni zombie thread) -----------
echo [riavvia_bot] Reset ADB server...
"%ADB%" kill-server >nul 2>nul
echo   ADB server resettato

REM --- 3. Cancella checkpoint e planned_order --------------------------
echo [riavvia_bot] Cancella checkpoint e planned_order...
if exist "last_checkpoint.json" del "last_checkpoint.json" >nul 2>nul
if exist "data\scheduler_planned_order.json" del "data\scheduler_planned_order.json" >nul 2>nul

REM --- Loop con restart automatico su exit code 100 -------------------
:run_loop
REM Pulizia checkpoint anche ad ogni restart automatico
if exist "last_checkpoint.json" del "last_checkpoint.json" >nul 2>nul
if exist "data\scheduler_planned_order.json" del "data\scheduler_planned_order.json" >nul 2>nul
py -3.14 main.py --no-dashboard --use-runtime
if %ERRORLEVEL%==100 (
    echo [riavvia_bot] Restart richiesto ^(exit code 100^), ripartenza fra 5s...
    timeout /t 5 /nobreak >nul
    goto :run_loop
)
echo [riavvia_bot] Bot uscito con exit code %ERRORLEVEL% — stop.
pause
