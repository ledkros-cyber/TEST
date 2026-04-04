@echo off
echo.
echo  Zapuskaem ustanovku...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_script.ps1"
echo.
echo  ================================================
echo   Nazhemite ENTER chtoby zakryt eto okno...
echo  ================================================
set /p DUMMY=
