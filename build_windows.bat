@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo === Budowa aplikacji XTB Portfolio Analyzer (Windows) ===
echo Tworzenie przenosnego folderu dist\XTBPortfolioAnalyzer ...
echo.

where py >nul 2>&1
if %errorlevel%==0 (
  set "PYLAUNCHER=py -3"
) else (
  where python >nul 2>&1
  if %errorlevel% NEQ 0 (
    echo Nie znaleziono Python 3. Zainstaluj z https://www.python.org/downloads/
    echo Zaznacz "Add python.exe to PATH", potem uruchom ten plik ponownie.
    pause
    exit /b 1
  )
  set "PYLAUNCHER=python"
)

set "VENV=%~dp0.venv-build"
if not exist "%VENV%\Scripts\python.exe" (
  echo Tworze srodowisko budowania .venv-build ...
  %PYLAUNCHER% -m venv "%VENV%"
  if not exist "%VENV%\Scripts\python.exe" (
    echo Nie udalo sie utworzyc venv.
    pause
    exit /b 1
  )
)

set "PY=%VENV%\Scripts\python.exe"
echo Instaluje zaleznosci i PyInstaller ...
"%PY%" -m pip install -U pip
"%PY%" -m pip install -e ".[dev]" pyarrow pyinstaller
if %errorlevel% NEQ 0 (
  echo Instalacja nie powiodla sie.
  pause
  exit /b 1
)

echo Zamykam ewentualnie uruchomiona aplikacje i czyszcze poprzedni build ...
taskkill /F /IM XTBPortfolioAnalyzer.exe >nul 2>&1
if exist "%~dp0build" rmdir /S /Q "%~dp0build"
if exist "%~dp0dist\XTBPortfolioAnalyzer" rmdir /S /Q "%~dp0dist\XTBPortfolioAnalyzer"

echo Buduje aplikacje dist\XTBPortfolioAnalyzer ...
"%PY%" -m PyInstaller --noconfirm --clean packaging\xtb_portfolio_analyzer.spec
if %errorlevel% NEQ 0 (
  echo PyInstaller zakonczyl sie bledem.
  pause
  exit /b 1
)

copy /Y "%~dp0src\xtb_analyzer\assets\app.ico" "%~dp0dist\XTBPortfolioAnalyzer\app.ico" >nul 2>&1

echo.
echo Gotowe! Aplikacja znajduje sie w:
echo   %~dp0dist\XTBPortfolioAnalyzer\XTBPortfolioAnalyzer.exe
echo.
pause
exit /b 0
