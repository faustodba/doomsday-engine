@echo off
cd /d C:\doomsday-engine
set PYTHONIOENCODING=utf-8
py -3.14 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8766 --reload
pause
