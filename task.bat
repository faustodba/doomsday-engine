@echo off
REM Launcher task isolato — Doomsday Engine V6
REM Uso: task.bat --istanza FAU_00 --task boost
REM      task.bat --istanza FAU_00 --task zaino --force
REM      task.bat --istanza FAU_00 --task zaino --dry-run

SET PYTHON=C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe
SET ROOT=C:\doomsday-engine

cd /d %ROOT%
"%PYTHON%" run_task.py %*
