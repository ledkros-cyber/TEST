# ============================================================
#  YouTube Video Generator - Setup Script (PowerShell)
#  Runs automatically from SETUP.bat
# ============================================================

$ErrorActionPreference = "Stop"

$AppDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $AppDir "venv"
$BinDir  = Join-Path $AppDir "bin"
$LogFile = Join-Path $AppDir "setup_log.txt"
$ReqFile = Join-Path $AppDir "requirements.txt"

# Helpers
function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function LogSection($title) {
    $sep = "=" * 50
    Write-Host ""
    Write-Host $sep -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host $sep -ForegroundColor Cyan
    Add-Content -Path $LogFile -Value "" -Encoding UTF8
    Add-Content -Path $LogFile -Value "=== $title ===" -Encoding UTF8
}

function Fail($msg) {
    Write-Host ""
    Write-Host "  OSHIBKA: $msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Log fayл: $LogFile" -ForegroundColor Yellow
    Write-Host "  Otkroyte ego i prishlite soderzhimoe." -ForegroundColor Yellow
    Add-Content -Path $LogFile -Value "OSHIBKA: $msg" -Encoding UTF8
    # DON'T exit - let SETUP.bat's pause handle it
    throw $msg
}

# ─── Init log ────────────────────────────────────────────────
Set-Content -Path $LogFile -Value "=== SETUP LOG $(Get-Date) ===" -Encoding UTF8
Log "App directory: $AppDir"

# ─── STEP 1: Python ──────────────────────────────────────────
LogSection "Shag 1/6 - Python"

$pythonExe = $null
$candidates = @(
    (Get-Command python -ErrorAction SilentlyContinue)?.Source,
    (Get-Command python3 -ErrorAction SilentlyContinue)?.Source,
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python312\python.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if ($candidates) {
    $pythonExe = $candidates[0]
    $ver = & $pythonExe --version 2>&1
    Log "Naydeno: $ver  ($pythonExe)"
} else {
    Log "Python ne nayden. Skachivaem Python 3.11..."
    $pyInstaller = Join-Path $env:TEMP "python_setup.exe"
    Invoke-WebRequest `
        -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
        -OutFile $pyInstaller -UseBasicParsing
    Log "Ustanavlivaem Python (zhdite ~30 sek)..."
    Start-Process -FilePath $pyInstaller `
        -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" `
        -Wait
    Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" + $env:PATH
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue)?.Source
    if (-not $pythonExe) { Fail "Python ne udalos ustanovit. Ustanovite vruchnuyu: https://www.python.org" }
    Log "Python ustanovlen: $pythonExe"
}

# ─── STEP 2: Virtual environment ─────────────────────────────
LogSection "Shag 2/6 - Virtualnoe okruzhenie"

$venvPy   = Join-Path $VenvDir "Scripts\python.exe"
$venvPyw  = Join-Path $VenvDir "Scripts\pythonw.exe"
$venvPip  = Join-Path $VenvDir "Scripts\pip.exe"

if (Test-Path $venvPy) {
    Log "Okruzhenie uzhe est, propuskaem."
} else {
    Log "Sozdayom venv v: $VenvDir"
    $out = & $pythonExe -m venv $VenvDir 2>&1
    Log $out
    if (-not (Test-Path $venvPy)) { Fail "Ne udalos sozdat venv. Output: $out" }
    Log "OK: okruzhenie sozdano."
}

# ─── STEP 3: pip upgrade ─────────────────────────────────────
LogSection "Shag 3/6 - Obnovlenie pip"

$out = & $venvPy -m pip install --upgrade pip 2>&1
Log ($out | Out-String)
Log "pip obnovlen."

# ─── STEP 4: Dependencies ────────────────────────────────────
LogSection "Shag 4/6 - Ustanovka zavisimostey"
Log "Ustanavlivaem: PyQt6, google-api, anthropic, requests..."
Log "(Eto mozhet zanyat 3-7 minut — pozhaluysta, zhdite)"
Write-Host ""

if (-not (Test-Path $ReqFile)) { Fail "Ne nayden fayл requirements.txt v $AppDir" }

