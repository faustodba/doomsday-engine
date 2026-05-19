@echo off
:: ============================================================
::  Doomsday Engine V6 — Setup avvio automatico Telegram Bot
::
::  Crea il task in \DoomsDayScheduler\DoomsdayTelegramBot con:
::  - Trigger:   accesso utente Fausto (AtLogOn)
::  - Delay:     60 secondi dopo il login
::  - Utente:    Fausto (Interactive — sessione utente, no password)
::  - Privilegi: massimi (RunLevel Highest)
::  - Restart:   automatico su crash (3x ogni 1 min)
::
::  NOTA IMPORTANTE: LogonType=Interactive (era S4U) e trigger AtLogOn
::  (era AtStartup). Questo garantisce che il bot giri in Session 1
::  (desktop interattivo) e possa aprire console visibili — necessario
::  per /avvia_tutto che lancia run_prod.bat e run_dashboard_prod.bat.
::  Con S4U/Session 0 i processi figli non potevano interagire col desktop.
::
::  ESEGUIRE UNA SOLA VOLTA come amministratore.
::  Per rimuovere:  setup_telegram_autostart.bat --remove
:: ============================================================
setlocal

set TASK_NAME=DoomsdayTelegramBot
set TASK_PATH=\DoomsDayScheduler\
set BAT_PATH=C:\doomsday-engine-prod\run_telegram_prod.bat

if "%1"=="--remove" goto remove

echo.
echo === Registrazione Task Scheduler: %TASK_PATH%%TASK_NAME% ===
echo Bat: %BAT_PATH%
echo Utente: Fausto (Interactive - sessione desktop, avvio al login)
echo.

if not exist "%BAT_PATH%" (
    echo ERRORE: %BAT_PATH% non trovato.
    echo Esegui prima sync_prod.bat per copiare i file in produzione.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$action   = New-ScheduledTaskAction -Execute '%BAT_PATH%' -WorkingDirectory 'C:\doomsday-engine-prod';" ^
    "$trigger  = New-ScheduledTaskTrigger -AtLogOn -User 'Fausto';" ^
    "$trigger.Delay = 'PT1M';" ^
    "$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable $true;" ^
    "$principal = New-ScheduledTaskPrincipal -UserId 'Fausto' -LogonType Interactive -RunLevel Highest;" ^
    "Register-ScheduledTask -TaskName '%TASK_NAME%' -TaskPath '%TASK_PATH%' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force;" ^
    "Write-Output 'Task registrato OK'"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERRORE. Assicurati di eseguire come amministratore.
    pause
    exit /b 1
)

echo.
echo === Task creato con successo ===
echo Percorso: %TASK_PATH%%TASK_NAME%
echo Il Telegram bot si avviera' automaticamente al login dell'utente Fausto.
echo.
echo Per avviarlo subito:
echo   schtasks /run /tn "%TASK_PATH%%TASK_NAME%"
echo.
echo Per verificare:
echo   schtasks /query /tn "%TASK_PATH%%TASK_NAME%" /fo LIST
echo.
pause
exit /b 0

:remove
echo.
echo === Rimozione: %TASK_PATH%%TASK_NAME% ===
schtasks /delete /tn "%TASK_PATH%%TASK_NAME%" /f
if %ERRORLEVEL% EQU 0 (
    echo Task rimosso.
) else (
    echo Task non trovato o errore.
)
echo.
pause
exit /b 0
