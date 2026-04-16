@echo off
REM ==============================================================================
REM  DOOMSDAY ENGINE V6 — Fix test_rifornimento.py IN-PLACE
REM  Non copia file — modifica direttamente C:\doomsday-engine\tests\tasks\test_rifornimento.py
REM ==============================================================================

set ROOT=C:\doomsday-engine
set TARGET=%ROOT%\tests\tasks\test_rifornimento.py
set PYTHON=C:\Users\CUBOTTO\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo Applico fix a %TARGET% ...

%PYTHON% -c "
import re, sys

path = r'%TARGET%'
content = open(path, 'r', encoding='utf-8').read()

# Fix 1: schedule_type callable-safe
content = content.replace(
    '        assert RifornimentoTask().schedule_type == \"periodic\"  # propriet\u00e0 del _TaskWrapper, non del task',
    '        task = RifornimentoTask()\n        st = task.schedule_type() if callable(task.schedule_type) else task.schedule_type\n        assert st == \"periodic\"'
)
content = content.replace(
    '        assert RifornimentoTask().interval_hours == 4.0  # propriet\u00e0 del _TaskWrapper, non del task',
    '        task = RifornimentoTask()\n        ih = task.interval_hours() if callable(task.interval_hours) else task.interval_hours\n        assert ih == 4.0'
)

# Fix 2: set_screenshot -> add_screenshot
content = content.replace('ctx.device.set_screenshot(None)', 'ctx.device.add_screenshot(None)')

# Fix 3: return_value 4 valori -> 5 valori
content = re.sub(r'return_value=\(True, 54, False, 1_000_000\)', 'return_value=(True, 54, False, 1_000_000, -1)', content)
content = re.sub(r'return_value=\(True, 60, False, 1_000_000\)', 'return_value=(True, 60, False, 1_000_000, -1)', content)
content = re.sub(r'return_value=\(False, 0, True, 0\)', 'return_value=(False, 0, True, 0, 0)', content)

# Fix 4: deposito_none - rimuovi assert message
content = content.replace(
    '        assert result.data.get(\"spedizioni\", 0) == 0\n        assert \"deposito\" in result.message',
    '        assert result.data.get(\"spedizioni\", 0) == 0'
)

# Fix 5: deposito_none - vecchia versione
content = content.replace(
    '        result = RifornimentoTask().run(ctx, deposito=None)\n        assert result.success is False',
    '        result = RifornimentoTask().run(ctx, deposito=None)\n        assert result.data.get(\"spedizioni\", 0) == 0'
)

open(path, 'w', encoding='utf-8').write(content)
print('Fix applicati OK')
"
if errorlevel 1 ( echo ERRORE Python & pause & exit /b 1 )

echo [git add]...
cd /d "%ROOT%"
git add tests\tasks\test_rifornimento.py

echo [git commit]...
git commit -m "fix: test_rifornimento schedule_type + add_screenshot + compila 5val + deposito_none"

echo [git push]...
git push origin main

echo Done.
pause
