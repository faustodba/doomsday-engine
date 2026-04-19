@echo off
setlocal

set SRC=C:\doomsday-engine
set DST=C:\doomsday-engine-prod

echo ============================================
echo  RELEASE PRODUZIONE
echo  SRC: %SRC%
echo  DST: %DST%
echo ============================================
echo.
echo Premi INVIO per procedere o CTRL+C per annullare.
pause

xcopy /Y /Q "%SRC%\core\*.py"       "%DST%\core\"
xcopy /Y /Q "%SRC%\tasks\*.py"      "%DST%\tasks\"
xcopy /Y /Q "%SRC%\shared\*.py"     "%DST%\shared\"
xcopy /Y /Q "%SRC%\config\*.py"     "%DST%\config\"
xcopy /Y /Q "%SRC%\monitor\*.py"    "%DST%\monitor\"
xcopy /Y /E /Q "%SRC%\radar_tool\"  "%DST%\radar_tool\"
xcopy /Y /Q "%SRC%\main.py"         "%DST%\"
xcopy /Y /Q "%SRC%\ROADMAP.md"      "%DST%\"

echo.
echo ============================================
echo  FATTO — verifica ROADMAP.md poi riavvia bot
echo ============================================
pause
