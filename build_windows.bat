@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo === Budowa przenosnej aplikacji XTB Portfolio Analyzer (Windows) ===
echo Jednorazowy krok na komputerze z Pythonem 3.10+. Po zbudowaniu
echo kopiujesz folder dist\XTBPortfolioAnalyzer na USB / do kolegi.
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

echo Buduje one-folder exe ...
"%PY%" -m PyInstaller --noconfirm --clean packaging\xtb_portfolio_analyzer.spec
if %errorlevel% NEQ 0 (
  echo PyInstaller zakonczyl sie bledem.
  pause
  exit /b 1
)

copy /Y "%~dp0packaging\Uruchom.bat" "%~dp0dist\XTBPortfolioAnalyzer\Uruchom.bat" >nul
copy /Y "%~dp0src\xtb_analyzer\assets\app.ico" "%~dp0dist\XTBPortfolioAnalyzer\app.ico" >nul 2>&1

echo.
echo Gotowe.
echo Skopiuj CALY folder:
echo   %~dp0dist\XTBPortfolioAnalyzer
echo na USB albo do innego komputera, potem dwuklik:
echo   XTBPortfolioAnalyzer.exe
echo   albo Uruchom.bat
echo Nie potrzeba Pythona na komputerze docelowym.
echo Internet jest potrzebny do notowan (Yahoo) i kursow NBP.
echo.
pause
exit /b 0
