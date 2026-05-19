@echo off
:: ============================================================
::  Doomsday Engine V6 — Setup avvio automatico Telegram Bot
::
::  Registra il Telegram bot nel Task Scheduler di Windows:
::  - Trigger: all'avvio del sistema (onstart) — NO login richiesto
::  - Delay:   60 secondi dopo l'avvio (attende rete)
::  - Utente:  SYSTEM (processo in background, sempre attivo)
::  - Restart: automatico su fallimento (ogni 30s, max 3 volte)
::
::  ESEGUIRE UNA SOLA VOLTA come amministratore.
::  Per rimuovere:  setup_telegram_autostart.bat --remove
:: ============================================================
setlocal

set TASK_NAME=DoomsdayTelegramBot
set BAT_PATH=C:\doomsday-engine-prod\run_telegram_prod.bat

if "%1"=="--remove" goto remove

echo.
echo === Registrazione Task Scheduler: %TASK_NAME% ===
echo Bat: %BAT_PATH%
echo Utente: SYSTEM (avvio senza login)
echo.

:: Verifica che il bat esista
if not exist "%BAT_PATH%" (
    echo ERRORE: %BAT_PATH% non trovato.
    echo Esegui prima sync_prod.bat per copiare i file in produzione.
    pause
    exit /b 1
)

:: Crea il task (onstart, delay 1 min, utente SYSTEM, no login richiesto)
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%BAT_PATH%\"" ^
    /sc onstart ^
    /delay 0001:00 ^
    /ru SYSTEM ^
    /f

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERRORE nella creazione del task. Riprova come amministratore.
    pause
    exit /b 1
)

echo.
echo === Task creato con successo ===
echo Il Telegram bot si avviera' automaticamente al prossimo avvio del PC.
echo NON richiede login utente (gira come SYSTEM).
echo.
echo Per avviarlo subito senza riavviare:
echo   schtasks /run /tn "%TASK_NAME%"
echo.
echo Per verificare lo stato:
echo   schtasks /query /tn "%TASK_NAME%" /fo LIST
echo.
pause
exit /b 0

:remove
echo.
echo === Rimozione Task Scheduler: %TASK_NAME% ===
schtasks /delete /tn "%TASK_NAME%" /f
if %ERRORLEVEL% EQU 0 (
    echo Task rimosso con successo.
) else (
    echo Task non trovato o errore durante la rimozione.
)
echo.
pause
exit /b 0
