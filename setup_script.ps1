# YouTube Video Generator - Setup Script
# Compatible with PowerShell 5.1 (Windows built-in)
# ASCII only - no Unicode characters

$ErrorActionPreference = "Stop"

$AppDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $AppDir "venv"
$BinDir  = Join-Path $AppDir "bin"
$LogFile = Join-Path $AppDir "setup_log.txt"
$ReqFile = Join-Path $AppDir "requirements.txt"

# ==============================================================
# If path has non-ASCII (Cyrillic etc.) redirect pip cache/temp
# to a safe ASCII location so install works from ANY folder
# ==============================================================
$SafeTemp = "C:\ProgramData\ytgen_tmp"
if (-not (Test-Path $SafeTemp)) {
    New-Item -ItemType Directory -Path $SafeTemp -Force | Out-Null
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8       = "1"
$env:PIP_CACHE_DIR    = "$SafeTemp\pip_cache"
$env:TEMP             = $SafeTemp
$env:TMP              = $SafeTemp

# Also put the venv in a guaranteed ASCII path if AppDir has non-ASCII
$nonAscii = $AppDir -match '[^\x00-\x7F]'
if ($nonAscii) {
    Write-Host ""
    Write-Host "  Path has non-ASCII characters (Cyrillic etc.)" -ForegroundColor Yellow
    Write-Host "  Using safe ASCII path for venv: C:\ProgramData\ytgen_venv" -ForegroundColor Yellow
    Write-Host "  Program files stay in: $AppDir" -ForegroundColor White
    Write-Host ""
    $VenvDir = "C:\ProgramData\ytgen_venv"
    # Write venv location to a config file so main.py can find it
    Set-Content -Path (Join-Path $AppDir "venv_path.txt") -Value $VenvDir -Encoding UTF8
}

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function LogSection($title) {
    Write-Host ""
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Add-Content -Path $LogFile -Value "" -Encoding UTF8
    Add-Content -Path $LogFile -Value "=== $title ===" -Encoding UTF8
}

function SafeGetCommand($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Set-Content -Path $LogFile -Value "=== SETUP LOG $(Get-Date) ===" -Encoding UTF8
Log "App dir: $AppDir"

# ==============================================================
# STEP 1 - Python
# ==============================================================
LogSection "Step 1/6 - Python"

$pythonExe = $null

$found1 = SafeGetCommand "python"
$found2 = SafeGetCommand "python3"
$found3 = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
$found4 = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$found5 = "C:\Python311\python.exe"
$found6 = "C:\Python312\python.exe"

foreach ($p in @($found1, $found2, $found3, $found4, $found5, $found6)) {
    if ($p -and (Test-Path $p)) {
        $pythonExe = $p
        break
    }
}

if ($pythonExe) {
    $ver = & $pythonExe --version 2>&1
    Log "Found: $ver  ($pythonExe)"
} else {
    Log "Python not found. Downloading Python 3.11..."
    $pyInstaller = Join-Path $env:TEMP "python_setup.exe"
    Invoke-WebRequest `
        -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
        -OutFile $pyInstaller -UseBasicParsing
    Log "Installing Python (wait ~30 sec)..."
    Start-Process -FilePath $pyInstaller `
        -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" `
        -Wait
    Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" + $env:PATH
    $found = SafeGetCommand "python"
    if ($found) { $pythonExe = $found }
    if (-not $pythonExe) {
        Write-Host "  ERROR: Python install failed." -ForegroundColor Red
        Write-Host "  Download manually: https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "  Check 'Add Python to PATH' during install." -ForegroundColor Yellow
        Log "ERROR: Python install failed"
        return
    }
    Log "Python installed: $pythonExe"
}

# ==============================================================
# STEP 2 - Virtual environment
# ==============================================================
LogSection "Step 2/6 - Virtual environment"

$venvPy  = Join-Path $VenvDir "Scripts\python.exe"
$venvPyw = Join-Path $VenvDir "Scripts\pythonw.exe"
$venvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (Test-Path $venvPy) {
    Log "venv already exists, skipping."
} else {
    Log "Creating venv at: $VenvDir"
    $out = & $pythonExe -m venv $VenvDir 2>&1
    if ($out) { Log ($out | Out-String) }
    if (-not (Test-Path $venvPy)) {
        Write-Host "  ERROR: Could not create venv." -ForegroundColor Red
        Log "ERROR: venv creation failed"
        return
    }
    Log "OK: venv created."
}

# ==============================================================
# STEP 3 - Upgrade pip
# ==============================================================
LogSection "Step 3/6 - Upgrade pip"

# Use Continue so pip's stderr logging noise doesn't kill the script
$ErrorActionPreference = "Continue"
$out = & $venvPy -m pip install --upgrade pip 2>&1
$ErrorActionPreference = "Stop"
Log ($out | Out-String)
Log "pip upgraded."

# ==============================================================
# STEP 4 - Install dependencies
# ==============================================================
LogSection "Step 4/6 - Install dependencies (3-7 min)"
Write-Host "  Installing: PyQt6, google-api, anthropic, requests..." -ForegroundColor White
Write-Host "  Please wait, do not close this window..." -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path $ReqFile)) {
    Write-Host "  ERROR: requirements.txt not found at $ReqFile" -ForegroundColor Red
    Log "ERROR: requirements.txt not found"
    return
}

