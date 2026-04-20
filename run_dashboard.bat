@echo off
REM ============================================================
REM  Doomsday Engine V6 — Avvio Dashboard
REM  Porta: 8765  |  URL: http://localhost:8765/
REM  Modifica PYTHON_EXE se il path cambia.
REM ============================================================

SET PYTHON_EXE=C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe
SET ROOT=C:\doomsday-engine

cd /d "%ROOT%"
echo [DASHBOARD] Avvio su http://localhost:8765/
echo [DASHBOARD] Swagger API: http://localhost:8765/docs
echo [DASHBOARD] Premi Ctrl+C per fermare.
echo.

"%PYTHON_EXE%" -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765

pause
