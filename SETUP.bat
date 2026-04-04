@echo off
chcp 65001 >nul
title YouTube Video Generator - Ustanovka
color 0A

set "APP_DIR=%~dp0"
set "VENV_DIR=%APP_DIR%venv"
set "BIN_DIR=%APP_DIR%bin"
set "LOG=%APP_DIR%setup_log.txt"

echo. > "%LOG%"
echo ===== SETUP LOG ===== >> "%LOG%"

echo.
echo  ================================================
echo    YouTube Video Generator - Ustanovka
echo    Log sokhranitsya v: setup_log.txt
echo  ================================================
echo.

:: -----------------------------------------------
:: 1. Python
:: -----------------------------------------------
echo  [1/6] Proveryaem Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        Python ne nayden. Skachivaem Python 3.11...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python_setup.exe' -UseBasicParsing"
    if %errorlevel% neq 0 (
        echo.
        echo  OSHIBKA: Ne udalos skachat Python.
        echo  Skayte vruchnuyu: https://www.python.org/downloads/
        echo  Pri ustanovke stavte galochku: Add Python to PATH
        echo. >> "%LOG%"
        echo  OSHIBKA: skachat Python >> "%LOG%"
        goto :end_error
    )
    "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del "%TEMP%\python_setup.exe" >nul 2>&1
    echo        Python ustanovlen!
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do (
        echo        OK: %%v
        echo  Python: %%v >> "%LOG%"
    )
)

:: -----------------------------------------------
:: 2. Virtual environment
:: -----------------------------------------------
echo.
echo  [2/6] Sozdayom virtualnoe okruzhenie...
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo        Uzhe est, propuskaem.
) else (
    python -m venv "%VENV_DIR%" >> "%LOG%" 2>&1
    if %errorlevel% neq 0 (
        echo  OSHIBKA: Ne udalos sozdat venv. Sm. setup_log.txt
        type "%LOG%"
        goto :end_error
    )
    echo        OK: okruzhenie sozdano.
)

:: -----------------------------------------------
:: 3. pip upgrade
:: -----------------------------------------------
echo.
echo  [3/6] Obnovlyaem pip...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
echo        pip obnov1en.

:: -----------------------------------------------
:: 4. Dependencies  (bez --quiet chtoby videt progress)
:: -----------------------------------------------
echo.
echo  [4/6] Ustanavlivaem zavisimosti (mozhet zanyat 3-7 minut)...
echo        Smotrite progress nizhe:
echo.

"%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%requirements.txt" 2>> "%LOG%"
set PIP_ERR=%errorlevel%

echo. >> "%LOG%"
echo  pip exit code: %PIP_ERR% >> "%LOG%"

if %PIP_ERR% neq 0 (
    echo.
    echo  ================================================
    echo   OSHIBKA pri ustanovke zavisimostey!
    echo   Chitayte setup_log.txt - tam prichina oshibki.
    echo  ================================================
    echo.
    echo  --- Poslednie stroki loga ---
    powershell -NoProfile -Command "Get-Content '%LOG%' | Select-Object -Last 30"
    goto :end_error
)
echo.
echo  [4/6] Zavisimosti ustanovleny!

:: -----------------------------------------------
:: 5. FFmpeg
:: -----------------------------------------------
echo.
echo  [5/6] Proveryaem FFmpeg...

if exist "%BIN_DIR%\ffmpeg.exe" (
    echo        FFmpeg uzhe est, propuskaem.
) else (
    mkdir "%BIN_DIR%" >nul 2>&1
    echo        Skachivaem FFmpeg (mozhet zanyat 1-3 minuty)...

    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile '%TEMP%\ffmpeg.zip' -UseBasicParsing" >> "%LOG%" 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  Ne udalos skachat FFmpeg avtomaticheski.
        echo  Skayte vruchnuyu: https://ffmpeg.org/download.html
        echo  Raspakoyte ffmpeg.exe i ffprobe.exe v: %BIN_DIR%
        echo  Zatem zapustite SETUP.bat snova.
        goto :end_error
    )

    echo        Raspakovyvaem...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::OpenRead('%TEMP%\ffmpeg.zip'); foreach($e in $zip.Entries){ if($e.Name -eq 'ffmpeg.exe' -or $e.Name -eq 'ffprobe.exe'){ [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, '%BIN_DIR%\' + $e.Name, $true) } }; $zip.Dispose()" >> "%LOG%" 2>&1
    del "%TEMP%\ffmpeg.zip" >nul 2>&1
    echo        FFmpeg gotov!
)

:: -----------------------------------------------
:: 5b. GPU check
:: -----------------------------------------------
echo.
echo        Proveryaem NVIDIA NVENC...
if exist "%BIN_DIR%\ffmpeg.exe" (
    "%BIN_DIR%\ffmpeg.exe" -hide_banner -encoders 2>nul | findstr /C:"h264_nvenc" >nul
    if %errorlevel% equ 0 (
        echo        NVIDIA NVENC naydeno - apparatnyy render vklyuchen!
    ) else (
        echo        NVENC ne naydeno - budet ispolzovatsya CPU.
    )
)

:: -----------------------------------------------
:: 6. Desktop shortcut
:: -----------------------------------------------
echo.
echo  [6/6] Sozdayom yarlyk na rabochem stole...

set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\VideoGenerator.lnk"
set "VBS_PATH=%APP_DIR%VideoGenerator.vbs"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '%VBS_PATH%'; $sc.WorkingDirectory = '%APP_DIR%'; $sc.Save()" >> "%LOG%" 2>&1

if exist "%SHORTCUT%" (
    echo        Yarlyk sozdan na rabochem stole!
) else (
    echo        Yarlyk ne sozdan - zapuskayte cherez VideoGenerator.vbs
)

:: -----------------------------------------------
:: USPESHNO
:: -----------------------------------------------
echo.
echo  ================================================
echo    USTANOVKA ZAVERSHENA USPESHNO!
echo.
echo    Zapustite:
echo    * Dvoynym klikom na yarlyk "VideoGenerator"
echo      na rabochem stole
echo    * ILI zapustite VideoGenerator.vbs
echo.
echo    Pervyy zapusk -> vkladka "Nastroyki" ->
echo    vvedite API klyuchi -> Sokhranit
echo  ================================================
echo.
goto :end_ok

:end_error
echo.
echo  ================================================
echo   USTANOVKA ZAVERSHILAS S OSHIBKOY.
echo   Otkroyte fayly setup_log.txt v papke programmy
echo   i prishlite ego soderzhimoe dlya diagnostiki.
echo  ================================================
echo.
pause
exit /b 1

:end_ok
pause
