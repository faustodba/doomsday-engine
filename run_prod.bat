@echo off
cd /d C:\doomsday-engine-prod
set PYTHONIOENCODING=utf-8
set DOOMSDAY_ROOT=C:\doomsday-engine-prod
py -3.14 main.py --tick-sleep 60 --no-dashboard --use-runtime --resume
pause
