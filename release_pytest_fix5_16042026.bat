@echo off
REM ==============================================================================
REM  DOOMSDAY ENGINE V6 — Release 16/04/2026 #10
REM  Fix pytest round 5:
REM  - test_orchestrator: StubTask schedule_type/interval_hours + e.task.name()
REM  - test_boost: FakeState con BoostState
REM  - test_rifornimento: schedule_type/interval_hours callable-safe
REM
REM  ISTRUZIONI: copiare i file scaricati direttamente in C:\doomsday-engine
REM  prima di eseguire questo bat, oppure modificare FILE_DIR qui sotto.
REM ==============================================================================

REM === MODIFICA QUI SE I FILE SONO IN ALTRA CARTELLA ===
set FILE_DIR=C:\doomsday-engine
set ROOT=C:\doomsday-engine

echo [1/5] Copia file...
copy /Y "%FILE_DIR%\test_orchestrator.py" "%ROOT%\tests\unit\test_orchestrator.py"
copy /Y "%FILE_DIR%\test_boost.py"        "%ROOT%\tests\tasks\test_boost.py"
copy /Y "%FILE_DIR%\test_rifornimento.py" "%ROOT%\tests\tasks\test_rifornimento.py"

echo [2/5] git add...
cd /d "%ROOT%"
git add tests\unit\test_orchestrator.py
git add tests\tasks\test_boost.py tests\tasks\test_rifornimento.py

echo [3/5] git commit...
git commit -m "fix: pytest round5 StubTask schedule_type + FakeState.boost + callable-safe 16/04/2026"

echo [4/5] git push...
git push origin main

echo [5/5] Done.
pause
