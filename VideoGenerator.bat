@echo off
chcp 65001 >nul
title YouTube Video Generator

set "APP_DIR=%~dp0"
set "VENV_PY=%APP_DIR%venv\Scripts\python.exe"
set "VENV_PATH_FILE=%APP_DIR%venv_path.txt"

:: Check if venv is in a custom location (non-ASCII path case)
if exist "%VENV_PATH_FILE%" (
    set /p CUSTOM_VENV=<"%VENV_PATH_FILE%"
    set "VENV_PY=%CUSTOM_VENV%\Scripts\python.exe"
)

if not exist "%VENV_PY%" (
    echo Program is not installed. Please run SETUP.bat first.
    pause
    exit /b 1
)

"%VENV_PY%" "%APP_DIR%main.py"
