@echo off
rem Registers an hourly Windows Task Scheduler job for run-cutoff.bat.
cd /d "%~dp0"
schtasks /Create /TN "EWMP Attendance Cutoff" /TR "\"%~dp0run-cutoff.bat\"" /SC HOURLY /F
if errorlevel 1 (
  echo.
  echo FAILED. Right-click this file and choose "Run as administrator", then try again.
  pause
  exit /b 1
)
echo.
echo Task created. Running it once now to test...
schtasks /Run /TN "EWMP Attendance Cutoff"
timeout /t 8 >nul
echo.
echo Last lines of cutoff.log:
powershell -NoProfile -Command "Get-Content cutoff.log -Tail 6"
echo.
pause
