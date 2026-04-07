@echo off
chcp 65001 >nul
title DEBUG - YouTube Video Generator

set "APP_DIR=%~dp0"
set "VENV_PY=%APP_DIR%venv\Scripts\python.exe"
set "VENV_PATH_FILE=%APP_DIR%venv_path.txt"

if exist "%VENV_PATH_FILE%" (
    set /p CUSTOM_VENV=<"%VENV_PATH_FILE%"
    set "VENV_PY=%CUSTOM_VENV%\Scripts\python.exe"
)

echo Python: %VENV_PY%
echo.

if not exist "%VENV_PY%" (
    echo ERROR: venv not found. Run SETUP.bat first.
    pause
    exit /b 1
)

echo Running app...
echo ─────────────────────────────────────────
"%VENV_PY%" "%APP_DIR%main.py" 2>&1
echo ─────────────────────────────────────────
echo.
echo App exited. See error above if any.
pause
