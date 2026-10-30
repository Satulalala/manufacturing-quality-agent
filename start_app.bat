@echo off
setlocal
cd /d "%~dp0"

set "QUALITY_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "QUALITY_PYTHON=%~dp0.venv\Scripts\python.exe"

"%QUALITY_PYTHON%" -c "import fastapi, multipart, pandas, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Missing API dependencies.
    echo Install them with: %QUALITY_PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "%~dp0frontend\dist\index.html" (
    where node >nul 2>&1
    if errorlevel 1 (
        echo Node.js is required to build the new workbench for the first launch.
        echo Install Node.js, then run start_app.bat again.
        pause
        exit /b 1
    )
    pushd "%~dp0frontend"
    if not exist "node_modules" (
        echo Installing frontend packages...
        call npm.cmd ci
        if errorlevel 1 (
            popd
            pause
            exit /b 1
        )
    )
    echo Building the Agent workbench...
    call npm.cmd run build
    if errorlevel 1 (
        popd
        pause
        exit /b 1
    )
    popd
)

echo Starting the local Agent workbench...
"%QUALITY_PYTHON%" -m server.launcher
if errorlevel 1 (
    echo.
    echo Startup failed. Review the error above.
    pause
)

endlocal
