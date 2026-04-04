@echo off
chcp 65001 >nul
title YouTube Video Generator — Установка
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║      YouTube Video Generator — Установка            ║
echo  ║      Подождите, это займёт 2-5 минут...             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Путь к папке программы
set "APP_DIR=%~dp0"
set "VENV_DIR=%APP_DIR%venv"
set "BIN_DIR=%APP_DIR%bin"

:: ──────────────────────────────────────────────────────────
:: 1. Проверяем Python
:: ──────────────────────────────────────────────────────────
echo  [1/5] Проверяем Python...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        Python не найден. Скачиваем Python 3.11...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python_setup.exe' -UseBasicParsing"
    if %errorlevel% neq 0 (
        echo.
        echo  ОШИБКА: Не удалось скачать Python.
        echo  Скачайте вручную: https://www.python.org/downloads/
        echo  При установке поставьте галочку "Add Python to PATH"
        pause
        exit /b 1
    )
    echo        Устанавливаем Python...
    "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del "%TEMP%\python_setup.exe" >nul 2>&1
    :: Обновляем PATH для текущей сессии
    for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "PATH=%%B;%PATH%"
    echo        Python установлен!
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        Найден: %%v
)

:: ──────────────────────────────────────────────────────────
:: 2. Создаём виртуальное окружение
:: ──────────────────────────────────────────────────────────
echo.
echo  [2/5] Создаём виртуальное окружение...

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo        Окружение уже существует, пропускаем.
) else (
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo  ОШИБКА: Не удалось создать venv.
        pause
        exit /b 1
    )
    echo        Окружение создано.
)

:: ──────────────────────────────────────────────────────────
:: 3. Устанавливаем зависимости
:: ──────────────────────────────────────────────────────────
echo.
echo  [3/5] Устанавливаем зависимости Python...
echo        (PyQt6, YouTube API, Anthropic, requests...)

"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%requirements.txt" --quiet

if %errorlevel% neq 0 (
    echo.
    echo  ОШИБКА при установке зависимостей.
    echo  Проверьте подключение к интернету и попробуйте снова.
    pause
    exit /b 1
)
echo        Зависимости установлены!

:: ──────────────────────────────────────────────────────────
:: 4. Скачиваем FFmpeg
:: ──────────────────────────────────────────────────────────
echo.
echo  [4/5] Проверяем FFmpeg...

if exist "%BIN_DIR%\ffmpeg.exe" (
    echo        FFmpeg уже есть, пропускаем.
) else (
    mkdir "%BIN_DIR%" >nul 2>&1
    echo        Скачиваем FFmpeg (может занять 1-3 минуты)...

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile '%TEMP%\ffmpeg.zip' -UseBasicParsing"

    if %errorlevel% neq 0 (
        echo.
        echo  Не удалось скачать FFmpeg автоматически.
        echo  Скачайте вручную: https://ffmpeg.org/download.html
        echo  Распакуйте ffmpeg.exe и ffprobe.exe в папку: %BIN_DIR%
        echo  Затем запустите SETUP.bat снова.
        pause
        exit /b 1
    )

    echo        Распаковываем FFmpeg...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::OpenRead('%TEMP%\ffmpeg.zip'); foreach($e in $zip.Entries){ if($e.Name -eq 'ffmpeg.exe' -or $e.Name -eq 'ffprobe.exe'){ [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, '%BIN_DIR%\' + $e.Name, $true) } }; $zip.Dispose()"

    del "%TEMP%\ffmpeg.zip" >nul 2>&1
    echo        FFmpeg готов!
)

:: ──────────────────────────────────────────────────────────
:: 5. Проверяем NVIDIA GPU (NVENC)
:: ──────────────────────────────────────────────────────────
echo.
echo  [5/6] Проверяем NVIDIA GPU...

"%BIN_DIR%\ffmpeg.exe" -hide_banner -encoders 2>nul | findstr /C:"h264_nvenc" >nul
if %errorlevel% equ 0 (
    echo        NVIDIA NVENC найден — аппаратный рендер включён!
    echo        Legion RTX: 1080p @ 60fps будет рендериться очень быстро.
) else (
    echo        NVIDIA NVENC не найден. Будет использоваться CPU.
    echo        Установите последние драйверы NVIDIA для аппаратного рендера.
)

:: ──────────────────────────────────────────────────────────
:: 6. Создаём ярлык на рабочем столе
:: ──────────────────────────────────────────────────────────
echo.
echo  [6/6] Создаём ярлык на рабочем столе...

set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\VideoGenerator.lnk"
set "VBS_PATH=%APP_DIR%VideoGenerator.vbs"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '%VBS_PATH%'; $sc.WorkingDirectory = '%APP_DIR%'; $sc.Description = 'YouTube Video Generator'; $sc.Save()"

if exist "%SHORTCUT%" (
    echo        Ярлык создан на рабочем столе!
) else (
    echo        Ярлык не создан, но программа работает через VideoGenerator.vbs
)

:: ──────────────────────────────────────────────────────────
:: Готово!
:: ──────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО!                      ║
echo  ║                                                      ║
echo  ║   Запустите программу:                              ║
echo  ║   • Двойной клик на ярлык "VideoGenerator"          ║
echo  ║     на рабочем столе                                 ║
echo  ║                                                      ║
echo  ║   Первый запуск:                                    ║
echo  ║   1. Откройте вкладку "Настройки"                   ║
echo  ║   2. Введите API ключи (YouTube, Claude, MiniMax)   ║
echo  ║   3. Укажите папки для видео                        ║
echo  ║   4. Нажмите "Сохранить настройки"                  ║
echo  ║                                                      ║
echo  ║   Далее: Поиск → Сценарий → Озвучка → Видео        ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
pause