# Stream pip output line by line
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName               = $venvPip
$psi.Arguments              = "install -r `"$ReqFile`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError  = $true
$psi.UseShellExecute        = $false
$psi.CreateNoWindow         = $false

$proc = [System.Diagnostics.Process]::Start($psi)

while (-not $proc.StandardOutput.EndOfStream) {
    $line = $proc.StandardOutput.ReadLine()
    Write-Host "  $line"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

$stderr   = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
$exitCode = $proc.ExitCode

if ($stderr) {
    Add-Content -Path $LogFile -Value $stderr -Encoding UTF8
}
Log "pip exit code: $exitCode"

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "  ERROR: pip install failed!" -ForegroundColor Red
    if ($stderr) { Write-Host $stderr -ForegroundColor Red }
    Write-Host "  See log file: $LogFile" -ForegroundColor Yellow
    Log "ERROR: pip failed with code $exitCode"
    return
}

Log "Dependencies installed successfully!"
Write-Host ""
Write-Host "  Dependencies installed OK!" -ForegroundColor Green

# ==============================================================
# STEP 5 - FFmpeg
# ==============================================================
LogSection "Step 5/6 - FFmpeg"

$ffmpegExe  = Join-Path $BinDir "ffmpeg.exe"
$ffprobeExe = Join-Path $BinDir "ffprobe.exe"

if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
    Log "FFmpeg already present, skipping."
} else {
    if (-not (Test-Path $BinDir)) {
        New-Item -ItemType Directory -Path $BinDir | Out-Null
    }

    $zipUrl  = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $zipFile = Join-Path $env:TEMP "ffmpeg_ytgen.zip"

    Log "Downloading FFmpeg (can take 1-3 minutes)..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($zipUrl, $zipFile)
    } catch {
        try {
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
        } catch {
            Write-Host "  ERROR: Could not download FFmpeg." -ForegroundColor Red
            Write-Host "  Download manually: https://ffmpeg.org/download.html" -ForegroundColor Yellow
            Write-Host "  Put ffmpeg.exe and ffprobe.exe into: $BinDir" -ForegroundColor Yellow
            Log "ERROR: FFmpeg download failed"
            return
        }
    }

    Log "Extracting ffmpeg.exe and ffprobe.exe..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipFile)
    foreach ($entry in $zip.Entries) {
        if ($entry.Name -eq "ffmpeg.exe" -or $entry.Name -eq "ffprobe.exe") {
            $dest = Join-Path $BinDir $entry.Name
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
            Log "Extracted: $($entry.Name)"
        }
    }
    $zip.Dispose()
    Remove-Item $zipFile -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $ffmpegExe)) {
        Write-Host "  ERROR: ffmpeg.exe not found after extraction." -ForegroundColor Red
        Log "ERROR: ffmpeg.exe missing after extract"
        return
    }
    Log "FFmpeg installed!"
}

# GPU check
Log ""
Log "Checking NVIDIA NVENC..."
$encoders = & $ffmpegExe -hide_banner -encoders 2>&1 | Out-String
if ($encoders -match "h264_nvenc") {
    Write-Host "  >>> NVIDIA NVENC FOUND - GPU render enabled!" -ForegroundColor Green
    Log "NVIDIA NVENC: AVAILABLE"
} else {
    Write-Host "  >>> NVENC not found - will use CPU render (normal)" -ForegroundColor Yellow
    Log "NVIDIA NVENC: not available (CPU fallback)"
}

# ==============================================================
# STEP 6 - Desktop shortcut
# ==============================================================
LogSection "Step 6/6 - Desktop shortcut"

$vbsPath = Join-Path $AppDir "VideoGenerator.vbs"
$lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "VideoGenerator.lnk"

if (Test-Path $vbsPath) {
    try {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($lnkPath)
        $sc.TargetPath       = $vbsPath
        $sc.WorkingDirectory = $AppDir
        $sc.Description      = "YouTube Video Generator"
        $sc.Save()
        if (Test-Path $lnkPath) {
            Write-Host "  Shortcut created on Desktop!" -ForegroundColor Green
            Log "Shortcut created: $lnkPath"
        }
    } catch {
        Log "Shortcut creation failed (non-critical): $_"
    }
} else {
    Log "VideoGenerator.vbs not found, skipping shortcut"
}

# ==============================================================
# DONE
# ==============================================================
Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host ""
Write-Host "  HOW TO LAUNCH:" -ForegroundColor White
Write-Host "  1. Double-click 'VideoGenerator' on Desktop" -ForegroundColor White
Write-Host "  OR" -ForegroundColor White
Write-Host "  2. Double-click VideoGenerator.vbs in this folder" -ForegroundColor White
Write-Host ""
Write-Host "  FIRST RUN:" -ForegroundColor White
Write-Host "  Tab 'Nastroyki' (Settings) -> enter API keys -> Save" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Log "=== INSTALLATION SUCCESSFUL ==="
