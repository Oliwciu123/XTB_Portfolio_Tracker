@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m xtb_analyzer.desktop
  exit /b 0
)
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw -m xtb_analyzer.desktop
  exit /b 0
)
where pyw >nul 2>&1
if %errorlevel%==0 (
  start "" pyw -3 -m xtb_analyzer.desktop
  exit /b 0
)
echo Nie znaleziono Python. Zainstaluj Python 3 ze strony python.org, potem w tym folderze:
echo   pip install -e .
pause
