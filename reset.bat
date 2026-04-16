@echo off
REM Reset schedule task — Doomsday Engine V6
REM Uso: reset.bat --istanza FAU_00 --task store

SET PYTHON=C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe
SET ROOT=C:\doomsday-engine

cd /d %ROOT%
"%PYTHON%" reset_schedule.py %*
