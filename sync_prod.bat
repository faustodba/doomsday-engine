@echo off
REM ============================================================================
REM  sync_prod.bat — Sync dev -> prod SENZA prompt interattivi
REM
REM  Uso: sync_prod.bat
REM
REM  COSA VIENE SINCRONIZZATO (codice + schema scheduler):
REM    - core/*.py        : logica core (orchestrator, logger, state, navigator...)
REM    - tasks/*.py       : implementazione dei task
REM    - shared/*.py      : utility condivise (OCR, template matcher, helpers)
REM    - config/*.py      : loader e validazione configurazione
REM    - config/task_setup.json : schema scheduler (priorita', intervalli, schedule)
REM                                aggiornato in dev e propagato a prod come codice
REM    - monitor/*.py     : MCP server log analysis
REM    - radar_tool/      : sottomodulo radar
REM    - dashboard/       : intera dashboard FastAPI (py + templates + static)
REM    - main.py
REM    - ROADMAP.md
REM    - run_prod.bat, run_dashboard_prod.bat : launcher produzione
REM
REM  BLACKLIST — NON SINCRONIZZATI (configurazione runtime specifica per ambiente):
REM    - config/instances.json          : anagrafica fisica istanze MuMu,
REM                                        puo' divergere tra dev (test) e prod
REM    - config/global_config.json      : parametri scritti dalla dashboard prod;
REM                                        dev ne ha una copia di sviluppo
REM    - config/runtime_overrides.json  : override runtime (abilitata, truppe,
REM                                        task flags) modificati dalla dashboard
REM    - state/                         : stato persistente per-istanza (schedule,
REM                                        rifornimento, raccolta) scritto dal bot
REM    - logs/                          : log prod (jsonl per istanza, bot.log)
REM    - engine_status.json             : snapshot live scritto dal bot prod
REM    - *.bak                          : backup rotazione
REM
REM  Differenze da release_prod.bat:
REM    - no conferma interattiva (pause)
REM    - no messaggi iniziali
REM    - exit code != 0 se xcopy fallisce
REM ============================================================================
setlocal

set SRC=C:\doomsday-engine
set DST=C:\doomsday-engine-prod

echo [sync] %SRC% -^> %DST%

REM --- Codice Python ---
xcopy /Y /Q "%SRC%\core\*.py"                  "%DST%\core\"       || goto :err
xcopy /Y /Q "%SRC%\tasks\*.py"                 "%DST%\tasks\"      || goto :err
xcopy /Y /Q "%SRC%\shared\*.py"                "%DST%\shared\"     || goto :err
xcopy /Y /Q "%SRC%\config\*.py"                "%DST%\config\"     || goto :err
xcopy /Y /Q "%SRC%\monitor\*.py"               "%DST%\monitor\"    || goto :err

REM --- Schema scheduler (codice, non configurazione runtime) ---
xcopy /Y /Q "%SRC%\config\task_setup.json"     "%DST%\config\"     || goto :err

REM --- Tool esterni e dashboard ---
xcopy /Y /E /Q "%SRC%\radar_tool\"              "%DST%\radar_tool\" || goto :err
xcopy /Y /E /Q "%SRC%\dashboard\"               "%DST%\dashboard\"  || goto :err

REM --- Entry point + documentazione ---
xcopy /Y /Q "%SRC%\main.py"                    "%DST%\"            || goto :err
xcopy /Y /Q "%SRC%\ROADMAP.md"                 "%DST%\"            || goto :err

REM --- Launcher produzione ---
xcopy /Y /Q "%SRC%\run_prod.bat"               "%DST%\"            || goto :err
xcopy /Y /Q "%SRC%\run_dashboard_prod.bat"     "%DST%\"            || goto :err

echo [sync] OK — ricorda di riavviare il bot in prod
exit /b 0

:err
echo [sync] ERRORE xcopy — ABORT
exit /b 1
