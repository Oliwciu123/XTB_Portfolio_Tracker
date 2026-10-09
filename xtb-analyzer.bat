@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

if not exist "%PY%" (
  echo Pierwsze uruchomienie: tworze srodowisko w tym folderze...
  where py >nul 2>&1
  if %errorlevel%==0 (
    py -3 -m venv "%VENV%"
  ) else (
    python -m venv "%VENV%"
  )
  if not exist "%PY%" (
    echo Nie znaleziono Python 3. Zainstaluj go ze strony python.org i uruchom ten plik ponownie.
    pause
    exit /b 1
  )
)

"%PY%" -c "import webview, tkinterdnd2" >nul 2>&1
if %errorlevel% NEQ 0 (
  echo Instaluje okno raportu w .venv tego folderu. To moze potrwac kilka minut...
  "%PY%" -m pip install -e "%ROOT%."
  if %errorlevel% NEQ 0 (
    echo Instalacja nie powiodla sie. W tym folderze mozesz sprobowac recznie: pip install -e .
    pause
    exit /b 1
  )
)

set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
if exist "%PYW%" (
  start "" "%PYW%" -m xtb_analyzer.desktop
) else (
  start "" "%PY%" -m xtb_analyzer.desktop
)
exit /b 0
