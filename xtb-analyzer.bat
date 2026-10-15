@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Prefer the portable one-folder build (no Python required on the PC).
if exist "%~dp0dist\XTBPortfolioAnalyzer\XTBPortfolioAnalyzer.exe" (
  start "" "%~dp0dist\XTBPortfolioAnalyzer\XTBPortfolioAnalyzer.exe"
  exit /b 0
)
if exist "%~dp0XTBPortfolioAnalyzer\XTBPortfolioAnalyzer.exe" (
  start "" "%~dp0XTBPortfolioAnalyzer\XTBPortfolioAnalyzer.exe"
  exit /b 0
)

echo Nie znaleziono zbudowanej aplikacji przenosnej.
echo.
echo Na Windows zbuduj ja raz:
echo   build_windows.bat
echo Potem skopiuj folder dist\XTBPortfolioAnalyzer (USB / do kolegi)
echo i uruchom XTBPortfolioAnalyzer.exe albo Uruchom.bat.
echo.
echo Opcja deweloperska (wymaga Pythona w PATH):
echo   python -m xtb_analyzer.desktop
echo.
set /p DEV=Uruchomic tryb deweloperski teraz? [t/N] 
if /I not "%DEV%"=="t" if /I not "%DEV%"=="y" exit /b 1

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

if not exist "%PY%" (
  echo Tworze .venv ...
  where py >nul 2>&1
  if %errorlevel%==0 (
    py -3 -m venv "%VENV%"
  ) else (
    python -m venv "%VENV%"
  )
  if not exist "%PY%" (
    echo Nie znaleziono Python 3. Zainstaluj z python.org albo uruchom build_windows.bat.
    pause
    exit /b 1
  )
)

"%PY%" -c "import webview, tkinterdnd2" >nul 2>&1
if %errorlevel% NEQ 0 (
  echo Instaluje zaleznosci do .venv ...
  "%PY%" -m pip install -e "%~dp0."
  if %errorlevel% NEQ 0 (
    echo Instalacja nie powiodla sie.
    pause
    exit /b 1
  )
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
if exist "%PYW%" (
  start "" "%PYW%" -m xtb_analyzer.desktop
) else (
  start "" "%PY%" -m xtb_analyzer.desktop
)
exit /b 0
