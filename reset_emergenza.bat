@echo off
REM ============================================================
REM  RESET EMERGENZA — Doomsday Engine V6
REM  Doppio clic quando il bot e' bloccato.
REM  Log: C:\doomsday-engine-prod\reset_emergenza.log
REM ============================================================

cd /d C:\doomsday-engine-prod
set ROOT=C:\doomsday-engine-prod
set ADB=C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe
set LOG=%ROOT%\reset_emergenza.log
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo ===== RESET EMERGENZA %DATE% %TIME% ===== > "%LOG%"
echo.
echo ===== RESET EMERGENZA DOOMSDAY ENGINE =====
echo Log: %LOG%
echo.

REM --- 1. Kill bot (PID file) -----------------------------------------
echo [1/5] Kill bot (PID file)...
echo [1/5] Kill bot PID file >> "%LOG%"
if exist "data\bot.pid" (
    for /f %%i in (data\bot.pid) do (
        echo     kill PID=%%i
        taskkill /F /PID %%i >> "%LOG%" 2>&1
    )
    del "data\bot.pid" >nul 2>nul
) else (
    echo     bot.pid non trovato
)

REM --- 2. Kill bot (python main.py via CIM) ---------------------------
echo [2/5] Kill python main.py orfani...
echo [2/5] Kill python CIM >> "%LOG%"
powershell -NoProfile -Command "@('python.exe','py.exe') | ForEach-Object { $n=$_; try { Get-CimInstance Win32_Process -Filter ('Name='''+$n+'''') | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -notlike '*-m uvicorn*' -and $_.CommandLine -notlike '*claude-bridge*' } | ForEach-Object { Write-Host ('  killed '+$n+' PID='+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue } } catch { Write-Host ('  errore: '+$_.Exception.Message) } }" 2>&1 >> "%LOG%"
timeout /t 3 /nobreak >nul

REM --- 3. Shutdown tutte le istanze MuMu (0-11) ----------------------
echo [3/5] Shutdown istanze MuMu...
echo [3/5] Shutdown istanze MuMu >> "%LOG%"
set MUMU_MGR=C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe
for /L %%i in (0,1,11) do (
    "%MUMU_MGR%" control -v %%i shutdown >> "%LOG%" 2>nul
)
echo     Istanze MuMu spente
timeout /t 2 /nobreak >nul

REM --- 4. Reset ADB server ---------------------------------------------
echo [4/5] Reset ADB server...
echo [4/5] ADB kill-server >> "%LOG%"
"%ADB%" kill-server >> "%LOG%" 2>&1
echo     OK

REM --- 5. Cancella checkpoint e planned_order -------------------------
echo [5/6] Cancella checkpoint...
echo [5/6] Cancella checkpoint >> "%LOG%"
if exist "last_checkpoint.json" (
    del "last_checkpoint.json" && echo     last_checkpoint.json cancellato
) else ( echo     last_checkpoint.json non presente )
if exist "data\scheduler_planned_order.json" (
    del "data\scheduler_planned_order.json" && echo     scheduler_planned_order.json cancellato
) else ( echo     scheduler_planned_order.json non presente )

REM --- 6. Disabilita adaptive_scheduler in runtime_overrides ----------
echo [6/6] Disabilita adaptive_scheduler...
echo [6/6] Disabilita adaptive_scheduler >> "%LOG%"
powershell -NoProfile -Command "try { $f='%ROOT%\config\runtime_overrides.json'; $j = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json; $j.globali.adaptive_scheduler_enabled = $false; $j.globali.adaptive_scheduler_shadow_only = $true; $j | ConvertTo-Json -Depth 20 | Set-Content $f -Encoding UTF8; Write-Host '    OK' } catch { Write-Host ('    ERRORE: ' + $_.Exception.Message) }" 2>&1 >> "%LOG%"

echo.
echo ===== Cleanup OK — avvio bot in 3s... =====
echo Cleanup OK >> "%LOG%"
timeout /t 3 /nobreak >nul

REM --- Avvio bot -------------------------------------------------------
echo.
echo Avvio: py -3.14 main.py --no-dashboard --use-runtime
echo Avvio bot >> "%LOG%"
py -3.14 main.py --no-dashboard --use-runtime

echo.
echo ===== Bot uscito (exit code %ERRORLEVEL%) =====
echo ===== Bot uscito exit=%ERRORLEVEL% >> "%LOG%"
echo Log: %LOG%
echo.
pause
