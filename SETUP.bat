@echo off
chcp 65001 >nul
title YouTube Video Generator - Ustanovka
color 0A

echo.
echo  ================================================
echo    YouTube Video Generator - Ustanovka
echo    Podozhdite, eto zaymet 2-5 minut...
echo  ================================================
echo.

set "APP_DIR=%~dp0"
set "VENV_DIR=%APP_DIR%venv"
set "BIN_DIR=%APP_DIR%bin"

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
        echo  Pri ustanovke postavte galochku "Add Python to PATH"
        pause
        exit /b 1
    )
    echo        Ustanavlivaem Python...
    "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del "%TEMP%\python_setup.exe" >nul 2>&1
    echo        Python ustanovlen!
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        Naydeno: %%v
)

:: -----------------------------------------------
:: 2. Virtual environment
:: -----------------------------------------------
echo.
echo  [2/6] Sozdayom virtualnoe okruzhenie...

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo        Okruzhenie uzhe est, propuskaem.
) else (
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo  OSHIBKA: Ne udalos sozdat venv.
        pause
        exit /b 1
    )
    echo        Okruzhenie sozdano.
)

:: -----------------------------------------------
:: 3. Dependencies
:: -----------------------------------------------
echo.
echo  [3/6] Ustanavlivaem zavisimosti Python...

"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%requirements.txt" --quiet

if %errorlevel% neq 0 (
    echo.
    echo  OSHIBKA pri ustanovke zavisimostey.
    echo  Proverte podklyuchenie k internetu i poprobuyte snova.
    pause
    exit /b 1
)
echo        Zavisimosti ustanovleny!

:: -----------------------------------------------
:: 4. FFmpeg
:: -----------------------------------------------
echo.
echo  [4/6] Proveryaem FFmpeg...

if exist "%BIN_DIR%\ffmpeg.exe" (
    echo        FFmpeg uzhe est, propuskaem.
) else (
    mkdir "%BIN_DIR%" >nul 2>&1
    echo        Skachivaem FFmpeg (1-3 minuty)...

    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile '%TEMP%\ffmpeg.zip' -UseBasicParsing"

    if %errorlevel% neq 0 (
        echo.
        echo  Ne udalos skachat FFmpeg avtomaticheski.
        echo  Skayte vruchnuyu: https://ffmpeg.org/download.html
        echo  Raspakoyte ffmpeg.exe i ffprobe.exe v papku: %BIN_DIR%
        pause
        exit /b 1
    )

    echo        Raspakovyvaem FFmpeg...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::OpenRead('%TEMP%\ffmpeg.zip'); foreach($e in $zip.Entries){ if($e.Name -eq 'ffmpeg.exe' -or $e.Name -eq 'ffprobe.exe'){ [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, '%BIN_DIR%\' + $e.Name, $true) } }; $zip.Dispose()"

    del "%TEMP%\ffmpeg.zip" >nul 2>&1
    echo        FFmpeg gotov!
)

:: -----------------------------------------------
:: 5. GPU check
:: -----------------------------------------------
echo.
echo  [5/6] Proveryaem NVIDIA GPU (NVENC)...

if exist "%BIN_DIR%\ffmpeg.exe" (
    "%BIN_DIR%\ffmpeg.exe" -hide_banner -encoders 2>nul | findstr /C:"h264_nvenc" >nul
    if %errorlevel% equ 0 (
        echo        NVIDIA NVENC naydeno - apparatnyy render vklyuchen!
        echo        Legion RTX: 1080p @ 60fps budet renderitsya ochen bystro.
    ) else (
        echo        NVIDIA NVENC ne naydeno. Budet ispolzovatsya CPU.
        echo        Ustanovite poslednie drayvery NVIDIA dlya apparatnogo rendera.
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

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '%VBS_PATH%'; $sc.WorkingDirectory = '%APP_DIR%'; $sc.Save()"

if exist "%SHORTCUT%" (
    echo        Yarlyk sozdan na rabochem stole!
) else (
    echo        Yarlyk ne sozdan, no programma rabotaet cherez VideoGenerator.vbs
)

:: -----------------------------------------------
:: Done
:: -----------------------------------------------
echo.
echo  ================================================
echo    USTANOVKA ZAVERSHENA USPESHNO!
echo.
echo    Zapustite programmu:
echo    * Dvoynym klikom na yarlyk "VideoGenerator"
echo      na rabochem stole
echo.
echo    Pervyy zapusk:
echo    1. Otkroyte vkladku "Nastroyki"
echo    2. Vvedite API klyuchi
echo    3. Ukazhite papki dlya video
echo    4. Nazhmite "Sokhranit nastroyki"
echo.
echo    Dalee: Poisk - Stsenariy - Ozvuchka - Video
echo  ================================================
echo.
pause