# Run pip and stream output live
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName  = $venvPip
$psi.Arguments = "install -r `"$ReqFile`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError  = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow  = $false

$proc = [System.Diagnostics.Process]::Start($psi)

while (-not $proc.StandardOutput.EndOfStream) {
    $line = $proc.StandardOutput.ReadLine()
    Write-Host "  $line"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
$exitCode = $proc.ExitCode

if ($stderr) { Add-Content -Path $LogFile -Value $stderr -Encoding UTF8 }
Log "pip exit code: $exitCode"

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "  OSHIBKA PIP:" -ForegroundColor Red
    Write-Host $stderr -ForegroundColor Red
    Fail "pip install failed (exit $exitCode). Sm. $LogFile"
}

Log "Zavisimosti ustanovleny uspeshno!"

# ─── STEP 5: FFmpeg ──────────────────────────────────────────
LogSection "Shag 5/6 - FFmpeg"

$ffmpegExe  = Join-Path $BinDir "ffmpeg.exe"
$ffprobeExe = Join-Path $BinDir "ffprobe.exe"

if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
    Log "FFmpeg uzhe est, propuskaem."
} else {
    if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }

    $zipUrl  = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $zipFile = Join-Path $env:TEMP "ffmpeg_ytgen.zip"

    Log "Skachivaem FFmpeg (mozhet zanyat 1-3 minuty)..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($zipUrl, $zipFile)
    } catch {
        Log "Osnovnoy server nedostupen. Probuyem zapasnoy..."
        try {
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
        } catch {
            Fail "Ne udalos skachat FFmpeg. Proverte internet i zapustite SETUP snova."
        }
    }

    Log "Raspakovyvaem ffmpeg.exe i ffprobe.exe..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipFile)
    foreach ($entry in $zip.Entries) {
        if ($entry.Name -eq "ffmpeg.exe" -or $entry.Name -eq "ffprobe.exe") {
            $destPath = Join-Path $BinDir $entry.Name
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destPath, $true)
            Log "Raspakovano: $($entry.Name)"
        }
    }
    $zip.Dispose()
    Remove-Item $zipFile -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $ffmpegExe)) { Fail "FFmpeg ne raspakovalsya. Sm. log." }
    Log "FFmpeg uspeshno ustanovlen!"
}

# GPU check
Log ""
Log "Proveryaem NVIDIA NVENC..."
$encoders = & $ffmpegExe -hide_banner -encoders 2>&1 | Out-String
if ($encoders -match "h264_nvenc") {
    Write-Host "  >>> NVIDIA NVENC NAYDENO - apparatnyy render vklyuchen!" -ForegroundColor Green
    Log "NVIDIA NVENC: DOSTUPNO"
} else {
    Write-Host "  >>> NVENC ne naydeno - budet CPU render (normalnyy rezim)" -ForegroundColor Yellow
    Log "NVIDIA NVENC: ne dostupno (CPU fallback)"
}

# ─── STEP 6: Desktop shortcut ────────────────────────────────
LogSection "Shag 6/6 - Yarlyk na rabochem stole"

$vbsPath  = Join-Path $AppDir "VideoGenerator.vbs"
$lnkPath  = Join-Path ([Environment]::GetFolderPath("Desktop")) "VideoGenerator.lnk"

if (Test-Path $vbsPath) {
    $ws  = New-Object -ComObject WScript.Shell
    $sc  = $ws.CreateShortcut($lnkPath)
    $sc.TargetPath      = $vbsPath
    $sc.WorkingDirectory = $AppDir
    $sc.Description     = "YouTube Video Generator"
    $sc.Save()

    if (Test-Path $lnkPath) {
        Log "Yarlyk sozdan: $lnkPath"
        Write-Host "  Yarlyk 'VideoGenerator' poyavilsya na rabochem stole!" -ForegroundColor Green
    } else {
        Log "Yarlyk ne sozdan (ne kritichno)"
    }
} else {
    Log "VideoGenerator.vbs ne nayden - yarlyk propuskaem"
}

# ─── SUCCESS ─────────────────────────────────────────────────
Write-Host ""
Write-Host ("=" * 52) -ForegroundColor Green
Write-Host "  USTANOVKA ZAVERSHENA USPESHNO!" -ForegroundColor Green
Write-Host ""
Write-Host "  Kak zapustit programmu:" -ForegroundColor White
Write-Host "  1. Dvoynym klikom na yarlyk 'VideoGenerator'" -ForegroundColor White
Write-Host "     na rabochem stole" -ForegroundColor White
Write-Host "  2. ILI dvoynym klikom na VideoGenerator.vbs" -ForegroundColor White
Write-Host "     v papke programmy" -ForegroundColor White
Write-Host ""
Write-Host "  Pervyy raz: vkladka Nastroyki -> API klyuchi" -ForegroundColor White
Write-Host ("=" * 52) -ForegroundColor Green
Write-Host ""
Log "=== USTANOVKA USPESHNA ==="
