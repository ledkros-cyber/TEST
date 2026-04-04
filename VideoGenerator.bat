@echo off
chcp 65001 >nul
title YouTube Video Generator

set "APP_DIR=%~dp0"
set "VENV_PY=%APP_DIR%venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Программа не установлена.
    echo Сначала запустите SETUP.bat
    pause
    exit /b 1
)

"%VENV_PY%" "%APP_DIR%main.py"
