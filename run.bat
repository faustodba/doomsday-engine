@echo off
REM Launcher Doomsday Engine V6
REM Uso: run.bat --istanze FAU_01 --tick-sleep 10

SET PYTHON=C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe
SET ROOT=C:\doomsday-engine

cd /d %ROOT%
"%PYTHON%" main.py %*
