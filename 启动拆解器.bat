@echo off
setlocal
title Dissector
cd /d "%~dp0"

if not exist "app\server.py" (
  echo  [error] app\server.py not found.
  echo          Is the "app" folder next to this file?
  echo          Do NOT rename or remove it - the program lives there.
  echo.
  pause
  exit /b 1
)

rem ============================================================
rem  Desktop-app mode (DEFAULT since 2026-10-12):
rem   hand over to dissector.pyw, which starts the service with
rem   pythonw (NO console window) and opens an INDEPENDENT app
rem   window (Edge/Chrome --app mode: no address bar, no tabs,
rem   its own taskbar icon). The desktop icon named "Dissector"
rem   runs the very same launcher.
rem   A desktop icon can be created by double-clicking
rem   "create_shortcut.py" once.
rem ============================================================
if exist "%~dp0python\pythonw.exe" (
  if exist "%~dp0dissector.pyw" (
    start "" "%~dp0python\pythonw.exe" "%~dp0dissector.pyw"
    exit /b 0
  )
)

rem ============================================================
rem  Added 2026-10-28 (open-source build): fall back to the SYSTEM
rem  pythonw when no bundled runtime is present.
rem
rem  Why: the branch above requires python\pythonw.exe. The
rem  open-source build ships WITHOUT python\, so it would fall all
rem  the way to FALLBACK below -- and FALLBACK runs the service in
rem  THIS console window with the page in the default browser, which
rem  is NOT an app window (address bar, tabs, browser taskbar icon).
rem  So people who already have Python still get the standalone
rem  window. pythonw.exe lives next to python.exe on Windows CPython,
rem  hence `where pythonw` finds it, and it shows no console window.
rem ============================================================
if exist "%~dp0dissector.pyw" (
  where pythonw >nul 2>nul
  if not errorlevel 1 (
    start "" pythonw "%~dp0dissector.pyw"
    exit /b 0
)
)

rem ------------------------------------------------------------
rem  FALLBACK (no bundled python\pythonw.exe): run the old way -
rem  service in THIS console window, page in the default browser.
rem ------------------------------------------------------------
if not exist "data"    mkdir "data"
if not exist "history" mkdir "history"

if not exist ".env.local" (
  echo.
  echo  [note] No .env.local found in THIS folder.
  echo         Copy "_env.example" to ".env.local" and fill in your API key,
  echo         otherwise the chat will refuse to serve.
  echo.
)

set PYEXE=
if exist "%~dp0python\python.exe" set PYEXE=%~dp0python\python.exe
if "%PYEXE%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set PYEXE=python
)
if "%PYEXE%"=="" (
  echo  [error] No Python runtime found.
  echo          Expected a "python" folder next to this file, with python.exe inside.
  echo.
  pause
  exit /b 1
)

set PORT=8394
if not "%ROOTTHINK_PORT%"=="" set PORT=%ROOTTHINK_PORT%

echo.
echo   ==========================================================
echo    Dissector  -  helps you see your problem clearly
echo   ==========================================================
echo     Your browser will open by itself in a few seconds.
echo     If it does not, open this address manually:
echo         http://127.0.0.1:%PORT%
echo     Keep this window OPEN while using the app.
echo     Stop the service:  press Ctrl+C in this window
echo.

rem --- If the service is ALREADY running on this port, do NOT start a
rem     second copy. Just open the page and tell the user it is running.
netstat -ano | findstr ":%PORT% " | findstr /i "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo   [ok] The service is ALREADY RUNNING on port %PORT%.
  echo        Opening the page now. You do NOT need to start it again.
  echo.
  start "" "http://127.0.0.1:%PORT%"
  echo   This window can be closed. The running service is in another window.
  echo.
  pause
  exit /b 0
)

cd /d "%~dp0app"
"%PYEXE%" server.py

echo.
echo  [service stopped]
pause
