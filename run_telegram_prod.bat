@echo off
:: ============================================================
::  Doomsday Engine V6 — Telegram Bot Service
::  Processo STANDALONE, indipendente da dashboard e bot.
::  Auto-restart su crash (loop infinito con delay 10s).
::  Log: C:\doomsday-engine-prod\logs\telegram_service.log
::
::  Avvio manuale:   doppio click o run_telegram_prod.bat
::  Avvio automatico: setup_telegram_autostart.bat (Task Scheduler)
::  Stop:            chiudi la finestra o Ctrl+C
:: ============================================================
setlocal

set ROOT=C:\doomsday-engine-prod
set PYTHONPATH=%ROOT%
set DOOMSDAY_ROOT=%ROOT%
set PYTHONUNBUFFERED=1

cd /d %ROOT%

if not exist logs mkdir logs

:loop
echo.
echo [%DATE% %TIME%] Avvio Telegram bot service...
python -u core\telegram_bot.py
set EXIT_CODE=%ERRORLEVEL%
echo [%DATE% %TIME%] Telegram bot terminato (exit=%EXIT_CODE%). Riavvio in 10s...
timeout /t 10 /nobreak > nul
goto loop
