@echo off
chcp 65001 >nul
title DEBUG - YouTube Video Generator

set "APP_DIR=%~dp0"
set "VENV_PY=%APP_DIR%venv\Scripts\python.exe"
set "VENV_PATH_FILE=%APP_DIR%venv_path.txt"

echo =============================================
echo  DEBUG - YouTube Video Generator
echo =============================================
echo.
echo App folder: %APP_DIR%
echo.

:: Check venv_path.txt
if exist "%VENV_PATH_FILE%" (
    set /p CUSTOM_VENV=<"%VENV_PATH_FILE%"
    echo venv_path.txt found: %CUSTOM_VENV%
    set "VENV_PY=%CUSTOM_VENV%\Scripts\python.exe"
) else (
    echo venv_path.txt: not found, using default path
)

echo Python path: %VENV_PY%
echo.

:: Check if python exists
if not exist "%VENV_PY%" (
    echo ERROR: Python not found at: %VENV_PY%
    echo.
    echo SOLUTION: Run SETUP.bat again and wait until it says INSTALLATION COMPLETE
    echo.
    if exist "%APP_DIR%setup_log.txt" (
        echo --- setup_log.txt ---
        type "%APP_DIR%setup_log.txt"
    )
    echo.
    pause
    exit /b 1
)

echo Python found OK
echo.
echo =============================================
echo  Starting app...
echo =============================================
echo.

"%VENV_PY%" "%APP_DIR%main.py" 2>&1

echo.
echo =============================================
echo  App stopped. See errors above if any.
echo =============================================
pause
