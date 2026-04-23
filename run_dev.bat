@echo off
cd /d C:\doomsday-engine
set PYTHONIOENCODING=utf-8
py -3.14 main.py --tick-sleep 60 --dry-run
pause
