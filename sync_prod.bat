@echo off
REM ============================================================================
REM  sync_prod.bat — Sync dev -> prod SENZA prompt interattivi
REM
REM  Uso: sync_prod.bat
REM  Copia .py di core/tasks/shared/config/monitor, radar_tool/, main.py,
REM  ROADMAP.md. Non tocca runtime.json, instances.json, state/, logs/.
REM
REM  Differenze da release_prod.bat:
REM   - no conferma interattiva (pause)
REM   - no messaggi iniziali
REM   - exit code != 0 se xcopy fallisce
REM ============================================================================
setlocal

set SRC=C:\doomsday-engine
set DST=C:\doomsday-engine-prod

echo [sync] %SRC% -> %DST%

xcopy /Y /Q "%SRC%\core\*.py"       "%DST%\core\"       || goto :err
xcopy /Y /Q "%SRC%\tasks\*.py"      "%DST%\tasks\"      || goto :err
xcopy /Y /Q "%SRC%\shared\*.py"     "%DST%\shared\"     || goto :err
xcopy /Y /Q "%SRC%\config\*.py"     "%DST%\config\"     || goto :err
xcopy /Y /Q "%SRC%\monitor\*.py"    "%DST%\monitor\"    || goto :err
xcopy /Y /E /Q "%SRC%\radar_tool\"  "%DST%\radar_tool\" || goto :err
xcopy /Y /Q "%SRC%\main.py"         "%DST%\"            || goto :err
xcopy /Y /Q "%SRC%\ROADMAP.md"      "%DST%\"            || goto :err

echo [sync] OK — ricorda di riavviare il bot in prod
exit /b 0

:err
echo [sync] ERRORE xcopy — ABORT
exit /b 1
