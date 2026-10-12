@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "LOG=%ROOT%install-error.txt"

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
  del /q "%LOG%" >nul 2>&1
  "%PY%" -m pip install --upgrade pip setuptools wheel > "%LOG%" 2>&1
  if errorlevel 1 goto :install_failed
  "%PY%" -m pip install -e "%ROOT%." >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo Edytowalna instalacja nie powiodla sie. Instaluje zaleznosci do .venv...
    "%PY%" -m pip install "pandas>=2.0" "numpy>=1.24" "yfinance>=0.2" "matplotlib>=3.7" "plotly>=5.18" "requests>=2.31" "openpyxl>=3.1" "ipykernel>=6.25" "ipywidgets>=8.0" "notebook>=7.0" "pywebview>=5.1" "tkinterdnd2>=0.4" >> "%LOG%" 2>&1
    if errorlevel 1 goto :install_failed
  )
  "%PY%" -c "import webview, tkinterdnd2" >> "%LOG%" 2>&1
  if errorlevel 1 goto :install_failed
  del /q "%LOG%" >nul 2>&1
)

set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
if exist "%PYW%" (
  start "" "%PYW%" -m xtb_analyzer.desktop
) else (
  start "" "%PY%" -m xtb_analyzer.desktop
)
exit /b 0

:install_failed
echo.
echo Instalacja nie powiodla sie.
echo Pelny log pip jest w pliku:
echo %LOG%
echo.
pause
exit /b 1
