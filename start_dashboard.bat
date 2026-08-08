@echo off
setlocal
cd /d "%~dp0"

set "MPLCONFIGDIR=%~dp0.cache\matplotlib"
if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"

python -c "import streamlit, pandas, matplotlib" >nul 2>&1
if errorlevel 1 (
    echo Missing dashboard dependencies.
    echo Install them with: python -m pip install streamlit pandas matplotlib
    pause
    exit /b 1
)

echo Starting Manufacturing Quality Dashboard...
echo URL: http://localhost:8501
echo Press Ctrl+C to stop the server.
echo.

python -m streamlit run app.py --browser.gatherUsageStats false --server.showEmailPrompt false

if errorlevel 1 (
    echo.
    echo Dashboard startup failed. Review the error above.
    pause
)

endlocal
