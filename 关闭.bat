@echo off
setlocal
title Dissector - Stop
cd /d "%~dp0"

set PORT=8394
if not "%ROOTTHINK_PORT%"=="" set PORT=%ROOTTHINK_PORT%

echo.
echo   Stopping Dissector (port %PORT%) ...
echo.

set FOUND=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr /i "LISTENING"') do (
  echo   Killing PID %%P
  taskkill /f /pid %%P >nul 2>nul
  set FOUND=1
)

if "%FOUND%"=="0" (
  echo   Nothing was listening on port %PORT%. Already stopped.
) else (
  echo   Done. The service has been stopped.
)

echo.
pause
