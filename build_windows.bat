@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Building XTB Portfolio Analyzer with uv...
uv run --locked --extra desktop --extra build python packaging\build_release.py
if errorlevel 1 goto :error
if /I not "%CI%"=="true" (
    uv run --locked python scripts\create_desktop_shortcut.py
)
echo Ready: dist\XTBPortfolioAnalyzer-Windows.zip
pause
exit /b 0
:error
echo Build failed. Install uv and check the details above.
pause
exit /b 1
